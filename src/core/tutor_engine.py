"""
TutorEngine - AI English Home Tutor state machine.

Controls the teaching flow: Word → Repeat → Meaning → Choice → Sentence → MicroDialogue.
LLM only generates content; phase transitions are fully controlled by this engine.
"""
import json
import os
import re
import random
import threading
from enum import Enum, auto

from src.core.qt_compat import QObject, pyqtSignal

from src.core.content_parser import _get_llm_client_and_model, _is_omni_provider, _get_omni_client
from src.core.speech_recognizer import WhisperRecognizer
from src.utils import get_user_data_path


class TutorPhase(Enum):
    IDLE = auto()
    WORD_LISTEN = auto()       # 跟读（GOP 评分）
    WORD_MEANING = auto()      # 问含义（ASR 识别回答）
    WORD_CHOICE = auto()       # 选择题
    SENTENCE_MAKING = auto()   # 造句（ASR + 语法检查 by LLM）
    MICRO_DIALOGUE = auto()    # 1轮微对话
    RETRY_PHASE = auto()       # 复习弱词
    SESSION_COMPLETE = auto()  # 会话结束


# Valid actions the LLM can return
VALID_ACTIONS = {
    "teach_word", "ask_repeat", "ask_meaning", "ask_choice",
    "ask_sentence", "dialogue", "feedback", "next_word", "session_end"
}

# Expected action(s) per phase — Engine validates LLM output
PHASE_EXPECTED_ACTIONS = {
    TutorPhase.WORD_LISTEN: {"teach_word", "ask_repeat", "feedback"},
    TutorPhase.WORD_MEANING: {"ask_meaning", "ask_choice", "feedback"},
    TutorPhase.WORD_CHOICE: {"ask_choice", "feedback"},
    TutorPhase.SENTENCE_MAKING: {"ask_sentence", "feedback"},
    TutorPhase.MICRO_DIALOGUE: {"dialogue", "feedback"},
    TutorPhase.RETRY_PHASE: {"ask_repeat", "dialogue", "feedback", "teach_word"},
    TutorPhase.SESSION_COMPLETE: {"session_end", "feedback"},
}


TUTOR_SYSTEM_PROMPT = """你是一个面向中国初中生的英语情景对话教练（学生年龄12-15岁，已有小学英语基础）。
你的任务是通过模拟真实场景的对话，让学生在交流中自然练习目标词汇。

学生: {student_name}

当前状态：
- 目标词条: {current_word} ({translation})
- 当前阶段: {phase}
- 可用词汇表: {allowed_words}

教学方式（极其重要）：
你不是在"教单词"——你是在和学生进行模拟情景对话！
每次轮到你说话时，你要设计一个自然的生活场景（如购物、问路、打电话、在学校等），
让对话中的英语句子包含当前目标词汇或其他词汇表中的词，然后引导学生用英语回应。

难度要求（极其重要）：
- 初中生已掌握基础日常词汇，不要再问太简单的问题（如 "What is your name?"、"How are you?"）
- 选择题的干扰项必须是合理的易混淆项（如同义词、形近词、相关但错误的搭配），不要设置明显错误的选项
- 造句要求应引导学生使用较复杂的句式（如条件句、定语从句、比较级等），不要只要求简单主谓宾
- 对话情景要体现真实交际需求（如委婉请求、表达观点、比较选择），而非机械问答
- 英语句子长度应在 8-15 词之间，避免过短（3-4词）或过长

例如，教 "profile" 时：
- 你说："假设你在学校认识新朋友，对方想了解你：Can you tell me something about your profile? 你会怎么介绍自己呢？"
- 学生尝试回答
- 你鼓励并纠正

RULES:
1. **语言规则**：你的所有输出必须用**中文**写！只有对话中的英文句子保留英文。
   ✅ "好，假设你在餐厅点餐。服务员问你：Would you like to see the menu? 你怎么回答？"
   ❌ "Welcome! Today we will learn menu." ← 全英文，错误！
2. ONLY use vocabulary from the allowed list. 禁止引入超纲词汇.
3. Keep responses SHORT (≤60 words for text field).
4. One task at a time. 每次只推动一步对话.
5. 鼓励学生，温和纠正错误.
6. You MUST respond in JSON format ONLY:
   {{"action": "...", "text": "...", "tts_text": "..."}}
7. For ask_choice action, also include: "options": ["A. xxx", "B. xxx", "C. xxx"] (3 choices, one correct). 干扰项必须有迷惑性！
8. NEVER decide phase transitions. Only generate content for the CURRENT phase.
9. tts_text 必须和 text 完全一样，直接复制 text 的内容即可.
10. 情景要多样化：购物、餐厅点餐、问路、看病、打电话、运动、旅行、天气、生日派对等，不要重复同一场景.
11. 尽量让对话中的英文句子同时包含多个词汇表中的词，帮学生在语境中串联记忆.
12. 不要做翻译练习或机械跟读，而是让学生在对话中自然使用英语.
13. 不要输出 <think> 或 <action> 等思考标签，直接输出JSON.
"""


class TutorEngine(QObject):
    """AI English Home Tutor - state machine driving the teaching flow."""

    # Signals for UI communication
    tutor_action_ready = pyqtSignal(dict)       # LLM action+text parsed result
    pronunciation_score_ready = pyqtSignal(int, str)  # score, feedback
    session_state_updated = pyqtSignal(dict)    # word_banner, progress, etc.
    asr_loading = pyqtSignal(bool)              # ASR model loading indicator
    error_occurred = pyqtSignal(str)            # Error message
    omni_audio_ready = pyqtSignal(str)          # Omni TTS audio URL (optional)

    MAX_RETRY_ROUNDS = 2
    MASTERY_THRESHOLD = 60  # below this → retry_queue

    def __init__(self, exercise_manager, tts_engine=None):
        super().__init__()
        self.exercise_manager = exercise_manager
        self.tts = tts_engine

        # Session state
        self.phase = TutorPhase.IDLE
        self.topic = ""
        self.vocabulary = []        # list of {"text": ..., "translation": ...}
        self.word_index = 0
        self.current_word = None    # current word dict
        self.student_name = ""

        # Three-dimensional mastery per word
        self.word_mastery = {}      # word_text → {pronunciation, meaning, grammar, used_in_dialogue}

        # Retry mechanism
        self.retry_queue = []
        self.retry_round = 0
        self._retry_count = 0       # retries within a phase (e.g. pronunciation < 70)
        self._in_retry = False

        # ASR (lazy-loaded)
        self._recognizer = None
        self._recognizer_lock = threading.Lock()

        # Dialogue history for LLM context
        self._messages = []

        # LLM client cache
        self._llm_client = None
        self._llm_model = None

    # ------------------------------------------------------------------ #
    #  Public API                                                          #
    # ------------------------------------------------------------------ #

    def start_session(self, topic: str, vocabulary: list):
        """Start a new tutoring session.

        Args:
            topic: Topic name (e.g. group name)
            vocabulary: list of dicts with "text" and "translation" keys
        """
        self.topic = topic
        self.vocabulary = vocabulary[:]
        random.shuffle(self.vocabulary)
        self.word_index = 0
        self.retry_queue = []
        self.retry_round = 0
        self._in_retry = False

        # Load student name from config
        config = self._load_config()
        self.student_name = config.get("student_name", "") or "同学"

        # Initialize mastery
        self.word_mastery = {}
        for w in self.vocabulary:
            self.word_mastery[w["text"]] = {
                "pronunciation": 0,
                "meaning": 0,
                "grammar": 0,
                "used_in_dialogue": False,
            }

        # Reset LLM context
        self._messages = []
        self._llm_client = None
        self._llm_model = None

        # Start ASR warmup in background
        self._warmup_asr_async()

        # Begin teaching first word
        self.current_word = self.vocabulary[0]
        self.phase = TutorPhase.WORD_LISTEN
        self._retry_count = 0

        self._emit_state()
        self._request_llm_intro()

    def stop_session(self):
        """Force-stop the session."""
        self.phase = TutorPhase.IDLE
        self._messages = []

    def handle_pronunciation_result(self, score: int, feedback: str = ""):
        """Called after GOP scoring completes.

        Args:
            score: 0-100 pronunciation score
            feedback: text feedback from GOP
        """
        if self.phase not in (TutorPhase.WORD_LISTEN, TutorPhase.RETRY_PHASE):
            return

        word_text = self.current_word["text"]
        self.word_mastery[word_text]["pronunciation"] = max(
            self.word_mastery[word_text]["pronunciation"], score
        )
        self.pronunciation_score_ready.emit(score, feedback)

        # Decide: advance or retry
        if score >= 70 or self._retry_count >= 3:
            if self._in_retry:
                # In retry, after pronunciation → micro dialogue
                self.phase = TutorPhase.MICRO_DIALOGUE
            else:
                self.phase = TutorPhase.WORD_MEANING
            self._retry_count = 0
            self._emit_state()
            self._request_llm_for_phase(
                extra_context=self._get_phase_hint()
            )
        else:
            self._retry_count += 1
            # Ask LLM to encourage and request repeat
            self._request_llm_for_phase(extra_context=f"学生发音得分 {score} 分（满分100）。请鼓励学生，让他/她再跟读一次。")

    def handle_asr_result(self, transcribed_text: str):
        """Called after ASR transcription completes.

        Args:
            transcribed_text: what the student said
        """
        if not transcribed_text.strip():
            self._request_llm_for_phase(extra_context="学生的回答听不清楚或为空。请让学生再说一次。")
            return

        word_text = self.current_word["text"]

        if self.phase == TutorPhase.WORD_MEANING:
            self._handle_meaning_answer(transcribed_text, word_text)
        elif self.phase == TutorPhase.SENTENCE_MAKING:
            self._handle_sentence_answer(transcribed_text, word_text)
        elif self.phase == TutorPhase.MICRO_DIALOGUE:
            self._handle_dialogue_answer(transcribed_text, word_text)
        else:
            # Generic: just send to LLM
            self._request_llm_for_phase(extra_context=f"学生说了：\"{transcribed_text}\"")

    def handle_choice_answer(self, chosen_option: str, correct_option: str):
        """Called when student selects a choice.

        Args:
            chosen_option: what they picked
            correct_option: the correct answer
        """
        word_text = self.current_word["text"]
        is_correct = chosen_option.strip().lower() == correct_option.strip().lower()

        # If we're in WORD_MEANING and LLM used ask_choice, update meaning score too
        if self.phase == TutorPhase.WORD_MEANING:
            self.word_mastery[word_text]["meaning"] = 100 if is_correct else 0

        if is_correct:
            # Advance: skip SENTENCE_MAKING for items that are already sentences
            next_phase = self._get_next_phase_after_choice()
            self.phase = next_phase
            self._retry_count = 0
            self._emit_state()
            if next_phase == TutorPhase.MICRO_DIALOGUE:
                self._request_llm_for_phase(
                    extra_context="学生选对了！现在进入微对话环节，请自然地使用目标词汇发起对话。"
                )
            else:
                self._request_llm_for_phase(
                    extra_context="学生选对了！" + self._get_phase_hint()
                )
        else:
            next_phase = self._get_next_phase_after_choice()
            self.phase = next_phase
            self._retry_count = 0
            self._emit_state()
            self._request_llm_for_phase(
                extra_context=f"学生选了'{chosen_option}'，但正确答案是'{correct_option}'。"
                              f"请简短纠正，然后继续下一个任务。"
            )

    def transcribe_audio(self, audio_path: str) -> str:
        """Run ASR on audio file (blocking). Call from worker thread."""
        recognizer = self._get_recognizer()
        if recognizer is None:
            return ""
        return recognizer.transcribe(audio_path, language="en")

    def is_asr_ready(self) -> bool:
        return self._recognizer is not None and self._recognizer.is_ready()

    def get_session_summary(self) -> dict:
        """Return summary statistics for the session."""
        total = len(self.vocabulary)
        mastered = 0
        weak_words = []
        for w in self.vocabulary:
            m = self.word_mastery.get(w["text"], {})
            avg = (m.get("pronunciation", 0) + m.get("meaning", 0) + m.get("grammar", 0)) / 3
            if avg >= self.MASTERY_THRESHOLD:
                mastered += 1
            else:
                weak_words.append(w["text"])
        return {
            "topic": self.topic,
            "total_words": total,
            "mastered": mastered,
            "weak_words": weak_words,
            "word_mastery": self.word_mastery,
        }

    # ------------------------------------------------------------------ #
    #  Phase Logic (private)                                               #
    # ------------------------------------------------------------------ #

    def _handle_meaning_answer(self, text: str, word_text: str):
        """Check if student knows the meaning."""
        translation = self.current_word.get("translation", "")
        # Simple check: if translation appears in student's answer
        # Let LLM do the actual judgment by including the context
        self._request_llm_for_phase(
            extra_context=f"学生回答：\"{text}\"。"
                          f"正确意思是：\"{translation}\"。"
                          f"请判断学生的回答是否表达了相同的意思。"
                          f"如果正确，用 action 'feedback' 回复并包含 'meaning_correct': true。"
                          f"如果错误，用 'meaning_correct': false 并给出正确答案。"
        )

    def _handle_sentence_answer(self, text: str, word_text: str):
        """Student made a sentence. LLM checks grammar."""
        self._request_llm_for_phase(
            extra_context=f"学生造了这个句子：\"{text}\"。"
                          f"请检查语法和词汇使用。"
                          f"在回复中包含 'grammar_correct': bool 和 'correction': str 或 null。"
        )

    def _handle_dialogue_answer(self, text: str, word_text: str):
        """Handle micro-dialogue reply."""
        self.word_mastery[word_text]["used_in_dialogue"] = True
        # Let LLM respond, then we advance
        self._request_llm_for_phase(
            extra_context=f"学生回复了：\"{text}\"。"
                          f"请给一个简短积极的回应来结束这段微对话。"
                          f"使用 action 'feedback'。"
        )

    def _advance_after_feedback(self, action_dict: dict):
        """Called after LLM feedback to decide next phase."""
        word_text = self.current_word["text"]

        if self.phase == TutorPhase.WORD_MEANING:
            meaning_correct = action_dict.get("meaning_correct", True)
            self.word_mastery[word_text]["meaning"] = 100 if meaning_correct else 0
            # For sentences, skip WORD_CHOICE and SENTENCE_MAKING
            if self._is_sentence():
                self.phase = TutorPhase.MICRO_DIALOGUE
            else:
                self.phase = TutorPhase.WORD_CHOICE
            self._retry_count = 0
            self._emit_state()
            self._request_llm_for_phase(extra_context=self._get_phase_hint())

        elif self.phase == TutorPhase.SENTENCE_MAKING:
            grammar_correct = action_dict.get("grammar_correct", True)
            if grammar_correct:
                self.word_mastery[word_text]["grammar"] = 100
            else:
                self.word_mastery[word_text]["grammar"] = 50
            self.phase = TutorPhase.MICRO_DIALOGUE
            self._retry_count = 0
            self._emit_state()
            self._request_llm_for_phase(extra_context=self._get_phase_hint())

        elif self.phase == TutorPhase.MICRO_DIALOGUE:
            self.word_mastery[word_text]["used_in_dialogue"] = True
            # Check mastery → retry_queue
            avg = self._calc_mastery(word_text)
            if avg < self.MASTERY_THRESHOLD:
                if word_text not in self.retry_queue:
                    self.retry_queue.append(word_text)
            self._next_word()

        elif self.phase == TutorPhase.RETRY_PHASE:
            # After retry dialogue, check again
            avg = self._calc_mastery(word_text)
            if avg >= self.MASTERY_THRESHOLD and word_text in self.retry_queue:
                self.retry_queue.remove(word_text)
            self._next_word()

    def _next_word(self):
        """Move to the next word or finish session."""
        if self._in_retry:
            # In retry mode: pop next from retry_queue
            if self.retry_queue and self.retry_round < self.MAX_RETRY_ROUNDS:
                word_text = self.retry_queue[0]
                # Find the word dict
                word_dict = next((w for w in self.vocabulary if w["text"] == word_text), None)
                if word_dict:
                    self.current_word = word_dict
                    self.phase = TutorPhase.RETRY_PHASE
                    self._retry_count = 0
                    self._emit_state()
                    self._request_llm_for_phase(
                        extra_context=f"现在是复习时间。学生需要再练习一下 '{word_text}'。"
                                      f"请让学生跟你读。"
                    )
                    return
            # Retry done
            self.retry_round += 1
            if self.retry_queue and self.retry_round < self.MAX_RETRY_ROUNDS:
                # Another round
                self._next_word()
                return
            # All retries done → session complete
            self.phase = TutorPhase.SESSION_COMPLETE
            self._emit_state()
            self._request_llm_session_end()
            return

        # Normal flow: next word
        self.word_index += 1
        if self.word_index < len(self.vocabulary):
            self.current_word = self.vocabulary[self.word_index]
            self.phase = TutorPhase.WORD_LISTEN
            self._retry_count = 0
            self._emit_state()
            self._request_llm_for_phase(
                extra_context=f"介绍新词 '{self.current_word['text']}'（{self.current_word.get('translation', '')}）。"
            )
        else:
            # All words done → check retry
            if self.retry_queue:
                self._in_retry = True
                self.retry_round = 0
                self._next_word()
            else:
                self.phase = TutorPhase.SESSION_COMPLETE
                self._emit_state()
                self._request_llm_session_end()

    def _calc_mastery(self, word_text: str) -> float:
        m = self.word_mastery.get(word_text, {})
        return (m.get("pronunciation", 0) + m.get("meaning", 0) + m.get("grammar", 0)) / 3

    def _is_sentence(self, text: str = None) -> bool:
        """Check if the current vocabulary item is already a sentence/long phrase."""
        if text is None:
            text = self.current_word.get("text", "") if self.current_word else ""
        word_count = len(text.split())
        has_punct = any(c in text for c in ".?!")
        return word_count > 4 or has_punct

    def _get_item_type(self) -> str:
        """Return the type of current vocabulary item for LLM context."""
        text = self.current_word.get("text", "") if self.current_word else ""
        if self._is_sentence(text):
            return "sentence/phrase (已是完整句子，不需要再造句)"
        return "word/short phrase"

    def _get_next_phase_after_choice(self) -> TutorPhase:
        """Determine next phase after choice answer: skip SENTENCE_MAKING for sentences."""
        if self._is_sentence():
            return TutorPhase.MICRO_DIALOGUE
        return TutorPhase.SENTENCE_MAKING

    def _get_phase_hint(self) -> str:
        """Generate extra context hint based on current phase and item type."""
        is_sent = self._is_sentence()
        if self.phase == TutorPhase.WORD_MEANING:
            if is_sent:
                return "请考考学生这个句子/短语的意思。用选择题（ask_choice），给出3个选项。"
            return "请考考学生这个词是什么意思。"
        elif self.phase == TutorPhase.SENTENCE_MAKING:
            other_words = [w["text"] for w in self.vocabulary if w["text"] != self.current_word.get("text", "")]
            sample = random.sample(other_words, min(3, len(other_words))) if other_words else []
            return (f"请让学生用 '{self.current_word.get('text', '')}' 造句。"
                    f"可以建议结合这些词汇：{sample}")
        elif self.phase == TutorPhase.MICRO_DIALOGUE:
            other_words = [w["text"] for w in self.vocabulary if w["text"] != self.current_word.get("text", "")]
            sample = random.sample(other_words, min(2, len(other_words))) if other_words else []
            return (f"请自然地使用 '{self.current_word.get('text', '')}' 发起一轮微对话。"
                    f"也可以提及：{sample}。向学生提一个可以回答的问题。")
        return ""

    # ------------------------------------------------------------------ #
    #  LLM Communication                                                   #
    # ------------------------------------------------------------------ #

    def _request_llm_intro(self):
        """Request opening message from LLM."""
        word = self.current_word
        extra = (
            f"请向 {self.student_name} 问好。告诉他/她今天的主题是 '{self.topic}'。"
            f"用一句自然的话介绍第一个词 '{word['text']}'（{word.get('translation', '')}），"
            f"比如'我们今天来学习一个新词'之类的开场白，然后让学生跟着读。"
            f"使用 action 'teach_word'。注意：text 字段要包含完整的开场白+词语介绍，不要只输出词本身。"
        )
        self._request_llm_for_phase(extra_context=extra)

    def _request_llm_session_end(self):
        """Request session summary from LLM."""
        summary = self.get_session_summary()
        extra = (
            f"课程即将结束。学生学了 {summary['total_words']} 个词，"
            f"掌握了 {summary['mastered']} 个。"
            f"薄弱词：{summary['weak_words'][:5]}。"
            f"请用中文给一个简短的鼓励性总结。使用 action 'session_end'。"
        )
        threading.Thread(
            target=self._llm_call,
            args=(extra,),
            daemon=True
        ).start()

    def _request_llm_for_phase(self, extra_context: str = ""):
        """Send request to LLM in background thread."""
        threading.Thread(
            target=self._llm_call,
            args=(extra_context,),
            daemon=True
        ).start()

    def _llm_call(self, extra_context: str = ""):
        """Background LLM call. Parses structured JSON response."""
        try:
            config = self._load_config()
            # Route to omni client if configured
            if _is_omni_provider(config):
                self._llm_call_omni(config, extra_context)
                return
            if self._llm_client is None:
                self._llm_client, self._llm_model = _get_llm_client_and_model(config)

            # Build system prompt
            allowed_words = ", ".join(w["text"] for w in self.vocabulary[:20])
            if len(self.vocabulary) > 20:
                allowed_words += f" ... ({len(self.vocabulary)} total)"

            system_prompt = TUTOR_SYSTEM_PROMPT.format(
                student_name=self.student_name,
                current_word=self.current_word["text"],
                translation=self.current_word.get("translation", ""),
                item_type=self._get_item_type(),
                phase=self.phase.name,
                allowed_words=allowed_words,
            )

            # Build messages
            messages = [{"role": "system", "content": system_prompt}]

            # Include recent dialogue history (last 10 messages)
            messages.extend(self._messages[-10:])

            # Add current user turn with extra context
            user_content = f"[Phase: {self.phase.name}]"
            if extra_context:
                user_content += f"\n{extra_context}"
            user_content += "\n\n请直接输出JSON，不要输出任何其他内容。格式：{\"action\": \"...\", \"text\": \"...\", \"tts_text\": \"...\"}"
            messages.append({"role": "user", "content": user_content})

            # Call LLM
            response = self._llm_client.chat.completions.create(
                 model=self._llm_model,
                messages=messages,
                temperature=0.4,
                max_tokens=300,
            )

            raw_text = response.choices[0].message.content.strip()
            # Some models (Qwen3 via Ollama) put thinking in reasoning_content — ignore it
            # If reasoning_content exists and content is empty, that's a problem; log it.
            rc = getattr(response.choices[0].message, 'reasoning_content', None)
            if rc:
                print(f"[TutorEngine] LLM reasoning_content ignored ({len(rc)} chars)")
            print(f"[TutorEngine] LLM raw: {raw_text[:200]}")

            # Parse JSON action
            action_dict = self._parse_llm_response(raw_text)

            # Save to dialogue history
            self._messages.append({"role": "user", "content": user_content})
            self._messages.append({"role": "assistant", "content": raw_text})

            # Validate action for current phase
            action = action_dict.get("action", "feedback")
            expected = PHASE_EXPECTED_ACTIONS.get(self.phase, {"feedback"})
            if action not in expected and action != "feedback":
                print(f"[TutorEngine] Action '{action}' not expected in {self.phase.name}, forcing 'feedback'")
                action_dict["action"] = "feedback"

            # Emit to UI
            self.tutor_action_ready.emit(action_dict)

            # Auto-advance for certain actions
            # Only auto-advance if this was a genuine feedback (not a forced fallback
            # from ask_choice/ask_meaning etc.)
            if action == "feedback" and self.phase in (
                TutorPhase.WORD_MEANING, TutorPhase.SENTENCE_MAKING,
                TutorPhase.MICRO_DIALOGUE, TutorPhase.RETRY_PHASE
            ):
                # Check if this is a response to student input (has meaning_correct/grammar_correct)
                # or a forced feedback from invalid action — don't auto-advance on introductory messages
                has_student_response = (
                    action_dict.get("meaning_correct") is not None
                    or action_dict.get("grammar_correct") is not None
                    or "学生" in (extra_context or "")
                    or "Student" in (extra_context or "")
                )
                if has_student_response:
                    self._advance_after_feedback(action_dict)

        except Exception as e:
            print(f"[TutorEngine] LLM error: {e}")
            self.error_occurred.emit(f"AI 请求失败: {str(e)[:100]}")

    def _llm_call_omni(self, config, extra_context: str = ""):
        """LLM call via MiniCPM-o Omni client (custom JWT+SSE API)."""
        try:
            from src.core.omni_client import OmniError
            client = _get_omni_client(config)

            # Build the same system + user prompt as the OpenAI path
            allowed_words = ", ".join(w["text"] for w in self.vocabulary[:20])
            if len(self.vocabulary) > 20:
                allowed_words += f" ... ({len(self.vocabulary)} total)"

            system_prompt = TUTOR_SYSTEM_PROMPT.format(
                student_name=self.student_name,
                current_word=self.current_word["text"],
                translation=self.current_word.get("translation", ""),
                item_type=self._get_item_type(),
                phase=self.phase.name,
                allowed_words=allowed_words,
            )

            # Omni chat has no separate system role; concatenate.
            user_content = f"[Phase: {self.phase.name}]"
            if extra_context:
                user_content += f"\n{extra_context}"
            user_content += "\n\n请直接输出JSON，不要输出任何其他内容。格式：{\"action\": \"...\", \"text\": \"...\", \"tts_text\": \"...\"}"

            # Include recent dialogue as context text
            history_text = ""
            for msg in self._messages[-10:]:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                history_text += f"{role}: {content}\n"

            full_prompt = (
                f"{system_prompt}\n\n"
                f"对话历史:\n{history_text}\n"
                f"user: {user_content}"
            )

            def on_audio_merged(url):
                if url and config.get("omni_tts_enabled", True):
                    self.omni_audio_ready.emit(url)

            raw_text = client.chat(
                text=full_prompt,
                on_audio_merged=on_audio_merged,
            )

            print(f"[TutorEngine] Omni raw: {raw_text[:200]}")

            # Reuse the same JSON parser + validation
            action_dict = self._parse_llm_response(raw_text)

            self._messages.append({"role": "user", "content": user_content})
            self._messages.append({"role": "assistant", "content": raw_text})

            action = action_dict.get("action", "feedback")
            expected = PHASE_EXPECTED_ACTIONS.get(self.phase, {"feedback"})
            if action not in expected and action != "feedback":
                print(f"[TutorEngine] Omni action '{action}' not expected in {self.phase.name}, forcing 'feedback'")
                action_dict["action"] = "feedback"

            self.tutor_action_ready.emit(action_dict)

            if action == "feedback" and self.phase in (
                TutorPhase.WORD_MEANING, TutorPhase.SENTENCE_MAKING,
                TutorPhase.MICRO_DIALOGUE, TutorPhase.RETRY_PHASE
            ):
                has_student_response = (
                    action_dict.get("meaning_correct") is not None
                    or action_dict.get("grammar_correct") is not None
                    or "学生" in (extra_context or "")
                    or "Student" in (extra_context or "")
                )
                if has_student_response:
                    self._advance_after_feedback(action_dict)

        except OmniError as e:
            print(f"[TutorEngine] Omni error: {e}")
            self.error_occurred.emit(f"Omni 请求失败: {str(e)[:100]}")
        except Exception as e:
            print(f"[TutorEngine] Omni error: {e}")
            self.error_occurred.emit(f"Omni 请求失败: {str(e)[:100]}")

    def _parse_llm_response(self, raw: str) -> dict:
        """Extract JSON from LLM response, with fallback."""
        # Strip thinking/reasoning tags — cover all known formats:
        # <think>...</think>, <thinking>...</thinking>, <action>...</action>, <reason>...</reason>
        cleaned = re.sub(r'<(?:think|thinking|action|reason)>.*?</(?:think|thinking|action|reason)>', '', raw, flags=re.DOTALL)
        # Some models (Qwen3 via Ollama) use ạcented brackets or no-angle formats
        # Strip any remaining XML-like tags before JSON
        cleaned = re.sub(r'<[^/][^>]*>.*?</[^>]*>', '', cleaned, flags=re.DOTALL)
        cleaned = cleaned.strip()
        # Also strip markdown code fences that some models wrap JSON in
        cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned)
        cleaned = re.sub(r'\s*```\s*$', '', cleaned)
        # Strip any leading non-JSON text (model preamble before the JSON object)
        # Find the first '{' and truncate everything before it
        brace_idx = cleaned.find('{')
        if brace_idx > 0:
            cleaned = cleaned[brace_idx:]

        # Try direct JSON parse
        try:
            data = json.loads(cleaned)
            if isinstance(data, dict) and "action" in data:
                return self._sanitize_action(data)
        except json.JSONDecodeError:
            pass

        # Try extracting JSON from markdown code block or mixed text
        json_match = re.search(r'\{[^{}]*"action"[^{}]*\}', cleaned, re.DOTALL)
        if json_match:
            try:
                data = json.loads(json_match.group())
                if isinstance(data, dict):
                    return self._sanitize_action(data)
            except json.JSONDecodeError:
                pass

        # Try more aggressive extraction with nested braces
        brace_match = re.search(r'\{.*\}', cleaned, re.DOTALL)
        if brace_match:
            try:
                data = json.loads(brace_match.group())
                if isinstance(data, dict):
                    return self._sanitize_action(data)
            except json.JSONDecodeError:
                pass

        # Fallback: treat entire response as text feedback
        print(f"[TutorEngine] Failed to parse JSON, using fallback. Cleaned: {cleaned[:100]}")
        return {
            "action": "feedback",
            "text": cleaned,
            "tts_text": "",
        }

    def _sanitize_action(self, data: dict) -> dict:
        """Strip any remaining thinking/reasoning tags from action text fields."""
        tag_pattern = r'<(?:think|thinking|action|reason)>.*?</(?:think|thinking|action|reason)>'
        for key in ("text", "tts_text"):
            val = data.get(key, "")
            if isinstance(val, str):
                data[key] = re.sub(tag_pattern, '', val, flags=re.DOTALL).strip()
        return data

    # ------------------------------------------------------------------ #
    #  ASR (Speech Recognition)                                            #
    # ------------------------------------------------------------------ #

    def _get_recognizer(self) -> WhisperRecognizer:
        """Get or create the Whisper recognizer (lazy)."""
        if self._recognizer is None:
            with self._recognizer_lock:
                if self._recognizer is None:
                    config = self._load_config()
                    model_size = config.get("whisper_model_size", "medium")
                    self.asr_loading.emit(True)
                    self._recognizer = WhisperRecognizer(model_size=model_size)
                    self._recognizer.warmup()
                    self.asr_loading.emit(False)
        return self._recognizer

    def _warmup_asr_async(self):
        """Pre-load ASR model in background."""
        def _warmup():
            self._get_recognizer()
        threading.Thread(target=_warmup, daemon=True).start()

    # ------------------------------------------------------------------ #
    #  Helpers                                                             #
    # ------------------------------------------------------------------ #

    def _load_config(self) -> dict:
        config_path = get_user_data_path("config.json")
        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                pass
        return {}

    def _emit_state(self):
        """Emit current session state for UI update."""
        state = {
            "phase": self.phase.name,
            "word": self.current_word.get("text", "") if self.current_word else "",
            "translation": self.current_word.get("translation", "") if self.current_word else "",
            "word_index": self.word_index,
            "total_words": len(self.vocabulary),
            "topic": self.topic,
            "in_retry": self._in_retry,
            "retry_queue_size": len(self.retry_queue),
            "mastery": self.word_mastery.get(
                self.current_word["text"], {}
            ) if self.current_word else {},
        }
        self.session_state_updated.emit(state)
