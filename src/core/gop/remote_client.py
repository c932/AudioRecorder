"""
Remote GOP HTTP client.

Talks to src/server/gop_server.py.
Output schema MUST match GopResult.to_dict() exactly. The response is run
through GopResult.from_dict() (which fail-fasts on missing fields) before
being re-serialized so callers always get a strict dict.
"""
from __future__ import annotations

import base64
import json
import os
from typing import Optional

from src.core.gop.schema import GopResult


def _build_headers(api_key: Optional[str]) -> dict:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def fetch_remote_fingerprint(base_url: str, api_key: Optional[str] = None, timeout: float = 5.0) -> str:
    """GET {base}/v1/gop/fingerprint -> {'model_fingerprint': str}."""
    import requests
    url = base_url.rstrip("/") + "/v1/gop/fingerprint"
    r = requests.get(url, headers=_build_headers(api_key), timeout=timeout)
    r.raise_for_status()
    data = r.json()
    return str(data.get("model_fingerprint", "") or "")


def score_remote(
    audio_path: str,
    reference_text: str,
    base_url: str,
    api_key: Optional[str] = None,
    timeout: float = 60.0,
) -> dict:
    """POST audio (base64) + reference to /v1/gop/score, return GopResult dict.

    Strict deserialization via GopResult.from_dict() — any missing required
    field raises ValueError (no silent degradation).
    """
    import requests
    if not base_url:
        raise ValueError("remote base_url is empty")
    if not os.path.isfile(audio_path):
        raise FileNotFoundError(audio_path)

    with open(audio_path, "rb") as f:
        audio_b64 = base64.b64encode(f.read()).decode("ascii")

    payload = {
        "audio_b64": audio_b64,
        "audio_format": os.path.splitext(audio_path)[1].lstrip(".").lower() or "wav",
        "reference": reference_text,
    }
    url = base_url.rstrip("/") + "/v1/gop/score"
    r = requests.post(url, headers=_build_headers(api_key), data=json.dumps(payload), timeout=timeout)
    r.raise_for_status()
    raw = r.json()

    # Strict schema validation.
    result = GopResult.from_dict(raw)
    return result.to_dict()
