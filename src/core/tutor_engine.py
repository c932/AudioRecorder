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

# 每个阶段的行为卡片（注入 system prompt）
PHASE_BEHAVIOR = {
    "WORD_LISTEN": "用一个小情景引入当前词（teach_word），英语台词里自然用到它；结尾一句中文提示跟读。不要给翻译腔的机械介绍。",
    "RETRY_PHASE": "这个词学生没掌握，先用 ask_repeat 请他跟读一遍，顺带鼓励。简短一点。",
    "WORD_MEANING": "考意思：优先 ask_meaning 用一个包含目标词的情景句问『它是什么意思』；偶尔出 ask_choice 选择题。",
    "WORD_CHOICE": "出一道四选一（ask_choice）考词义或用法，界面会展示选项列表。",
    "SENTENCE_MAKING": "请学生用目标词造句（ask_sentence），可以给一个句式开头提示，鼓励复杂一点的句式。",
    "MICRO_DIALOGUE": "以真实场景发起一轮对话（dialogue）：你说一句含目标词的英文（8-15词），然后向学生提一个具体的、需要思考的问题。",
    "SESSION_COMPLETE": "总结本课（session_end）：点出学到的词、发音或用法的进步和仍需努力的词，给一句鼓励。",
}

TUTOR_SYSTEM_PROMPT = """你是 {student_name} 的英语随身老师（学生：中国初中生，12-15 岁，有小学英语基础）。
你的任务：通过自然的生活情景对话，帮助学生掌握目标词汇。全程中文交流，英文台词自然穿插其中。

当前教学状态：
- 学生: {student_name}
- 目标词条: "{current_word}"（中文释义: {translation}；类型: {item_type}）
- 当前阶段: {phase}
- 本组可用词汇: {allowed_words}（只能使用这些词，禁止引入超纲词）

本轮要做什么（严格执行）：
{phase_behavior}

台词风格（重要）：
1. 中文口语化，像聘请的真人老师，每次回复控制在 2-3 句；拒绝说教和罗列规则。
2. 英文台词完整自然（8-15 词），场景要真实，例如点餐、问路、借书、运动、假期、聚会等。
3. 不要重复上一次用过的情景；开头不要每次都用"好"、"很好"、"接下来"。
4. 鼓励要具体到这次表现（例如指出他连读/回答里的亮点），纠正时给出正确的说法。
5. {item_type} 注意：若是句子/短语（已是完整句子），不要再要求造句，直接在情景中使用它。

输出纪律（最最重要）：
- 只输出一个 JSON 对象。禁止输出任何其它文字、markdown 或思考过程。禁止 <think> 标签。
- 格式: {{"action": "...", "text": "..."}}
  - action 只能取: teach_word, ask_repeat, ask_meaning, ask_choice, ask_sentence, dialogue, feedback, next_word, session_end
  - text = 这一轮说给学生听的完整台词（中文为主体，英文句子穿插其中）。
  - 不要输出 tts_text 字段（系统会自动用 text 配音）。
- ask_choice 追加字段: {{"options": ["A. 选项1", "B. 选项2", "C. 选项3"], "correct_answer": "带A./B./C.前缀的正确选项原文"}}；正确项位置随机；干扰项要有迷惑性（同话题不同义、反义、形近），绝不能出现明显荒谬的选项。
- 讲评学生回答时（feedback），必须追加判定字段：
  - 判断词义回答: {{"meaning_correct": true 或 false}}
  - 判断造句: {{"grammar_correct": true 或 false, "correction": "修正后的句子或 null"}}
  - 微对话回应: 不需要额外字段。
- 语言规则: text 的中文部分必须占主体，英文仅为台词。绝不允许整条 text 全英文。
- 只对本轮内容负责，phase 切换由系统控制，不要在 text 里说"现在进入XX阶段"这种系统口吻。
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

        # 微对话轮数（同一词最多 2 轮学生发言后强制收尾）
        self._dialogue_rounds = {}

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
            # Generic: 通用回答 -> 学生轮，LLM 自然接话；RETRY 等阶段讲评后可推进
            self._request_llm_student(
                extra_context=(
                    f"学生刚才说了: \"{transcribed_text}\"\n"
                    f"请结合当前任务自然接话讲评。"
                ),
                student_text=transcribed_text,
            )

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
        self._request_llm_student(
            extra_context=(
                f"学生的回答: \"{text}\"\n"
                f"正确含义: \"{translation}\"\n"
                f"判定规则：学生只答一个词、短语也算完整回答；核心意思与正确含义一致"
                f"（含同义词、中英文均可）→ meaning_correct=true；只有完全偏离或明显误解才 false。\n"
                f"先用中文给一句具体讲评，然后必须输出 meaning_correct 字段。"
            ),
            student_text=text,
        )

    def _handle_sentence_answer(self, text: str, word_text: str):
        """Student made a sentence. LLM checks grammar."""
        self._request_llm_student(
            extra_context=(
                f"学生造的句子: \"{text}\"\n"
                f"判定规则：学生是初中生，允许小瑕疵——只要句子基本通顺且用上了目标词，"
                f"grammar_correct=true，correction 可以给出更高级的说法；结构混乱/目标词用错才 false。\n"
                f"先用中文给一句具体讲评，然后必须输出 grammar_correct / correction 字段。"
            ),
            student_text=text,
        )

    def _handle_dialogue_answer(self, text: str, word_text: str):
        """Handle micro-dialogue reply."""
        self.word_mastery[word_text]["used_in_dialogue"] = True
        self._request_llm_student(
            extra_context=(
                f"学生回复: \"{text}\"\n"
                f"请用一两句自然回应，肯定发言亮点并推进对话（对话继续 -> 以 dialogue 结尾），"
                f"然后结束本轮微对话。"
            ),
            student_text=text,
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
        """Teacher turn: 引擎主动推进，向 LLM 请求本轮台词。"""
        threading.Thread(
            target=self._llm_call,
            args=(extra_context, None),
            daemon=True
        ).start()

    def _request_llm_student(self, extra_context: str, student_text: str):
        """Student turn: 刚收到学生输入，LLM 讲评后引擎自动推进。"""
        threading.Thread(
            target=self._llm_call,
            args=(extra_context, student_text),
            daemon=True
        ).start()

    # ------------------------------------------------------------------ #

    def _build_system_prompt(self) -> str:
        allowed_words = ", ".join(w["text"] for w in self.vocabulary[:20])
        if len(self.vocabulary) > 20:
            allowed_words += f" ...（共 {len(self.vocabulary)} 个）"
        return TUTOR_SYSTEM_PROMPT.format(
            student_name=self.student_name,
            current_word=self.current_word.get("text", ""),
            translation=self.current_word.get("translation", ""),
            item_type=self._get_item_type(),
            phase=self.phase.name,
            allowed_words=allowed_words,
            phase_behavior=PHASE_BEHAVIOR.get(self.phase.name, "继续当前任务。"),
        )

    def _build_user_turn(self, extra_context: str) -> str:
        base = "[教学提示·内部信息，不要原样复述给学生]"
        if extra_context:
            base += f"\n{extra_context}"
        base += "\n（语言提醒：回复必须以中文为主，英文只能作为示例台词出现。）"
        return base

    def _llm_call(self, extra_context: str = "", student_text: str = None):
        """Background LLM call. Parses structured JSON response.

        student_text 非 None 表示本轮由学生输入触发 -> feedback 后自动推进。
        """
        try:
            config = self._load_config()
            if _is_omni_provider(config):
                self._llm_call_omni(config, extra_context, student_text)
                return
            if self._llm_client is None:
                self._llm_client, self._llm_model = _get_llm_client_and_model(config)

            user_content = self._build_user_turn(extra_context)
            messages = [{"role": "system", "content": self._build_system_prompt()}]
            messages.extend(self._messages[-12:])
            messages.append({"role": "user", "content": user_content})

            # 讲评/出题轮次降温，保证判分与 JSON 纪律；自由台词高温增加多样性
            judging = student_text is not None or self.phase in (
                TutorPhase.WORD_MEANING, TutorPhase.WORD_CHOICE,
            )
            response = self._llm_client.chat.completions.create(
                model=self._llm_model,
                messages=messages,
                temperature=0.35 if judging else 0.7,
                max_tokens=600,
            )

            raw_text = (response.choices[0].message.content or "").strip()
            rc = getattr(response.choices[0].message, "reasoning_content", None)
            if rc:
                print(f"[TutorEngine] LLM reasoning_content ignored ({len(rc)} chars)")
            print(f"[TutorEngine] LLM raw: {raw_text[:200]}")

            action_dict = self._parse_llm_response(raw_text)
            self._finalize_action(action_dict, extra_context, student_text)

        except Exception as e:
            print(f"[TutorEngine] LLM error: {e}")
            self.error_occurred.emit(f"AI 请求失败: {str(e)[:100]}")

    def _llm_call_omni(self, config, extra_context: str = "", student_text: str = None):
        """LLM call via MiniCPM-o Omni client (custom JWT+SSE API)."""
        try:
            from src.core.omni_client import OmniError
            client = _get_omni_client(config)

            user_content = self._build_user_turn(extra_context)

            # Omni 无独立 system role：拼接为纯文本
            history_text = ""
            for msg in self._messages[-12:]:
                history_text += f"{msg.get('role')}: {msg.get('content', '')}\n"

            full_prompt = (
                f"{self._build_system_prompt()}\n\n"
                f"对话历史:\n{history_text}"
                f"user: {user_content}\n"
                f"assistant: "
            )

            def on_audio_merged(url):
                if url and config.get("omni_tts_enabled", True):
                    self.omni_audio_ready.emit(url)

            raw_text = client.chat(text=full_prompt, on_audio_merged=on_audio_merged)
            print(f"[TutorEngine] Omni raw: {raw_text[:200]}")

            action_dict = self._parse_llm_response(raw_text)
            self._finalize_action(action_dict, extra_context, student_text)

        except Exception as e:
            print(f"[TutorEngine] Omni error: {e}")
            self.error_occurred.emit(f"Omni 请求失败: {str(e)[:100]}")

    # ------------------------------------------------------------------ #

    def _finalize_action(self, action_dict: dict, extra_context: str, student_text: str):
        """解析后统一处理：校验 action、保证判定字段、记录干净历史、必要时推进。"""
        # 非结构化散文 + 引擎主动任务轮：按阶段回填任务 action，避免 UI 卡在纯气泡上
        if student_text is None and action_dict.pop("_fallback", None):
            instruct = {
                TutorPhase.WORD_LISTEN: "ask_repeat",
                TutorPhase.WORD_MEANING: "ask_meaning",
                TutorPhase.SENTENCE_MAKING: "ask_sentence",
                TutorPhase.MICRO_DIALOGUE: "dialogue",
                TutorPhase.RETRY_PHASE: "ask_repeat",
            }.get(self.phase)
            if instruct:
                print(f"[TutorEngine] Fallback prose during teacher turn -> remap to '{instruct}'")
                action_dict["action"] = instruct

        action = action_dict.get("action", "feedback")

        # 阶段外 action 强制回落为 feedback，防止越权推进
        expected = PHASE_EXPECTED_ACTIONS.get(self.phase, {"feedback"})
        if action not in expected and action != "feedback":
            print(f"[TutorEngine] Action '{action}' not expected in {self.phase.name}, forcing 'feedback'")
            action_dict["action"] = "feedback"
            action = "feedback"

        # tts_text 统一等于 text（路由按 text 合成 TTS，省掉 LLM 重复输出）
        action_dict["tts_text"] = action_dict.get("text", "")

        # 选择题：确保能定位正确选项
        if action == "ask_choice":
            self._ensure_choice_answer(action_dict)

        # 微对话轮数上限：同一词最多 2 轮学生发言，之后强制收尾
        if student_text is not None and self.phase == TutorPhase.MICRO_DIALOGUE:
            word = self.current_word.get("text", "")
            rounds = self._dialogue_rounds.get(word, 0) + 1
            self._dialogue_rounds[word] = rounds
            if rounds >= 2 and action_dict["action"] == "dialogue":
                action_dict["action"] = "feedback"
                action_dict.setdefault("_wrap_dialogue", True)

        # 写入安静历史：assistant 只存台词，student turn 存学生原话
        assistant_text = action_dict.get("text", "") or "(…)"
        self._messages.append({
            "role": "assistant",
            "content": assistant_text,
        })
        if student_text is not None:
            self._messages.append({"role": "user", "content": f"（学生：{student_text}）"})

        # LLM 漏掉判定字段时本地兜底，避免"说什么都判对"
        if student_text is not None and action_dict["action"] == "feedback":
            self._resolve_judgment(action_dict, student_text)

        self.tutor_action_ready.emit(action_dict)

        # 学生轮 + feedback -> 引擎自动推进阶段
        if (
            student_text is not None
            and action_dict["action"] == "feedback"
            and self.phase in (
                TutorPhase.WORD_MEANING, TutorPhase.SENTENCE_MAKING,
                TutorPhase.MICRO_DIALOGUE, TutorPhase.RETRY_PHASE,
            )
        ):
            self._advance_after_feedback(action_dict)

    def _ensure_choice_answer(self, action_dict: dict):
        """保证 ask_choice 有可判定的 correct_answer（LLM 漏掉时本地推断）。"""
        options = action_dict.get("options") or []
        if not options:
            return
        correct = str(action_dict.get("correct_answer") or "").strip()
        if correct and any(str(o).strip() == correct for o in options):
            try:
                action_dict["correct_index"] = list(options).index(
                    next(o for o in options if str(o).strip() == correct))
            except StopIteration:
                pass
            return

        # 本地推断：清洗 "A. " 前缀后按目标词/释义匹配
        word = self.current_word.get("text", "")
        trans = self.current_word.get("translation", "")
        best = None
        for o in options:
            clean = re.sub(r"^[A-G][.、]\s*", "", str(o)).strip()
            if clean and word and (
                clean.lower() == word.lower()
                or (trans and (clean == trans or clean in trans or trans in clean))
            ):
                best = o
                break
        if best is None:
            best = options[0]
        print(f"[TutorEngine] correct_answer missing, local guess: {best}")
        action_dict["correct_answer"] = best
        try:
            action_dict["correct_index"] = list(options).index(best)
        except ValueError:
            pass

    def _resolve_judgment(self, action_dict: dict, student_text: str):
        """讲评轮次缺判定字段时的本地启发式兜底。"""
        if self.phase == TutorPhase.WORD_MEANING:
            guess = self._guess_meaning(student_text)
            if "meaning_correct" not in action_dict:
                action_dict["meaning_correct"] = guess
                print(f"[TutorEngine] meaning_correct missing, local guess={guess}")
            # LLM 明显失判（学生原话 == 释义关键词）时本地覆写
            elif action_dict["meaning_correct"] is False and guess:
                action_dict["meaning_correct"] = True
                print("[TutorEngine] LLM said False but local overrule -> True (exact match)")
        if self.phase == TutorPhase.SENTENCE_MAKING:
            guess = self._guess_sentence_ok(student_text)
            if "grammar_correct" not in action_dict:
                action_dict["grammar_correct"] = guess
                if guess:
                    action_dict.setdefault("correction", None)
                print(f"[TutorEngine] grammar_correct missing, local guess={guess}")
            elif action_dict["grammar_correct"] is False and guess:
                action_dict["grammar_correct"] = True
                print("[TutorEngine] LLM said False but local overrule -> True (target word ok)")

    def _guess_meaning(self, student_text: str) -> bool:
        """词义判定兜底：学生回答命中释义片段即算对。"""
        trans = self.current_word.get("translation", "")
        t = (student_text or "").strip()
        if not t:
            return False
        lo = t.lower()
        word = self.current_word.get("text", "").lower()
        # 学生直接说出英文目标词（如"What is X?"句式下的回答）也算对
        if word and word in lo:
            return True
        segments = [s.strip() for s in re.split(r"[；;，,、\s（）()]+", trans) if s.strip()]
        for seg in segments:
            if len(seg) >= 2 and seg in t:
                return True
        # 学生上下文包含中文释义任一连续 2 字片段（容错 ASR 误差）
        chars = re.sub(r"[^\u4e00-\u9fff]", "", (segments[0] if segments else trans))
        for i in range(len(chars) - 1):
            if chars[i:i + 2] in t:
                return True
        return False

    def _guess_sentence_ok(self, student_text: str) -> bool:
        """造句判定兜底：使用目标词且长度合格即算通过。"""
        t = (student_text or "").strip()
        target = self.current_word.get("text", "")
        if len(t.split()) < 3:
            return False
        stem = target.split()[0].lower()[:4] if target else ""
        lo = t.lower()
        return bool(stem and stem in lo) or target.lower() in lo

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

        # Last resort: 宽松修复破损 JSON（引号未闭合/字段裸写/前缀复读）
        repaired = self._repair_loose_json(cleaned)
        if repaired:
            print("[TutorEngine] Broken JSON repaired by loose parser")
            return self._sanitize_action(repaired)

        # Fallback: treat entire response as text feedback
        print(f"[TutorEngine] Failed to parse JSON, using fallback. Cleaned: {cleaned[:100]}")
        return {
            "action": "feedback",
            "text": cleaned,
            "tts_text": "",
            "_fallback": True,   # 标记：非结构化散文，finalize 按阶段回填任务语义
        }

    def _repair_loose_json(self, cleaned: str):
        """宽松修复破损的 JSON 输出：只提取 action/text/判定字段，修不了返回 None。"""
        m = re.search(
            r'"action"\s*:\s*"(teach_word|ask_repeat|ask_meaning|ask_choice|ask_sentence|'
            r'dialogue|feedback|next_word|session_end)"', cleaned)
        if not m:
            return None
        d = {"action": m.group(1)}

        # text / tts_text：值可能尾部缺引号，截断到下一个疑似字段边界
        for key in ("text", "tts_text"):
            km = re.search(rf'"{key}"\s*:\s*"(.*)$', cleaned, re.DOTALL)
            if km:
                val = km.group(1)
                cut = re.search(r'(?:",?\s*)?[a-z_]{4,}"?\s*:\s*', val)
                if cut:
                    val = val[:cut.start()]
                d[key] = val.rstrip('"}\\ \n\r\t').strip()
        if not d.get("text"):
            d["text"] = cleaned.strip()[:120]  # 修复不了就用原始文本前段

        for key in ("meaning_correct", "grammar_correct"):
            vm = re.search(rf'"?{key}"?\s*:\s*(true|false)', cleaned, re.IGNORECASE)
            if vm:
                d[key] = vm.group(1).lower() == "true"
        cr = re.search(r'"correction"\s*:\s*(null|"(?:[^"\\]|\\.)*)', cleaned)
        if cr and cr.group(1) != "null":
            g = cr.group(1)
            if g.endswith('"'):
                d["correction"] = g[1:-1]
        om = re.search(r'"?options"?\s*:\s*(\[[^\]]*\])', cleaned, re.DOTALL)
        if om:
            try:
                d["options"] = json.loads(om.group(1))
            except json.JSONDecodeError:
                d["options"] = None
        ca = re.search(r'"correct_answer"\s*:\s*("(?:[^"\\]|\\.)*")', cleaned)
        if ca:
            d["correct_answer"] = ca.group(1)[1:-1]
        if d.get("action") == "ask_choice" and not d.get("options"):
            return None   # 缺选项的选择题修不了，交回 fallback
        return d

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
