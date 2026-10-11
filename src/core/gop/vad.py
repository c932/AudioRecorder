"""
silero-vad wrapper with short-sentence bypass.

Rules:
  - duration < 1.2s OR phoneme_count <= 4 -> skip VAD entirely (return original path)
  - VAD load/run failure -> return original path (graceful degrade)
  - Output: path to a temp wav containing only voiced segments
"""
from __future__ import annotations

import os
import tempfile
import wave
from typing import Optional

# Bypass thresholds (per plan).
SHORT_DURATION_S = 1.2
SHORT_PHONEME_COUNT = 4

# 清辅音保留 padding（毫秒）：
# silero-vad 对能量低的清辅音 (/p/, /t/, /k/, /s/, /f/, /θ/) 判定起点
# 偏晚，直接拼接会切掉单词首字母。前后各保留一段 padding 能显著改善。
PAD_BEFORE_MS = 80
PAD_AFTER_MS = 80


def _audio_duration_seconds(audio_path: str) -> float:
    """Return WAV duration in seconds. Returns 0 on failure."""
    try:
        with wave.open(audio_path, "rb") as wf:
            frames = wf.getnframes()
            rate = float(wf.getframerate())
            if rate <= 0:
                return 0.0
            return frames / rate
    except Exception:
        return 0.0


def should_bypass_vad(audio_path: str, expected_phoneme_count: int) -> bool:
    """Plan rule: short audio or very few expected phonemes -> bypass VAD."""
    if expected_phoneme_count <= SHORT_PHONEME_COUNT:
        return True
    dur = _audio_duration_seconds(audio_path)
    if 0.0 < dur < SHORT_DURATION_S:
        return True
    return False


def extract_speech(audio_path: str, expected_phoneme_count: int = 0) -> tuple[str, bool]:
    """
    Run silero-vad and return path to a temp wav containing only speech segments.

    On bypass / failure, returns the original audio_path unchanged.

    Returns:
        (path, is_temp) — is_temp=True means the returned path is a temp file
        that should be deleted after use.
    """
    if should_bypass_vad(audio_path, expected_phoneme_count):
        print(f"[gop.vad] bypass (short audio or few phonemes): {audio_path}")
        return audio_path, False

    try:
        import numpy as np
        import soundfile as sf
        import torch

        # Load silero-vad via torch.hub (cached after first download).
        model, utils = torch.hub.load(
            repo_or_dir="snakers4/silero-vad",
            model="silero_vad",
            trust_repo=True,
        )
        (get_speech_timestamps, _, _, _, _) = utils

        # Load audio with soundfile (avoid torchaudio.load -> torchcodec dep).
        data, sr = sf.read(audio_path, dtype="float32", always_2d=True)
        if data.shape[1] > 1:
            data = data.mean(axis=1, keepdims=True)
        mono = np.ascontiguousarray(data[:, 0])
        if sr != 16000:
            import torchaudio
            wav_t = torch.from_numpy(mono)
            wav_t = torchaudio.functional.resample(wav_t, sr, 16000)
            mono = wav_t.numpy()
        wav = torch.from_numpy(mono)

        timestamps = get_speech_timestamps(wav, model, sampling_rate=16000)
        if not timestamps:
            print("[gop.vad] no speech detected, returning original audio")
            return audio_path, False

        # Apply padding to preserve voiceless onsets (e.g. /p/, /t/, /k/).
        pad_before = int(PAD_BEFORE_MS * 16000 / 1000)  # samples
        pad_after = int(PAD_AFTER_MS * 16000 / 1000)
        padded = []
        for t in timestamps:
            start = max(0, t["start"] - pad_before)
            end = min(len(mono), t["end"] + pad_after)
            padded.append(mono[start:end])
        out = np.concatenate(padded) if padded else mono

        tmp = tempfile.NamedTemporaryFile(prefix="gop_vad_", suffix=".wav", delete=False)
        tmp_path = tmp.name
        tmp.close()
        sf.write(tmp_path, out, 16000, subtype="PCM_16")
        print(f"[gop.vad] speech segments extracted: {len(timestamps)} "
              f"(+{PAD_BEFORE_MS}/{PAD_AFTER_MS}ms padding) -> {tmp_path}")
        return tmp_path, True
    except Exception as e:
        print(f"[gop.vad] failed ({e}), returning original audio")
        return audio_path, False
