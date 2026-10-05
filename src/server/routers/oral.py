"""口语朗读测试路由。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.server.deps import get_exercise_manager, await_signal
from src.core.oral_test_engine import OralTestEngine

router = APIRouter(prefix="/api/oral", tags=["oral"])

_engine = None


def _get_engine() -> OralTestEngine:
    global _engine
    if _engine is None:
        _engine = OralTestEngine(get_exercise_manager())
    return _engine


@router.get("/banks")
def list_banks():
    return {"banks": _get_engine().get_all_banks()}


class GenerateBank(BaseModel):
    groups: list
    count: int = 10


@router.post("/generate")
def generate_bank(req: GenerateBank):
    """生成口语测试题库（异步 LLM，阻塞等待完成）。"""
    eng = _get_engine()
    try:
        bank = await_signal(
            eng, "bank_generation_done", "bank_generation_error",
            lambda: eng.generate_bank(req.groups, req.count),
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


@router.get("/bank/{bank_id}/sentences")
def bank_sentences(bank_id: str):
    sentences = _get_engine().load_bank_sentences(bank_id)
    return {"sentences": sentences}
