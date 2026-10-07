"""发音练习路由：跟读评分 + TTS + 练习会话。"""
from __future__ import annotations

import os
import random
import subprocess

from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from src.server.deps import (
    get_coach, get_exercise_manager, load_config,
    save_audio_temp, cleanup_temp, synthesize_tts,
    get_all_practice_items,
)

router = APIRouter(prefix="/api/practice", tags=["practice"])


class ScoreRequest(BaseModel):
    audio_b64: str
    audio_format: str = "wav"
    reference: str


@router.post("/score")
def score_pronunciation(req: ScoreRequest):
    """录音评分：base64 音频 + 参考文本 → GOP/omni 评分结果。"""
    if not req.reference or not req.reference.strip():
        raise HTTPException(status_code=400, detail="reference 为空")
    if not req.audio_b64:
        raise HTTPException(status_code=400, detail="audio_b64 为空")

    path = save_audio_temp(req.audio_b64, req.audio_format)

    # 诊断：记录音频文件信息
    try:
        size = os.path.getsize(path)
        probe = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries",
             "stream=codec_name,sample_rate,channels,duration",
             "-of", "csv=p=0", path],
            capture_output=True, text=True, timeout=5,
        )
        print(f"[score] audio format={req.audio_format}, size={size}, "
              f"probe={probe.stdout.strip() or probe.stderr.strip()[:100] or 'N/A'}")
    except Exception as e:
        print(f"[score] probe failed: {e}")

    try:
        result = get_coach().assess(path, req.reference)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"评分失败: {e}")
    finally:
        cleanup_temp(path)


class TTSRequest(BaseModel):
    text: str
    voice: Optional[str] = None


@router.post("/tts")
def tts(req: TTSRequest):
    """文本 → 语音（Qwen3-TTS GPU WAV 优先 / edge-tts MP3 回退）。"""
    if not req.text.strip():
        raise HTTPException(status_code=400, detail="text 为空")
    try:
        audio, media_type = synthesize_tts(req.text, voice=req.voice)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"TTS 失败: {e}")
    return Response(content=audio, media_type=media_type)


@router.get("/session")
def practice_session(count: int = 20):
    """开始一轮练习：按配置选词、打乱，返回练习列表。"""
    config = load_config()
    active_groups = config.get("active_groups", []) or None

    full = get_all_practice_items(active_groups)
    if not full:
        raise HTTPException(status_code=404, detail="没有可练习的词条")

    pool = list(full)
    if config.get("strategy_no_repeat", False):
        pool = [i for i in pool if i.get("last_score", 0) < 90]
        if not pool:
            raise HTTPException(status_code=404, detail="所有词条都已掌握")

    if config.get("strategy_smart", True):
        pool.sort(key=lambda x: (x.get("times_practiced", 0), x.get("last_score", 0)))
        if config.get("strategy_random", True):
            # 取前 2N 再打乱，兼顾"优先低分"与"不打乱顺序"
            pool = pool[: count * 2]
            random.shuffle(pool)
    elif config.get("strategy_random", True):
        random.shuffle(pool)

    items = pool[:count]
    return {"items": items, "total": len(items)}
