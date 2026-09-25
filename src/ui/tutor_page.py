"""
TutorPage - AI English Home Tutor chat UI.

Three views:
  - setup_view: select word group & start
  - chat_view: teaching interaction (bubbles + recording + scores)
  - summary_view: session report
"""
import os
import json
import threading

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QStackedWidget, QScrollArea, QFrame, QSizePolicy,
    QProgressBar, QSpacerItem
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject
from PyQt6.QtMultimedia import QMediaPlayer

from src.core.tutor_engine import TutorEngine, TutorPhase
from src.utils import get_user_data_path
from .styles import (
    AppStyles, FONT_FALLBACK, PAPER, DESK, INK, INK_SOFT,
    MANGO, MANGO_DK, LEAF, CLAY, LEAF_SOFT, CLAY_SOFT,
    DESK_LINE, SP_2, SP_3, SP_4, SP_5, RADIUS, SIZE_BODY, SIZE_UI,
    SIZE_TITLE, SIZE_SECTION, SIZE_HEADER,
)


class _WorkerSignals(QObject):
    """Thread-safe signals for background tasks."""
    asr_done = pyqtSignal(str)            # transcribed text
    gop_done = pyqtSignal(int, str)       # score, feedback


class TutorPage(QWidget):
    """Main page for the AI Home Tutor feature."""

    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self.engine = TutorEngine(
            exercise_manager=main_window.exercise_manager,
            tts_engine=main_window.tts,
        )
        self.tts = main_window.tts

        # Worker signals
        self._signals = _WorkerSignals()
        self._signals.asr_done.connect(self._on_asr_done)
        self._signals.gop_done.connect(self._on_gop_done)

        # Recording state
        self._is_recording = False
        self._current_mode = "gop"   # "gop" or "asr"
        self._correct_option = ""    # for choice questions
        self._tts_playing = False

        # Connect engine signals
        self.engine.tutor_action_ready.connect(self._on_action)
        self.engine.pronunciation_score_ready.connect(self._on_pronunciation_score)
        self.engine.session_state_updated.connect(self._on_state_update)
        self.engine.asr_loading.connect(self._on_asr_loading)
        self.engine.error_occurred.connect(self._on_error)

        self._setup_ui()

    # ================================================================== #
    #  UI Setup                                                            #
    # ================================================================== #

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.view_stack = QStackedWidget()
        layout.addWidget(self.view_stack)

        self._create_setup_view()
        self._create_chat_view()
        self._create_summary_view()

        self.view_stack.setCurrentWidget(self.setup_view)

    def _create_setup_view(self):
        """Setup view: pick word group and start."""
        self.setup_view = QWidget()
        self.setup_view.setStyleSheet(f"background-color: {PAPER};")
        layout = QVBoxLayout(self.setup_view)
        layout.setContentsMargins(SP_5, SP_4, SP_5, SP_4)

        # Top bar
        top_bar = QHBoxLayout()
        btn_back = QPushButton("Back")
        btn_back.setStyleSheet(AppStyles.GHOST_BUTTON)
        btn_back.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_back.clicked.connect(self._go_back)
        top_bar.addWidget(btn_back)
        top_bar.addStretch()
        layout.addLayout(top_bar)

        # Title
        title = QLabel("AI Home Tutor")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(AppStyles.HEADER_LABEL)
        layout.addWidget(title)

        subtitle = QLabel("选择词库开始智能教学")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setStyleSheet(AppStyles.SUBTITLE_LABEL)
        layout.addWidget(subtitle)

        # Group selector
        grp_frame = QFrame()
        grp_frame.setStyleSheet(AppStyles.GROUP_BOX)
        grp_layout = QVBoxLayout(grp_frame)

        grp_layout.addWidget(QLabel("选择词库分组:"))
        self.combo_group = QComboBox()
        self.combo_group.setStyleSheet(AppStyles.INPUT)
        self.combo_group.currentIndexChanged.connect(self._on_group_changed)
        grp_layout.addWidget(self.combo_group)

        self.lbl_word_count = QLabel("共 0 个单词")
        self.lbl_word_count.setStyleSheet(
            f"font-family: {FONT_FALLBACK}; font-size: {SIZE_BODY}px; "
            f"color: {INK_SOFT}; margin-top: {SP_2}px;"
        )
        grp_layout.addWidget(self.lbl_word_count)

        layout.addWidget(grp_frame)
        layout.addSpacing(SP_4)

        # Start button
        self.btn_start = QPushButton("开始学习")
        self.btn_start.setStyleSheet(AppStyles.BIG_BUTTON)
        self.btn_start.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_start.clicked.connect(self._start_session)
        layout.addWidget(self.btn_start)

        layout.addStretch()
        self.view_stack.addWidget(self.setup_view)

    def _create_chat_view(self):
        """Chat view: the main teaching interaction area."""
        self.chat_view = QWidget()
        self.chat_view.setStyleSheet(f"background-color: {PAPER};")
        layout = QVBoxLayout(self.chat_view)
        layout.setContentsMargins(SP_2, SP_2, SP_2, SP_2)
        layout.setSpacing(SP_2)

        # Top bar: back + progress
        top_bar = QHBoxLayout()
        btn_back_chat = QPushButton("Back")
        btn_back_chat.setStyleSheet(AppStyles.GHOST_BUTTON)
        btn_back_chat.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_back_chat.clicked.connect(self._confirm_exit)
        top_bar.addWidget(btn_back_chat)

        self.lbl_progress = QLabel("1/10")
        self.lbl_progress.setStyleSheet(
            f"font-family: {FONT_FALLBACK}; font-size: {SIZE_BODY}px; "
            f"color: {INK}; font-weight: bold;"
        )
        top_bar.addStretch()
        top_bar.addWidget(self.lbl_progress)
        layout.addLayout(top_bar)

        # Word banner
        self.word_banner = QLabel("word")
        self.word_banner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.word_banner.setStyleSheet(
            f"font-family: {FONT_FALLBACK}; font-size: {SIZE_TITLE}px; "
            f"font-weight: bold; color: {INK}; "
            f"background: {DESK}; padding: {SP_3}px; border-radius: {RADIUS}px;"
        )
        layout.addWidget(self.word_banner)

        # Chat area (scrollable)
        self.chat_scroll = QScrollArea()
        self.chat_scroll.setWidgetResizable(True)
        self.chat_scroll.setStyleSheet(
            f"border: none; background-color: {PAPER};"
        )

        self.chat_container = QWidget()
        self.chat_layout = QVBoxLayout(self.chat_container)
        self.chat_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.chat_layout.setSpacing(SP_2)
        self.chat_layout.addStretch()

        self.chat_scroll.setWidget(self.chat_container)
        layout.addWidget(self.chat_scroll, 1)

        # Score panel
        self.score_panel = QLabel("")
        self.score_panel.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.score_panel.setStyleSheet(
            f"font-family: {FONT_FALLBACK}; font-size: {SIZE_BODY}px; "
            f"color: {INK}; background: {DESK}; "
            f"padding: {SP_2}px; border-radius: {RADIUS}px;"
        )
        self.score_panel.setVisible(False)
        layout.addWidget(self.score_panel)

        # Choice panel (hidden by default)
        self.choice_panel = QFrame()
        self.choice_panel.setVisible(False)
        choice_layout = QHBoxLayout(self.choice_panel)
        choice_layout.setSpacing(SP_3)
        self.choice_buttons = []
        for i in range(3):
            btn = QPushButton(f"选项 {i+1}")
            btn.setStyleSheet(
                f"QPushButton {{ font-family: {FONT_FALLBACK}; font-size: {SIZE_UI}px; "
                f"padding: {SP_3}px {SP_4}px; "
                f"border: 2px solid {MANGO}; border-radius: {RADIUS}px; color: {INK}; "
                f"background: {PAPER}; }}"
                f"QPushButton:hover {{ background: {DESK}; }}"
            )
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda checked, idx=i: self._on_choice_clicked(idx))
            choice_layout.addWidget(btn)
            self.choice_buttons.append(btn)
        layout.addWidget(self.choice_panel)

        # Record button
        self.btn_record = QPushButton("按住说话")
        self.btn_record.setStyleSheet(AppStyles.RECORD_BUTTON_IDLE)
        self.btn_record.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_record.setEnabled(False)
        self.btn_record.pressed.connect(self._start_recording)
        self.btn_record.released.connect(self._stop_recording)
        layout.addWidget(self.btn_record)

        self.view_stack.addWidget(self.chat_view)

    def _create_summary_view(self):
        """Summary view after session ends."""
        self.summary_view = QWidget()
        self.summary_view.setStyleSheet(f"background-color: {PAPER};")
        layout = QVBoxLayout(self.summary_view)
        layout.setContentsMargins(SP_5, SP_4, SP_5, SP_4)

        title = QLabel("学习报告")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(AppStyles.SECTION_LABEL)
        layout.addWidget(title)

        # Summary content (scrollable)
        self.summary_scroll = QScrollArea()
        self.summary_scroll.setWidgetResizable(True)
        self.summary_scroll.setStyleSheet(AppStyles.SCROLL_AREA)
        self.summary_content = QWidget()
        self.summary_layout = QVBoxLayout(self.summary_content)
        self.summary_scroll.setWidget(self.summary_content)
        layout.addWidget(self.summary_scroll, 1)

        # Return button
        btn_return = QPushButton("返回首页")
        btn_return.setStyleSheet(AppStyles.BIG_BUTTON)
        btn_return.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_return.clicked.connect(self._go_back)
        layout.addWidget(btn_return)

        self.view_stack.addWidget(self.summary_view)

    # ================================================================== #
    #  Public API                                                          #
    # ================================================================== #

    def reset_to_setup(self):
        """Reset page to setup view (called when navigating here)."""
        self.engine.stop_session()
        self._refresh_groups()
        self.view_stack.setCurrentWidget(self.setup_view)

    # ================================================================== #
    #  Setup View Logic                                                    #
    # ================================================================== #

    def _refresh_groups(self):
        """Reload available word groups from exercise_manager."""
        self.combo_group.blockSignals(True)
        self.combo_group.clear()

        groups = self.main_window.exercise_manager.get_groups()
        for g in groups:
            self.combo_group.addItem(g, g)

        self.combo_group.blockSignals(False)
        self._on_group_changed()

    def _on_group_changed(self):
        """Update word count label when group changes."""
        group = self.combo_group.currentData()
        if not group:
            self.lbl_word_count.setText("共 0 个单词")
            self.btn_start.setEnabled(False)
            return

        words = self._get_words_for_group(group)
        count = len(words)
        self.lbl_word_count.setText(f"共 {count} 个单词")
        self.btn_start.setEnabled(count > 0)

    def _get_words_for_group(self, group: str) -> list:
        """Get word list for a group."""
        em = self.main_window.exercise_manager
        all_words = em.exercises.get("words", [])
        all_sentences = em.exercises.get("sentences", [])
        # Combine words and short phrases from this group
        items = []
        for w in all_words:
            if w.get("group", "Default") == group:
                items.append({
                    "text": w.get("text", ""),
                    "translation": w.get("translation", ""),
                })
        # Also include short sentences as "vocabulary"
        for s in all_sentences:
            if s.get("group", "Default") == group:
                text = s.get("text", "")
                # Only include short ones (<=4 words) as vocab items
                if len(text.split()) <= 4:
                    items.append({
                        "text": text,
                        "translation": s.get("translation", ""),
                    })
        return items

    def _start_session(self):
        """Start the tutoring session."""
        group = self.combo_group.currentData()
        if not group:
            return
        words = self._get_words_for_group(group)
        if not words:
            return

        # Clear chat
        self._clear_chat()
        self.score_panel.setVisible(False)
        self.choice_panel.setVisible(False)

        # Switch to chat view
        self.view_stack.setCurrentWidget(self.chat_view)

        # Start engine
        self.engine.start_session(topic=group, vocabulary=words)

    # ================================================================== #
    #  Chat View Logic                                                     #
    # ================================================================== #

    def _add_bubble(self, role: str, text: str):
        """Add a chat bubble. role: 'ai' or 'user'."""
        bubble = QFrame()
        bubble_layout = QVBoxLayout(bubble)
        bubble_layout.setContentsMargins(SP_3, SP_2, SP_3, SP_2)

        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        if role == "ai":
            bubble.setStyleSheet(
                f"QFrame {{ background: {DESK}; border-radius: {RADIUS}px; "
                f"margin-right: 60px; }}"
            )
            lbl.setStyleSheet(
                f"font-family: {FONT_FALLBACK}; font-size: {SIZE_BODY}px; color: {INK};"
            )
        else:
            bubble.setStyleSheet(
                f"QFrame {{ background: #FBFAF5; border-radius: {RADIUS}px; "
                f"margin-left: 60px; }}"
            )
            lbl.setStyleSheet(
                f"font-family: {FONT_FALLBACK}; font-size: {SIZE_BODY}px; color: {INK};"
            )

        bubble_layout.addWidget(lbl)

        # Insert before the stretch
        count = self.chat_layout.count()
        self.chat_layout.insertWidget(count - 1, bubble)

        # Scroll to bottom
        QTimer.singleShot(50, self._scroll_to_bottom)

    def _scroll_to_bottom(self):
        vbar = self.chat_scroll.verticalScrollBar()
        vbar.setValue(vbar.maximum())

    def _clear_chat(self):
        """Remove all chat bubbles."""
        while self.chat_layout.count() > 1:
            item = self.chat_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _show_choice_panel(self, options: list):
        """Show choice buttons with the given options."""
        for i, btn in enumerate(self.choice_buttons):
            if i < len(options):
                btn.setText(options[i])
                btn.setVisible(True)
                btn.setStyleSheet(
                    f"QPushButton {{ font-family: {FONT_FALLBACK}; font-size: {SIZE_UI}px; "
                    f"padding: {SP_3}px {SP_4}px; "
                    f"border: 2px solid {MANGO}; border-radius: {RADIUS}px; color: {INK}; "
                    f"background: {PAPER}; }}"
                    f"QPushButton:hover {{ background: {DESK}; }}"
                )
                btn.setEnabled(True)
            else:
                btn.setVisible(False)
        self.choice_panel.setVisible(True)
        self.btn_record.setEnabled(False)

    def _hide_choice_panel(self):
        self.choice_panel.setVisible(False)

    def _on_choice_clicked(self, idx: int):
        """Handle choice button click."""
        chosen = self.choice_buttons[idx].text()
        # Visual feedback
        if chosen.strip().lower() == self._correct_option.strip().lower():
            self.choice_buttons[idx].setStyleSheet(
                f"QPushButton {{ font-family: {FONT_FALLBACK}; font-size: {SIZE_UI}px; "
                f"padding: {SP_3}px {SP_4}px; "
                f"border: 2px solid {LEAF}; border-radius: {RADIUS}px; color: {PAPER}; "
                f"background: {LEAF}; }}"
            )
        else:
            self.choice_buttons[idx].setStyleSheet(
                f"QPushButton {{ font-family: {FONT_FALLBACK}; font-size: {SIZE_UI}px; "
                f"padding: {SP_3}px {SP_4}px; "
                f"border: 2px solid {CLAY}; border-radius: {RADIUS}px; color: {PAPER}; "
                f"background: {CLAY}; }}"
            )
        # Disable all
        for btn in self.choice_buttons:
            btn.setEnabled(False)

        self._add_bubble("user", f"选择: {chosen}")

        # Hide after a moment and send to engine
        QTimer.singleShot(800, self._hide_choice_panel)
        self.engine.handle_choice_answer(chosen, self._correct_option)

    # ================================================================== #
    #  Recording                                                           #
    # ================================================================== #

    def _start_recording(self):
        """Start audio recording."""
        if self._tts_playing or self._is_recording:
            return
        self._is_recording = True
        self.btn_record.setText("录音中...")
        self.btn_record.setStyleSheet(AppStyles.RECORD_BUTTON_ACTIVE)
        # Use main_window's audio recorder
        try:
            self.main_window.audio_recorder.start_recording()
        except Exception as e:
            print(f"[TutorPage] Recording start error: {e}")
            self._is_recording = False

    def _stop_recording(self):
        """Stop recording and process."""
        if not self._is_recording:
            return
        self._is_recording = False
        self.btn_record.setText("处理中...")
        self.btn_record.setEnabled(False)
        self.btn_record.setStyleSheet(AppStyles.RECORD_BUTTON_IDLE)

        try:
            audio_path = self.main_window.audio_recorder.stop_recording()
        except Exception as e:
            print(f"[TutorPage] Recording stop error: {e}")
            self._reset_record_btn()
            return

        if not audio_path or not os.path.exists(audio_path):
            self._reset_record_btn()
            return

        # Process based on current mode
        if self._current_mode == "gop":
            self._process_gop(audio_path)
        else:
            self._process_asr(audio_path)

    def _process_gop(self, audio_path: str):
        """Run GOP scoring in background."""
        reference_text = self.engine.current_word["text"] if self.engine.current_word else ""

        def _worker():
            try:
                result = self.main_window.ai_coach.assess(audio_path, reference_text)
                score = result.get("accuracy_score", 0) if result else 0
                feedback = result.get("feedback", "") if result else ""
                self._signals.gop_done.emit(int(score), feedback)
            except Exception as e:
                print(f"[TutorPage] GOP error: {e}")
                self._signals.gop_done.emit(0, str(e))

        threading.Thread(target=_worker, daemon=True).start()

    def _process_asr(self, audio_path: str):
        """Run ASR transcription in background."""
        def _worker():
            text = self.engine.transcribe_audio(audio_path)
            self._signals.asr_done.emit(text)

        threading.Thread(target=_worker, daemon=True).start()

    def _on_gop_done(self, score: int, feedback: str):
        """Handle GOP result on main thread."""
        self._add_bubble("user", f"发音得分: {score}")
        self._update_score_panel(score)
        # Keep record button DISABLED until next LLM action arrives
        self.btn_record.setText("等待AI回复...")
        self.btn_record.setEnabled(False)
        self.engine.handle_pronunciation_result(score, feedback)

    def _on_asr_done(self, text: str):
        """Handle ASR result on main thread."""
        if text:
            self._add_bubble("user", text)
        else:
            self._add_bubble("user", "(未识别到内容)")
        # Keep record button DISABLED until next LLM action arrives
        self.btn_record.setText("等待AI回复...")
        self.btn_record.setEnabled(False)
        self.engine.handle_asr_result(text)

    def _reset_record_btn(self):
        """Reset record button to ready state."""
        self.btn_record.setText("按住说话")
        self.btn_record.setEnabled(True)
        self.btn_record.setStyleSheet(AppStyles.RECORD_BUTTON_IDLE)

    def _update_score_panel(self, score: int):
        """Show pronunciation score."""
        stars = "⭐" * min(5, score // 20)
        self.score_panel.setText(f"发音: {score} {stars}")
        self.score_panel.setVisible(True)

    # ================================================================== #
    #  Engine Signal Handlers                                              #
    # ================================================================== #

    def _on_action(self, action_dict: dict):
        """Handle structured action from TutorEngine/LLM."""
        action = action_dict.get("action", "feedback")
        text = action_dict.get("text", "")
        tts_text = action_dict.get("tts_text", "") or text  # Fallback to full text for TTS

        # Display AI bubble
        if text:
            self._add_bubble("ai", text)

        # Handle action types
        if action == "teach_word":
            # Update word banner
            self._update_word_banner()
            self._play_tts_then_unlock(tts_text, mode="gop")

        elif action == "ask_repeat":
            self._current_mode = "gop"
            self._play_tts_then_unlock(tts_text, mode="gop")

        elif action == "ask_meaning":
            self._current_mode = "asr"
            self._play_tts_then_unlock(tts_text, mode="asr")

        elif action == "ask_choice":
            options = action_dict.get("options", [])
            if options:
                # Determine correct option (usually the target word/meaning)
                word_text = self.engine.current_word["text"] if self.engine.current_word else ""
                translation = self.engine.current_word.get("translation", "") if self.engine.current_word else ""
                # Find the correct option: match word or translation
                self._correct_option = ""
                for opt in options:
                    opt_clean = opt.lstrip("ABCDEFG. 、").strip()
                    if (opt_clean.lower() == word_text.lower()
                            or opt_clean == translation
                            or translation in opt_clean
                            or opt_clean in translation):
                        self._correct_option = opt
                        break
                if not self._correct_option and options:
                    # Fallback: first option is usually correct (LLM convention)
                    self._correct_option = options[0]
                self._show_choice_panel(options)
            # Disable record button during choice
            self.btn_record.setEnabled(False)
            if tts_text:
                self._play_tts(tts_text)

        elif action == "ask_sentence":
            self._current_mode = "asr"
            self._play_tts_then_unlock(tts_text, mode="asr")

        elif action == "dialogue":
            self._current_mode = "asr"
            self._play_tts_then_unlock(tts_text, mode="asr")

        elif action == "feedback":
            if tts_text:
                self._play_tts(tts_text)
            # Don't unlock recording — engine will advance phase and send next action

        elif action == "session_end":
            self.btn_record.setEnabled(False)
            if tts_text:
                self._play_tts(tts_text)
            QTimer.singleShot(2000, self._show_summary)

        elif action == "next_word":
            pass  # Engine handles state update via session_state_updated

    def _on_pronunciation_score(self, score: int, feedback: str):
        """Additional score display from engine."""
        self._update_score_panel(score)

    def _on_state_update(self, state: dict):
        """Update UI based on engine state."""
        # Update progress
        idx = state.get("word_index", 0) + 1
        total = state.get("total_words", 1)
        self.lbl_progress.setText(f"{state.get('topic', '')} ({idx}/{total})")

        # Update word banner
        self._update_word_banner_from_state(state)

    def _on_asr_loading(self, loading: bool):
        """Show/hide ASR loading indicator."""
        if loading:
            self._add_bubble("ai", "正在加载语音识别模型...")

    def _on_error(self, msg: str):
        """Show error in chat."""
        self._add_bubble("ai", f"Error: {msg}")
        self._reset_record_btn()

    # ================================================================== #
    #  TTS + Record Lock                                                   #
    # ================================================================== #

    def _play_tts_then_unlock(self, tts_text: str, mode: str = "gop"):
        """Play TTS, then unlock recording button."""
        self._current_mode = mode
        self.btn_record.setEnabled(False)
        self._tts_playing = True

        if tts_text and self.tts:
            # Connect to playback state change
            try:
                self.tts.player.playbackStateChanged.disconnect(self._on_tts_state_changed)
            except (TypeError, RuntimeError):
                pass
            self.tts.player.playbackStateChanged.connect(self._on_tts_state_changed)
            self.tts.speak(tts_text)
        else:
            # No TTS, just unlock after brief delay
            QTimer.singleShot(500, self._unlock_recording)

    def _play_tts(self, tts_text: str):
        """Play TTS without unlocking recording."""
        if tts_text and self.tts:
            self.tts.speak(tts_text)

    def _on_tts_state_changed(self, state):
        """When TTS finishes playing, unlock recording."""
        if state == QMediaPlayer.PlaybackState.StoppedState:
            QTimer.singleShot(300, self._unlock_recording)

    def _unlock_recording(self):
        """Enable recording button."""
        self._tts_playing = False
        self.btn_record.setEnabled(True)

    # ================================================================== #
    #  Summary View                                                        #
    # ================================================================== #

    def _show_summary(self):
        """Display session summary."""
        summary = self.engine.get_session_summary()

        # Clear old summary
        while self.summary_layout.count():
            item = self.summary_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # Stats card
        total = summary["total_words"]
        mastered = summary["mastered"]
        weak = summary["weak_words"]

        stats_frame = QFrame()
        stats_frame.setStyleSheet(
            f"background: {DESK}; border: 1px solid {DESK_LINE}; "
            f"border-radius: {RADIUS}px; padding: {SP_4}px;"
        )
        stats_layout = QVBoxLayout(stats_frame)

        lbl_overview = QLabel(f"主题: {summary['topic']}")
        lbl_overview.setStyleSheet(
            f"font-family: {FONT_FALLBACK}; font-size: {SIZE_UI}px; "
            f"font-weight: bold; color: {INK};"
        )
        stats_layout.addWidget(lbl_overview)

        lbl_stats = QLabel(f"掌握: {mastered}/{total}    薄弱: {len(weak)}")
        lbl_stats.setStyleSheet(
            f"font-family: {FONT_FALLBACK}; font-size: {SIZE_UI}px; "
            f"color: {INK}; margin-top: {SP_2}px;"
        )
        stats_layout.addWidget(lbl_stats)

        # Progress bar
        pbar = QProgressBar()
        pbar.setRange(0, max(1, total))
        pbar.setValue(mastered)
        pbar.setStyleSheet(AppStyles.PROGRESS_BAR)
        stats_layout.addWidget(pbar)

        self.summary_layout.addWidget(stats_frame)

        # Word-by-word mastery
        mastery_data = summary.get("word_mastery", {})
        for word_text, m in mastery_data.items():
            card = QFrame()
            card.setStyleSheet(
                f"background: #FBFAF5; border: 1px solid {DESK_LINE}; "
                f"border-radius: {RADIUS}px; padding: {SP_2}px; margin: 2px;"
            )
            card_layout = QHBoxLayout(card)

            lbl_word = QLabel(f"<b>{word_text}</b>")
            lbl_word.setStyleSheet(
                f"font-family: {FONT_FALLBACK}; font-size: {SIZE_BODY}px; min-width: 80px;"
            )
            card_layout.addWidget(lbl_word)

            pron = m.get("pronunciation", 0)
            mean = m.get("meaning", 0)
            gram = m.get("grammar", 0)

            lbl_scores = QLabel(f"发音:{pron}  含义:{mean}  语法:{gram}")
            lbl_scores.setStyleSheet(
                f"font-family: {FONT_FALLBACK}; font-size: {SIZE_BODY - 1}px; color: {INK_SOFT};"
            )
            card_layout.addWidget(lbl_scores)
            card_layout.addStretch()

            avg = (pron + mean + gram) / 3
            lbl_avg = QLabel(f"{'✅' if avg >= 60 else '❌'} {int(avg)}")
            lbl_avg.setStyleSheet(
                f"font-family: {FONT_FALLBACK}; font-size: {SIZE_BODY}px; "
                f"color: {LEAF if avg >= 60 else CLAY};"
            )
            card_layout.addWidget(lbl_avg)

            self.summary_layout.addWidget(card)

        self.summary_layout.addStretch()
        self.view_stack.setCurrentWidget(self.summary_view)

    # ================================================================== #
    #  Helpers                                                             #
    # ================================================================== #

    def _update_word_banner(self):
        """Update word banner from engine's current word."""
        if self.engine.current_word:
            word = self.engine.current_word["text"]
            trans = self.engine.current_word.get("translation", "")
            self.word_banner.setText(f"{word}    {trans}")

    def _update_word_banner_from_state(self, state: dict):
        word = state.get("word", "")
        trans = state.get("translation", "")
        if word:
            self.word_banner.setText(f"{word}    {trans}")

    def _confirm_exit(self):
        """Confirm before exiting mid-session."""
        from PyQt6.QtWidgets import QMessageBox
        reply = QMessageBox.question(
            self, "确认退出",
            "学习还未结束，确定要退出吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.engine.stop_session()
            self._go_back()

    def _go_back(self):
        """Navigate back to oral hub."""
        self.main_window.stack.setCurrentWidget(self.main_window.page_oral_hub)
