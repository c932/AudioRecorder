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
# 无头 TTS：Qwen3-TTS GPU（中英文，内置音色）→ edge-tts 回退
# ---------------------------------------------------------------------- #
def _has_chinese(text: str) -> bool:
    return any('一' <= ch <= '鿿' for ch in text)


# 合成结果缓存：同一文本只合成一次，零延迟重放
_TTS_CACHE: OrderedDict[tuple, tuple[bytes, str]] = OrderedDict()
_TTS_CACHE_LOCK = threading.Lock()
_TTS_CACHE_MAX = 256


def _tts_url() -> str:
    """从 config.json 读取 TTS 服务地址，默认 host.docker.internal:50000。"""
    cfg = load_config()
    url = cfg.get("cosyvoice_url", "").strip().rstrip("/")
    if not url:
        # Docker 容器内：TTS 跑在宿主机
        url = "http://host.docker.internal:50000"
    return url


def _detect_lang(text: str) -> str:
    """根据文本内容判断语言：含中文字符 → zh，否则 → en。"""
    return "zh" if _has_chinese(text) else "en"


# 音色名 → Qwen3-TTS 内置音色映射
_VOICE_MAP = {
    "英文女": "Aiden",
    "英文男": "Aiden",
    "中文女": "Vivian",
    "中文男": "Uncle_Fu",
    "en_female": "Aiden",
    "en_male": "Aiden",
    "zh_female": "Vivian",
    "zh_male": "Uncle_Fu",
}

# Qwen3-TTS 语言名
_LANG_MAP = {"en": "English", "zh": "Chinese"}


def _resolve_speaker(voice: str | None, lang: str) -> str:
    """根据 voice 名称和语言返回 Qwen3-TTS 内置音色 ID。"""
    if voice:
        mapped = _VOICE_MAP.get(voice)
        if mapped:
            return mapped
    return "Aiden" if lang == "en" else "Vivian"


def _pcm_to_wav(pcm_data: bytes, sample_rate: int = 24000) -> tuple[bytes, str]:
    """将 raw PCM int16 mono 封装为 WAV。"""
    import wave
    from io import BytesIO

    buf = BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_data)
    return buf.getvalue(), "audio/wav"


def _synthesize_qwen_tts(text: str, speaker: str = "", lang: str = "en") -> tuple[bytes, str]:
    """用 Qwen3-TTS FastAPI 服务合成语音（GPU 加速，中英文原生），返回 (WAV bytes, media_type)。

    Qwen3-TTS 内置 9 种音色，无需参考音频。
    """
    import requests

    url = _tts_url()
    data = {
        "text": text,
        "speaker": speaker,
        "language": _LANG_MAP.get(lang, "English"),
    }

    resp = requests.post(f"{url}/tts", data=data, timeout=60)
    if resp.status_code != 200:
        raise RuntimeError(f"Qwen3-TTS 返回 {resp.status_code}: {resp.text[:200]}")
    pcm_data = resp.content
    if len(pcm_data) < 100:
        raise RuntimeError("Qwen3-TTS 返回空音频")
    return _pcm_to_wav(pcm_data)


def synthesize_tts(text: str, voice: Optional[str] = None) -> tuple[bytes, str]:
    """合成音频字节 + MIME 类型。

    主引擎：Qwen3-TTS（中英文，内置音色，无需参考音频）。
    回退：edge-tts（中英文均可）。
    """
    lang = _detect_lang(text)
    speaker = _resolve_speaker(voice, lang)

    # --- Qwen3-TTS 优先（中英文） ---
    tts_key = ("qwen-tts", speaker, text)
    with _TTS_CACHE_LOCK:
        cached = _TTS_CACHE.get(tts_key)
    if cached is not None:
        return cached
    try:
        result = _synthesize_qwen_tts(text, speaker, lang)
    except Exception as e:
        print(f"[deps] Qwen3-TTS 失败，回退 edge-tts: {e}")
    else:
        with _TTS_CACHE_LOCK:
            _TTS_CACHE[tts_key] = result
            while len(_TTS_CACHE) > _TTS_CACHE_MAX:
                _TTS_CACHE.popitem(last=False)
        return result

    # --- edge-tts 回退（中英文） ---
    if lang == "en":
        en_voice_map = {"英文女": "en-US-AriaNeural", "英文男": "en-US-GuyNeural"}
        edge_voice = en_voice_map.get(voice, "") if voice else ""
        if not edge_voice:
            edge_voice = voice if voice and voice not in ("中文女", "中文男") else "en-US-AriaNeural"
    else:
        zh_voice_map = {"中文女": "zh-CN-XiaoxiaoNeural", "中文男": "zh-CN-YunxiNeural"}
        edge_voice = zh_voice_map.get(voice, "") if voice else ""
        if not edge_voice:
            edge_voice = "zh-CN-XiaoxiaoNeural"
    return _synthesize_edge(text, edge_voice)


def _synthesize_edge(text: str, voice: str) -> tuple[bytes, str]:
    """edge-tts 合成，返回 (audio_bytes, media_type)。"""
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


# ---------------------------------------------------------------------- #
# 词库合并：exercise_manager 词库 + memorize 速记模块
# ---------------------------------------------------------------------- _
import re as _re

_MEMORIZE_DAY_RE = _re.compile(r"^速记Day(\d+)$")


def get_all_practice_items(groups: list[str] | None = None) -> list[dict]:
    """返回合并后的全部词条（exercise_manager + memorize），按 groups 过滤。

    groups 为空或 None 时返回全部词条。
    当 groups 包含速记DayN 格式时，自动加载对应速记模块的词条。
    """
    mgr = get_exercise_manager()
    words = mgr.exercises.get("words", [])
    sentences = mgr.exercises.get("sentences", [])
    full = words + sentences

    # 如果需要速记模块，加载并合并
    if groups and any(_MEMORIZE_DAY_RE.match(g) for g in groups):
        try:
            eng = get_memorize()
            existing_keys = {(i.get("text", ""), i.get("group", "")) for i in full}
            for d in eng.get_days():
                day_no = d.get("day")
                group = f"速记Day{day_no}"
                for entry in eng.get_day_entries(day_no):
                    text = entry.get("text", "").strip()
                    if text:
                        key = (text, group)
                        if key not in existing_keys:
                            full.append({
                                "text": text,
                                "phonetic": entry.get("pos", ""),
                                "translation": entry.get("translation", ""),
                                "group": group,
                            })
                            existing_keys.add(key)
        except Exception as e:
            print(f"[deps] 加载速记词条失败: {e}")

    if groups:
        full = [i for i in full if i.get("group", "Default") in groups]

    return full
