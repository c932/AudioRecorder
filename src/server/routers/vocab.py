"""词库管理路由。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.server.deps import get_exercise_manager

router = APIRouter(prefix="/api/vocab", tags=["vocab"])


@router.get("/groups")
def list_groups():
    """返回分组列表及词数。"""
    mgr = get_exercise_manager()
    counts = mgr.get_group_word_counts()
    groups = [
        {"name": g, "count": counts.get(g, 0)}
        for g in mgr.get_groups()
    ]
    return {"groups": groups}


@router.get("/words")
def list_words(group: str = ""):
    """返回某分组的全部词条（不传 group 返回全部）。"""
    mgr = get_exercise_manager()
    words = mgr.exercises.get("words", [])
    sentences = mgr.exercises.get("sentences", [])
    full = words + sentences
    if group:
        full = [i for i in full if i.get("group", "Default") == group]
    return {"items": full}


class ImportText(BaseModel):
    text: str
    group: str = "Default"


@router.post("/import-text")
def import_text(req: ImportText):
    """从纯文本导入词条，每行一条「英文 中文」或「英文,中文」。"""
    import re
    lines = [l.strip() for l in req.text.splitlines() if l.strip()]
    items = []
    for line in lines:
        # 支持 tab / 逗号 / 多个空格 分隔
        parts = re.split(r"[\t,，]+", line, maxsplit=1)
        if len(parts) == 2:
            en, zh = parts[0].strip(), parts[1].strip()
        else:
            parts = re.split(r"\s{2,}", line, maxsplit=1)
            if len(parts) == 2:
                en, zh = parts[0].strip(), parts[1].strip()
            else:
                en, zh = line, ""
        if en:
            items.append({"text": en, "translation": zh, "group": req.group})
    if not items:
        raise HTTPException(status_code=400, detail="没有解析到任何词条")
    count = get_exercise_manager().add_exercises(items, "words")
    return {"imported": count}


@router.delete("/group/{name}")
def delete_group(name: str):
    changed = get_exercise_manager().delete_group(name)
    if not changed:
        raise HTTPException(status_code=404, detail=f"分组 '{name}' 不存在或为空")
    return {"deleted": name}
