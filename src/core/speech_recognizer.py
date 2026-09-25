"""
SpeechRecognizer - ASR abstraction layer.

Provides a unified interface for speech-to-text transcription.
Current implementation: WhisperRecognizer (local openai-whisper).
Future: OmniRecognizer, RemoteRecognizer, etc.
"""
import os
import threading
from abc import ABC, abstractmethod


class SpeechRecognizer(ABC):
    """Abstract base class for speech recognition."""

    @abstractmethod
    def transcribe(self, audio_path: str, language: str = "en") -> str:
        """Transcribe audio file to text.

        Args:
            audio_path: Path to WAV/audio file.
            language: Language hint (default "en").

        Returns:
            Transcribed text string, or empty string if nothing detected.
        """
        ...

    @abstractmethod
    def is_ready(self) -> bool:
        """Check if the recognizer model is loaded and ready."""
        ...

    @abstractmethod
    def warmup(self) -> None:
        """Pre-load the model. May take seconds (blocking)."""
        ...


class WhisperRecognizer(SpeechRecognizer):
    """Local Whisper (openai-whisper) recognizer.

    Lazy-loads the model on first transcribe() call.
    Falls back to CPU if GPU OOM occurs.
    """

    def __init__(self, model_size: str = "medium", device: str = "auto"):
        """
        Args:
            model_size: Whisper model size (tiny/base/small/medium/large).
            device: "auto" (try cuda then cpu), "cuda", or "cpu".
        """
        self._model_size = model_size
        self._device_pref = device
        self._model = None
        self._lock = threading.Lock()
        self._actual_device = None

    def is_ready(self) -> bool:
        return self._model is not None

    def warmup(self) -> None:
        """Load the Whisper model. Thread-safe, idempotent."""
        if self._model is not None:
            return
        with self._lock:
            if self._model is not None:
                return
            self._load_model()

    def transcribe(self, audio_path: str, language: str = "en") -> str:
        """Transcribe audio using Whisper."""
        if not os.path.exists(audio_path):
            print(f"[WhisperRecognizer] Audio file not found: {audio_path}")
            return ""

        self.warmup()

        if self._model is None:
            print("[WhisperRecognizer] Model failed to load.")
            return ""

        try:
            import torch
            use_fp16 = (self._actual_device == "cuda" and torch.cuda.is_available())
            result = self._model.transcribe(
                audio_path,
                language=language,
                fp16=use_fp16,
            )
            text = (result.get("text") or "").strip()
            print(f"[WhisperRecognizer] Transcribed: '{text}'")
            return text
        except Exception as e:
            print(f"[WhisperRecognizer] Transcription error: {e}")
            return ""

    def _load_model(self):
        """Internal model loading with GPU fallback."""
        import torch

        device = self._device_pref
        if device == "auto":
            device = "cuda" if torch.cuda.is_available() else "cpu"

        print(f"[WhisperRecognizer] Loading Whisper '{self._model_size}' on {device}...")

        try:
            import whisper
            self._model = whisper.load_model(self._model_size, device=device)
            self._actual_device = device
            print(f"[WhisperRecognizer] Model loaded on {device}.")
        except (RuntimeError, torch.cuda.OutOfMemoryError) as e:
            if device == "cuda":
                print(f"[WhisperRecognizer] GPU load failed ({e}), falling back to CPU...")
                try:
                    import whisper
                    self._model = whisper.load_model(self._model_size, device="cpu")
                    self._actual_device = "cpu"
                    print("[WhisperRecognizer] Model loaded on CPU (fallback).")
                except Exception as e2:
                    print(f"[WhisperRecognizer] CPU fallback also failed: {e2}")
                    self._model = None
            else:
                print(f"[WhisperRecognizer] Load failed: {e}")
                self._model = None
        except Exception as e:
            print(f"[WhisperRecognizer] Unexpected load error: {e}")
            self._model = None
