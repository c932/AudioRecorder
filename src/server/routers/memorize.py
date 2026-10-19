"""分类速记路由 — 支持 Day1-28 内置词库 + 用户导入词库。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.core import question_generator as qg
from src.server.deps import get_memorize, get_exercise_manager

router = APIRouter(prefix="/api/memorize", tags=["memorize"])


@router.get("/days")
def list_days():
    """返回全部模块（内置 Day1-28 + 词库分组），含词数、是否已开始。"""
    eng = get_memorize()
    items = []

    # 内置速记 Day1-28
    for d in eng.get_days():
        day_no = d.get("day")
        key = f"d{day_no}"
        entries = eng.get_day_entries(day_no)
        items.append({
            "key": key,
            "title": d.get("title", f"Day {day_no}"),
            "source": "builtin",
            "count": len(entries),
            "started": eng.is_started(key),
            "progress": eng.get_module_progress(key),
        })

    # 用户词库分组
    for v in eng.get_vocab_days():
        items.append({
            "key": v["key"],
            "title": v["title"],
            "source": "vocab",
            "count": v["count"],
            "started": eng.is_started(v["key"]),
            "progress": eng.get_module_progress(key=v["key"]),
        })

    return {"days": items}


@router.get("/module")
def get_module(key: str):
    """返回某模块的全部词条 + 进度。key=d1~d28 或 v:分组名。"""
    eng = get_memorize()
    entries = eng.get_entries(key)
    if not entries:
        raise HTTPException(status_code=404, detail=f"模块 {key} 不存在")
    return {
        "key": key,
        "entries": entries,
        "progress": eng.get_module_progress(key),
    }


@router.get("/due")
def due_reviews():
    """返回今天应复习的模块。"""
    return {"due": get_memorize().get_due_reviews()}


class KeyRequest(BaseModel):
    key: str


@router.post("/start")
def start_module(req: KeyRequest):
    eng = get_memorize()
    entries = eng.get_entries(req.key)
    if not entries:
        raise HTTPException(status_code=404, detail=f"模块 {req.key} 不存在")
    eng.start_module(req.key)
    return {"ok": True, "progress": eng.get_module_progress(req.key)}


@router.post("/review")
def complete_review(req: KeyRequest):
    eng = get_memorize()
    ok = eng.complete_review(req.key)
    if not ok:
        raise HTTPException(status_code=400, detail=f"模块 {req.key} 尚未开始")
    return {"ok": True, "progress": eng.get_module_progress(req.key)}


# ------------------------------------------------------------------ #
#  学习中心复习：统一出题引擎（英选中 / 中选英 / 例句填空）
# ------------------------------------------------------------------ #

class QuizRequest(BaseModel):
    key: str
    mode: str = "en2cn"  # en2cn 英→中四选一 | cn2en 中→英四选一 | fill 例句填空


@router.post("/quiz")
def generate_quiz(req: QuizRequest):
    """统一出题（复用 quiz_engine 同一条 LLM 实现），失败自动本地回退。"""
    eng = get_memorize()
    entries = eng.get_entries(req.key)
    if not entries:
        raise HTTPException(status_code=404, detail=f"模块 {req.key} 不存在或无词条")

    mode = req.mode if req.mode in qg.VALID_MODES else qg.MODE_EN2CN

    # 词条统一标组名（内置 Day / 词库名），错题记录与跟读跳转都用它
    items = []
    for e in entries:
        if req.key.startswith("d"):
            group = f"速记Day{req.key[1:]}"
        elif req.key.startswith("v:"):
            group = req.key[2:]
        else:
            group = e.get("group", "Default")
        items.append({
            "text": e.get("text", ""),
            "translation": e.get("translation", ""),
            "pos": e.get("pos", ""),
            "group": group,
        })

    questions = qg.generate(items, mode, pool=items)

    # 艾宾浩斯测试记录
    eng.record_test(req.key, 0, len(questions))
    return {"questions": questions, "total": len(questions), "mode": mode}


class AnswerRequest(BaseModel):
    question: dict
    user_answer: Any


@router.post("/answer")
def answer_quiz(req: AnswerRequest):
    """判分 + 记错题（词条不在练习词库中时自动补录，保证错题本可见）。"""
    is_correct = qg.validate_answer(req.question, req.user_answer)

    source = req.question.get("source_item") or {}
    if source.get("text"):
        get_exercise_manager().record_quiz_result(source, is_correct)

    if req.question.get("type") == "en2zh":
        correct = req.question.get("answer", "")
    else:
        correct = req.question.get("answers") or ""
    return {"is_correct": is_correct, "correct_answer": correct}
