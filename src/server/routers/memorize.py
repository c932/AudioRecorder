"""分类速记路由 — 支持 Day1-28 内置词库 + 用户导入词库。"""
from __future__ import annotations

import json
import random

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.server.deps import get_memorize, load_config

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
            "progress": eng.get_module_progress(v["key"]),
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
#  复习测验：LLM 生成混淆选项的四选一
# ------------------------------------------------------------------ #

class QuizRequest(BaseModel):
    key: str
    mode: str = "en2cn"  # "en2cn" (英→中) 或 "cn2en" (中→英)


@router.post("/quiz")
def generate_quiz(req: QuizRequest):
    """用 LLM 生成四选一测验题（混淆选项质量远高于本地随机抽取）。"""
    eng = get_memorize()
    entries = eng.get_entries(req.key)
    if not entries:
        raise HTTPException(status_code=404, detail=f"模块 {req.key} 不存在或无词条")

    mode = req.mode if req.mode in ("en2cn", "cn2en") else "en2cn"

    # 尝试用 LLM 生成
    try:
        questions = _generate_llm_quiz(entries, mode)
    except Exception as e:
        print(f"[memorize/quiz] LLM 生成失败，回退本地: {e}")
        questions = _generate_local_quiz(entries, mode)

    # 记录测试
    eng.record_test(req.key, 0, len(questions))
    return {"questions": questions, "total": len(questions)}


def _generate_llm_quiz(entries: list, mode: str) -> list:
    """调用 LLM 批量生成四选一题目。"""
    from src.core.content_parser import _get_llm_client_and_model

    cfg = load_config()
    client, model = _get_llm_client_and_model(cfg)
    if not client:
        raise RuntimeError("LLM 未配置")

    BATCH = 5
    questions = []
    for i in range(0, len(entries), BATCH):
        batch = entries[i:i + BATCH]
        if mode == "en2cn":
            questions.extend(_llm_en2cn(client, model, batch))
        else:
            questions.extend(_llm_cn2en(client, model, batch))
    return questions


def _llm_en2cn(client, model: str, items: list) -> list:
    """英→中：给英文，选中文释义。"""
    item_list = "\n".join([
        f'{i+1}. "{item["text"]}" (正确中文: {item.get("translation", "")})'
        for i, item in enumerate(items)
    ])
    prompt = f"""You are an English quiz expert for children. Generate multiple-choice questions (English to Chinese).

Word list:
{item_list}

CRITICAL Rules for distractors:
1. For each word, generate exactly 4 Chinese options.
2. 1 correct answer + 3 distractors with CLEARLY DIFFERENT meanings.
3. Distractor strategies: related-but-wrong, antonyms, same-word-family confusion, context trap.
4. BAD: synonyms or near-synonyms. GOOD: each option has a distinct meaning.
5. Correct answer position should be random.
6. Return ONLY a JSON array.
7. Format: [{{"index": 0, "options": ["介绍", "发现", "推荐", "隐藏"], "correct_index": 0}}]

Return JSON:"""

    resp = client.chat.completions.create(
        model=model, messages=[{"role": "user", "content": prompt}],
        max_tokens=600, temperature=0.7,
    )
    parsed = _parse_json(resp.choices[0].message.content.strip())

    questions = []
    for i, item in enumerate(items):
        llm_result = next((r for r in parsed if r.get("index") == i), None)
        correct_answer = item.get("translation", "")
        if llm_result and len(llm_result.get("options", [])) == 4:
            opts = llm_result["options"]
            ci = -1
            for j, opt in enumerate(opts):
                if opt.strip() == correct_answer.strip() or correct_answer.strip() in opt:
                    ci = j
                    break
            if ci < 0:
                opts[0] = correct_answer
                ci = 0
            questions.append({
                "direction": "en2cn",
                "question": item["text"],
                "question_extra": item.get("pos", ""),
                "options": opts,
                "answer_index": ci,
                "entry": item,
            })
        else:
            questions.append(_local_en2cn(item, entries_pool=items))
    return questions


def _llm_cn2en(client, model: str, items: list) -> list:
    """中→英：给中文，选英文单词/词组。"""
    item_list = "\n".join([
        f'{i+1}. 中文: "{item.get("translation", "")}" → 英文: "{item["text"]}"'
        for i, item in enumerate(items)
    ])
    prompt = f"""You are an English quiz expert for children. Generate multiple-choice questions (Chinese to English).

Word list:
{item_list}

CRITICAL Rules for distractors:
1. For each word, generate exactly 4 English options.
2. 1 correct answer + 3 distractors with CLEARLY DIFFERENT meanings.
3. Distractors should be real English words, plausible but wrong. Use same-topic confusion, similar spelling, antonyms.
4. Return ONLY a JSON array.
5. Format: [{{"index": 0, "options": ["introduce", "discover", "recommend", "invent"], "correct_index": 0}}]

Return JSON:"""

    resp = client.chat.completions.create(
        model=model, messages=[{"role": "user", "content": prompt}],
        max_tokens=600, temperature=0.7,
    )
    parsed = _parse_json(resp.choices[0].message.content.strip())

    questions = []
    for i, item in enumerate(items):
        llm_result = next((r for r in parsed if r.get("index") == i), None)
        correct_answer = item["text"]
        if llm_result and len(llm_result.get("options", [])) == 4:
            opts = llm_result["options"]
            ci = -1
            for j, opt in enumerate(opts):
                if opt.strip().lower() == correct_answer.strip().lower():
                    ci = j
                    break
            if ci < 0:
                opts[0] = correct_answer
                ci = 0
            questions.append({
                "direction": "cn2en",
                "question": item.get("translation", ""),
                "question_extra": "",
                "options": opts,
                "answer_index": ci,
                "entry": item,
            })
        else:
            questions.append(_local_cn2en(item, entries_pool=items))
    return questions


def _generate_local_quiz(entries: list, mode: str) -> list:
    """本地回退：从同一天词条中随机抽取干扰项。"""
    questions = []
    for item in entries:
        if mode == "en2cn":
            questions.append(_local_en2cn(item, entries))
        else:
            questions.append(_local_cn2en(item, entries))
    return questions


def _local_en2cn(item: dict, entries_pool: list) -> dict:
    correct = item.get("translation", "未知")
    distractors = [e.get("translation", "") for e in entries_pool if e.get("translation") != correct]
    random.shuffle(distractors)
    opts = [correct] + distractors[:3]
    if len(opts) < 4:
        opts += ["未知含义"] * (4 - len(opts))
    random.shuffle(opts)
    return {
        "direction": "en2cn",
        "question": item["text"],
        "question_extra": item.get("pos", ""),
        "options": opts,
        "answer_index": opts.index(correct),
        "entry": item,
    }


def _local_cn2en(item: dict, entries_pool: list) -> dict:
    correct = item["text"]
    distractors = [e["text"] for e in entries_pool if e["text"] != correct]
    random.shuffle(distractors)
    opts = [correct] + distractors[:3]
    if len(opts) < 4:
        opts += ["unknown"] * (4 - len(opts))
    random.shuffle(opts)
    return {
        "direction": "cn2en",
        "question": item.get("translation", ""),
        "question_extra": "",
        "options": opts,
        "answer_index": opts.index(correct),
        "entry": item,
    }


def _parse_json(content: str) -> list:
    """从 LLM 响应中提取 JSON 数组。"""
    if content.startswith("```"):
        lines = content.split("\n")
        content = "\n".join(l for l in lines if not l.startswith("```"))
    content = content.strip()
    start = content.find("[")
    end = content.rfind("]")
    if start >= 0 and end > start:
        content = content[start:end + 1]
    try:
        return json.loads(content)
    except Exception:
        return []
