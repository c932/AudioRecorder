"""AI 家教路由。

TutorEngine 是有状态的多轮状态机。一次学生输入可能触发引擎连发多个
tutor_action_ready（先 feedback、再自动推进到下一阶段的 prompt），这里把
一次触发的所有 action 收集齐再返回，前端按顺序渲染成聊天气泡。

链式判定：引擎自动推进（_advance_after_feedback / _next_word）总是先
emit session_state_updated 再发起下一个 LLM 请求，因此收到 feedback 后
观察 state 序号是否变化，即可判断是否还有后续 action，无竞态。
"""
from __future__ import annotations

import threading
import time
from typing import Callable, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.server.deps import (
    get_exercise_manager, get_coach, get_recognizer,
    save_audio_temp, cleanup_temp,
)
from src.core.tutor_engine import TutorEngine

router = APIRouter(prefix="/api/tutor", tags=["tutor"])

_engine: Optional[TutorEngine] = None
_last_state: dict = {}
_state_lock = threading.Lock()

_action_queue: list = []
_pending_error: list = []
_state_seq = 0
_action_cond = threading.Condition()


def _get_engine() -> TutorEngine:
    global _engine
    if _engine is None:
        _engine = TutorEngine(get_exercise_manager())
        _engine.session_state_updated.connect(_on_state)
        _engine.tutor_action_ready.connect(_on_action)
        _engine.error_occurred.connect(_on_error)
    return _engine


def _on_state(state: dict):
    global _last_state, _state_seq
    with _state_lock:
        _last_state = state
    with _action_cond:
        _state_seq += 1
        _action_cond.notify_all()


def _on_action(action: dict):
    with _action_cond:
        _action_queue.append(action)
        _action_cond.notify_all()


def _on_error(msg: str):
    with _action_cond:
        _pending_error.append(msg)
        _action_cond.notify_all()


def _get_state() -> dict:
    with _state_lock:
        return dict(_last_state)


def _wait_action(timeout: float) -> Optional[dict]:
    """等下一个 action。state 更新也会唤醒等待，但只有 action 算结果。"""
    deadline = time.time() + timeout
    with _action_cond:
        while not _action_queue:
            remaining = deadline - time.time()
            if remaining <= 0:
                return None
            _action_cond.wait(remaining)
        return _action_queue.pop(0)


def _pop_error() -> Optional[str]:
    with _action_cond:
        if _pending_error:
            return _pending_error.pop(0)
    return None


def _await_actions(trigger: Callable[[], None],
                   first_timeout: float = 180,
                   chain_timeout: float = 120) -> dict:
    """触发一个引擎操作，收集它连发的所有 action 再返回。

    学生输入（answer/text/choice）后引擎收到 LLM feedback 会自动推进到
    下一阶段并再发一个 action —— 继续等；其余 action（提问/选择/结束）
    意味着轮到学生了，立即返回。
    """
    with _action_cond:
        _action_queue.clear()
        _pending_error.clear()
    trigger()
    # 基线在 trigger 之后取：choice/pronunciation 会在 trigger 内同步切换
    # phase 并 emit state，之后发生的 state 变化才意味着「自动推进」。
    with _action_cond:
        seq = _state_seq

    actions: list = []
    while True:
        timeout = first_timeout if not actions else chain_timeout
        action = _wait_action(timeout)
        if action is None:
            error = _pop_error()
            if error and not actions:
                raise RuntimeError(error)
            break
        actions.append(action)
        if action.get("action") != "feedback":
            break
        # feedback：引擎自动推进会紧跟着 emit 一次 state 更新。短暂观察
        # 序号变化——变了说明还有后续 action（下一阶段的 LLM 请求）。
        with _action_cond:
            deadline = time.time() + 1.0
            while _state_seq == seq and time.time() < deadline:
                _action_cond.wait(max(0.01, deadline - time.time()))
            chained = _state_seq != seq
            seq = _state_seq
        if not chained:
            break

    if not actions:
        raise TimeoutError("AI 没有在规定时间内回复")
    resp: dict = {"actions": actions, "state": _get_state()}
    error = _pop_error()
    if error:
        resp["error"] = error
    return resp


def _run(trigger: Callable[[], None]) -> dict:
    try:
        return _await_actions(trigger)
    except TimeoutError as e:
        raise HTTPException(status_code=504, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------- #
class TutorStart(BaseModel):
    topic: str
    vocabulary: list


@router.post("/start")
def start(req: TutorStart):
    if not req.vocabulary:
        raise HTTPException(status_code=400, detail="vocabulary 为空")
    eng = _get_engine()
    return _run(lambda: eng.start_session(req.topic, req.vocabulary))


class TutorAudio(BaseModel):
    audio_b64: str
    audio_format: str = "wav"


@router.post("/pronunciation")
def pronunciation(req: TutorAudio):
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

    resp = _run(lambda: eng.handle_pronunciation_result(score, feedback))
    resp["score"] = score
    resp["feedback"] = feedback
    return resp


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

    resp = _run(lambda: eng.handle_asr_result(text))
    resp["recognized"] = text
    return resp


class TutorText(BaseModel):
    text: str


@router.post("/text")
def answer_text(req: TutorText):
    """文本回答（含义/造句/微对话阶段）。"""
    eng = _get_engine()
    if eng.current_word is None:
        raise HTTPException(status_code=400, detail="会话未开始")
    return _run(lambda: eng.handle_asr_result(req.text))


class TutorChoice(BaseModel):
    chosen: str
    correct: str


@router.post("/choice")
def choice(req: TutorChoice):
    """选择题作答。"""
    eng = _get_engine()
    if eng.current_word is None:
        raise HTTPException(status_code=400, detail="会话未开始")
    return _run(lambda: eng.handle_choice_answer(req.chosen, req.correct))


@router.get("/state")
def state():
    return {"state": _get_state()}


@router.get("/summary")
def summary():
    return _get_engine().get_session_summary()


@router.post("/stop")
def stop():
    _get_engine().stop_session()
    return {"ok": True}
