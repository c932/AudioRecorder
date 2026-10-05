"""分类速记（28天计划）路由。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.server.deps import get_memorize

router = APIRouter(prefix="/api/memorize", tags=["memorize"])


@router.get("/days")
def list_days():
    """返回全部 28 天模块（含当天词数、是否已开始）。"""
    eng = get_memorize()
    days = []
    for d in eng.get_days():
        day_no = d.get("day")
        entries = eng.get_day_entries(day_no)
        days.append({
            "day": day_no,
            "title": d.get("title", f"Day {day_no}"),
            "count": len(entries),
            "started": eng.is_started(day_no),
            "progress": eng.get_module_progress(day_no),
        })
    return {"days": days}


@router.get("/day/{day_no}")
def get_day(day_no: int):
    """返回某天的全部词条 + 进度。"""
    eng = get_memorize()
    entries = eng.get_day_entries(day_no)
    if not entries:
        raise HTTPException(status_code=404, detail=f"Day {day_no} 不存在")
    return {
        "day": day_no,
        "entries": entries,
        "progress": eng.get_module_progress(day_no),
    }


@router.get("/due")
def due_reviews():
    """返回今天应复习的模块。"""
    return {"due": get_memorize().get_due_reviews()}


class StartModule(BaseModel):
    day: int


@router.post("/start")
def start_module(req: StartModule):
    eng = get_memorize()
    if not eng.get_day(req.day):
        raise HTTPException(status_code=404, detail=f"Day {req.day} 不存在")
    eng.start_module(req.day)
    return {"ok": True, "progress": eng.get_module_progress(req.day)}


@router.post("/review")
def complete_review(req: StartModule):
    eng = get_memorize()
    ok = eng.complete_review(req.day)
    if not ok:
        raise HTTPException(status_code=400, detail=f"Day {req.day} 尚未开始")
    return {"ok": True, "progress": eng.get_module_progress(req.day)}
