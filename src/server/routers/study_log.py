"""学习记录 API — 开始/更新/结束学习，查询记录，统计，删除。"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from src.server.deps import get_study_log

router = APIRouter(prefix="/api/study-log", tags=["study-log"])


# ── 请求模型 ────────────────────────────────────────────────────────── #

class StartRequest(BaseModel):
    module: str
    module_label: str


class UpdateRequest(BaseModel):
    snapshot: Optional[Any] = None
    content_summary: str = ""


class EndRequest(BaseModel):
    content_summary: str = ""
    snapshot: Optional[Any] = None
    status: str = "completed"


# ── 端点 ────────────────────────────────────────────────────────────── #

@router.post("/start")
def start_study(req: StartRequest):
    """开始一次学习，返回新建的记录（含 id）。"""
    mgr = get_study_log()
    rec = mgr.start(req.module, req.module_label)
    return rec


@router.put("/update/{record_id}")
def update_study(record_id: str, req: UpdateRequest):
    """更新学习进度快照。"""
    mgr = get_study_log()
    ok = mgr.update(record_id, snapshot=req.snapshot, content_summary=req.content_summary)
    if not ok:
        raise HTTPException(404, "记录不存在")
    return {"ok": True}


@router.post("/end/{record_id}")
def end_study(record_id: str, req: EndRequest):
    """结束一次学习，计算时长并持久化。"""
    mgr = get_study_log()
    rec = mgr.end(record_id, content_summary=req.content_summary,
                   snapshot=req.snapshot, status=req.status)
    if not rec:
        raise HTTPException(404, "记录不存在")
    return rec


@router.get("/records")
def list_records(
    module: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """查询学习记录列表。"""
    mgr = get_study_log()
    return {"records": mgr.list_records(
        module=module, status=status,
        date_from=date_from, date_to=date_to,
        limit=limit, offset=offset,
    )}


@router.get("/stats")
def get_stats():
    """统计汇总：今日/本周时长、连续天数、模块占比等。"""
    mgr = get_study_log()
    return mgr.stats()


@router.delete("/{record_id}")
def delete_study(record_id: str):
    """删除一条学习记录。"""
    mgr = get_study_log()
    ok = mgr.delete(record_id)
    if not ok:
        raise HTTPException(404, "记录不存在")
    return {"ok": True}
