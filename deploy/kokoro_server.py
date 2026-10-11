"""Kokoro TTS FastAPI 服务 — 英文本地 TTS，ONNX CPU 推理，零延迟。"""
from __future__ import annotations

import io
import os
import argparse

import numpy as np
import soundfile as sf
import uvicorn
from fastapi import FastAPI, Form
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Kokoro TTS Server")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_kokoro = None
_model_path = os.environ.get("KOKORO_MODEL", "/home/manfred/AI/services/kokoro/kokoro-v0_19.onnx")
# Prefer .npz (numpy native), fallback to .json
_voices_npz = os.environ.get("KOKORO_VOICES", "/home/manfred/AI/services/kokoro/voices.npz")

DEFAULT_VOICE = "af_bella"
SUPPORTED_VOICES = [
    "af", "af_bella", "af_nicole", "af_sarah", "af_sky",
    "am_adam", "am_michael",
    "bf_emma", "bf_isabella",
    "bm_george", "bm_lewis",
]


def get_model():
    global _kokoro
    if _kokoro is None:
        from kokoro_onnx import Kokoro
        print(f"[kokoro] Loading model: {_model_path}, voices: {_voices_npz}")
        _kokoro = Kokoro(_model_path, _voices_npz)
        print(f"[kokoro] Model loaded. Voices: {SUPPORTED_VOICES}")
    return _kokoro


@app.get("/health")
async def health():
    return {"status": "ok", "model": "kokoro", "voices": SUPPORTED_VOICES}


@app.get("/voices")
async def voices():
    return {"voices": SUPPORTED_VOICES}


@app.post("/tts")
async def tts(
    text: str = Form(),
    voice: str = Form(default="af_bella"),
    speed: float = Form(default=1.0),
):
    """英文文本 → WAV 音频。"""
    if not text.strip():
        return StreamingResponse(iter([]), media_type="audio/wav")

    v = voice if voice in SUPPORTED_VOICES else DEFAULT_VOICE
    try:
        model = get_model()
        samples, sample_rate = model.create(
            text, voice=v, speed=speed, lang="en-us", trim=False,
        )
        buf = io.BytesIO()
        sf.write(buf, samples, sample_rate, format="WAV", subtype="PCM_16")
        buf.seek(0)
        return StreamingResponse(buf, media_type="audio/wav")
    except Exception as e:
        print(f"[kokoro] TTS failed: {e}")
        return StreamingResponse(iter([]), media_type="audio/wav")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=18400)
    args = parser.parse_args()
    uvicorn.run("server:app", host=args.host, port=args.port, log_level="info")
