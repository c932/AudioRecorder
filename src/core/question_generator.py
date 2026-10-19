"""
question_generator — 统一 LLM 出题引擎（中英互译测验 / 学习中心复习 共用）。

取代原先 quiz_engine 与 memorize 里的两套重复实现，提供三种题型：
- en2cn   看英文，选中文释义（四选一）
- cn2en   看中文释义，选英文词（四选一）
- fill    例句翻译填空（打字填写，原 zh2en 模式）

统一题目结构（对 /api/quiz/answer 与桌面版保持兼容）：
{
  "type": "en2zh" | "zh2en",     # en2zh 与 zh2en 系列都保留原语义，便于判分与统计
  "mode":  "en2cn" | "cn2en" | "fill",
  "source_item": {...},          # 原词条（含 text/translation/pos/group），记错题用
  "question_text": str,          # 题干（英文词 / 中文释义 / 填空句）
  "question_extra": str,         # 附加信息（词性等）
  "options": list | None,        # 四选一的选项
  "answer": str,                 # 四选一正确项文本
  "answers": list | None,        # 填空模式的答案数组
  "correct_index": int | None,   # 四选一正确项下标
  "chinese_hint": str | None,    # 填空题的整句中文翻译
}
"""
from __future__ import annotations

import json
import os
import random
import re

from src.utils import get_user_data_path

MODE_EN2CN = "en2cn"
MODE_CN2EN = "cn2en"
MODE_FILL = "fill"
VALID_MODES = (MODE_EN2CN, MODE_CN2EN, MODE_FILL)

BATCH = 5  # 每次 LLM 请求出题数


# ── 题目结构 ──────────────────────────────────────────────

def _choice_question(item: dict, options: list, mode: str) -> dict:
    opts = list(options)
    correct_idx = opts.index(item["answer_text"])
    return {
        "type": "en2zh",
        "mode": mode,
        "source_item": item,
        "question_text": item["question_text"],
        "question_extra": item.get("pos") or "",
        "options": opts,
        "answer": item["answer_text"],
        "answers": None,
        "correct_index": correct_idx,
        "chinese_hint": None,
    }


def _fill_question(item: dict, blanked: str, answers: list, chinese_hint: str) -> dict:
    return {
        "type": "zh2en",
        "mode": MODE_FILL,
        "source_item": item,
        "question_text": blanked,
        "question_extra": "",
        "options": None,
        "answer": None,
        "answers": answers,
        "correct_index": None,
        "chinese_hint": chinese_hint,
    }


# ── 输入规整 ──────────────────────────────────────────────

def source_group(item: dict, fallback_group: str = "Default") -> str:
    """词条记录错题用的分组名。"""
    return item.get("group") or fallback_group


def _fill_item(item: dict, mode: str) -> dict:
    """补齐出题所需的字段。"""
    return {
        "text": item.get("text", ""),
        "translation": item.get("translation", ""),
        "pos": item.get("pos", ""),
        "group": item.get("group", "Default"),
        "question_text": item["text"] if mode != MODE_CN2EN else item.get("translation", ""),
        "answer_text": item.get("translation", "") if mode != MODE_CN2EN else item["text"],
    }


def _item_list(items: list, mode: str) -> str:
    lines = []
    for i, it in enumerate(items):
        if mode == MODE_CN2EN:
            lines.append(f'{i}. 中文: "{it["translation"]}" (英文: {it["text"]})')
        else:
            lines.append(f'{i}. "{it["text"]}" (中文: {it.get("translation", "")})')
    return "\n".join(lines)


# ── JSON 解析与校验 ──────────────────────────────────────

def parse_json_array(content: str) -> list:
    """从 LLM 响应中稳健地提取 JSON 数组。"""
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass

    match = re.search(r"\[.*\]", content, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    cleaned = re.sub(r"```(?:json)?\s*", "", content).strip()
    cleaned = cleaned.rstrip("`").strip()
    match = re.search(r"\[.*\]", cleaned, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    print(f"[question_generator] JSON 解析失败: {content[:200]}")
    return []


def is_valid_english_answer(answers: list) -> bool:
    """答案必须只含可输入的英文字符（拒绝 ℃、°、$ 等符号）。"""
    pattern = re.compile(r"^[a-zA-Z0-9\s\.\,\-\']+$")
    for a in answers:
        if not a or not pattern.match(str(a).strip()):
            return False
    return True


# ── 本地回退（无 LLM / LLM 失败时） ───────────────────────

def local_choice(item: dict, pool: list, mode: str) -> dict:
    """四选一回退：优先从同组词条抽干扰项。"""
    it = _fill_item(item, mode)
    correct = it["answer_text"]
    pool_texts = [e.get("translation", "") if mode != MODE_CN2EN else e["text"]
                  for e in pool if (e.get("translation", "") if mode != MODE_CN2EN else e["text"]) != correct]
    pool_texts = [t for t in pool_texts if t]
    random.shuffle(pool_texts)
    opts = [correct] + pool_texts[:3]
    if len(opts) < 4:
        opts += ["未知含义", "其他意思", "无关词"][: 4 - len(opts)]
    random.shuffle(opts)
    return _choice_question(it, opts, mode)


def get_blank_count(config: dict | None = None) -> int:
    """从 config.json 读取填空空数（默认 1）。"""
    if config is not None:
        return max(1, int(config.get("quiz_blank_count", 1)))
    path = get_user_data_path("config.json")
    blank_count = 1
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                blank_count = max(1, int(json.load(f).get("quiz_blank_count", 1)))
        except Exception:
            pass
    return blank_count


def local_fill_batch(items: list, blank_count: int | None = None) -> list:
    """填空回退：把最长的 N 个词挖空。"""
    blank_count = blank_count or get_blank_count()
    questions = []
    for item in items:
        it = _fill_item(item, MODE_FILL)
        words = it["text"].split()
        to_blank = sorted(words, key=len, reverse=True)[: min(blank_count, len(sorted(words, key=len, reverse=True)))]
        blanked = it["text"]
        answers = []
        for idx, w in enumerate(to_blank):
            blanked = re.sub(r"\b" + re.escape(w) + r"\b", f"({idx+1})______", blanked, count=1)
            answers.append(w)
        questions.append(_fill_question(item, blanked, answers, it.get("translation", "")))
    return questions


# ── LLM 出题 ─────────────────────────────────────────────

def _choice_prompt(items: list, mode: str) -> str:
    item_list = _item_list(items, mode)
    if mode == MODE_EN2CN:
        return f"""You are an English quiz expert for children. Generate multiple-choice questions (English to Chinese) for the following words/phrases.

Word list:
{item_list}

CRITICAL Rules for distractors:
1. For each word/phrase, generate exactly 4 Chinese options (A/B/C/D).
2. 1 correct answer + 3 distractors.
3. IMPORTANT: Each distractor MUST have a CLEARLY DIFFERENT meaning from the correct answer. Do NOT use synonyms or near-synonyms — if a student argues "that also means the same thing", it's a BAD distractor.
4. Distractor strategies (use a MIX):
   - Related but WRONG: words from the same category/topic but meaning something completely different (e.g., for "slow down" = "减速", use "加速" (speed up), "停下来" (stop), "转弯" (turn) — NOT "放慢速度" or "慢下来" which are synonyms)
   - Opposite meaning: antonyms or contrasting actions
   - Same word family confusion: words that share characters but mean different things (e.g., "发现" vs "发明" vs "发展")
   - Context trap: plausible in the same situation but different action (e.g., for "wake up": "睡着" (fall asleep) not "醒来" (wake up synonym))
5. BAD example for "slow down": ["减速", "放慢速度", "慢下来", "降低速度"] — ALL are synonyms, any could be correct!
6. GOOD example for "slow down": ["减速", "加速", "停下来", "转弯"] — each has a distinct meaning.
7. Correct answer position should be random (not always A).
8. Difficulty suitable for children.
9. Return ONLY a JSON array, no other text.
10. Format: [{{"index": 0, "question": "introduce", "options": ["介绍", "发现", "推荐", "隐藏"], "correct_index": 0}}]

Return JSON:"""

    return f"""You are an English quiz expert for children. Generate multiple-choice questions (Chinese to English): given the Chinese meaning, choose the correct English word.

Word list:
{item_list}

CRITICAL Rules for distractors:
1. For each entry, generate exactly 4 English options.
2. 1 correct answer + 3 distractors.
3. IMPORTANT: Each distractor MUST be a clearly different word — do NOT use synonyms, same-family words or misspellings of the correct answer.
4. Distractor strategies (use a MIX):
   - Same topic but different meaning (for "run" = 跑: use "fly", "swim", "climb")
   - Word-family confusion sharing letters (for "listen": "little", "lesson", "lost")
   - Similar-looking but unrelated words
5. Correct answer position should be random (not always A).
6. Difficulty suitable for children.
7. Return ONLY a JSON array, no other text.
8. Format: [{{"index": 0, "meaning": "介绍", "options": ["introduce", "destroy", "damage", "arrange"], "correct_index": 0}}]

Return JSON:"""


def _choice_result_index(r: dict, mode: str) -> int:
    return r.get("correct_index", 0)


def llm_choice_batch(client, model: str, items: list, mode: str, pool: list | None = None) -> list:
    """一次 LLM 调用生成一批四选一题目；逐题回退到本地。"""
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": _choice_prompt(items, mode)}],
            max_tokens=600,
            temperature=0.7,
        )
        content = response.choices[0].message.content.strip()
        parsed = parse_json_array(content)

        questions = []
        for i, item in enumerate(items):
            it = _fill_item(item, mode)
            llm_result = next((r for r in parsed if r.get("index") == i), None)
            options = None
            if llm_result and llm_result.get("options") and len(llm_result["options"]) == 4:
                raw_opts = llm_result["options"]
                correct_text = it["answer_text"]
                correct_idx = _choice_result_index(llm_result, mode)
                # 校验正确项下标合法，不合法则计入正确项
                if not (0 <= correct_idx < len(raw_opts)):
                    correct_idx = 0
                options = raw_opts
                # 保证 LLM 的正确项文本与我们记录的一致（en2cn 下项即中文释义）
                if options[correct_idx] != correct_text:
                    options = list(raw_opts)
                    options[correct_idx] = correct_text
                questions.append(_choice_question(item, options, mode))
            else:
                questions.append(local_choice(item, pool or [],
                                              mode if mode != MODE_FILL else MODE_EN2CN))
        return questions
    except Exception as e:
        print(f"[question_generator] 四选一 LLM 失败，本地回退: {e}")
        return [local_choice(it, pool or [], mode) for it in items]


def _fill_prompt(items: list, blank_count: int) -> str:
    item_list = _item_list(items, MODE_EN2CN)
    if blank_count == 1:
        blank_rule = "Replace exactly 1 word — the most educationally valuable (key vocabulary) — with (1)______"
        format_example = '[{{"index": 0, "full_sentence": "I keep a diary every night.", "blanked_sentence": "I (1)______ a diary every night.", "answers": ["keep"], "chinese_sentence": "我每天晚上记日记。"}}]'
    else:
        blank_rule = (
            f"Replace exactly {blank_count} SEPARATE words with numbered blanks (1)______, (2)______, etc.\n"
            "   - Choose {n} non-adjacent words if possible (spread across the sentence).\n"
            "   - Pick the most challenging/complex words that test vocabulary knowledge.\n"
            "   - Each blank should be a single word (not a phrase).\n"
            "   - The answers array must list the words in blank order (1), (2), etc."
        ).format(n=blank_count)
        format_example = f'[{{"index": 0, "full_sentence": "She always keeps a diary and writes stories.", "blanked_sentence": "She always (1)______ a diary and (2)______ stories.", "answers": ["keeps", "writes"], "chinese_sentence": "她总是记日记并写故事。"}}]'

    return f"""You are an English quiz expert for children. Generate fill-in-the-blank questions for the following English phrases.

Phrase list:
{item_list}

Rules:
1. For each phrase, create a simple example sentence containing the phrase (suitable for children).
2. {blank_rule}
3. CRITICAL: The blanked words (answers) must be plain English words only — letters, no symbols. NEVER use symbols like ℃, °, ℉, $, %, etc. as answers. If the phrase contains such symbols, rewrite the sentence to avoid them (e.g., "40.3 degrees" instead of "40.3°C").
4. Provide a natural Chinese translation of the FULL sentence (chinese_sentence field). This helps students understand the context.
5. Return ONLY a JSON array, no other text.
6. Format: {format_example}

Return JSON:"""


def llm_fill_batch(client, model: str, items: list, blank_count: int | None = None) -> list:
    """一次 LLM 调用生成一批填空题；逐题回退到本地。"""
    blank_count = blank_count or get_blank_count()
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": _fill_prompt(items, blank_count)}],
            max_tokens=800,
            temperature=0.3,
        )
        content = response.choices[0].message.content.strip()
        parsed = parse_json_array(content)

        questions = []
        for i, item in enumerate(items):
            it = _fill_item(item, MODE_FILL)
            llm_result = next((r for r in parsed if r.get("index") == i), None)

            if not llm_result:
                questions.append(_local_fill_one(it, blank_count))
                continue

            answers = llm_result.get("answers")
            if answers is None:
                ans = llm_result.get("answer", it["text"].split()[-1])
                answers = [ans] if isinstance(ans, str) else ans

            if not is_valid_english_answer(answers):
                questions.append(_local_fill_one(it, blank_count))
                continue

            chinese_hint = llm_result.get("chinese_sentence", "") or it.get("translation", "")
            questions.append(_fill_question(
                item,
                llm_result.get("blanked_sentence", ""),
                [str(a).strip() for a in answers],
                chinese_hint,
            ))
        return questions
    except Exception as e:
        print(f"[question_generator] 填空 LLM 失败，本地回退: {e}")
        return local_fill_batch(items, blank_count)


def _local_fill_one(item: dict, blank_count: int) -> dict:
    words = item["text"].split()
    to_blank = sorted(words, key=len, reverse=True)[: min(blank_count, len(words) or 1)]
    blanked = item["text"]
    answers = []
    for idx, w in enumerate(to_blank):
        blanked = re.sub(r"\b" + re.escape(w) + r"\b", f"({idx+1})______", blanked, count=1)
        answers.append(w)
    return _fill_question(item, blanked, answers, item.get("translation", ""))


# ── 判分 ────────────────────────────────────────────────

def validate_answer(question: dict, user_answer) -> bool:
    """本地判分（无 LLM）。

    四选一（en2zh 系列，含 cn2en）：user_answer 为选项文本。
    填空（zh2en）：单空为字符串，多空为数组。
    """
    if not user_answer:
        return False

    if question["type"] == "en2zh":
        if isinstance(user_answer, str):
            return user_answer.strip() == question.get("answer", "").strip()
        return False

    answers = question.get("answers") or []
    if not answers:
        correct = question.get("answer", "").strip()
        if isinstance(user_answer, str):
            return user_answer.strip().lower() == correct.lower()
        return False

    if isinstance(user_answer, list):
        if len(user_answer) != len(answers):
            return False
        return all(
            str(ua).strip().lower() == str(ca).strip().lower()
            for ua, ca in zip(user_answer, answers)
        )
    elif isinstance(user_answer, str):
        if len(answers) == 1:
            return user_answer.strip().lower() == str(answers[0]).strip().lower()
        parts = user_answer.strip().split()
        if len(parts) == len(answers):
            return all(
                p.strip().lower() == str(ca).strip().lower()
                for p, ca in zip(parts, answers)
            )
        return False
    return False


# ── 高层入口（供 router 直接使用） ───────────────────────

def generate(items: list, mode: str, *, client=None, model: str = None,
             pool: list | None = None) -> list:
    """同步批量出题：自动分批调 LLM，失败逐批回退本地。

    Args:
        items: 词条列表（text/translation/pos/group）
        mode: en2cn | cn2en | fill
        client/model: 可传入已构建的 LLM client；缺省时从 config 构建
        pool: 本地回退抽干扰项用的词条池（缺省用 items 自身）
    """
    if mode not in VALID_MODES:
        mode = MODE_EN2CN

    items = [dict(it) for it in items if it.get("text")]
    if not items:
        return []
    if pool is None:
        pool = items

    if client is None:
        from src.core.content_parser import _get_llm_client_and_model
        from src.server.deps import load_config
        client, model = _get_llm_client_and_model(load_config())

    blank_count = get_blank_count() if mode == MODE_FILL else None

    questions = []
    for i in range(0, len(items), BATCH):
        batch = items[i:i + BATCH]
        if mode == MODE_FILL:
            questions.extend(llm_fill_batch(client, model, batch, blank_count))
        else:
            questions.extend(llm_choice_batch(client, model, batch, mode, pool))
    return questions
