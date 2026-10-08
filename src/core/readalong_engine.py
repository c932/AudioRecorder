"""ReadAlongEngine — 课文跟读引擎：拆句/段、翻译、总结。"""
from __future__ import annotations

import re


class ReadAlongEngine:
    """课文跟读引擎：拆分课文、LLM 翻译、生成总结。"""

    @staticmethod
    def split_text(text: str, mode: str = "sentence") -> list[str]:
        """拆分课文为句子或段落列表。

        sentence 模式：按句号/问号/感叹号拆分，保留缩写（如 Mr. Mrs.）。
        paragraph 模式：按空行拆分，空行内保留原文本。
        """
        text = text.strip()
        if not text:
            return []

        if mode == "paragraph":
            # 按一个或多个空行拆分段落
            paragraphs = re.split(r'\n\s*\n', text)
            return [p.strip() for p in paragraphs if p.strip()]

        # 逐句模式：按句末标点拆分，但避免缩写中的句号
        # 缩写模式：Mr. Mrs. Dr. Ms. Prof. St. etc. e.g. i.e.
        abbrevs = r'(?:Mr|Mrs|Dr|Ms|Prof|St|etc|e\.g|i\.e)\.'
        # 先保护缩写中的句号
        protected = text
        placeholder_map = {}
        for i, m in enumerate(re.finditer(abbrevs, text)):
            ph = f"__ABBR{i}__"
            placeholder_map[ph] = m.group()
            protected = protected.replace(m.group(), ph, 1)

        # 按句末标点拆分
        parts = re.split(r'(?<=[.!?])\s+', protected)
        # 按换行也拆（课文可能一行一句）
        expanded = []
        for p in parts:
            expanded.extend(p.split('\n'))

        # 还原缩写 + 清理
        result = []
        for seg in expanded:
            seg = seg.strip()
            for ph, original in placeholder_map.items():
                seg = seg.replace(ph, original)
            if seg and len(seg) > 1:
                result.append(seg)

        return result

    @staticmethod
    def extract_words_from_segment(text: str) -> list[str]:
        """从一句/段英文中提取单词列表（去重，小写，过滤短词）。"""
        words = re.findall(r"[a-zA-Z']+", text)
        seen = set()
        result = []
        for w in words:
            low = w.lower()
            if low not in seen and len(low) > 1:
                seen.add(low)
                result.append(low)
        return result

    @staticmethod
    def translate_segments(segments: list[str], config: dict) -> list[str]:
        """批量翻译英文句子/段落为中文（LLM）。

        LLM 失败时返回空串列表（与输入等长），应用可降级运行。
        对每句单独翻译以保证对齐可靠，即使模型较弱也不会串行。
        """
        if not segments:
            return []

        try:
            from src.core.content_parser import _get_llm_client_and_model
            client, model = _get_llm_client_and_model(config)
        except Exception as e:
            print(f"[readalong] LLM 翻译：无法获取客户端: {e}")
            return [""] * len(segments)

        all_translations = []
        for seg in segments:
            try:
                prompt = (
                    f'Translate to Chinese. ONLY output the Chinese translation.\n'
                    f'English: {seg}'
                )
                response = client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": "You translate English to Chinese. Respond with ONLY Chinese characters. No English, no explanation, no punctuation marks like colons before the translation."},
                        {"role": "user", "content": prompt},
                    ],
                    max_tokens=300,
                    temperature=0.3,
                )
                content = response.choices[0].message.content.strip()
                # 清理模型思考/推理过程，只保留最终翻译
                content = _strip_model_thinking(content)
                all_translations.append(content)
            except Exception as e:
                print(f"[readalong] 单句翻译失败: {e}")
                all_translations.append("")

        return all_translations

    @staticmethod
    def generate_llm_correction(score: int, reference: str, recognized: str,
                                errors: list[dict], config: dict) -> str:
        """用 LLM 生成具体的发音纠错建议（中文，20 字以内）。

        LLM 失败时返回空串——应用必须在无 LLM 时仍可工作。
        """
        try:
            from src.core.content_parser import _get_llm_client_and_model
            client, model = _get_llm_client_and_model(config)
        except Exception as e:
            print(f"[readalong] LLM 纠错：无法获取客户端: {e}")
            return ""

        error_desc = ""
        for e in errors[:3]:
            etype = e.get("type", "")
            exp = e.get("expected", "")
            act = e.get("actual", "")
            word = e.get("word", "")
            if etype == "substitution" and exp and act:
                error_desc += f"{word}里 /{exp}/ 读成了 /{act}/；"
            elif etype == "deletion":
                error_desc += f"{word}里 /{exp}/ 漏读了；"
            elif etype == "vowel_confusion":
                error_desc += f"{word}里元音 /{exp}/ 听起来像 /{act}/；"

        if not error_desc:
            error_desc = "整体发音可以再清晰一些。"

        prompt = (
            f"学生读「{reference}」得了 {score} 分。"
            f"问题：{error_desc}\n"
            "请用中文给出一句简短（20字以内）的发音纠正建议。"
        )

        try:
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=100,
                temperature=0.5,
            )
            return (response.choices[0].message.content or "").strip()
        except Exception as e:
            print(f"[readalong] LLM 纠错失败: {e}")
            return ""

    @staticmethod
    def generate_summary(results: list[dict], segments: list[dict],
                         config: dict) -> dict:
        """生成跟读总结，提取薄弱句和需复习词汇。

        Args:
            results: [{"seg_idx": int, "score": int, "retries": int}]
            segments: [{"text": str, "translation": str}]
            config: config dict for LLM

        Returns:
            {
                "summary": str,
                "avg_score": int,
                "weak_segments": list[dict],
                "weak_words": list[str],
                "total_segments": int,
                "total_retries": int,
            }
        """
        from src.core.content_parser import _get_llm_client_and_model

        total = len(results)
        avg = sum(r["score"] for r in results) / total if total else 0
        weak = [r for r in results if r["score"] < 80]
        total_retries = sum(r.get("retries", 0) for r in results)

        weak_segments = []
        weak_words_set = set()
        for r in weak:
            idx = r["seg_idx"]
            if idx < len(segments):
                seg = segments[idx]
                weak_segments.append(seg)
                for w in ReadAlongEngine.extract_words_from_segment(seg["text"]):
                    weak_words_set.add(w)

        weak_words = sorted(weak_words_set)[:20]  # 最多 20 个词

        # LLM 总结
        summary_text = ""
        try:
            client, model = _get_llm_client_and_model(config)
            weak_text = "\n".join(
                f"- 「{s['text']}」（{r['score']}分）"
                for r, s in zip(weak, weak_segments[:5])
            )
            prompt = (
                f"学生完成了一篇 {total} 句课文的跟读练习，平均分 {avg:.0f}。"
                f"重读了 {total_retries} 次。\n"
                f"薄弱句：\n{weak_text if weak_text else '无'}\n\n"
                "请用中文写一段简短的总结评价（50字以内），鼓励学生。"
            )
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=150,
                temperature=0.5,
            )
            summary_text = (response.choices[0].message.content or "").strip()
        except Exception as e:
            print(f"[readalong] LLM 总结失败: {e}")

        if not summary_text:
            if avg >= 80:
                summary_text = f"很棒！平均 {avg:.0f} 分，继续保持！"
            else:
                summary_text = f"平均 {avg:.0f} 分，多练薄弱句会进步更快！"

        return {
            "summary": summary_text,
            "avg_score": round(avg),
            "weak_segments": weak_segments,
            "weak_words": weak_words,
            "total_segments": total,
            "total_retries": total_retries,
        }


# ---------------------------------------------------------------------------
# Helpers — 剥离弱模型输出中的推理过程
# ---------------------------------------------------------------------------

# XML 思考标签 — 覆盖已知格式 (think, thinking) + 处理指令 <?...?> + 孤立闭合标签
_THINKING_RE = re.compile(
    r'<(?:think|thinking|action|reason)>.*?</(?:think|thinking|action|reason)>'
    r'|<\?.*?\?>'
    r'|</(?:think|thinking|action|reason)>',
    re.DOTALL,
)
# 分隔线：---, ===, *** 等
_SEPARATOR_RE = re.compile(r'^[\s\-=*~]{3,}$', re.MULTILINE)
# 英文推理前缀 — 弱模型常在翻译前加 "I'll go with:" / "Translation:" / "So:" / "Okay:" 等
_ENGLISH_PREFIX_RE = re.compile(
    r'^(?:'
    r"I(?:'ll| will| should)? (?:go with|output|translate|provide|give|say|choose|write|put|think it(?:'s| is))"
    r"(?:\s+(?:it|that|this|the|only|just|the Chinese|the translation))?\s*[:：]\s*"
    r"|Translation\s*[:：]\s*"
    r"|The (?:translation|answer|result|Chinese|meaning) (?:is|would be)\s*[:：]?\s*"
    r"|Here(?:'s| is) (?:the )?(?:translation|Chinese)\s*[:：]?\s*"
    r"|In Chinese\s*[:：]\s*"
    r"|So\s*[:：]\s*"
    r"|Okay\s*[:：]?\s*"
    r"|中文(?:翻译|意思|是)\s*[:：]?\s*"
    r"|翻译(?:如下|为|是)\s*[:：]?\s*"
    r")",
    re.IGNORECASE,
)
# 中文标点结尾的句子（句号、问号、感叹号等）
_CN_SENTENCE_END_RE = re.compile(r'[。！？…」）》、]')


def _has_chinese(text: str) -> bool:
    """检查文本是否包含中文字符。"""
    return any('一' <= ch <= '鿿' for ch in text)


def _is_mostly_chinese(text: str) -> bool:
    """判断文本是否以中文为主（中文字符数 > 英文字母数）。"""
    cn = sum(1 for ch in text if '一' <= ch <= '鿿')
    en = sum(1 for ch in text if 'a' <= ch <= 'z' or 'A' <= ch <= 'Z')
    return cn > en


def _extract_last_chinese_sentence(text: str) -> str:
    """从英文+中文混合文本中提取最后一个完整的中文句子。

    策略：从右往左找中文标点结尾，再往前找中文开头，截取这段。
    例如 '猫坐在垫子上。" but they said...猫坐在垫子上' → '猫坐在垫子上'
    """
    # 先找最后一个中文标点结尾的位置
    last_end = -1
    for i in range(len(text) - 1, -1, -1):
        if _CN_SENTENCE_END_RE.match(text[i]):
            last_end = i
            break

    if last_end >= 0:
        # 从这个标点往前找，找到中文句子的开头
        # 往前找：直到遇到非中文/非中文标点的连续英文段
        start = last_end
        while start > 0 and (('一' <= text[start - 1] <= '鿿')
                             or _CN_SENTENCE_END_RE.match(text[start - 1])
                             or text[start - 1] in '，、；：""''（）【】'):
            start -= 1
        candidate = text[start:last_end + 1].strip()
        if _has_chinese(candidate) and len(candidate) >= 2:
            return candidate

    # 没有中文标点结尾：取最后一个连续中文段
    # 从右往左找中文字符连续段
    in_chinese = False
    end = len(text)
    for i in range(len(text) - 1, -1, -1):
        is_cn = '一' <= text[i] <= '鿿'
        if is_cn and not in_chinese:
            end = i + 1
            in_chinese = True
        elif not is_cn and in_chinese:
            candidate = text[i + 1:end].strip()
            if len(candidate) >= 2:
                return candidate

    # 回退：找第一个中文字符开始
    for i, ch in enumerate(text):
        if '一' <= ch <= '鿿':
            candidate = text[i:].strip()
            if _has_chinese(candidate) and len(candidate) >= 2:
                return candidate

    return text


def _deduplicate_chinese(text: str) -> str:
    """去除重复的中文翻译（弱模型常在标签前后各输出一次翻译）。

    例如 "猫坐在垫子上。猫坐在垫子上。" → "猫坐在垫子上。"
         "你好世界你好世界" → "你好世界"
    """
    if not _has_chinese(text) or len(text) < 4:
        return text

    # 尝试将文本对半分割，检查是否重复
    half = len(text) // 2
    # 精确对半
    if len(text) % 2 == 0 and text[:half] == text[half:]:
        return text[:half]

    # 尝试不同分割点（±1~3 字符，处理标点/空格差异）
    for offset in range(-3, 4):
        split_at = half + offset
        if split_at <= 0 or split_at >= len(text):
            continue
        left = text[:split_at].rstrip('，。、！？：； ')
        right = text[split_at:].lstrip('，。、！？：； ')
        if left and right and left == right:
            return text[:split_at].rstrip()

    return text


def _strip_model_thinking(text: str) -> str:
    """剥离模型输出的思考/推理过程，只保留最终翻译。

    处理策略（按顺序）：
    1. XML 格式思考标签 + 孤立闭合标签 + 处理指令 <?...?>
    2. 以分隔线分隔的推理+结论
    3. 多行输出：取最后一行含中文内容（递归处理）
    4. 单行含英文推理前缀：剥离前缀
    5. 单行含英文+中文混合：提取最后一个完整中文句子
    6. 重复翻译去重
    """
    # 1. 去掉 XML 思考标签 + 孤立闭合标签 + <?...?> 处理指令
    cleaned = _THINKING_RE.sub('', text).strip()

    # 2. 如果有分隔线，取分隔线之后的部分
    parts = _SEPARATOR_RE.split(cleaned)
    if len(parts) > 1:
        cleaned = parts[-1].strip()

    # 3. 如果有多行，取最后一行含中文的行（递归处理）
    lines = [l.strip() for l in cleaned.splitlines() if l.strip()]
    if len(lines) > 1:
        for line in reversed(lines):
            if _has_chinese(line):
                return _strip_model_thinking(line)
        # 没有中文行则取最后一行
        return lines[-1]

    # 单行处理
    if not lines:
        return cleaned
    single = lines[0]

    # 4. 去掉英文推理前缀
    single = _ENGLISH_PREFIX_RE.sub('', single).strip()

    # 5. 如果单行以英文为主但含中文，提取最后一个完整中文句子
    if _has_chinese(single) and not _is_mostly_chinese(single):
        single = _extract_last_chinese_sentence(single)

    # 6. 重复翻译去重
    single = _deduplicate_chinese(single)

    return single
