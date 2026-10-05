"""AI 家教路由。

TutorEngine 是有状态的多轮状态机，用单例承载会话。每次调用通过
await_signal 阻塞等待引擎的下一个 tutor_action_ready（LLM 响应）。
"""
from __future__ import annotations

import threading
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.server.deps import (
    get_exercise_manager, get_coach, get_recognizer, await_signal,
    save_audio_temp, cleanup_temp,
)
from src.core.tutor_engine import TutorEngine

router = APIRouter(prefix="/api/tutor", tags=["tutor"])

_engine: Optional[TutorEngine] = None
_last_state: dict = {}
_state_lock = threading.Lock()


def _get_engine() -> TutorEngine:
    global _engine
    if _engine is None:
        _engine = TutorEngine(get_exercise_manager())
        _engine.session_state_updated.connect(_on_state)
    return _engine


def _on_state(state: dict):
    global _last_state
    with _state_lock:
        _last_state = state


def _get_state() -> dict:
    with _state_lock:
        return dict(_last_state)


def _await_action(trigger, timeout=180) -> dict:
    """触发一个引擎操作，阻塞等待下一个 tutor_action_ready。"""
    eng = _get_engine()
    try:
        action = await_signal(
            eng, "tutor_action_ready", "error_occurred", trigger, timeout
        )[0]
    except TimeoutError as e:
        raise HTTPException(status_code=504, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"action": action, "state": _get_state()}


# ---------------------------------------------------------------------- #
class TutorStart(BaseModel):
    topic: str
    vocabulary: list


@router.post("/start")
def start(req: TutorStart):
    if not req.vocabulary:
        raise HTTPException(status_code=400, detail="vocabulary 为空")
    eng = _get_engine()

    def _start():
        eng.start_session(req.topic, req.vocabulary)

    return _await_action(_start)


class TutorPronunciation(BaseModel):
    audio_b64: str
    audio_format: str = "wav"


@router.post("/pronunciation")
def pronunciation(req: TutorPronunciation):
    """跟读评分：GOP/omni 打分后交给引擎推进状态。"""
    eng = _get_engine()
    word = eng.current_word
    if not word:
        raise HTTPException(status_code=400, detail="会话未开始")
    reference = word.get("text", "")

    path = save_audio_temp(req.audio_b64, req.audio_format)
    try:
        result = get_coach().assess(path, reference)
        score = int(result.get("accuracy_score", 0))
        feedback = result.get("feedback", "")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"评分失败: {e}")
    finally:
        cleanup_temp(path)

    resp = _await_action(lambda: eng.handle_pronunciation_result(score, feedback))
    resp["score"] = score
    resp["feedback"] = feedback
    return resp


class TutorAudio(BaseModel):
    audio_b64: str
    audio_format: str = "wav"


@router.post("/answer")
def answer(req: TutorAudio):
    """录音回答（含义/造句/微对话阶段）：ASR 转写后交给引擎。"""
    eng = _get_engine()
    if eng.current_word is None:
        raise HTTPException(status_code=400, detail="会话未开始")

    path = save_audio_temp(req.audio_b64, req.audio_format)
    try:
        text = get_recognizer().transcribe(path, language="en")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"识别失败: {e}")
    finally:
        cleanup_temp(path)

    return _await_action(lambda: eng.handle_asr_result(text))


class TutorText(BaseModel):
    text: str


@router.post("/text")
def answer_text(req: TutorText):
    """文本回答（含义/造句/微对话阶段）。"""
    eng = _get_engine()
    if eng.current_word is None:
        raise HTTPException(status_code=400, detail="会话未开始")
    return _await_action(lambda: eng.handle_asr_result(req.text))


class TutorChoice(BaseModel):
    chosen: str
    correct: str


@router.post("/choice")
def choice(req: TutorChoice):
    """选择题作答。"""
    eng = _get_engine()
    if eng.current_word is None:
        raise HTTPException(status_code=400, detail="会话未开始")
    return _await_action(lambda: eng.handle_choice_answer(req.chosen, req.correct))


@router.get("/state")
def state():
    return {"state": _get_state()}


@router.get("/summary")
def summary():
    eng = _get_engine()
    return eng.get_session_summary()


@router.post("/stop")
def stop():
    _get_engine().stop_session()
    return {"ok": True}
