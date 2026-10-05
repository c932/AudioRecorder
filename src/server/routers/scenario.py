"""情景会话路由。"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.server.deps import get_exercise_manager, await_signal
from src.core.scenario_engine import ScenarioEngine

router = APIRouter(prefix="/api/scenario", tags=["scenario"])

_engine = None


def _get_engine() -> ScenarioEngine:
    global _engine
    if _engine is None:
        _engine = ScenarioEngine(get_exercise_manager())
    return _engine


@router.get("/banks")
def list_banks():
    return {"banks": _get_engine().get_all_banks()}


class GenerateBank(BaseModel):
    groups: list
    turn_count: Optional[int] = None
    name: Optional[str] = None


@router.post("/generate")
def generate_bank(req: GenerateBank):
    """生成情景对话题库（异步 LLM，阻塞等待完成）。"""
    eng = _get_engine()
    try:
        bank = await_signal(
            eng, "bank_generation_done", "bank_generation_error",
            lambda: eng.generate_bank(req.groups, req.turn_count, req.name, True),
            timeout=300,
        )[0]
    except TimeoutError as e:
        raise HTTPException(status_code=504, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"bank": bank}


@router.get("/bank/{bank_id}")
def get_bank(bank_id: str):
    bank = _get_engine().get_bank_by_id(bank_id)
    if not bank:
        raise HTTPException(status_code=404, detail="题库不存在")
    return {"bank": bank}


class SummaryRequest(BaseModel):
    session_results: list
    scenario_title: str = ""


@router.post("/summary")
def summary(req: SummaryRequest):
    """生成会话总结（异步 LLM，阻塞等待完成）。"""
    eng = _get_engine()
    try:
        text = await_signal(
            eng, "summary_ready", "summary_error",
            lambda: eng.summarize_session(req.session_results, req.scenario_title),
            timeout=120,
        )[0]
    except TimeoutError as e:
        raise HTTPException(status_code=504, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"summary": text}
