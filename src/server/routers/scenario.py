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


class GenerateBankFromItems(BaseModel):
    """直接用词条列表生成情景对话（速记页等场景，词条不在词库分组里）。"""
    items: list   # [{text, translation?, ...}]
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


@router.post("/generate-from-items")
def generate_bank_from_items(req: GenerateBankFromItems):
    """用词条列表生成情景对话（词条无需在词库分组中）。"""
    eng = _get_engine()
    # 把 items 临时注入 ExerciseManager 为虚拟分组，再传分组名给引擎
    import uuid as _uuid
    temp_group = f"_temp_{_uuid.uuid4().hex[:8]}"
    mgr = get_exercise_manager()
    items_to_add = []
    for it in req.items:
        if isinstance(it, dict):
            item = {**it, "group": temp_group}
        else:
            item = {"text": str(it), "group": temp_group}
        items_to_add.append(item)
    mgr.add_exercises(items_to_add, "words")
    name = req.name or f"速记 {len(items_to_add)} 词"
    try:
        bank = await_signal(
            eng, "bank_generation_done", "bank_generation_error",
            lambda: eng.generate_bank([temp_group], req.turn_count, name, True),
            timeout=300,
        )[0]
    except TimeoutError as e:
        raise HTTPException(status_code=504, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        # 清理临时分组（无论成功或失败）
        mgr.delete_group(temp_group)
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
