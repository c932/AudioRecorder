"""
ScenarioEngine - LLM-based dialogue scenario script generation and management.

Generates two-person (A/B) dialogue scripts that exercise all words/sentences
from selected vocabulary groups. Banks are persisted to scenario_banks.json.
"""
import json
import os
import random
import re
import threading
import time
import uuid
from datetime import datetime

from src.core.qt_compat import QObject, pyqtSignal

from src.core.content_parser import _get_llm_client_and_model, _is_omni_provider, _get_omni_client
from src.utils import get_user_data_path


class ScenarioEngine(QObject):
    """Generates and manages two-person scenario dialogue banks."""

    # Bank generation signals (mirrors OralTestEngine for UI reuse)
    bank_progress_update = pyqtSignal(int, int)   # (generated, total)
    bank_generation_done = pyqtSignal(dict)       # Full bank dict
    bank_generation_error = pyqtSignal(str)       # Error message

    # Session summary signal
    summary_ready = pyqtSignal(str)               # LLM-generated feedback text
    summary_error = pyqtSignal(str)

    # Hard caps to keep prompts and conversations sane
    MAX_VOCAB = 60          # If group has more, sample top-N (latest first)
    MAX_PHRASES = 30        # 短句/固定搭配上限（用户最关心，尽量保留）
    MIN_TURNS = 8
    MAX_TURNS = 60          # 对话轮数上限（配合设置页记忆上次轮数）
    DEFAULT_TURNS = 12

    @staticmethod
    def _is_phrase(text: str) -> bool:
        """判定一个词条是否是短句/固定搭配（≥2 个英文 token 即视为搭配）。"""
        if not text:
            return False
        # 计英文/数字片段数
        tokens = re.findall(r"[A-Za-z][A-Za-z'\-]*", text)
        return len(tokens) >= 2

    def __init__(self, exercise_manager):
        super().__init__()
        self.exercise_manager = exercise_manager

    # ------------------------------------------------------------------ #
    #  Bank Generation                                                    #
    # ------------------------------------------------------------------ #
    def generate_bank(self, groups, turn_count: int = None, name: str = None,
                      persist: bool = True):
        """Kick off background generation of a scenario dialogue bank.

        Args:
            groups: list of group names (or single string)
            turn_count: desired number of dialogue turns. None → DEFAULT_TURNS.
                        Clamped to [MIN_TURNS, MAX_TURNS].
            name: optional explicit bank name
            persist: if False, the generated bank is NOT written to
                     scenario_banks.json. It is only emitted via the
                     bank_generation_done signal (for one-shot practice).
        """
        if isinstance(groups, str):
            groups = [groups]
        if not groups:
            self.bank_generation_error.emit("请先勾选至少一个词库分组。")
            return

        # Clamp turn_count
        if turn_count is None:
            turn_count = self.DEFAULT_TURNS
        try:
            turn_count = int(turn_count)
        except Exception:
            turn_count = self.DEFAULT_TURNS
        turn_count = max(self.MIN_TURNS, min(self.MAX_TURNS, turn_count))

        # Collect words + sentences from selected groups
        all_words = self.exercise_manager.exercises.get("words", [])
        all_sentences = self.exercise_manager.exercises.get("sentences", [])

        words = [w for w in all_words if w.get("group", "Default") in groups]
        sentences = [s for s in all_sentences if s.get("group", "Default") in groups]

        if not words and not sentences:
            self.bank_generation_error.emit("所选分组中没有任何词条。")
            return

        # Cap vocab to keep prompt size reasonable.
        # 关键：词条数也要跟 turn_count 挂钩 —— 否则 LLM 为了"用完所有词"
        # 会无视轮数硬约束（实测 67 词 + 20 轮 → 生成 56 轮）。
        # 经验值：每轮平均能自然容纳约 2 个新词 + 句子结构词。
        max_words_for_turns = max(8, turn_count * 2)
        hard_cap = min(self.MAX_VOCAB, max_words_for_turns)

        # 用一个新的随机源（基于当前时间），确保每次抽样和 prompt nonce 都不同。
        rng = random.Random(time.time_ns())

        # 拆分单词 vs 短句/固定搭配 —— 后者用户最看重，必须在 prompt 中显式强调
        single_words = [w for w in words if not self._is_phrase(w.get("text", ""))]
        phrases = [w for w in words if self._is_phrase(w.get("text", ""))]

        # 短句：尽量全保留（仅在超过 MAX_PHRASES 时才随机抽样）
        if len(phrases) > self.MAX_PHRASES:
            print(f"[ScenarioEngine] phrases {len(phrases)} > cap "
                  f"{self.MAX_PHRASES}; randomly sampling.")
            phrases = rng.sample(phrases, self.MAX_PHRASES)
        else:
            phrases = list(phrases)
            rng.shuffle(phrases)

        # 单词：扣除短句已占的"轮预算"后再 cap（每条短句估算耗 1 轮预算）
        words_budget = max(4, hard_cap - len(phrases))
        if len(single_words) > words_budget:
            print(f"[ScenarioEngine] single_words {len(single_words)} > budget "
                  f"{words_budget} (turn_count={turn_count}, "
                  f"phrases={len(phrases)}); randomly sampling.")
            single_words = rng.sample(single_words, words_budget)
        else:
            single_words = list(single_words)
            rng.shuffle(single_words)

        # Sentences 同样随机抽样（每轮最多匹配 1 句较自然），避免长 prompt + 重复输出
        max_sents_for_turns = max(4, turn_count)
        if len(sentences) > max_sents_for_turns:
            print(f"[ScenarioEngine] sentences {len(sentences)} > cap "
                  f"{max_sents_for_turns}; randomly sampling.")
            sentences = rng.sample(sentences, max_sents_for_turns)
        else:
            sentences = list(sentences)
            rng.shuffle(sentences)

        # 把 nonce 传给生成线程，写入 prompt 防止 LLM 端缓存复用
        nonce = f"{int(time.time())}-{rng.randint(1000, 9999)}"

        # Initial progress: indeterminate-ish (1 of 2 phases)
        self.bank_progress_update.emit(0, 2)

        t = threading.Thread(
            target=self._run_generation,
            args=(groups, single_words, phrases, sentences, turn_count,
                  name, nonce, persist),
            daemon=True,
        )
        t.start()

    def _run_generation(self, groups, single_words, phrases, sentences,
                        turn_count, name, nonce="", persist: bool = True):
        try:
            config = self._load_config()

            # Route to omni if configured
            if _is_omni_provider(config):
                self._run_generation_omni(config, groups, single_words, phrases,
                                         sentences, turn_count, name, nonce, persist)
                return

            client, model = _get_llm_client_and_model(config)
            print(f"[ScenarioEngine] Using model={model} base_url={client.base_url} "
                  f"turns={turn_count} words={len(single_words)} "
                  f"phrases={len(phrases)} sentences={len(sentences)} nonce={nonce}")

            self.bank_progress_update.emit(1, 2)

            # 带连贯性自检的重试循环：最多 2 次尝试，保留连贯性最好的一次
            max_attempts = 2
            script = []
            raw_content = ""
            best_script = []
            best_raw = ""
            best_score = -1.0
            last_reason = ""
            for attempt in range(1, max_attempts + 1):
                attempt_nonce = f"{nonce}-try{attempt}" if nonce else f"try{attempt}"
                script, raw_content = self._call_llm_for_dialogue(
                    client, model, single_words, phrases, sentences,
                    turn_count, attempt_nonce,
                )
                score = self._dialogue_coherence_score(script)
                # 保留连贯性最佳的一次，避免重试越重越差却拿了最后一次
                if score > best_score or not best_script:
                    best_score = score
                    best_script = script
                    best_raw = raw_content
                ok, reason = self._check_coherence(script)
                if ok:
                    if attempt > 1:
                        print(f"[ScenarioEngine] coherence retry succeeded on "
                              f"attempt {attempt} (score={score:.2f}).")
                    best_script = script
                    best_raw = raw_content
                    break
                last_reason = reason
                print(f"[ScenarioEngine] coherence check FAILED (attempt {attempt}"
                      f"/{max_attempts}): score={score:.2f} < 0.55; retrying...")
            else:
                # 重试耗尽：采用连贯性最佳的版本（而非最后一次）
                print(f"[ScenarioEngine] coherence retry exhausted; using best "
                      f"available script (best_score={best_score:.2f}, {last_reason}).")
                script = best_script
                raw_content = best_raw

            if not script:
                self.bank_generation_error.emit("LLM 未生成有效对话内容。")
                return

            # Build bank
            bank_id = ("oneshot_" + str(uuid.uuid4())[:8]) if not persist else str(uuid.uuid4())[:8]
            group_str = "+".join(groups[:3])
            if len(groups) > 3:
                group_str += f"+{len(groups)-3}more"
            prefix = "🎲 随机会话_" if not persist else "情景会话_"
            bank_name = name or f"{prefix}{group_str}_{len(script)}轮"

            bank = {
                "id": bank_id,
                "name": bank_name,
                "source_groups": list(groups),
                "turn_count": len(script),
                "created_at": datetime.now().isoformat(),
                "script": script,
                "ephemeral": not persist,   # 标记此 bank 为一次性
            }

            if persist:
                data = self._load_banks_file()
                data["banks"].append(bank)
                self._save_banks_file(data)

            self.bank_progress_update.emit(2, 2)
            self.bank_generation_done.emit(bank)

        except Exception as e:
            err_str = str(e)
            print(f"[ScenarioEngine] generation failed: {e}")
            # 给 404 一个更具体的提示，因为这通常意味着 base_url 没指到 /v1 或模型名错
            if "404" in err_str or "Not Found" in err_str:
                hint = "（404：LLM 服务未找到对应路径。请检查「设置 → AI 引擎」中 base_url 是否包含 /v1，以及模型名是否正确。）"
                self.bank_generation_error.emit(f"生成失败: {e}\n{hint}")
            else:
                self.bank_generation_error.emit(f"生成失败: {e}")

    def _run_generation_omni(self, config, groups, single_words, phrases, sentences,
                             turn_count, name, nonce="", persist: bool = True):
        """Omni-path bank generation. Reuses _call_llm_for_dialogue's prompt +
        retry loop, but routes the LLM call through OmniClient.chat()."""
        try:
            client = _get_omni_client(config)
            model = config.get("omni_model", "minicpm-o45")
            print(f"[ScenarioEngine] Omni model={model} host={config.get('omni_host')} "
                  f"turns={turn_count} words={len(single_words)} "
                  f"phrases={len(phrases)} sentences={len(sentences)} nonce={nonce}")

            self.bank_progress_update.emit(1, 2)

            max_attempts = 2
            script = []
            raw_content = ""
            best_script = []
            best_raw = ""
            best_score = -1.0
            last_reason = ""
            for attempt in range(1, max_attempts + 1):
                attempt_nonce = f"{nonce}-try{attempt}" if nonce else f"try{attempt}"
                script, raw_content = self._call_llm_for_dialogue(
                    client, model, single_words, phrases, sentences,
                    turn_count, attempt_nonce,
                )
                score = self._dialogue_coherence_score(script)
                if score > best_score or not best_script:
                    best_score = score
                    best_script = script
                    best_raw = raw_content
                ok, reason = self._check_coherence(script)
                if ok:
                    if attempt > 1:
                        print(f"[ScenarioEngine] omni coherence retry succeeded on "
                              f"attempt {attempt} (score={score:.2f}).")
                    best_script = script
                    best_raw = raw_content
                    break
                else:
                    last_reason = reason
                    print(f"[ScenarioEngine] omni coherence check FAILED (attempt {attempt}"
                          f"/{max_attempts}): score={score:.2f} < 0.55; retrying...")
            else:
                print(f"[ScenarioEngine] omni coherence retry exhausted; using best "
                      f"available script (best_score={best_score:.2f}, {last_reason}).")
                script = best_script
                raw_content = best_raw

            if not script:
                self.bank_generation_error.emit("Omni 未生成有效对话内容。")
                return

            bank_id = ("oneshot_" + str(uuid.uuid4())[:8]) if not persist else str(uuid.uuid4())[:8]
            group_str = "+".join(groups[:3])
            if len(groups) > 3:
                group_str += f"+{len(groups)-3}more"
            prefix = "🎲 随机会话_" if not persist else "情景会话_"
            bank_name = name or f"{prefix}{group_str}_{len(script)}轮"

            bank = {
                "id": bank_id,
                "name": bank_name,
                "source_groups": list(groups),
                "turn_count": len(script),
                "created_at": datetime.now().isoformat(),
                "script": script,
                "ephemeral": not persist,
            }

            if persist:
                data = self._load_banks_file()
                data["banks"].append(bank)
                self._save_banks_file(data)

            self.bank_progress_update.emit(2, 2)
            self.bank_generation_done.emit(bank)

        except Exception as e:
            print(f"[ScenarioEngine] omni generation failed: {e}")
            self.bank_generation_error.emit(f"Omni 生成失败: {e}")

    # 候选场景池：每次生成随机挑 1 个，让 LLM 有不同主线
    SCENARIO_POOL = [
        "a school day with classmates",
        "a weekend trip to the park",
        "helping mom cook dinner at home",
        "a birthday party with friends",
        "visiting grandparents in the countryside",
        "shopping at a supermarket",
        "a rainy afternoon indoors",
        "preparing for a sports day",
        "a visit to the zoo",
        "an evening reading time before bed",
        "playing in the playground after school",
        "taking the bus to a museum",
        "tidying up the bedroom together",
        "a summer beach trip",
        "going to the doctor for a check-up",
        "celebrating Chinese New Year with family",
    ]

    # 用于连贯性自检的停用词（英文高频虚词 + 对话衔接词，不参与余弦相似度判断）
    _STOP = {
        "the", "a", "an", "i", "you", "we", "he", "she", "it", "they", "my", "your",
        "our", "his", "her", "their", "is", "are", "was", "were", "be", "been",
        "have", "has", "had", "do", "does", "did", "can", "could", "will", "would",
        "should", "may", "might", "must", "am", "and", "or", "but", "so", "yes",
        "no", "ok", "thanks", "thank", "of", "in", "on", "at", "to", "for", "with",
        "about", "it's", "that", "this", "those", "these",
    }

    @classmethod
    def _dialogue_coherence_score(cls, script: list) -> float:
        """简易连贯性自检：统计"相邻两轮共享至少 1 个实义词"的占比。

        阈值在 _check_coherence 中使用。只统计文本层，不依赖外部 NLP 库。
        返回 [0.0, 1.0]，越大越连贯。
        """
        if len(script) < 2:
            return 1.0

        def tokens(text):
            return {w for w in re.findall(r"[A-Za-z][A-Za-z'\-]*", (text or "").lower())
                    if w not in cls._STOP and len(w) > 1}

        hits = 0
        for i in range(1, len(script)):
            prev = tokens(script[i - 1].get("text", ""))
            cur = tokens(script[i].get("text", ""))
            if prev and cur and prev & cur:
                hits += 1
        return hits / max(1, len(script) - 1)

    @classmethod
    def _check_coherence(cls, script: list, threshold: float = 0.55) -> tuple:
        """返回 (ok, reason). 低于阈值则认为连贯性差，应触发重试。"""
        score = cls._dialogue_coherence_score(script)
        if score < threshold:
            return False, f"coherence_score={score:.2f} < {threshold}"
        return True, ""

    # ------------------------------------------------------------------ #
    #  Placeholder handling (sb./sth./sb./sb. sth. etc.)                   #
    # ------------------------------------------------------------------ #
    # 匹配词典体占位符：sb./sth.、sb.、sth.、sb. sth. 等（忽略大小写、允许尾部点号）
    _PLACEHOLDER_RE = re.compile(
        r"\b(?:sb\./sth\.|sb\.\s*/\s*sth\.|sb\.\s+sth\.|sb\.|sth\.)",
        re.IGNORECASE,
    )

    @classmethod
    def _substitute_placeholders(cls, text: str) -> str:
        """将词条里的词典体占位符替换为显式标记，便于 LLM 在对话里填入具体人/物。

        - "sb."         → "[PERSON]"
        - "sth."        → "[THING]"
        - "sb./sth."    → "[PERSON or THING]"
        没有占位符的词条原样返回。
        """
        if not text:
            return text
        # 顺序很重要：先匹配复合形式（sb./sth.、sb. sth.），再匹配单个
        def repl(m):
            s = m.group(0).lower().strip()
            if s.startswith("sb./sth.") or s.startswith("sb. sth.") or s.startswith("sb. / sth."):
                return "[PERSON or THING]"
            if s.startswith("sb"):
                return "[PERSON]"
            return "[THING]"
        return cls._PLACEHOLDER_RE.sub(repl, text)

    def _call_llm_for_dialogue(self, client, model: str,
                               single_words: list, phrases: list,
                               sentences: list, turn_count: int,
                               nonce: str = "") -> list:
        """Call LLM to produce a JSON dialogue script. Returns list of turns.

        参数：
            single_words: 单词词条（1 token）
            phrases:      短句/固定搭配词条（≥2 token）—— 优先级最高，必须原样复现
            sentences:    完整例句（来自 sentences 表）
        """
        # 预处理：把 sb./sth. 等词典占位符替换为显式 [PERSON]/[THING] 标记，
        # 避免 LLM 把 "sb." 原样写入对话台词。
        word_lines = "\n".join(
            f'- "{self._substitute_placeholders(w.get("text", ""))}" '
            f'({w.get("translation", "")})'
            for w in single_words if w.get("text")
        )
        phrase_lines = "\n".join(
            f'- "{self._substitute_placeholders(p.get("text", ""))}" '
            f'({p.get("translation", "")})'
            for p in phrases if p.get("text")
        )
        sentence_lines = "\n".join(
            f'- "{self._substitute_placeholders(s.get("text", ""))}" '
            f'({s.get("translation", "")})'
            for s in sentences if s.get("text")
        )

        # 每次随机选一个场景主线 —— 进一步增加多样性
        rng = random.Random(nonce or time.time_ns())
        scenario_hint = rng.choice(self.SCENARIO_POOL)

        # 短句覆盖目标：在轮数限制下尽可能多覆盖。若短句数 ≥ turn_count，
        # 至少要求覆盖 70% 的短句（避免饱和但保证主导地位）。
        if phrase_lines:
            phrase_target = min(len(phrases), max(1, int(turn_count * 0.7)))
            phrase_block = (
                f"🔑 CRITICAL: PHRASES / FIXED EXPRESSIONS — these MUST be reproduced "
                f"VERBATIM (do NOT paraphrase, split, or change tense/word order). "
                f"Aim to use AT LEAST {phrase_target} of the {len(phrases)} phrases below. "
                f"Each phrase should appear as a contiguous span inside a turn's English text:\n"
                f"{phrase_lines}\n"
            )
        else:
            phrase_block = ""

        prompt = f"""You are an English teacher writing a coherent, two-person dialogue for Chinese children (age 8-12).

The dialogue is between speaker A and speaker B.

⚠️ TOP PRIORITY (MUST FOLLOW): Generate EXACTLY {turn_count} turns total — no more, no less. Alternate A and B (start with A). The "script" array MUST contain exactly {turn_count} items.

REQUIREMENTS (in strict priority order):
1. ✅ Turn count: EXACTLY {turn_count} turns. If the vocabulary list is too long to fit in {turn_count} turns, IGNORE the extra single words rather than adding more turns. Phrases (below) take priority over single words.
2. 🧵 Narrative coherence: The conversation MUST be ONE continuous storyline.
   - Pick ONE scenario (recommended: "{scenario_hint}").
   - Every turn must either RESPOND TO the previous turn or NATURALLY CONTINUE the same storyline (e.g., "By the way...", "And then...").
   - ⛔ NEVER hard-cut to a completely unrelated topic just to squeeze in a vocabulary item. If a word doesn't fit the scene, skip it.
   - A and B should be having a REAL back-and-forth, not reciting disconnected facts.
3. 👤 Character consistency (LOCK):
   - In the "characters" object, define 2 characters with name + gender + age.
   - Keep the SAME characters and genders throughout the entire dialogue.
   - Pronouns (he/she/her/him/his) MUST always match the declared gender of the person being talked about.
   - ⛔ NEVER refer to a boy as "she" or a girl as "he". If you don't know the gender, use "it" for animals/objects only.
4. 🧩 Placeholder substitution (CRITICAL):
   - The word/phrase list may contain marked placeholders: [PERSON], [THING], [PERSON or THING].
   - These are dictionary-style abbreviations (sb. / sth.). ⛔ NEVER output them literally (never write "[PERSON]", "sb.", "sth." in the dialogue).
   - Replace each placeholder with a concrete noun from the current scene:
     • [PERSON] → a character's name declared in "characters" (Lily, Tom...) or a fitting role ("my mom", "the teacher").
     • [THING]  → a concrete object or topic fitting the scene ("the poster", "my new book", "lunch").
     • [PERSON or THING] → pick whichever fits better.
   - Example: vocabulary "I can offer to do sth." → "I can offer to help with the poster."
   - Example: vocabulary "share sth. with sb." → "share my story with Lily."
5. 🔑 Phrases / fixed expressions MUST appear VERBATIM in the dialogue (see CRITICAL block below) — EXCEPT any [PERSON]/[THING] marks, which MUST be replaced per rule 4.
6. Single words SHOULD be used as much as fits naturally; you may skip any that don't fit the scene.
7. Use simple grammar and short sentences (5-15 words each), suitable for children.
8. Provide a Chinese translation for each turn.
9. Return ONLY a single JSON object, no markdown fences, no explanations.

{phrase_block}
SINGLE WORDS (use as many as fit; randomly sampled, OK to skip any that don't fit the scene):
{word_lines if word_lines else "(none)"}

EXTRA SENTENCES (use only if natural and within turn limit):
{sentence_lines if sentence_lines else "(none)"}

OUTPUT FORMAT (strict JSON, "script" array length MUST be {turn_count}):
{{
  "title": "A short scenario title in English",
  "characters": [
    {{"name": "Lily", "gender": "girl", "age": 10, "role": "A"}},
    {{"name": "Tom", "gender": "boy", "age": 10, "role": "B"}}
  ],
  "script": [
    {{"role": "A", "text": "Hi Tom, did you have a try today?", "translation": "嗨，汤姆，你今天试了吗？"}},
    {{"role": "B", "text": "Yes! I want to make friends with everyone.", "translation": "试了！我想和大家做朋友。"}}
  ]
}}

Self-check before returning:
• Are there exactly {turn_count} items in "script"?
• Does every turn either reply to the previous one or continue the same scene?
• Are pronouns consistent with the "characters" genders?
• Does ANY turn contain "sb.", "sth.", "[PERSON]", "[THING]", or "[PERSON or THING]"? If so, REPLACE with concrete nouns from the scene.

Generation tag (for variety, ignore in output): {nonce}

Return JSON now (remember: exactly {turn_count} items in script; one coherent scene; consistent characters):"""

        # Scale max_tokens roughly with desired turns: ~120 tokens per turn (text+translation+JSON overhead)
        max_tokens = max(800, min(4000, turn_count * 130 + 400))

        # Detect omni client (no .chat.completions attribute) vs OpenAI client
        is_omni = not hasattr(client, "chat") or not hasattr(getattr(client, "chat", None), "completions")

        if is_omni:
            # OmniClient.chat(text) — single-turn, no seed param
            content = client.chat(text=prompt).strip()
        else:
            # 用更高的 temperature 让每次生成更多样；同时显式给一个随机 seed（部分服务支持）
            try:
                seed_val = int(nonce.split("-")[-1]) if nonce else rng.randint(1, 2**31 - 1)
            except Exception:
                seed_val = rng.randint(1, 2**31 - 1)

            kwargs = dict(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=max_tokens,
                temperature=0.9,
                top_p=0.95,
            )
            # 部分 OpenAI 兼容服务支持 seed；不支持时退回不带 seed 的调用
            try:
                response = client.chat.completions.create(seed=seed_val, **kwargs)
            except TypeError:
                response = client.chat.completions.create(**kwargs)
            except Exception as e:
                # seed 参数不被服务接受时也回退
                if "seed" in str(e).lower():
                    response = client.chat.completions.create(**kwargs)
                else:
                    raise

            content = response.choices[0].message.content.strip()
        script = self._parse_script_json(content)

        # 引擎层兜底：即使 LLM 没遵守也强制截断到 turn_count（保留偶数以维持 A/B 配对）。
        if len(script) > turn_count:
            print(f"[ScenarioEngine] LLM returned {len(script)} turns; "
                  f"truncating to {turn_count} (requested).")
            # 截到 turn_count；如果末尾恰好 A 单独成对，最后一对若不完整再去掉一句
            script = script[:turn_count]
        return script, content

    # ------------------------------------------------------------------ #
    #  Session Summary                                                    #
    # ------------------------------------------------------------------ #
    def summarize_session(self, session_results: list, scenario_title: str = ""):
        """Generate a friendly LLM summary based on per-turn scores. Async."""
        t = threading.Thread(
            target=self._run_summary,
            args=(session_results, scenario_title),
            daemon=True,
        )
        t.start()

    def _run_summary(self, session_results: list, scenario_title: str):
        try:
            if not session_results:
                self.summary_ready.emit("还没有得分数据呢，再来一次试试吧！")
                return

            scored = [r for r in session_results if r.get("score") is not None]
            if not scored:
                self.summary_ready.emit("这次会话评分还在计算中，可以稍后再看反馈。")
                return

            avg = sum(r.get("score", 0) for r in scored) / len(scored)
            low = [r for r in scored if r.get("score", 0) < 80]

            # Build summary lines for the prompt
            lines = []
            for i, r in enumerate(scored, 1):
                line = f"{i}. \"{r.get('text','')}\" → {r.get('score',0)}分"
                err_summary = r.get("error_brief", "")
                if err_summary:
                    line += f"  [问题: {err_summary}]"
                lines.append(line)
            score_block = "\n".join(lines)

            config = self._load_config()

            prompt = f"""你是给 8-12 岁中国孩子做英语口语教练。下面是孩子刚刚完成的一段情景会话录音的逐句发音得分。

场景：{scenario_title or '情景会话'}
平均分: {avg:.1f}
共 {len(scored)} 句，其中分数 < 80 的有 {len(low)} 句。

逐句得分：
{score_block}

请用中文写一段 80-150 字的鼓励反馈，要求：
1. 先肯定整体表现（基于平均分）。
2. 挑出 1-2 条最值得改进的发音问题（针对低分句中的具体音素或单词），给出具体可行的练习建议。
3. 语气亲切活泼，多用感叹号和小表情，让孩子愿意继续练习。
4. 不要列原文得分表，直接讲建议。

直接输出反馈文本，不要任何前缀或 JSON。"""

            # Route to omni if configured, else OpenAI-compatible
            if _is_omni_provider(config):
                try:
                    client = _get_omni_client(config)
                    text = client.chat(text=prompt).strip()
                    self.summary_ready.emit(text)
                    return
                except Exception as e:
                    print(f"[ScenarioEngine] omni summary failed: {e}")
                    self.summary_error.emit(f"Omni 反馈生成失败: {e}")
                    return

            client, model = _get_llm_client_and_model(config)
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=400,
                temperature=0.6,
            )
            text = response.choices[0].message.content.strip()
            self.summary_ready.emit(text)
        except Exception as e:
            print(f"[ScenarioEngine] summary failed: {e}")
            self.summary_error.emit(f"AI 反馈生成失败: {e}")

    # ------------------------------------------------------------------ #
    #  Bank Persistence (mirrors OralTestEngine)                          #
    # ------------------------------------------------------------------ #
    def _banks_file_path(self) -> str:
        return get_user_data_path("scenario_banks.json")

    def _load_banks_file(self) -> dict:
        path = self._banks_file_path()
        if not os.path.exists(path):
            return {"banks": []}
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if not isinstance(data, dict) or "banks" not in data:
                    return {"banks": []}
                return data
        except Exception as e:
            print(f"[ScenarioEngine] Failed to read scenario_banks.json: {e}")
            return {"banks": []}

    def _save_banks_file(self, data: dict):
        path = self._banks_file_path()
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[ScenarioEngine] Failed to write scenario_banks.json: {e}")

    def get_all_banks(self) -> list:
        data = self._load_banks_file()
        banks = data.get("banks", [])
        # 过滤掉遗留的 ephemeral（oneshot）记录：它们是一次性的，重启后应消失
        # 如果发现了需要过滤的，顺便清理文件
        filtered = [b for b in banks if not b.get("ephemeral")]
        if len(filtered) < len(banks):
            data["banks"] = filtered
            self._save_banks_file(data)
        filtered.sort(key=lambda b: b.get("created_at", ""), reverse=True)
        return filtered

    def get_bank_by_id(self, bank_id: str) -> dict:
        data = self._load_banks_file()
        for b in data.get("banks", []):
            if b.get("id") == bank_id:
                return b
        return None

    def delete_bank(self, bank_id: str) -> bool:
        data = self._load_banks_file()
        original_len = len(data["banks"])
        data["banks"] = [b for b in data["banks"] if b.get("id") != bank_id]
        if len(data["banks"]) < original_len:
            self._save_banks_file(data)
            return True
        return False

    def rename_bank(self, bank_id: str, new_name: str) -> bool:
        data = self._load_banks_file()
        for b in data.get("banks", []):
            if b.get("id") == bank_id:
                b["name"] = new_name
                self._save_banks_file(data)
                return True
        return False

    # ------------------------------------------------------------------ #
    #  Helpers                                                            #
    # ------------------------------------------------------------------ #
    def _load_config(self) -> dict:
        path = get_user_data_path("config.json")
        if not os.path.exists(path):
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _parse_script_json(self, content: str) -> list:
        """Parse the LLM dialogue JSON. Returns the script list, or [] on failure."""
        if not content:
            return []
        # Strip markdown fences if any
        content = re.sub(r"^```(?:json)?\s*", "", content.strip())
        content = re.sub(r"\s*```$", "", content.strip())

        # Direct attempt
        obj = None
        try:
            obj = json.loads(content)
        except json.JSONDecodeError:
            # Try to grab the first {...} block
            m = re.search(r"\{.*\}", content, re.DOTALL)
            if m:
                try:
                    obj = json.loads(m.group())
                except json.JSONDecodeError:
                    obj = None

        if not isinstance(obj, dict):
            return []
        script = obj.get("script", [])
        if not isinstance(script, list):
            return []

        # Sanitize each turn
        cleaned = []
        for turn in script:
            if not isinstance(turn, dict):
                continue
            role = str(turn.get("role", "")).strip().upper()
            if role not in ("A", "B"):
                continue
            text = str(turn.get("text", "")).strip()
            if not text:
                continue
            cleaned.append({
                "role": role,
                "text": text,
                "translation": str(turn.get("translation", "")).strip(),
            })

        return cleaned
