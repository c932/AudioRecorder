"""Web 后端共享依赖：引擎单例 + 工具函数。

无 GUI 服务器环境（不装 PyQt6）下，核心引擎依赖 src/core/qt_compat.py
的轻量信号实现，可正常 import 和 emit。
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import subprocess
import tempfile
import threading
from collections import OrderedDict
from typing import Any, Callable, Optional

from src.utils import get_user_data_path

# ---------------------------------------------------------------------- #
# 单例数据/引擎层（单用户局域网场景足够线程安全）
# ---------------------------------------------------------------------- #
_exercise_manager = None
_coach = None
_memorize = None
_recognizer = None


def get_exercise_manager():
    global _exercise_manager
    if _exercise_manager is None:
        from src.core.exercise_manager import ExerciseManager
        _exercise_manager = ExerciseManager(get_user_data_path("words.json"))
    return _exercise_manager


def get_coach():
    global _coach
    if _coach is None:
        from src.core.ai_assessor import PronunciationCoach
        _coach = PronunciationCoach()
    return _coach


def get_memorize():
    global _memorize
    if _memorize is None:
        from src.core.memorize_engine import MemorizeEngine
        _memorize = MemorizeEngine()
    return _memorize


def get_recognizer():
    """Lazy Whisper ASR（跨请求复用，避免重复加载模型）。"""
    global _recognizer
    if _recognizer is None:
        from src.core.speech_recognizer import WhisperRecognizer
        size = load_config().get("whisper_model_size", "medium")
        _recognizer = WhisperRecognizer(model_size=size)
    return _recognizer


# ---------------------------------------------------------------------- #
# 配置读写
# ---------------------------------------------------------------------- #
def load_config() -> dict:
    path = get_user_data_path("config.json")
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {}


def save_config(cfg: dict):
    path = get_user_data_path("config.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------- #
# 音频工具
# ---------------------------------------------------------------------- #
def save_audio_temp(audio_b64: str, audio_format: str = "wav") -> str:
    """解码 base64 音频到临时文件（必要时转 16kHz mono WAV），返回文件路径。"""
    raw = base64.b64decode(audio_b64)
    suffix = "." + (audio_format or "wav").lstrip(".")
    fd, path = tempfile.mkstemp(prefix="web_audio_", suffix=suffix)
    with os.fdopen(fd, "wb") as f:
        f.write(raw)

    fmt = (audio_format or "wav").lower()
    if fmt in ("wav", "mp3"):
        return path
    # 浏览器 MediaRecorder 默认 webm/ogg → 转 WAV 供 GOP/Whisper 使用
    return _convert_to_wav(path)


def _convert_to_wav(path: str) -> str:
    out = path + ".wav"
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-i", path, "-ar", "16000", "-ac", "1", out],
            capture_output=True, check=True, timeout=120,
        )
        return out
    except Exception as e:
        print(f"[deps] ffmpeg conversion failed: {e}")
        return path  # 返回原文件，让下游尽力而为


def cleanup_temp(path: str):
    try:
        os.remove(path)
    except OSError:
        pass
    # 顺带清理可能的转换产物
    try:
        os.remove(path + ".wav")
    except OSError:
        pass


# ---------------------------------------------------------------------- #
# 信号等待：让异步（信号驱动）引擎在同步 HTTP 处理中返回结果
# ---------------------------------------------------------------------- #
def await_signal(engine, done_name: str, error_name: str,
                 trigger: Callable[[], None], timeout: float = 180):
    """运行一个会 emit done/error 信号的异步引擎操作，阻塞等待结果。

    返回 done 信号的参数元组；出错抛 RuntimeError，超时抛 TimeoutError。
    """
    result: dict = {}
    evt = threading.Event()
    done = getattr(engine, done_name)
    err = getattr(engine, error_name)

    def _on_done(*args):
        result["done"] = args
        evt.set()

    def _on_err(*args):
        result["error"] = args
        evt.set()

    done.connect(_on_done)
    err.connect(_on_err)
    try:
        trigger()
        if not evt.wait(timeout):
            raise TimeoutError(f"{done_name} 在 {timeout}s 内未完成")
        if "error" in result:
            raise RuntimeError(result["error"][0] if result["error"] else "未知错误")
        return result.get("done", ())
    finally:
        done.disconnect(_on_done)
        err.disconnect(_on_err)


# ---------------------------------------------------------------------- #
# 无头 TTS：纯英文 → Kokoro ONNX GPU（WAV），含中文 → edge-tts（MP3）
# ---------------------------------------------------------------------- #
def _has_chinese(text: str) -> bool:
    return any('一' <= ch <= '鿿' for ch in text)


# 合成结果缓存：同一文本只合成一次，零延迟重放
_TTS_CACHE: OrderedDict[tuple, tuple[bytes, str]] = OrderedDict()
_TTS_CACHE_LOCK = threading.Lock()
_TTS_CACHE_MAX = 256

_kokoro = None
_kokoro_lock = threading.Lock()


def get_kokoro():
    """Lazy Kokoro ONNX TTS 单例（GPU 加速，纯英文）。

    沿用桌面版 SafeKokoro 模式：手动构建 ONNX Session + 加载 voices.json，
    不依赖 kokoro-onnx 的构造函数（不同版本 API 不同）。
    模型路径：Docker 卷挂载 /app/kokoro/，本地开发可通过环境变量指定。
    """
    global _kokoro
    if _kokoro is None:
        with _kokoro_lock:
            if _kokoro is None:
                model_path = os.environ.get(
                    "KOKORO_MODEL", "/app/kokoro/kokoro-v0_19.onnx"
                )
                voices_path = os.environ.get(
                    "KOKORO_VOICES", "/app/kokoro/voices.json"
                )
                if not os.path.isfile(model_path) or not os.path.isfile(voices_path):
                    raise FileNotFoundError(
                        f"Kokoro 模型未找到（{model_path} / {voices_path}），"
                        "纯英文 TTS 将回退到 edge-tts"
                    )
                print(f"[deps] Loading Kokoro TTS model: {model_path}")

                from kokoro_onnx import Kokoro
                import numpy as np
                import onnxruntime as rt
                from kokoro_onnx.config import KoKoroConfig
                from kokoro_onnx.tokenizer import Tokenizer

                class SafeKokoro(Kokoro):
                    """子类化 Kokoro 以安全加载 JSON 格式的 voices.json。"""
                    def __init__(self, model_path, voices_path,
                                 espeak_config=None, vocab_config=None):
                        self.config = KoKoroConfig(model_path, voices_path, espeak_config)
                        self.config.validate()

                        # GPU 检测：CUDA → 回退 CPU
                        available = rt.get_available_providers()
                        print(f"[Kokoro] ONNX providers: {available}")
                        self.sess = None
                        if "CUDAExecutionProvider" in available:
                            try:
                                self.sess = rt.InferenceSession(
                                    model_path,
                                    providers=["CUDAExecutionProvider", "CPUExecutionProvider"],
                                )
                                print("[Kokoro] Using CUDA GPU")
                            except Exception:
                                self.sess = None
                        if self.sess is None:
                            self.sess = rt.InferenceSession(
                                model_path, providers=["CPUExecutionProvider"]
                            )
                            print("[Kokoro] Using CPU")

                        # 加载 voices（JSON 格式，v0_19 模型配套）
                        import json
                        try:
                            with open(voices_path, "r", encoding="utf-8") as f:
                                data = json.load(f)
                            self.voices = {
                                k: np.array(v, dtype=np.float32) for k, v in data.items()
                            }
                        except (json.JSONDecodeError, UnicodeDecodeError):
                            self.voices = np.load(voices_path, allow_pickle=True)

                        vocab = self._load_vocab(vocab_config)
                        self.tokenizer = Tokenizer(espeak_config, vocab=vocab)

                _kokoro = SafeKokoro(model_path, voices_path)
                print("[deps] Kokoro TTS ready")
    return _kokoro


def _synthesize_kokoro(text: str, voice: str = "af_bella") -> tuple[bytes, str]:
    """用 Kokoro ONNX 合成英文语音（GPU 加速），返回 (WAV bytes, media_type)。"""
    import io

    import soundfile as sf

    kokoro = get_kokoro()
    samples, sr = kokoro.create(text, voice=voice, speed=1.0, lang="en-us")
    buf = io.BytesIO()
    sf.write(buf, samples, sr, format="WAV", subtype="PCM_16")
    return buf.getvalue(), "audio/wav"


def synthesize_tts(text: str, voice: Optional[str] = None) -> tuple[bytes, str]:
    """合成音频字节 + MIME 类型。

    - 纯英文：Kokoro ONNX GPU → WAV（失败回退 edge-tts）
    - 含中文：edge-tts zh-CN-YunxiNeural → MP3
    返回 (audio_bytes, media_type)；相同文本命中缓存，零延迟。
    """
    if not voice and not _has_chinese(text):
        # 纯英文 → 优先 Kokoro GPU
        key = ("kokoro", text)
        with _TTS_CACHE_LOCK:
            cached = _TTS_CACHE.get(key)
        if cached is not None:
            return cached
        try:
            result = _synthesize_kokoro(text)
        except Exception as e:
            print(f"[deps] Kokoro TTS 失败，回退 edge-tts: {e}")
            voice = "en-US-AriaNeural"
        else:
            with _TTS_CACHE_LOCK:
                _TTS_CACHE[key] = result
                while len(_TTS_CACHE) > _TTS_CACHE_MAX:
                    _TTS_CACHE.popitem(last=False)
            return result

    if not voice:
        voice = "zh-CN-YunxiNeural" if _has_chinese(text) else "en-US-AriaNeural"

    # edge-tts（纯英文回退 或 含中文）
    import edge_tts

    key = (text, voice)
    with _TTS_CACHE_LOCK:
        cached = _TTS_CACHE.get(key)
    if cached is not None:
        return cached

    async def _run():
        communicate = edge_tts.Communicate(text, voice)
        chunks = []
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                chunks.append(chunk["data"])
        return b"".join(chunks)

    audio = asyncio.run(_run())
    result = (audio, "audio/mpeg")
    with _TTS_CACHE_LOCK:
        _TTS_CACHE[key] = result
        while len(_TTS_CACHE) > _TTS_CACHE_MAX:
            _TTS_CACHE.popitem(last=False)
    return result


def transcribe_audio(path: str) -> str:
    """用本地 Whisper 转录音频，返回文本。"""
    try:
        return get_recognizer().transcribe(path)
    except Exception as e:
        print(f"[deps] transcription error: {e}")
        return ""
