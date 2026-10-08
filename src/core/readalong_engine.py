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
                prompt = f'Translate the following English sentence to Chinese. Output ONLY the Chinese translation, nothing else.\n\nEnglish: {seg}'
                response = client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": "You are a translator. Translate English to Chinese. Output ONLY the translation."},
                        {"role": "user", "content": prompt},
                    ],
                    max_tokens=300,
                    temperature=0.3,
                )
                content = response.choices[0].message.content.strip()
                # 清理：去掉可能的引号包裹
                content = content.strip('"\'""''')
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
