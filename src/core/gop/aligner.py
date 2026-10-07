"""
wav2vec2 phoneme CTC + forced alignment.

Model: facebook/wav2vec2-lv-60-espeak-cv-ft
  - input: 16kHz mono waveform
  - output: per-frame logits over IPA phoneme vocab (~393 tokens)

Phoneme normalization happens via ARPABET <-> IPA mapping table; both reference
phonemes (from g2p_en) and the model vocab are normalized into the same label
space before alignment.

Forced alignment: Python Viterbi over collapsed CTC posteriors. Output:
  - frame_logits: (T, V) raw logits (kept for GOP scoring)
  - alignment:    list of (phoneme, start_frame, end_frame, alignment_confidence)
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import List, Optional, Tuple


# ARPABET -> IPA mapping (covers all 39 normalized ARPABET phonemes).
# Vowels follow CMU dict conventions; consonants are straight transliterations.
ARPABET_TO_IPA = {
    # Vowels
    "AA": "ɑ", "AE": "æ", "AH": "ʌ", "AO": "ɔ",
    "AW": "aʊ", "AY": "aɪ",
    "EH": "ɛ", "ER": "ɝ", "EY": "eɪ",
    "IH": "ɪ", "IY": "i",
    "OW": "oʊ", "OY": "ɔɪ",
    "UH": "ʊ", "UW": "u",
    # Consonants
    "B": "b", "CH": "tʃ", "D": "d", "DH": "ð",
    "F": "f", "G": "ɡ", "HH": "h",
    "JH": "dʒ", "K": "k", "L": "l", "M": "m", "N": "n",
    "NG": "ŋ", "P": "p", "R": "ɹ", "S": "s", "SH": "ʃ",
    "T": "t", "TH": "θ", "V": "v", "W": "w", "Y": "j",
    "Z": "z", "ZH": "ʒ",
    # Placeholder
    "UNK": "",
}

# Alternate IPA forms that some wav2vec2-lv-60 vocabs use.
# We try the primary mapping first, then these fallbacks when looking up token ids.
ARPABET_TO_IPA_ALT = {
    "G": ["g"],          # 'g' (latin) instead of ɡ (IPA voiced velar)
    "R": ["r"],          # plain r (some vocabs use r instead of ɹ)
    "AW": ["aw"],
    "AY": ["ai"],
    "EY": ["ei", "e"],
    "OW": ["o", "ow"],
    "OY": ["oi", "ɔi"],
    "AH": ["ə"],         # schwa often used for unstressed AH
    "ER": ["ɚ", "ɜ"],
    "IY": ["iː"],
    "UW": ["uː"],
    "UH": ["ʊː"],
    "AA": ["ɑː", "a"],
    "AO": ["ɔː"],
    "CH": ["ʧ"],
    "JH": ["ʤ"],
}


@dataclass
class PhoneAlignment:
    phoneme: str            # normalized ARPABET
    start_frame: int
    end_frame: int          # exclusive
    log_prob_mean: float    # avg log P(target token id) across its frames
    confidence: float       # avg posterior P(target | frame) in [0,1]


@dataclass
class AlignmentResult:
    log_probs: "object"     # torch.Tensor (T, V) log-softmax
    frame_duration_s: float
    alignment: List[PhoneAlignment]
    asr_text: str           # greedy CTC decode (for debug)
    blank_token_id: int
    target_token_ids: List[int]   # token id picked for each expected phoneme (-1 if missing)
    target_phonemes: List[str]    # normalized ARPABET sequence (flat across all words)
    word_boundaries: List[int]    # phoneme-index splits between words


class Wav2Vec2Aligner:
    """Lazy-loaded wav2vec2 phoneme aligner."""

    DEFAULT_MODEL = "facebook/wav2vec2-lv-60-espeak-cv-ft"

    def __init__(self, model_name: str = DEFAULT_MODEL, device: str = "auto"):
        self.model_name = model_name
        self.device_pref = device
        self._loaded = False

        self.processor = None
        self.feature_extractor = None
        self.model = None
        self.device = None
        self.vocab = {}                      # token (str) -> id (int)
        self.id_to_token = {}                # id -> str
        self.blank_token_id = 0
        self.frame_duration_s = 0.02         # wav2vec2 stride is 20ms
        self.fingerprint = ""

    # ------------------------------------------------------------------ #
    @staticmethod
    def _validate_cuda(torch) -> str:
        """Test a tiny CUDA computation. If GPU CC is too old, fallback to CPU.

        Some GPUs (e.g. GTX 1060 sm_61) report cuda.is_available() == True
        because the driver is installed, but the bundled PyTorch was built
        only for sm_75+. Actual kernel launch fails with RuntimeError.
        """
        try:
            t = torch.zeros(1, device="cuda")
            _ = t + t  # triggers CUDA kernel
            return "cuda"
        except RuntimeError as e:
            print(f"[gop.aligner] CUDA validation failed ({e}); falling back to CPU.")
            return "cpu"

    # ------------------------------------------------------------------ #
    @staticmethod
    def _resolve_hf_token() -> str:
        """Resolve HuggingFace token: env var `HF_TOKEN` first, then config.json.

        Returns an empty string if no token is configured. Transformers / huggingface_hub
        accept either None or an empty string as "no token", but we pass only when non-empty.
        """
        import os as _os
        tok = _os.environ.get("HF_TOKEN", "").strip()
        if tok:
            return tok
        try:
            # Lazy import to avoid circular deps (utils is tiny and has no deps)
            from src.utils import get_user_data_path
            cfg_path = get_user_data_path("config.json")
            if cfg_path and _os.path.exists(cfg_path):
                import json as _json
                with open(cfg_path, "r", encoding="utf-8") as f:
                    cfg = _json.load(f)
                tok = (cfg.get("hf_token") or "").strip()
                return tok
        except Exception as e:
            print(f"[gop.aligner] failed to read hf_token from config: {e}")
        return ""

    # ------------------------------------------------------------------ #
    def load(self) -> None:
        if self._loaded:
            return
        import json as _json
        import torch
        from transformers import AutoFeatureExtractor, AutoModelForCTC

        if self.device_pref == "cuda":
            device = "cuda" if torch.cuda.is_available() else "cpu"
        elif self.device_pref == "cpu":
            device = "cpu"
        else:
            device = "cuda" if torch.cuda.is_available() else "cpu"

        # Validate CUDA actually works (GPU compute capability may be too old).
        if device == "cuda":
            device = self._validate_cuda(torch)

        # Check free VRAM: wav2vec2 needs ~1.2 GB for model + inference buffers.
        # If GPU is nearly full (e.g. another container's TTS model), fall back to CPU.
        if device == "cuda":
            free_mb = torch.cuda.mem_get_info()[0] / (1024 * 1024)
            if free_mb < 1500:
                print(f"[gop.aligner] GPU free VRAM only {free_mb:.0f} MB, "
                      f"need ~1500 MB; falling back to CPU.")
                device = "cpu"

        print(f"[gop.aligner] loading {self.model_name} on {device}...")

        # NOTE: We deliberately avoid AutoProcessor / AutoTokenizer for
        # wav2vec2-phoneme: its tokenizer pulls in `phonemizer` + `espeak-ng`
        # at init (system binary).  We only need:
        #   - the feature extractor (raw audio -> input_values)
        #   - the vocab (id <-> string), which we load from vocab.json directly
        # G2P is done by g2p_en in src/core/gop/g2p.py, so the espeak backend
        # is unnecessary here.
        #
        # Load order: prefer local cache (local_files_only=True) to avoid
        # repeated HF Hub network round-trips on every startup. Fall back to
        # online download only when the model is not yet cached locally.
        #
        # Token: read from HF_TOKEN env or config.json ("hf_token") to silence
        # HF Hub "unauthenticated" warnings and allow gated / private models.
        token = self._resolve_hf_token()
        if token:
            print("[gop.aligner] HF token loaded (source: env or config.json).")

        def _from_pretrained(cls, **extra):
            try:
                return cls.from_pretrained(self.model_name, local_files_only=True, **extra)
            except Exception as e:
                print(f"[gop.aligner] local cache miss ({cls.__name__}: {e}); "
                      f"downloading from HF Hub once...")
                kwargs = dict(**extra)
                if token:
                    kwargs["token"] = token
                return cls.from_pretrained(self.model_name, **kwargs)

        self.feature_extractor = _from_pretrained(AutoFeatureExtractor)
        self.model = _from_pretrained(AutoModelForCTC)
        self.model.eval()
        self.model.to(device)
        self.device = device

        # Load vocab.json from the HF cache (downloaded as part of the model snapshot).
        from huggingface_hub import hf_hub_download
        try:
            vocab_path = hf_hub_download(
                repo_id=self.model_name, filename="vocab.json",
                local_files_only=True,
            )
        except Exception as e:
            print(f"[gop.aligner] vocab.json not in local cache ({e}); fetching once...")
            vocab_path = hf_hub_download(
                repo_id=self.model_name, filename="vocab.json",
                **({"token": token} if token else {}),
            )
        with open(vocab_path, "r", encoding="utf-8") as vf:
            self.vocab = dict(_json.load(vf))
        self.id_to_token = {v: k for k, v in self.vocab.items()}

        # CTC blank id: prefer model.config.pad_token_id, else look up "<pad>" in vocab, else 0.
        blank_id = getattr(self.model.config, "pad_token_id", None)
        if blank_id is None:
            blank_id = self.vocab.get("<pad>", 0)
        self.blank_token_id = int(blank_id)

        # Compute fingerprint.
        from src.core.gop.fingerprint import compute_fingerprint
        revision = getattr(self.model.config, "_commit_hash", "") or ""
        self.fingerprint = compute_fingerprint(self.model_name, self.vocab, revision)

        self._loaded = True
        print(f"[gop.aligner] ready. vocab_size={len(self.vocab)}, "
              f"blank_id={self.blank_token_id}, fingerprint={self.fingerprint}")

    # ------------------------------------------------------------------ #
    def _arpabet_to_token_id(self, arpabet: str) -> int:
        """Map a normalized ARPABET symbol to the closest wav2vec2 token id, or -1."""
        if arpabet == "UNK":
            return -1

        # Primary IPA form.
        primary = ARPABET_TO_IPA.get(arpabet, "")
        candidates = []
        if primary:
            candidates.append(primary)
        candidates.extend(ARPABET_TO_IPA_ALT.get(arpabet, []))
        # Last-ditch: lowercase ARPABET letter (some vocabs include latin letters).
        candidates.append(arpabet.lower())

        for c in candidates:
            if c in self.vocab:
                return self.vocab[c]
        # Try first character of primary (for digraphs like 'aʊ' -> 'a').
        if primary and primary[0] in self.vocab:
            return self.vocab[primary[0]]
        return -1

    # ------------------------------------------------------------------ #
    def _load_waveform(self, audio_path: str):
        """Load 16kHz mono waveform tensor from path.

        Uses soundfile for I/O (project-wide dependency) and torchaudio only
        for resampling — torchaudio 2.9+ removed native audio backends in
        favour of torchcodec, which we explicitly avoid.
        """
        import numpy as np
        import soundfile as sf
        import torch
        import torchaudio

        data, sr = sf.read(audio_path, dtype="float32", always_2d=True)
        # data: (samples, channels)
        if data.shape[1] > 1:
            data = data.mean(axis=1, keepdims=True)
        wav = torch.from_numpy(np.ascontiguousarray(data[:, 0]))
        if sr != 16000:
            wav = torchaudio.functional.resample(wav, sr, 16000)
        return wav  # (samples,)

    # ------------------------------------------------------------------ #
    def _greedy_decode(self, log_probs) -> str:
        """Collapse CTC argmax to readable IPA text."""
        import torch
        ids = torch.argmax(log_probs, dim=-1).tolist()
        out = []
        prev = -1
        for i in ids:
            if i == self.blank_token_id:
                prev = -1
                continue
            if i != prev:
                tok = self.id_to_token.get(i, "")
                if tok and tok not in ("<s>", "</s>", "<pad>", "<unk>", "|"):
                    out.append(tok)
            prev = i
        return " ".join(out)

    # ------------------------------------------------------------------ #
    def _viterbi_forced_align(self, log_probs, target_ids: List[int]):
        """
        Viterbi forced alignment over standard CTC topology with blanks between
        every target symbol (and at start/end).

        target_ids may contain -1 entries meaning 'no token in vocab': we treat
        these as wildcards (any non-blank emission accepted) so the alignment
        can still progress.

        Returns list of (start_frame, end_frame) per target symbol.
        """
        import torch
        T, V = log_probs.shape
        if not target_ids:
            return []

        blank = self.blank_token_id
        # Build expanded sequence: B t1 B t2 B ... tN B
        S = 2 * len(target_ids) + 1
        seq = [blank] * S
        for i, tid in enumerate(target_ids):
            seq[2 * i + 1] = tid

        NEG = float("-1e30")
        # log alphas
        a = torch.full((T, S), NEG, dtype=torch.float32, device=log_probs.device)
        bp = torch.full((T, S), -1, dtype=torch.int32, device=log_probs.device)

        def emit(t, s):
            tid = seq[s]
            if tid == -1:
                # Wildcard: max over non-blank tokens at this frame.
                row = log_probs[t].clone()
                row[blank] = NEG
                return float(row.max().item())
            return float(log_probs[t, tid].item())

        # Initialize at t=0: only states 0 (blank) and 1 (first target) reachable.
        a[0, 0] = emit(0, 0)
        if S > 1:
            a[0, 1] = emit(0, 1)

        for t in range(1, T):
            # State 0 only from itself.
            v = a[t - 1, 0].item() + emit(t, 0)
            a[t, 0] = v
            bp[t, 0] = 0
            for s in range(1, S):
                # Transitions: from s, s-1.
                cands = [(a[t - 1, s].item(), s), (a[t - 1, s - 1].item(), s - 1)]
                # CTC skip: from s-2 if s-2 >= 0 and seq[s] != seq[s-2] and seq[s] != blank
                if s >= 2 and seq[s] != blank and seq[s] != seq[s - 2]:
                    cands.append((a[t - 1, s - 2].item(), s - 2))
                best_v, best_p = max(cands, key=lambda x: x[0])
                a[t, s] = best_v + emit(t, s)
                bp[t, s] = best_p

        # Backtrace from best of last two states.
        last_candidates = [(a[T - 1, S - 1].item(), S - 1)]
        if S >= 2:
            last_candidates.append((a[T - 1, S - 2].item(), S - 2))
        _, s = max(last_candidates, key=lambda x: x[0])
        path = [0] * T
        path[T - 1] = s
        for t in range(T - 1, 0, -1):
            s = int(bp[t, s].item())
            path[t - 1] = s

        # Convert state path to per-target frame ranges.
        ranges = [(-1, -1)] * len(target_ids)  # (start, end_exclusive)
        for t, s in enumerate(path):
            if s % 2 == 1:
                idx = s // 2
                start, end = ranges[idx]
                if start < 0:
                    start = t
                end = t + 1
                ranges[idx] = (start, end)

        # Fill gaps (a target may be skipped entirely under wildcards / extreme noise).
        for i, (st, en) in enumerate(ranges):
            if st < 0:
                # Inherit a 1-frame slot from neighbor end (deletion-like, will be flagged).
                if i > 0 and ranges[i - 1][1] >= 0:
                    pos = ranges[i - 1][1]
                else:
                    pos = 0
                ranges[i] = (pos, min(pos + 1, T))
        return ranges

    # ------------------------------------------------------------------ #
    def align(
        self,
        audio_path: str,
        word_phoneme_pairs: List[Tuple[str, List[str]]],
    ) -> AlignmentResult:
        """
        Force-align a waveform to a flat sequence of expected phonemes.

        Args:
            audio_path: 16kHz mono WAV.
            word_phoneme_pairs: [(word, [ARPABET, ...]), ...]

        Returns AlignmentResult.
        """
        self.load()
        import torch

        # Flatten phonemes + record word boundaries.
        target_phonemes: List[str] = []
        word_boundaries: List[int] = []
        for _, phones in word_phoneme_pairs:
            for p in phones:
                target_phonemes.append(p)
            word_boundaries.append(len(target_phonemes))

        target_token_ids = [self._arpabet_to_token_id(p) for p in target_phonemes]

        # Load + run wav2vec2.
        wav = self._load_waveform(audio_path).to(self.device)
        with torch.no_grad():
            inputs = self.feature_extractor(
                wav.cpu().numpy(),
                sampling_rate=16000,
                return_tensors="pt",
            )
            input_values = inputs.input_values.to(self.device)
            logits = self.model(input_values).logits[0]   # (T, V)
            log_probs = torch.log_softmax(logits.float(), dim=-1).cpu()

        T = log_probs.shape[0]
        # Stride: ~20ms per frame for base wav2vec2, but compute precisely.
        wav_len_s = float(wav.shape[-1]) / 16000.0
        frame_duration_s = wav_len_s / max(T, 1)

        # Greedy decode (debug ASR text).
        asr_text = self._greedy_decode(log_probs)

        # Viterbi forced alignment.
        ranges = self._viterbi_forced_align(log_probs, target_token_ids)

        # Per-phoneme avg log_prob and confidence.
        alignments: List[PhoneAlignment] = []
        probs = torch.exp(log_probs)  # (T, V) posterior probabilities
        for i, (st, en) in enumerate(ranges):
            tid = target_token_ids[i]
            if en <= st:
                en = st + 1
            if tid >= 0 and tid < log_probs.shape[1]:
                slc = log_probs[st:en, tid]
                lp_mean = float(slc.mean().item()) if slc.numel() > 0 else float("-1e9")
                conf_mean = float(probs[st:en, tid].mean().item()) if slc.numel() > 0 else 0.0
            else:
                # No vocab token: take best-non-blank confidence as a proxy.
                slc_row = probs[st:en].clone()
                slc_row[:, self.blank_token_id] = 0.0
                conf_mean = float(slc_row.max(dim=-1).values.mean().item()) if slc_row.numel() > 0 else 0.0
                lp_mean = float(math.log(max(conf_mean, 1e-9)))
            alignments.append(PhoneAlignment(
                phoneme=target_phonemes[i],
                start_frame=int(st),
                end_frame=int(en),
                log_prob_mean=lp_mean,
                confidence=max(0.0, min(1.0, conf_mean)),
            ))

        return AlignmentResult(
            log_probs=log_probs,
            frame_duration_s=frame_duration_s,
            alignment=alignments,
            asr_text=asr_text,
            blank_token_id=self.blank_token_id,
            target_token_ids=target_token_ids,
            target_phonemes=target_phonemes,
            word_boundaries=word_boundaries,
        )
