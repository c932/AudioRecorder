"""
FastAPI GOP scoring server.

Endpoints:
    POST /v1/gop/score         -> GopResult JSON (same schema as local)
    GET  /v1/gop/fingerprint   -> {"model_fingerprint": "<16-hex>"}
    GET  /v1/health            -> {"status": "ok"}

Runs the same GopPipeline used locally, so local <-> remote outputs are
guaranteed to share schema and (when fingerprints match) be comparable.

Deployment:
    pip install fastapi uvicorn
    uvicorn src.server.gop_server:app --host 0.0.0.0 --port 18200

Optional auth: set GOP_SERVER_KEY env var; clients must send Authorization: Bearer <key>.
"""
from __future__ import annotations

import base64
import os
import tempfile
from typing import Optional

# FastAPI is an optional dependency; importing inside try lets the file be importable
# in environments where the server isn't deployed (the client side never imports app).
try:
    from fastapi import FastAPI, HTTPException, Header, Request
    from pydantic import BaseModel
except Exception as e:  # pragma: no cover
    FastAPI = None
    HTTPException = None
    Header = None
    Request = None
    BaseModel = object
    _IMPORT_ERROR = e
else:
    _IMPORT_ERROR = None

from src.core.gop.pipeline import GopPipeline


# ---------------------------------------------------------------------- #
# Pipeline singleton (lives for the life of the process).
_PIPELINE: Optional[GopPipeline] = None


def _get_pipeline() -> GopPipeline:
    global _PIPELINE
    if _PIPELINE is None:
        device = os.environ.get("GOP_DEVICE", "auto")
        model = os.environ.get("GOP_MODEL", "facebook/wav2vec2-lv-60-espeak-cv-ft")
        _PIPELINE = GopPipeline(mode="local", model_name=model, device=device)
    return _PIPELINE


def _check_auth(authorization: Optional[str]):
    """Optional bearer-token auth via GOP_SERVER_KEY env var."""
    expected = os.environ.get("GOP_SERVER_KEY", "")
    if not expected:
        return
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    if token != expected:
        raise HTTPException(status_code=403, detail="invalid token")


# ---------------------------------------------------------------------- #
if FastAPI is not None:
    app = FastAPI(title="GOP Scoring Server", version="1.0")

    class ScoreRequest(BaseModel):
        audio_b64: str
        audio_format: str = "wav"
        reference: str

    @app.get("/v1/health")
    def health():
        return {"status": "ok"}

    @app.get("/v1/gop/fingerprint")
    def fingerprint(authorization: Optional[str] = Header(default=None)):
        _check_auth(authorization)
        try:
            fp = _get_pipeline().fingerprint()
            return {"model_fingerprint": fp}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"fingerprint failed: {e}")

    @app.post("/v1/gop/score")
    def score(req: ScoreRequest, authorization: Optional[str] = Header(default=None)):
        _check_auth(authorization)

        if not req.audio_b64:
            raise HTTPException(status_code=400, detail="audio_b64 is empty")
        if not req.reference or not req.reference.strip():
            raise HTTPException(status_code=400, detail="reference is empty")

        try:
            audio_bytes = base64.b64decode(req.audio_b64)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"invalid base64: {e}")

        suffix = "." + (req.audio_format or "wav").lstrip(".")
        tmp = tempfile.NamedTemporaryFile(prefix="gop_srv_", suffix=suffix, delete=False)
        tmp_path = tmp.name
        try:
            tmp.write(audio_bytes)
            tmp.close()
            try:
                result = _get_pipeline().score(tmp_path, req.reference)
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"scoring failed: {e}")
            return result
        finally:
            try:
                os.remove(tmp_path)
            except Exception:
                pass
else:  # pragma: no cover
    app = None


def main():  # pragma: no cover
    """CLI entry: python -m src.server.gop_server [--host H --port P]"""
    import argparse
    if _IMPORT_ERROR is not None:
        raise SystemExit(f"FastAPI/uvicorn not installed: {_IMPORT_ERROR}")
    import uvicorn
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=18200)
    args = parser.parse_args()
    uvicorn.run("src.server.gop_server:app", host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":  # pragma: no cover
    main()
