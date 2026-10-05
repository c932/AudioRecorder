"""中英互译测验路由。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.server.deps import get_exercise_manager, await_signal
from src.core.quiz_engine import QuizEngine

router = APIRouter(prefix="/api/quiz", tags=["quiz"])

_engine = None


def _get_engine() -> QuizEngine:
    global _engine
    if _engine is None:
        _engine = QuizEngine(get_exercise_manager())
    return _engine


class QuizStart(BaseModel):
    groups: list
    count: int = 10


@router.post("/start")
def start_quiz(req: QuizStart):
    """生成测验题目（异步 LLM，阻塞等待完成）。"""
    eng = _get_engine()
    try:
        questions = await_signal(
            eng, "questions_ready", "generation_error",
            lambda: eng.start_quiz(req.groups, req.count),
            timeout=180,
        )[0]
    except TimeoutError as e:
        raise HTTPException(status_code=504, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"questions": questions, "total": len(questions)}


class QuizAnswer(BaseModel):
    question: dict
    user_answer: Any


@router.post("/answer")
def answer_quiz(req: QuizAnswer):
    """校验答案，返回对错 + 正确答案。"""
    eng = _get_engine()
    is_correct = eng.validate_answer(req.question, req.user_answer)
    eng.record_result(req.question, is_correct, req.user_answer)

    correct = req.question.get("answer") or req.question.get("answers", "")
    return {"is_correct": is_correct, "correct_answer": correct}
