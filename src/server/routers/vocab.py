"""词库管理路由。"""
from __future__ import annotations

import os
import re
import tempfile

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from src.server.deps import cleanup_temp, get_exercise_manager, get_all_practice_items, load_config

router = APIRouter(prefix="/api/vocab", tags=["vocab"])

# 与桌面版 import_dialog 支持的格式一致
_IMPORT_EXTS = {".pdf", ".txt", ".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif"}
_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif"}


@router.get("/groups")
def list_groups():
    """返回分组列表及词数（包含词库 + 速记模块）。"""
    from src.server.deps import get_memorize
    mgr = get_exercise_manager()
    counts = mgr.get_group_word_counts()
    groups = [
        {"name": g, "count": counts.get(g, 0)}
        for g in mgr.get_groups()
    ]
    # 合并速记模块的分组
    try:
        eng = get_memorize()
        existing = {g["name"] for g in groups}
        for d in eng.get_days():
            day_no = d.get("day")
            name = f"速记Day{day_no}"
            if name not in existing:
                entries = eng.get_day_entries(day_no)
                groups.append({"name": name, "count": len(entries)})
                existing.add(name)
    except Exception as e:
        print(f"[vocab] 加载速记分组失败: {e}")
    return {"groups": groups}


@router.get("/words")
def list_words(group: str = ""):
    """返回某分组的全部词条（不传 group 返回全部）。

    速记DayN 分组由 memorize 引擎提供，不在 words.json 里，
    所以用 get_all_practice_items 合并两个来源。
    """
    groups = [group] if group else None
    full = get_all_practice_items(groups)
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


# ---------------------------------------------------------------------- #
# 文件导入（与桌面版 import_dialog 同一解析内核，两步走：解析预览 → 编辑入库）
# ---------------------------------------------------------------------- #
@router.post("/parse-file")
async def parse_file(file: UploadFile = File(...), use_ai: bool = Form(True)):
    """上传 PDF / TXT / 图片 → 解析词条（只预览，不入库）。

    图片必须走多模态 LLM；TXT 直读文本；PDF 用 pdfplumber（无文本时自动
    转图片走视觉模型）。解析在线程池里跑，避免 LLM 长调用卡住事件循环。
    """
    from fastapi.concurrency import run_in_threadpool

    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in _IMPORT_EXTS:
        raise HTTPException(400, f"不支持的文件类型「{ext or file.filename}」，支持 PDF / TXT / 图片")
    raw = await file.read()
    if not raw:
        raise HTTPException(400, "文件是空的")
    if len(raw) > 20 * 1024 * 1024:
        raise HTTPException(400, "文件超过 20MB 上限")

    from src.core.content_parser import ContentParser
    config = load_config()
    path = None
    try:
        if ext == ".txt":
            text = raw.decode("utf-8", errors="replace")
            if use_ai:
                items = await run_in_threadpool(
                    ContentParser._parse_with_llm, text, config=config)
            else:
                items = ContentParser._parse_lines(text.splitlines())
        else:
            fd, path = tempfile.mkstemp(prefix="web_import_", suffix=ext)
            with os.fdopen(fd, "wb") as f:
                f.write(raw)
            if ext in _IMAGE_EXTS:
                items = await run_in_threadpool(
                    ContentParser.parse_image, path, config=config)
            else:
                items = await run_in_threadpool(
                    ContentParser.parse_pdf, path, use_ai=use_ai, config=config)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"解析失败：{e}")
    finally:
        if path:
            cleanup_temp(path)

    clean = []
    for it in items or []:
        text = str((it or {}).get("text", "")).strip()
        if not text:
            continue
        clean.append({
            "text": text,
            "phonetic": str((it or {}).get("phonetic", "")).strip(),
            "translation": str((it or {}).get("translation", "")).strip(),
        })
    if not clean:
        raise HTTPException(422, "没有解析到词条；扫描版 PDF 或图片请勾选 AI 智能解析")
    return {"items": clean}


class ImportItems(BaseModel):
    items: list[dict]
    group: str = "Default"


@router.post("/import-items")
def import_items(req: ImportItems):
    """预览编辑后的词条入库（与桌面版表格导入同一入口，按 词+分组 去重）。"""
    clean = []
    for it in req.items:
        text = str(it.get("text", "")).strip()
        if not text:
            continue
        clean.append({
            "text": text,
            "phonetic": str(it.get("phonetic", "")).strip(),
            "translation": str(it.get("translation", "")).strip(),
            "group": req.group,
        })
    if not clean:
        raise HTTPException(400, "没有可导入的词条")
    count = get_exercise_manager().add_exercises(clean, "words")
    return {"imported": count}


@router.delete("/group/{name}")
def delete_group(name: str):
    changed = get_exercise_manager().delete_group(name)
    if not changed:
        raise HTTPException(status_code=404, detail=f"分组 '{name}' 不存在或为空")
    return {"deleted": name}
