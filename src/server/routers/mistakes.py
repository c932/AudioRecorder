"""错题本路由。"""
from __future__ import annotations

from fastapi import APIRouter

from src.server.deps import get_exercise_manager

router = APIRouter(prefix="/api/mistakes", tags=["mistakes"])


@router.get("")
def mistakes():
    mgr = get_exercise_manager()
    full = mgr.exercises.get("words", []) + mgr.exercises.get("sentences", [])

    # 口语错题：练过且分数 < 80
    oral = [i for i in full if i.get("times_practiced", 0) > 0 and i.get("last_score", 0) < 80]
    oral.sort(key=lambda x: x.get("last_score", 999))

    # 翻译错题：quiz_wrong > 0
    quiz = [i for i in full if i.get("quiz_wrong", 0) > 0]
    quiz.sort(key=lambda x: -x.get("quiz_wrong", 0))

    return {"oral": oral, "quiz": quiz}
