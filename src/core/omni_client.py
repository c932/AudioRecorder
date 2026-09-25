"""
MiniCPM-o 4.5 Omni client.

Custom REST API (NOT OpenAI-compatible): JWT auth + SSE streaming.
Handles text and/or audio input → streaming text + TTS audio output.

Public API:
    OmniConfig   — connection settings (from_config)
    OmniClient   — login, chat (sync + async SSE), audio download, reset
    OmniSignals  — pyqtSignals for async streaming
    OmniAudioPlayer — downloads + plays omni TTS WAV via QMediaPlayer
    OmniError    — raised on API failures
"""
from __future__ import annotations

import base64
import json
import os
import tempfile
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

import requests
from PyQt6.QtCore import QObject, pyqtSignal, QThread


class OmniError(Exception):
    """Raised on MiniCPM-o API failures."""


# ──────────────────────────────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────────────────────────────
@dataclass
class OmniConfig:
    host: str = "127.0.0.1"
    auth_port: int = 18500
    chat_port: int = 18400
    username: str = "admin"
    password: str = "admin123"
    model: str = "minicpm-o45"
    tts_enabled: bool = True
    request_timeout: float = 120.0
    connect_timeout: float = 10.0

    @classmethod
    def from_config(cls, config: dict) -> "OmniConfig":
        return cls(
            host=config.get("omni_host", "127.0.0.1").strip() or "127.0.0.1",
            auth_port=int(config.get("omni_auth_port", 18500)),
            chat_port=int(config.get("omni_chat_port", 18400)),
            username=config.get("omni_username", "admin").strip() or "admin",
            password=config.get("omni_password", "admin123"),
            model=config.get("omni_model", "minicpm-o45").strip() or "minicpm-o45",
            tts_enabled=bool(config.get("omni_tts_enabled", True)),
        )

    @property
    def auth_url(self) -> str:
        return f"http://{self.host}:{self.auth_port}/api/auth/login"

    @property
    def chat_url(self) -> str:
        return f"http://{self.host}:{self.chat_port}/api/omni/minicpm-o45/chat"

    @property
    def reset_url(self) -> str:
        return f"http://{self.host}:{self.chat_port}/api/omni/minicpm-o45/reset"

    @property
    def status_url(self) -> str:
        return f"http://{self.host}:{self.chat_port}/api/omni/minicpm-o45/status"

    def audio_base_url(self) -> str:
        return f"http://{self.host}:{self.chat_port}"


# ──────────────────────────────────────────────────────────────────────
# Signals
# ──────────────────────────────────────────────────────────────────────
class OmniSignals(QObject):
    """Signals emitted during async SSE streaming."""
    status       = pyqtSignal(str)      # stage: init/decode/tts/...
    text_chunk   = pyqtSignal(str)      # incremental text fragment
    text_done    = pyqtSignal(str)      # full accumulated text
    audio_url    = pyqtSignal(str)      # chunk URL (may fire multiple)
    audio_merged = pyqtSignal(str)      # full-round URL
    done         = pyqtSignal()
    error        = pyqtSignal(str)


# ──────────────────────────────────────────────────────────────────────
# Client
# ──────────────────────────────────────────────────────────────────────
class OmniClient:
    """
    Synchronous MiniCPM-o client with JWT auth and SSE streaming.

    chat() blocks and invokes callbacks; run it in a thread for async use.
    chat_async() spins a QThread and returns an OmniSignals object.
    """

    _TOKEN_TTL = 23 * 3600  # treat as expired before the 24h server expiry

    def __init__(self, config: OmniConfig):
        self.config = config
        self._token: Optional[str] = None
        self._token_time: float = 0.0

    # ── Auth ───────────────────────────────────────────────────────
    def _login(self) -> str:
        try:
            r = requests.post(
                self.config.auth_url,
                json={"username": self.config.username,
                      "password": self.config.password},
                timeout=self.config.connect_timeout,
            )
            r.raise_for_status()
            data = r.json()
            token = data.get("token")
            if not token:
                raise OmniError("Login response missing 'token' field")
            self._token = token
            self._token_time = time.time()
            return token
        except requests.RequestException as e:
            raise OmniError(f"Omni login failed: {e}") from e

    def _token_value(self) -> str:
        if self._token and (time.time() - self._token_time) < self._TOKEN_TTL:
            return self._token
        return self._login()

    def _auth_headers(self) -> dict:
        return {"Authorization": f"Bearer {self._token_value()}"}

    # ── Audio helpers ──────────────────────────────────────────────
    @staticmethod
    def _encode_audio(path: str) -> Optional[str]:
        """Read a WAV file and return base64 string, or None on failure."""
        if not path or not os.path.exists(path):
            return None
        try:
            with open(path, "rb") as f:
                return base64.b64encode(f.read()).decode("ascii")
        except OSError as e:
            print(f"[OmniClient] audio encode error: {e}")
            return None

    def download_audio(self, url: str) -> bytes:
        """Download a WAV file by relative URL (e.g. /api/omni/.../wav_3.wav)."""
        full = self.config.audio_base_url() + url if url.startswith("/") else url
        params = {"token": self._token_value()}
        r = requests.get(full, params=params, timeout=self.config.request_timeout)
        r.raise_for_status()
        return r.content

    # ── Context ────────────────────────────────────────────────────
    def reset_context(self) -> bool:
        try:
            r = requests.post(self.config.reset_url, headers=self._auth_headers(),
                              timeout=self.config.connect_timeout)
            return r.status_code < 300
        except requests.RequestException as e:
            print(f"[OmniClient] reset failed: {e}")
            return False

    def status(self) -> dict:
        """Check server status. Returns dict or raises OmniError."""
        try:
            r = requests.get(self.config.status_url, headers=self._auth_headers(),
                             timeout=self.config.connect_timeout)
            r.raise_for_status()
            return r.json()
        except requests.RequestException as e:
            raise OmniError(f"Omni status check failed: {e}") from e

    # ── Chat (SSE) ─────────────────────────────────────────────────
    def chat(
        self,
        text: str,
        audio_path: Optional[str] = None,
        on_chunk: Optional[Callable[[str], None]] = None,
        on_status: Optional[Callable[[str], None]] = None,
        on_audio: Optional[Callable[[str], None]] = None,
        on_audio_merged: Optional[Callable[[str], None]] = None,
        on_done: Optional[Callable[[], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
    ) -> str:
        """
        Blocking SSE chat. Returns the full accumulated text.

        Raises OmniError on failure. Caller should run in a thread.
        """
        body: dict = {"text": text, "search": None}
        audio_b64 = self._encode_audio(audio_path) if audio_path else None
        if audio_b64:
            body["audio_base64"] = audio_b64
            body["audio_mime"] = "audio/wav"

        # Retry once on 401 (token expired mid-session)
        for attempt in range(2):
            try:
                r = requests.post(
                    self.config.chat_url,
                    headers=self._auth_headers(),
                    json=body,
                    stream=True,
                    timeout=(self.config.connect_timeout, self.config.request_timeout),
                )
                if r.status_code == 401 and attempt == 0:
                    self._token = None
                    continue
                r.raise_for_status()
                break
            except requests.RequestException as e:
                if attempt == 0 and "401" in str(e):
                    self._token = None
                    continue
                msg = f"Omni chat request failed: {e}"
                if on_error:
                    on_error(msg)
                raise OmniError(msg) from e
        else:
            raise OmniError("Omni chat failed after auth retry")

        full_text_parts: list[str] = []
        try:
            for raw in r.iter_lines(decode_unicode=True):
                if not raw:
                    continue
                if not raw.startswith("data: "):
                    continue
                payload = raw[6:]
                if payload == "[DONE]":
                    break
                try:
                    ev = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                self._dispatch_event(ev, full_text_parts, on_chunk, on_status,
                                     on_audio, on_audio_merged, on_error)
        except requests.RequestException as e:
            msg = f"Omni SSE stream interrupted: {e}"
            if on_error:
                on_error(msg)
            raise OmniError(msg) from e

        full = "".join(full_text_parts)
        if on_done:
            on_done()
        return full

    def _dispatch_event(self, ev: dict, parts: list, on_chunk, on_status,
                        on_audio, on_audio_merged, on_error):
        etype = ev.get("type", "")
        if etype == "text":
            frag = ev.get("content", "")
            if frag:
                parts.append(frag)
                if on_chunk:
                    on_chunk(frag)
        elif etype == "status":
            stage = ev.get("stage", "")
            if on_status:
                on_status(stage)
        elif etype == "audio":
            urls = ev.get("urls", []) or []
            for u in urls:
                if on_audio:
                    on_audio(u)
        elif etype == "audio_merged":
            url = ev.get("url", "")
            if on_audio_merged:
                on_audio_merged(url)
        elif etype == "error":
            msg = ev.get("message", "unknown omni error")
            if on_error:
                on_error(msg)
            raise OmniError(msg)

    # ── Chat (async) ───────────────────────────────────────────────
    def chat_async(self, text: str, audio_path: Optional[str] = None) -> OmniSignals:
        """Non-blocking: runs SSE on a QThread, returns signals to connect to."""
        signals = OmniSignals()
        worker = _OmniChatWorker(self, text, audio_path, signals)
        worker.finished.connect(worker.deleteLater)
        worker.start()
        return signals


class _OmniChatWorker(QThread):
    """Internal QThread that runs a blocking OmniClient.chat()."""

    def __init__(self, client: OmniClient, text: str, audio_path: Optional[str],
                 signals: OmniSignals):
        super().__init__()
        self._client = client
        self._text = text
        self._audio_path = audio_path
        self._signals = signals

    def run(self):
        try:
            self._client.chat(
                text=self._text,
                audio_path=self._audio_path,
                on_chunk=self._signals.text_chunk.emit,
                on_status=self._signals.status.emit,
                on_audio=self._signals.audio_url.emit,
                on_audio_merged=self._signals.audio_merged.emit,
                on_done=self._signals.done.emit,
                on_error=self._signals.error.emit,
            )
            # text_done emitted with full text — collect via closure
        except OmniError as e:
            self._signals.error.emit(str(e))


# ──────────────────────────────────────────────────────────────────────
# Audio player
# ──────────────────────────────────────────────────────────────────────
class OmniAudioPlayer(QObject):
    """Downloads omni TTS WAV and plays it via QMediaPlayer (reuses TTSEngine path)."""

    playback_finished = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, client: OmniClient, tts_engine):
        super().__init__()
        self._client = client
        self._tts = tts_engine
        self._temp_files: list[str] = []
        self._player = None
        if tts_engine is not None:
            self._player = getattr(tts_engine, "player", None)

    def play_url(self, url: str):
        """Download a single WAV URL and play it."""
        try:
            wav_bytes = self._client.download_audio(url)
        except Exception as e:
            self.error.emit(str(e))
            return
        path = self._write_temp_wav(wav_bytes)
        if path and self._tts:
            self._tts._play_file(path)

    def _write_temp_wav(self, data: bytes) -> Optional[str]:
        try:
            fd, path = tempfile.mkstemp(suffix="_omni.wav")
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            self._temp_files.append(path)
            return path
        except OSError as e:
            print(f"[OmniAudioPlayer] temp write error: {e}")
            return None

    def cleanup(self):
        """Remove temp WAV files."""
        for p in self._temp_files:
            try:
                os.unlink(p)
            except OSError:
                pass
        self._temp_files.clear()
