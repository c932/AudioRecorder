"""Whisper ASR FastAPI server.

Endpoints:
    POST /v1/transcribe   -> {"text": "..."}
    GET  /v1/health        -> {"status": "ok", "model": "medium"}

Deployment:
    uvicorn server:app --host 0.0.0.0 --port 18350
"""
from __future__ import annotations

import argparse
import os
import tempfile
from typing import Optional

from fastapi import FastAPI, Form, UploadFile, File
from fastapi.responses import JSONResponse
import uvicorn

app = FastAPI(title="Whisper ASR Server")

# Singleton model
_model = None
_model_size = "medium"
_device = "auto"


def get_model():
    global _model
    if _model is None:
        import torch
        device = _device
        if device == "auto":
            device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"[whisper] Loading Whisper '{_model_size}' on {device}...")
        try:
            import whisper
            _model = whisper.load_model(_model_size, device=device)
            print(f"[whisper] Model loaded on {device}.")
        except (RuntimeError, Exception) as e:
            if device == "cuda":
                print(f"[whisper] GPU load failed ({e}), falling back to CPU...")
                import whisper
                _model = whisper.load_model(_model_size, device="cpu")
                print("[whisper] Model loaded on CPU (fallback).")
            else:
                raise
    return _model


@app.get("/v1/health")
async def health():
    return {"status": "ok", "model": _model_size}


@app.post("/v1/transcribe")
async def transcribe(
    audio: UploadFile = File(...),
    language: str = Form(default="en"),
):
    """Transcribe uploaded audio file."""
    model = get_model()
    if model is None:
        return JSONResponse({"text": "", "error": "model not loaded"}, status_code=503)

    suffix = os.path.splitext(audio.filename or "audio.wav")[1] or ".wav"
    tmp = tempfile.NamedTemporaryFile(prefix="whisper_", suffix=suffix, delete=False)
    tmp_path = tmp.name
    try:
        content = await audio.read()
        tmp.write(content)
        tmp.close()

        import torch
        use_fp16 = (hasattr(model, "device") and str(model.device) == "cuda"
                    and torch.cuda.is_available())
        result = model.transcribe(tmp_path, language=language, fp16=use_fp16)
        text = (result.get("text") or "").strip()
        return {"text": text}
    except Exception as e:
        return JSONResponse({"text": "", "error": str(e)}, status_code=500)
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=18350)
    parser.add_argument("--model", default="medium")
    parser.add_argument("--device", default="auto")
    args = parser.parse_args()
    _model_size = args.model
    _device = args.device
    uvicorn.run("server:app", host=args.host, port=args.port, log_level="info")
