"""Qwen3-TTS FastAPI 服务 — 中英文 TTS，内置音色，无需参考音频。"""
from __future__ import annotations

import io
import os
import argparse
import logging

import numpy as np
import soundfile as sf
import uvicorn
from fastapi import FastAPI, Form
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware

logging.getLogger("matplotlib").setLevel(logging.WARNING)

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 全局模型引用
model = None

# 内置音色列表
SPEAKERS = {
    # 中文
    "Vivian": {"language": "Chinese", "desc": "明亮年轻女声"},
    "Serena": {"language": "Chinese", "desc": "温柔年轻女声"},
    "Uncle_Fu": {"language": "Chinese", "desc": "沉稳男声"},
    "Dylan": {"language": "Chinese", "desc": "京腔男声"},
    "Eric": {"language": "Chinese", "desc": "川腔男声"},
    # 英文
    "Ryan": {"language": "English", "desc": "Dynamic English male"},
    "Aiden": {"language": "English", "desc": "Sunny American male"},
    # 日韩
    "Ono_Anna": {"language": "Japanese", "desc": "俏皮日文女声"},
    "Sohee": {"language": "Korean", "desc": "温暖韩文女声"},
}

# 音色名映射（中文名 → 内置 speaker ID）
VOICE_MAP = {
    "英文女": "Aiden",   # Qwen3-TTS 无英文女声，用男声先代替
    "英文男": "Aiden",
    "en_female": "Aiden",
    "en_male": "Aiden",
    "中文女": "Vivian",
    "中文男": "Uncle_Fu",
    "zh_female": "Vivian",
    "zh_male": "Uncle_Fu",
    "Ryan": "Ryan",
    "Aiden": "Aiden",
    "Vivian": "Vivian",
    "Serena": "Serena",
    "Uncle_Fu": "Uncle_Fu",
    "Dylan": "Dylan",
    "Eric": "Eric",
}

# 语言检测
def _detect_lang(text: str) -> str:
    if any('一' <= ch <= '鿿' for ch in text):
        return "Chinese"
    return "English"


@app.get("/speakers")
async def list_speakers():
    """列出可用音色。"""
    return {"speakers": {k: v for k, v in SPEAKERS.items()}}


@app.post("/tts")
async def tts(
    text: str = Form(),
    speaker: str = Form(default=""),
    language: str = Form(default=""),
    instruct: str = Form(default=""),
):
    """文本 → 语音。返回 PCM int16 24kHz mono 流。"""
    if not text.strip():
        return StreamingResponse(iter([]), media_type="audio/pcm")

    # 解析音色
    spk = VOICE_MAP.get(speaker, speaker) if speaker else ""
    if spk and spk in SPEAKERS:
        lang = language or SPEAKERS[spk]["language"]
    else:
        # 自动检测语言，选默认音色
        lang = language or _detect_lang(text)
        spk = "Vivian" if lang == "Chinese" else "Aiden"

    try:
        wavs, sr = model.generate_custom_voice(
            text=text,
            language=lang,
            speaker=spk,
            instruct=instruct,
        )
    except Exception as e:
        logging.error(f"TTS generation failed: {e}")
        return StreamingResponse(iter([]), media_type="audio/pcm")

    # 转为 PCM int16 流
    def generate():
        for wav in wavs:
            # wav 是 numpy float32 数组 → int16
            pcm = (wav * 32767).clip(-32768, 32767).astype(np.int16).tobytes()
            yield pcm

    return StreamingResponse(generate(), media_type="audio/pcm")


@app.post("/tts_wav")
async def tts_wav(
    text: str = Form(),
    speaker: str = Form(default=""),
    language: str = Form(default=""),
    instruct: str = Form(default=""),
):
    """文本 → WAV 文件。返回完整 WAV bytes。"""
    if not text.strip():
        return StreamingResponse(iter([]), media_type="audio/wav")

    spk = VOICE_MAP.get(speaker, speaker) if speaker else ""
    if spk and spk in SPEAKERS:
        lang = language or SPEAKERS[spk]["language"]
    else:
        lang = language or _detect_lang(text)
        spk = "Vivian" if lang == "Chinese" else "Aiden"

    try:
        wavs, sr = model.generate_custom_voice(
            text=text,
            language=lang,
            speaker=spk,
            instruct=instruct,
        )
    except Exception as e:
        logging.error(f"TTS generation failed: {e}")
        return StreamingResponse(iter([]), media_type="audio/wav")

    # 合并所有 chunk 为一个 WAV
    full_wav = np.concatenate(wavs)
    buf = io.BytesIO()
    sf.write(buf, full_wav, sr, format='WAV', subtype='PCM_16')
    buf.seek(0)
    return StreamingResponse(buf, media_type="audio/wav")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=50000)
    parser.add_argument("--model_dir", type=str, default="Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice")
    args = parser.parse_args()

    from qwen_tts import Qwen3TTSModel
    import torch

    # 从 ModelScope 下载模型（如果本地不存在）
    model_dir = args.model_dir
    if not os.path.exists(model_dir):
        from modelscope import snapshot_download
        cache_dir = os.environ.get("MODELSCOPE_CACHE", "/opt/qwen-tts/models")
        model_dir = snapshot_download(model_dir, cache_dir=cache_dir)
        print(f"[qwen-tts] Model downloaded from ModelScope to: {model_dir}")

    dtype = torch.bfloat16 if torch.cuda.is_available() else torch.float32

    # flash-attn 可选加速
    attn_impl = "flash_attention_2" if torch.cuda.is_available() else "sdpa"
    try:
        import flash_attn  # noqa: F401
    except ImportError:
        attn_impl = "sdpa"

    model = Qwen3TTSModel.from_pretrained(
        model_dir,
        device_map="cuda:0" if torch.cuda.is_available() else "cpu",
        dtype=dtype,
        attn_implementation=attn_impl,
    )
    print(f"[qwen-tts] Model loaded: {model_dir}, dtype={dtype}, device={'cuda' if torch.cuda.is_available() else 'cpu'}, attn={attn_impl}")

    # 用模型 API 验证音色
    try:
        supported = model.get_supported_speakers()
        print(f"[qwen-tts] Model supported speakers: {supported}")
    except Exception:
        print(f"[qwen-tts] Available speakers (hardcoded): {list(SPEAKERS.keys())}")

    uvicorn.run(app, host="0.0.0.0", port=args.port)
