"""
GopPipeline: orchestrator for local & remote GOP scoring.

Local mode flow:
    text -> g2p -> vad? -> wav2vec2 align -> GOP score -> aggregate -> classify -> GopResult

Remote mode flow:
    POST audio + reference_text to gop_server -> deserialize GopResult.

Both modes return the SAME schema (src.core.gop.schema.GopResult.to_dict()).

CLI:
    python -m src.core.gop.pipeline path/to/audio.wav "the cat sat"
"""
from __future__ import annotations

import json
import os
import sys
import time
from typing import Optional

from src.core.gop.schema import GopResult, PIPELINE_VERSION
from src.core.gop.g2p import text_to_phonemes, expected_phoneme_count
from src.core.gop.scorer import score_alignment


# Module-level singletons (avoid reloading the heavy aligner across calls).
_ALIGNER_SINGLETON = None
_PIPELINE_SINGLETON = None


def _get_aligner(model_name: str, device: str):
    """Cache a single Wav2Vec2Aligner per (model_name, device) pair."""
    global _ALIGNER_SINGLETON
    from src.core.gop.aligner import Wav2Vec2Aligner

    key = (model_name, device)
    if _ALIGNER_SINGLETON is not None and getattr(_ALIGNER_SINGLETON, "_cache_key", None) == key:
        return _ALIGNER_SINGLETON

    aligner = Wav2Vec2Aligner(model_name=model_name, device=device)
    aligner._cache_key = key
    _ALIGNER_SINGLETON = aligner
    return aligner


class GopPipeline:
    """End-to-end GOP scoring pipeline (local or remote)."""

    def __init__(
        self,
        mode: str = "local",
        model_name: str = "facebook/wav2vec2-lv-60-espeak-cv-ft",
        device: str = "auto",
        remote_url: Optional[str] = None,
        remote_key: Optional[str] = None,
        use_vad: bool = True,
    ):
        self.mode = (mode or "local").lower()
        self.model_name = model_name
        self.device = device or "auto"
        self.remote_url = remote_url or ""
        self.remote_key = remote_key or ""
        self.use_vad = bool(use_vad)

    # ------------------------------------------------------------------ #
    def fingerprint(self) -> str:
        """Return current model fingerprint (loads aligner if needed)."""
        if self.mode == "remote":
            from src.core.gop.remote_client import fetch_remote_fingerprint
            try:
                return fetch_remote_fingerprint(self.remote_url, self.remote_key)
            except Exception as e:
                print(f"[gop.pipeline] remote fingerprint failed: {e}")
                return ""
        aligner = _get_aligner(self.model_name, self.device)
        aligner.load()
        return aligner.fingerprint

    # ------------------------------------------------------------------ #
    def score(self, audio_path: str, reference_text: str) -> dict:
        """Score one (audio, reference_text) pair. Returns GopResult.to_dict()."""
        if not audio_path or not os.path.isfile(audio_path):
            raise FileNotFoundError(f"audio file not found: {audio_path}")
        if not reference_text or not reference_text.strip():
            raise ValueError("reference_text is empty")

        if self.mode == "remote":
            return self._score_remote(audio_path, reference_text)
        return self._score_local(audio_path, reference_text)

    # ------------------------------------------------------------------ #
    def _score_local(self, audio_path: str, reference_text: str) -> dict:
        # 每次打分前刷新校准参数（用户在设置页调整后立即生效）
        try:
            from src.core.gop.scorer import load_calib_from_config
            load_calib_from_config()
        except Exception as _e:
            print(f"[gop.pipeline] load_calib failed (using last): {_e}")

        t0 = time.time()

        # 1. G2P
        word_phoneme_pairs = text_to_phonemes(reference_text)
        if not word_phoneme_pairs:
            raise ValueError(f"no phonemes derived from reference text: {reference_text!r}")
        ph_count = sum(len(ph) for _, ph in word_phoneme_pairs)

        # 2. VAD (with short-sentence bypass)
        align_input = audio_path
        if self.use_vad:
            try:
                from src.core.gop.vad import extract_speech
                align_input = extract_speech(audio_path, expected_phoneme_count=ph_count)
            except Exception as e:
                print(f"[gop.pipeline] VAD failed, using original audio: {e}")
                align_input = audio_path

        # 3. wav2vec2 forced alignment
        aligner = _get_aligner(self.model_name, self.device)
        aligner.load()
        align_result = aligner.align(align_input, word_phoneme_pairs)

        # 4. Scoring
        elapsed_ms = int((time.time() - t0) * 1000)
        result = score_alignment(
            reference_text=reference_text,
            align_result=align_result,
            id_to_token=aligner.id_to_token,
            word_phoneme_pairs=word_phoneme_pairs,
            fingerprint=aligner.fingerprint,
            elapsed_ms=elapsed_ms,
        )
        return result.to_dict()

    # ------------------------------------------------------------------ #
    def _score_remote(self, audio_path: str, reference_text: str) -> dict:
        from src.core.gop.remote_client import score_remote
        return score_remote(
            audio_path=audio_path,
            reference_text=reference_text,
            base_url=self.remote_url,
            api_key=self.remote_key,
        )


# ---------------------------------------------------------------------- #
def get_pipeline(
    mode: str = "local",
    model_name: str = "facebook/wav2vec2-lv-60-espeak-cv-ft",
    device: str = "auto",
    remote_url: Optional[str] = None,
    remote_key: Optional[str] = None,
    use_vad: bool = True,
) -> GopPipeline:
    """Singleton-ish accessor used by ai_assessor."""
    global _PIPELINE_SINGLETON
    key = (mode, model_name, device, remote_url or "", remote_key or "", bool(use_vad))
    if _PIPELINE_SINGLETON is not None and getattr(_PIPELINE_SINGLETON, "_cache_key", None) == key:
        return _PIPELINE_SINGLETON
    p = GopPipeline(
        mode=mode,
        model_name=model_name,
        device=device,
        remote_url=remote_url,
        remote_key=remote_key,
        use_vad=use_vad,
    )
    p._cache_key = key
    _PIPELINE_SINGLETON = p
    return p


def score(audio_path: str, reference_text: str, **kwargs) -> dict:
    """Convenience function: score with a default singleton pipeline."""
    p = get_pipeline(**kwargs)
    return p.score(audio_path, reference_text)


# ---------------------------------------------------------------------- #
def _cli_main():
    if len(sys.argv) < 3:
        print("Usage: python -m src.core.gop.pipeline <audio.wav> \"<reference_text>\"")
        sys.exit(2)
    audio = sys.argv[1]
    ref = sys.argv[2]
    p = GopPipeline(mode="local")
    out = p.score(audio, ref)
    # Force UTF-8 stdout for IPA / non-ASCII content (Windows GBK by default).
    text = json.dumps(out, ensure_ascii=False, indent=2)
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # py3.7+
    except Exception:
        pass
    try:
        print(text)
    except UnicodeEncodeError:
        sys.stdout.buffer.write(text.encode("utf-8", errors="replace"))
        sys.stdout.buffer.write(b"\n")


if __name__ == "__main__":
    _cli_main()
