"""
ScenarioChatPage - 情景会话练习页面

三视图（QStackedWidget）：
  setup_view   选择脚本 + 开始
  chat_view    A/B 双人对话气泡 + 异步评分
  summary_view LLM 反馈 + 错误发音表格

关键设计：
- A 角：TTS 自动播放 → 监听 player.playbackStateChanged 推进
- B 角：用户录音 → 立即推进下一轮，评分丢线程池异步进行
- 评分通过 pyqtSignal 转回主线程刷新对应气泡
- 错题并入主 words.json（last_score / times_practiced）
"""
from concurrent.futures import ThreadPoolExecutor
import json
import os

from PyQt6.QtCore import Qt, pyqtSignal, QObject, QTimer
from PyQt6.QtGui import QPixmap
from PyQt6.QtMultimedia import QMediaPlayer
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QStackedWidget,
    QComboBox, QGroupBox, QScrollArea, QFrame, QMessageBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QSizePolicy,
    QListWidget, QListWidgetItem, QSpinBox, QProgressBar,
)

from src.ui.recording_widget import RecordingWidget
from src.ui.styles import (
    AppStyles, FONT_FALLBACK, PAPER, DESK, INK, INK_SOFT, MANGO, MANGO_DK,
    LEAF, CLAY, LEAF_SOFT, CLAY_SOFT, DESK_LINE, SP_1, SP_2, SP_3, SP_4, SP_5,
    RADIUS, RADIUS_SM, SIZE_BODY, SIZE_UI, SIZE_TITLE, SIZE_SECTION, SIZE_HEADER,
)
from src.utils import get_user_data_path

# 白色粗勾 SVG 的绝对路径，用于 QListWidget indicator 的 checked 状态
_CHECK_ICON_PATH = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "resources", "images", "check_white.svg")
).replace("\\", "/")


class _ScoreSignal(QObject):
    """Helper to marshal worker-thread results back to the main thread."""
    score_returned = pyqtSignal(int, int, dict)   # turn_idx, score, full_assess_result
    score_error = pyqtSignal(int, str)            # turn_idx, error message


class ScenarioChatPage(QWidget):
    """Scenario dialogue practice page with async GOP scoring."""

    USER_ROLE = "B"  # 用户固定演 B 角

    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self.scenario_engine = main_window.scenario_engine
        self.tts = main_window.tts
        self.audio_recorder = main_window.audio_recorder
        self.ai_coach = main_window.ai_coach

        # Async infra
        self.executor = ThreadPoolExecutor(max_workers=2)
        self.signals = _ScoreSignal()
        self.signals.score_returned.connect(self._on_score_returned)
        self.signals.score_error.connect(self._on_score_error)

        # Engine signals
        self.scenario_engine.summary_ready.connect(self._on_summary_ready)
        self.scenario_engine.summary_error.connect(self._on_summary_error)

        # Session state
        self.current_bank = None
        self.script = []
        self.current_turn_idx = -1
        self.session_active = False
        self.bubble_frames = []      # list[QFrame] per turn
        self.bubble_status = []      # list[QLabel] per turn (the ⏳/✓ tag)
        self.session_results = []    # list of dict per scored turn
        self.pending_count = 0       # outstanding async scoring tasks
        self.oneshot_in_flight = False   # 一次性生成是否正在进行

        self._setup_ui()
        # Listen for TTS finish -> advance A turn
        self.tts.player.playbackStateChanged.connect(self._on_player_state_changed)

    # ====================================================================== #
    #   UI SETUP                                                              #
    # ====================================================================== #
    def _setup_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        self.stack = QStackedWidget()
        outer.addWidget(self.stack)

        self.setup_view = self._create_setup_view()
        self.chat_view = self._create_chat_view()
        self.summary_view = self._create_summary_view()

        self.stack.addWidget(self.setup_view)
        self.stack.addWidget(self.chat_view)
        self.stack.addWidget(self.summary_view)

    # ---------------------------------------------------------------- setup -
    def _create_setup_view(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 20, 20, 20)

        # Top bar
        top = QHBoxLayout()
        btn_back = QPushButton("Back")
        btn_back.setStyleSheet(AppStyles.GHOST_BUTTON)
        btn_back.clicked.connect(self._go_hub)
        top.addWidget(btn_back)
        top.addStretch()
        layout.addLayout(top)

        title = QLabel("情景会话")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(AppStyles.HEADER_LABEL)
        layout.addWidget(title)

        subtitle = QLabel("AI 演 A 角、你演 B 角。完成后获得发音诊断。")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setStyleSheet(AppStyles.SUBTITLE_LABEL)
        layout.addWidget(subtitle)

        layout.addSpacing(12)

        # ========== 随机会话（一次性，不入题库）==========
        rnd_group = QGroupBox("随机会话（不保存到题库，一次性练习）")
        rnd_group.setStyleSheet(AppStyles.GROUP_BOX)
        rnd_layout = QVBoxLayout(rnd_group)

        lbl_select = QLabel("选择词库（可多选）：")
        lbl_select.setStyleSheet(
            f"font-family: {FONT_FALLBACK}; font-size: {SIZE_UI}px; color: {INK};"
        )
        rnd_layout.addWidget(lbl_select)
        self.list_groups_oneshot = QListWidget()
        self.list_groups_oneshot.setMaximumHeight(120)
        # 高对比度复选框 indicator：未选白底灰框、选中芒果底白色粗勾，
        # 18×18 尺寸保证在浅色主题下也能清楚辨认。
        self.list_groups_oneshot.setStyleSheet(
            AppStyles.LIST_WIDGET +
            f"""
            QListWidget::indicator {{
                width: 18px; height: 18px;
                border: 2px solid {DESK_LINE};
                border-radius: 3px;
                background: #FBFAF5;
                margin-right: 6px;
            }}
            QListWidget::indicator:checked {{
                background: {MANGO};
                border: 2px solid {MANGO_DK};
                image: url({_CHECK_ICON_PATH});
            }}
            QListWidget::indicator:hover {{
                border-color: {MANGO};
            }}"""
        )
        rnd_layout.addWidget(self.list_groups_oneshot)

        rnd_row = QHBoxLayout()
        lbl_turns = QLabel("对话轮数：")
        lbl_turns.setStyleSheet(
            f"font-family: {FONT_FALLBACK}; font-size: {SIZE_UI}px; color: {INK};"
        )
        rnd_row.addWidget(lbl_turns)
        self.spin_oneshot_turns = QSpinBox()
        self.spin_oneshot_turns.setRange(8, 60)
        self.spin_oneshot_turns.setStyleSheet(
            f"""QSpinBox {{
                background-color: #FBFAF5;
                color: {INK};
                border: 1px solid {DESK_LINE};
                border-radius: {RADIUS_SM}px;
                padding: {SP_2}px {SP_3}px;
                font-family: {FONT_FALLBACK};
                font-size: {SIZE_UI}px;
            }}
            QSpinBox:focus {{
                border-color: {MANGO};
            }}"""
        )
        # 从 config.json 记忆上次轮数（全局生效）
        try:
            cfg_path = self._config_path()
            if cfg_path and os.path.exists(cfg_path):
                with open(cfg_path, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                self.spin_oneshot_turns.setValue(int(cfg.get("scenario_turn_count", 12)))
            else:
                self.spin_oneshot_turns.setValue(12)
        except Exception:
            self.spin_oneshot_turns.setValue(12)
        self.spin_oneshot_turns.valueChanged.connect(self._persist_turn_count)
        self.spin_oneshot_turns.setToolTip("情景对话总轮数（8–60，自动记忆上次设置）")
        rnd_row.addWidget(self.spin_oneshot_turns)
        lbl_turns_unit = QLabel("轮")
        lbl_turns_unit.setStyleSheet(
            f"font-family: {FONT_FALLBACK}; font-size: {SIZE_UI}px; color: {INK};"
        )
        rnd_row.addWidget(lbl_turns_unit)
        rnd_row.addStretch()

        self.btn_oneshot = QPushButton("立即生成随机会话")
        self.btn_oneshot.setStyleSheet(AppStyles.BIG_BUTTON)
        self.btn_oneshot.clicked.connect(self._start_oneshot_generation)
        rnd_row.addWidget(self.btn_oneshot)
        rnd_layout.addLayout(rnd_row)

        self.oneshot_progress = QProgressBar()
        self.oneshot_progress.setVisible(False)
        self.oneshot_progress.setRange(0, 0)  # indeterminate
        self.oneshot_progress.setStyleSheet(AppStyles.PROGRESS_BAR)
        rnd_layout.addWidget(self.oneshot_progress)

        self.lbl_oneshot_status = QLabel("")
        self.lbl_oneshot_status.setStyleSheet(
            f"font-family: {FONT_FALLBACK}; font-size: {SIZE_BODY}px; color: {MANGO_DK};"
        )
        self.lbl_oneshot_status.setVisible(False)
        rnd_layout.addWidget(self.lbl_oneshot_status)

        layout.addWidget(rnd_group)

        layout.addSpacing(8)

        # ========== 使用已保存的题库 ==========
        bank_group = QGroupBox("使用已保存的题库")
        bank_group.setStyleSheet(AppStyles.GROUP_BOX)
        bank_layout = QVBoxLayout(bank_group)

        self.combo_bank = QComboBox()
        self.combo_bank.setStyleSheet(AppStyles.INPUT + f" min-width: 320px;")
        self.combo_bank.currentIndexChanged.connect(self._on_bank_selected)
        bank_layout.addWidget(self.combo_bank)

        self.lbl_bank_info = QLabel("")
        self.lbl_bank_info.setWordWrap(True)
        self.lbl_bank_info.setStyleSheet(
            f"font-family: {FONT_FALLBACK}; font-size: {SIZE_BODY}px; color: {INK_SOFT}; "
            f"padding: {SP_2}px; background: {DESK}; border-radius: {RADIUS_SM}px;"
        )
        self.lbl_bank_info.setVisible(False)
        bank_layout.addWidget(self.lbl_bank_info)

        self.lbl_empty_hint = QLabel("暂无情景会话脚本，请到 设置 → 题库 中先生成。")
        self.lbl_empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_empty_hint.setStyleSheet(
            f"font-family: {FONT_FALLBACK}; font-size: {SIZE_UI}px; color: {CLAY}; padding: {SP_3}px;"
        )
        self.lbl_empty_hint.setVisible(False)
        bank_layout.addWidget(self.lbl_empty_hint)

        layout.addWidget(bank_group)

        layout.addStretch()

        self.btn_start = QPushButton("开始会话")
        self.btn_start.setStyleSheet(AppStyles.BIG_BUTTON)
        self.btn_start.setEnabled(False)
        self.btn_start.clicked.connect(self._start_session)
        layout.addWidget(self.btn_start)

        return page

    # ---------------------------------------------------------------- chat -
    def _create_chat_view(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)

        # Top bar
        top = QHBoxLayout()
        self.btn_quit_chat = QPushButton("结束会话")
        self.btn_quit_chat.setStyleSheet(AppStyles.GHOST_BUTTON)
        self.btn_quit_chat.clicked.connect(self._quit_chat_early)
        top.addWidget(self.btn_quit_chat)
        top.addStretch()

        self.lbl_chat_progress = QLabel("第 0 / 0 轮")
        self.lbl_chat_progress.setStyleSheet(
            f"font-family: {FONT_FALLBACK}; font-size: {SIZE_BODY}px; color: {INK}; font-weight: bold;"
        )
        top.addWidget(self.lbl_chat_progress)
        layout.addLayout(top)

        # Scroll area for bubbles
        self.chat_scroll = QScrollArea()
        self.chat_scroll.setWidgetResizable(True)
        self.chat_scroll.setStyleSheet(AppStyles.SCROLL_AREA)
        self.chat_container = QWidget()
        self.chat_container.setStyleSheet(f"background-color: {PAPER};")
        self.chat_layout = QVBoxLayout(self.chat_container)
        self.chat_layout.setSpacing(10)
        self.chat_layout.setContentsMargins(12, 12, 12, 12)
        self.chat_layout.addStretch()
        self.chat_scroll.setWidget(self.chat_container)
        layout.addWidget(self.chat_scroll, 1)

        # Recorder (shared audio_recorder instance) — compact mode for chat
        self.recorder_widget = RecordingWidget(self.audio_recorder)
        # Compact: hide the bulky listening-icon placeholder so "该你说了" sits
        # right above the mic button.
        try:
            self.recorder_widget.icon_label.setVisible(False)
            self.recorder_widget.icon_label.setFixedHeight(0)
            # Tighten outer layout margins of recorder
            rl = self.recorder_widget.layout()
            if rl is not None:
                rl.setContentsMargins(0, 0, 0, 0)
                rl.setSpacing(6)
            # Slimmer status label
            self.recorder_widget.status_label.setStyleSheet(
                f"font-family: {FONT_FALLBACK}; font-size: {SIZE_UI}px; color: {INK_SOFT}; padding: 0;"
            )
        except Exception:
            pass
        self.recorder_widget.recording_finished.connect(self._on_user_recording)
        layout.addWidget(self.recorder_widget)

        # "Enter summary" button (hidden until last turn done)
        self.btn_to_summary = QPushButton("进入总结")
        self.btn_to_summary.setStyleSheet(AppStyles.BIG_BUTTON)
        self.btn_to_summary.setVisible(False)
        self.btn_to_summary.clicked.connect(self._enter_summary)
        layout.addWidget(self.btn_to_summary)

        return page

    # ------------------------------------------------------------- summary -
    def _create_summary_view(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 20, 20, 20)

        self.lbl_summary_score = QLabel("完成！")
        self.lbl_summary_score.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_summary_score.setStyleSheet(
            f"font-family: {FONT_FALLBACK}; font-size: {SIZE_SECTION}px; font-weight: bold; "
            f"color: {LEAF}; padding: {SP_3}px;"
        )
        layout.addWidget(self.lbl_summary_score)

        self.lbl_summary_encourage = QLabel("")
        self.lbl_summary_encourage.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_summary_encourage.setStyleSheet(
            f"font-family: {FONT_FALLBACK}; font-size: {SIZE_UI}px; color: {INK_SOFT};"
        )
        self.lbl_summary_encourage.setWordWrap(True)
        layout.addWidget(self.lbl_summary_encourage)

        # LLM feedback box
        feedback_box = QGroupBox("AI 教练反馈")
        feedback_box.setStyleSheet(AppStyles.GROUP_BOX)
        fb_layout = QVBoxLayout(feedback_box)
        self.lbl_feedback = QLabel("AI 正在分析你的发音...")
        self.lbl_feedback.setWordWrap(True)
        self.lbl_feedback.setStyleSheet(
            f"font-family: {FONT_FALLBACK}; font-size: {SIZE_UI}px; color: {INK}; "
            f"padding: {SP_2}px; background: {DESK}; border-radius: {RADIUS_SM}px;"
        )
        self.lbl_feedback.setMinimumHeight(80)
        fb_layout.addWidget(self.lbl_feedback)
        layout.addWidget(feedback_box)

        # Error table
        err_box = QGroupBox("需要加强的发音")
        err_box.setStyleSheet(AppStyles.GROUP_BOX)
        err_layout = QVBoxLayout(err_box)
        self.error_table = QTableWidget()
        self.error_table.setStyleSheet(AppStyles.TABLE)
        self.error_table.setColumnCount(4)
        self.error_table.setHorizontalHeaderLabels(["内容", "分数", "出错音素", "标准发音"])
        self.error_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.error_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.error_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.error_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.error_table.setMinimumHeight(180)
        err_layout.addWidget(self.error_table)
        self.lbl_no_errors = QLabel("全部很棒，没有低分项！")
        self.lbl_no_errors.setStyleSheet(
            f"font-family: {FONT_FALLBACK}; color: {LEAF}; font-size: {SIZE_BODY}px; padding: {SP_1}px;"
        )
        self.lbl_no_errors.setVisible(False)
        err_layout.addWidget(self.lbl_no_errors)
        layout.addWidget(err_box, 1)

        # Buttons
        btn_row = QHBoxLayout()
        btn_again = QPushButton("再来一次")
        btn_again.setStyleSheet(AppStyles.BIG_BUTTON)
        btn_again.clicked.connect(self.reset_to_setup)
        btn_row.addWidget(btn_again)

        btn_home = QPushButton("回到首页")
        btn_home.setStyleSheet(AppStyles.CARD_BUTTON)
        btn_home.clicked.connect(self._go_home)
        btn_row.addWidget(btn_home)
        layout.addLayout(btn_row)

        return page

    # ====================================================================== #
    #   PUBLIC ENTRY                                                          #
    # ====================================================================== #
    def reset_to_setup(self):
        """Public: go back to setup_view, refresh bank list."""
        self._reset_oneshot_ui()
        self._refresh_bank_list()
        self._refresh_group_list_oneshot()
        self.stack.setCurrentWidget(self.setup_view)

    # ====================================================================== #
    #   SETUP VIEW LOGIC                                                      #
    # ====================================================================== #
    def showEvent(self, event):
        """Refresh banks + group list each time the page is shown."""
        super().showEvent(event)
        self._refresh_bank_list()
        self._refresh_group_list_oneshot()

    def _refresh_group_list_oneshot(self):
        """Reload available word groups into the oneshot multi-select list."""
        self.list_groups_oneshot.blockSignals(True)
        self.list_groups_oneshot.clear()
        em = self.main_window.exercise_manager
        groups = em.get_groups() if hasattr(em, "get_groups") else []
        if not groups:
            # fallback: scan exercises for group names
            seen = set()
            for cat in ("words", "sentences"):
                for item in em.exercises.get(cat, []):
                    g = item.get("group")
                    if g:
                        seen.add(g)
            groups = sorted(seen)
        word_counts = em.get_group_word_counts() if hasattr(em, "get_group_word_counts") else {}
        for g in groups:
            cnt = word_counts.get(g, 0)
            item = QListWidgetItem(f"{g} ({cnt} 条)")
            item.setData(Qt.ItemDataRole.UserRole, g)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            self.list_groups_oneshot.addItem(item)
        self.list_groups_oneshot.blockSignals(False)

    def _start_oneshot_generation(self):
        """Kick off a one-shot dialogue generation (not persisted)."""
        selected = []
        for i in range(self.list_groups_oneshot.count()):
            it = self.list_groups_oneshot.item(i)
            if it.checkState() == Qt.CheckState.Checked:
                selected.append(it.data(Qt.ItemDataRole.UserRole))
        if not selected:
            QMessageBox.warning(self, "提示", "请至少勾选一个词库。")
            return
        turn_count = self.spin_oneshot_turns.value()

        self.btn_oneshot.setEnabled(False)
        self.oneshot_in_flight = True
        self.oneshot_progress.setVisible(True)
        self.oneshot_progress.setRange(0, 0)  # indeterminate
        self.lbl_oneshot_status.setVisible(True)
        self.lbl_oneshot_status.setText("正在生成随机会话，请稍候...")
        self.lbl_oneshot_status.setStyleSheet(
            f"font-family: {FONT_FALLBACK}; font-size: {SIZE_BODY}px; color: {MANGO_DK};"
        )

        # Temporarily connect generation signals (disconnect after)
        self._oneshot_connected = True
        self.scenario_engine.bank_generation_done.connect(self._on_oneshot_done)
        self.scenario_engine.bank_generation_error.connect(self._on_oneshot_error)

        # Fire generation with persist=False
        try:
            self.scenario_engine.generate_bank(
                selected, turn_count=turn_count, persist=False
            )
        except Exception as e:
            self._on_oneshot_error(str(e))

    def _finish_oneshot(self):
        """Common cleanup after oneshot success/failure."""
        if getattr(self, "_oneshot_connected", False):
            try:
                self.scenario_engine.bank_generation_done.disconnect(
                    self._on_oneshot_done
                )
            except Exception:
                pass
            try:
                self.scenario_engine.bank_generation_error.disconnect(
                    self._on_oneshot_error
                )
            except Exception:
                pass
            self._oneshot_connected = False
        self.oneshot_in_flight = False
        self._reset_oneshot_ui()

    def _reset_oneshot_ui(self):
        """Clean up all oneshot-related UI state so the setup view is pristine
        when the user returns or after generation finishes.
        """
        self.btn_oneshot.setEnabled(True)
        self.oneshot_progress.setVisible(False)
        self.oneshot_progress.setRange(0, 0)
        self.lbl_oneshot_status.setVisible(False)
        self.lbl_oneshot_status.setText("")

    @staticmethod
    def _config_path() -> str:
        return get_user_data_path("config.json")

    def _persist_turn_count(self, value: int):
        """Remember the last chosen turn count to config.json (global effect).

        与 settings_dialog 的 scenario_turn_count 字段共享，下次进入
        settings_dialog 或 scenario_chat_page 都会加载此值。
        """
        try:
            path = self._config_path()
            cfg = {}
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
            if cfg.get("scenario_turn_count") == int(value):
                return
            cfg["scenario_turn_count"] = int(value)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[ScenarioChatPage] persist turn count failed: {e}")

    def _on_oneshot_done(self, bank):
        """Called when a one-shot generation finishes successfully."""
        if not self.oneshot_in_flight:
            return
        self._finish_oneshot()
        # Mark as current and start chat session immediately
        self.current_bank = bank
        self.script = bank.get("script", [])
        if not self.script:
            QMessageBox.warning(self, "提示", "AI 返回的对话为空，请重试。")
            return
        self._start_session_from_bank()

    def _on_oneshot_error(self, err):
        """Called when a one-shot generation fails."""
        if not self.oneshot_in_flight:
            return
        self._finish_oneshot()
        self.lbl_oneshot_status.setVisible(True)
        self.lbl_oneshot_status.setText(f"生成失败：{err}")
        self.lbl_oneshot_status.setStyleSheet(
            f"font-family: {FONT_FALLBACK}; font-size: {SIZE_BODY}px; color: {CLAY};"
        )
        QMessageBox.critical(self, "生成失败", err)

    def _refresh_bank_list(self):
        self.combo_bank.blockSignals(True)
        self.combo_bank.clear()
        banks = self.scenario_engine.get_all_banks() if self.scenario_engine else []
        if not banks:
            self.combo_bank.addItem("（无可用脚本）", None)
            self.combo_bank.setEnabled(False)
            self.btn_start.setEnabled(False)
            self.lbl_bank_info.setVisible(False)
            self.lbl_empty_hint.setVisible(True)
        else:
            self.combo_bank.setEnabled(True)
            self.lbl_empty_hint.setVisible(False)
            for b in banks:
                self.combo_bank.addItem(b.get("name", "未命名"), b.get("id"))
            self.combo_bank.setCurrentIndex(0)
        self.combo_bank.blockSignals(False)
        self._on_bank_selected()

    def _on_bank_selected(self):
        bank_id = self.combo_bank.currentData()
        if not bank_id or not self.scenario_engine:
            self.btn_start.setEnabled(False)
            self.lbl_bank_info.setVisible(False)
            return
        bank = self.scenario_engine.get_bank_by_id(bank_id)
        if not bank:
            self.btn_start.setEnabled(False)
            self.lbl_bank_info.setVisible(False)
            return
        self.current_bank = bank
        turns = bank.get("turn_count", len(bank.get("script", [])))
        groups = ", ".join(bank.get("source_groups", [])) or "(未知)"
        created = bank.get("created_at", "")[:10] or "-"
        self.lbl_bank_info.setText(
            f"轮次：{turns}     来源分组：{groups}     创建时间：{created}"
        )
        self.lbl_bank_info.setVisible(True)
        self.btn_start.setEnabled(turns > 0)

    # ====================================================================== #
    #   CHAT VIEW LOGIC                                                       #
    # ====================================================================== #
    def _start_session(self):
        if not self.current_bank:
            return
        self.script = self.current_bank.get("script", [])
        if not self.script:
            QMessageBox.warning(self, "脚本为空", "该脚本没有任何对话内容。")
            return
        self._start_session_from_bank()

    def _start_session_from_bank(self):
        """Shared: enter chat_view using self.current_bank / self.script already set."""
        # Reset state
        self.session_results = []
        self.pending_count = 0
        self.session_active = True
        self.btn_to_summary.setVisible(False)

        # Build all bubbles upfront (faded), then highlight current
        self._populate_chat_bubbles()
        self._update_progress(0)
        self.stack.setCurrentWidget(self.chat_view)
        # Kick off first turn
        QTimer.singleShot(200, lambda: self._play_turn(0))

    def _populate_chat_bubbles(self):
        # Clear old bubbles
        while self.chat_layout.count() > 0:
            item = self.chat_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self.bubble_frames = []
        self.bubble_status = []

        for i, turn in enumerate(self.script):
            bubble = QFrame()
            bubble.setObjectName("chatBubble")
            bubble.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
            bubble.setMaximumWidth(540)
            bubble_layout = QVBoxLayout(bubble)
            bubble_layout.setContentsMargins(14, 10, 14, 10)
            bubble_layout.setSpacing(4)

            role = turn.get("role", "A")
            text = turn.get("text", "")
            translation = turn.get("translation", "")

            head = QLabel(f"{'AI' if role == 'A' else '你'} · 第 {i+1} 轮")
            head.setStyleSheet(
                f"background: transparent; border: none; padding: 0; "
                f"font-family: {FONT_FALLBACK}; font-size: 11px; color: {INK_SOFT}; "
                f"font-weight: 600; letter-spacing: 0.3px;"
            )
            bubble_layout.addWidget(head)

            lbl_text = QLabel(text)
            lbl_text.setStyleSheet(
                f"background: transparent; border: none; padding: 0; "
                f"font-family: {FONT_FALLBACK}; font-size: {SIZE_UI}px; color: {INK}; line-height: 1.4;"
            )
            lbl_text.setWordWrap(True)
            bubble_layout.addWidget(lbl_text)

            if translation:
                lbl_tr = QLabel(translation)
                lbl_tr.setStyleSheet(
                    f"background: transparent; border: none; padding: 0; "
                    f"font-family: {FONT_FALLBACK}; font-size: 12px; color: {INK_SOFT};"
                )
                lbl_tr.setWordWrap(True)
                bubble_layout.addWidget(lbl_tr)

            status_lbl = QLabel("")
            status_lbl.setStyleSheet(
                f"background: transparent; border: none; padding: 0; "
                f"font-family: {FONT_FALLBACK}; font-size: 12px;"
            )
            status_lbl.setVisible(False)
            bubble_layout.addWidget(status_lbl)
            self.bubble_status.append(status_lbl)

            self._apply_bubble_style(bubble, role, active=False)
            self.bubble_frames.append(bubble)

            wrapper = QWidget()
            wrapper_layout = QHBoxLayout(wrapper)
            wrapper_layout.setContentsMargins(0, 0, 0, 0)
            if role == "A":
                wrapper_layout.addWidget(bubble)
                wrapper_layout.addStretch()
            else:
                wrapper_layout.addStretch()
                wrapper_layout.addWidget(bubble)
            self.chat_layout.addWidget(wrapper)
        self.chat_layout.addStretch()

    def _apply_bubble_style(self, frame, role, active):
        if role == "A":
            base = "#FBFAF5"
        else:
            base = DESK
        border = MANGO if active else DESK_LINE
        # Selector limited to QFrame#chatBubble so child QLabel won't inherit border
        frame.setStyleSheet(
            f"QFrame#chatBubble {{ background: {base}; border: 1px solid {border}; "
            f"border-radius: {RADIUS}px; }}"
        )

    def _highlight_bubble(self, idx):
        for i, frame in enumerate(self.bubble_frames):
            role = self.script[i].get("role", "A")
            self._apply_bubble_style(frame, role, active=(i == idx))
        # Auto-scroll to current bubble
        if 0 <= idx < len(self.bubble_frames):
            QTimer.singleShot(50, lambda: self.chat_scroll.ensureWidgetVisible(self.bubble_frames[idx]))

    def _update_progress(self, idx):
        total = len(self.script)
        cur = min(idx + 1, total)
        self.lbl_chat_progress.setText(f"第 {cur} / {total} 轮")

    # -------------------------------------------------- turn driver -------
    def _play_turn(self, idx):
        if not self.session_active:
            return
        if idx >= len(self.script):
            self._show_finish_button()
            return

        self.current_turn_idx = idx
        turn = self.script[idx]
        self._highlight_bubble(idx)
        self._update_progress(idx)

        if turn.get("role", "A") == "A":
            self._set_recorder_locked("AI 正在说...")
            self.tts.speak(turn.get("text", ""))
            # _on_player_state_changed will advance
        else:
            self._set_recorder_unlocked("该你说了，点击话筒录音")
            # 自动开始录音（settings → "默认开启自动录音" 控制）
            # 直接从 config 读取，不依赖 main_window.auto_mode（后者仅在发音练习启动时设置）
            try:
                cfg_path = self._config_path()
                auto_rec = True  # 默认开启
                if cfg_path and os.path.exists(cfg_path):
                    with open(cfg_path, "r", encoding="utf-8") as f:
                        auto_rec = json.load(f).get("auto_mode_default", True)
            except Exception:
                auto_rec = True
            if auto_rec:
                QTimer.singleShot(800, lambda i=idx: self._auto_start_recording(i))

    def _auto_start_recording(self, expected_idx):
        """Auto-start recording with VAD (auto-stop on silence) for current B turn."""
        if not self.session_active:
            return
        if self.stack.currentWidget() is not self.chat_view:
            return
        if self.current_turn_idx != expected_idx:
            return
        if expected_idx < 0 or expected_idx >= len(self.script):
            return
        if self.script[expected_idx].get("role", "A") != "B":
            return
        if getattr(self.recorder_widget, "is_recording", False):
            return
        if not self.recorder_widget.record_btn.isEnabled():
            return
        try:
            # Read device index from config
            dev_idx = None
            cfg_path = self._config_path()
            if cfg_path and os.path.exists(cfg_path):
                with open(cfg_path, "r", encoding="utf-8") as f:
                    dev_idx = json.load(f).get("device_index")

            # Start recording with VAD enabled for auto-stop on silence
            self.audio_recorder.start_recording(
                device_index=dev_idx,
                volume_callback=self.recorder_widget.on_volume_data,
                vad_enabled=True,
                stop_callback=self._vad_stop_recording,
            )
            # Update recording widget UI state
            self.recorder_widget.is_recording = True
            self.recorder_widget.record_btn.setStyleSheet(AppStyles.RECORD_BUTTON_ACTIVE)
            self.recorder_widget.status_label.setText("正在录音... (自动停止)")
        except Exception as e:
            print(f"[ScenarioChatPage] auto-record failed: {e}")

    def _vad_stop_recording(self):
        """Callback from VAD silence detection — stop recording on UI thread."""
        QTimer.singleShot(0, self._do_stop_recording)

    def _do_stop_recording(self):
        """Stop recording via the widget's toggle, which emits recording_finished."""
        if self.recorder_widget.is_recording:
            self.recorder_widget.toggle_recording()

    def _set_recorder_locked(self, status_text):
        self.recorder_widget.record_btn.setEnabled(False)
        self.recorder_widget.status_label.setText(status_text)

    def _set_recorder_unlocked(self, status_text):
        self.recorder_widget.record_btn.setEnabled(True)
        self.recorder_widget.status_label.setText(status_text)

    def _on_player_state_changed(self, state):
        # Only drive scenario flow when we are actively in chat_view
        if not self.session_active:
            return
        if self.stack.currentWidget() is not self.chat_view:
            return
        if state != QMediaPlayer.PlaybackState.StoppedState:
            return
        # Was the current turn an A turn?
        if 0 <= self.current_turn_idx < len(self.script):
            turn = self.script[self.current_turn_idx]
            if turn.get("role", "A") == "A":
                # Advance with a small pause for natural pacing
                idx = self.current_turn_idx
                QTimer.singleShot(400, lambda i=idx + 1: self._play_turn(i))

    # ----------------------------------------------- user recording -------
    def _on_user_recording(self, file_path):
        if not self.session_active:
            return
        idx = self.current_turn_idx
        if idx < 0 or idx >= len(self.script):
            return
        turn = self.script[idx]
        if turn.get("role", "A") != "B":
            return
        ref_text = turn.get("text", "")

        # Mark bubble as scoring
        if idx < len(self.bubble_status):
            self.bubble_status[idx].setVisible(True)
            self.bubble_status[idx].setText("评分中...")
            self.bubble_status[idx].setStyleSheet(
                f"background: transparent; border: none; padding: 0; "
                f"font-family: {FONT_FALLBACK}; font-size: 12px; color: {MANGO_DK};"
            )

        # Submit to executor (don't block UI)
        self.pending_count += 1
        self.executor.submit(self._score_in_worker, idx, file_path, ref_text)

        # Advance to next turn immediately
        QTimer.singleShot(200, lambda i=idx + 1: self._play_turn(i))

    def _score_in_worker(self, idx, file_path, ref_text):
        """Runs in worker thread. Emits signals to marshal back to UI thread."""
        try:
            result = self.ai_coach.assess(file_path, ref_text)
            score = int(result.get("accuracy_score", 0))
            self.signals.score_returned.emit(idx, score, result)
        except Exception as e:
            self.signals.score_error.emit(idx, str(e))

    def _on_score_returned(self, idx, score, result):
        self.pending_count = max(0, self.pending_count - 1)

        # Update bubble UI
        if 0 <= idx < len(self.bubble_status):
            color = LEAF if score >= 90 else MANGO_DK if score >= 70 else CLAY
            self.bubble_status[idx].setVisible(True)
            self.bubble_status[idx].setText(f"✓ {score} 分")
            self.bubble_status[idx].setStyleSheet(
                f"background: transparent; border: none; padding: 0; "
                f"font-family: {FONT_FALLBACK}; font-size: {SIZE_BODY}px; color: {color}; font-weight: bold;"
            )

        # Save result
        ref = self.script[idx].get("text", "")
        self.session_results.append({
            "turn_idx": idx,
            "role": "B",
            "text": ref,
            "score": score,
            "details": result.get("details", {}) if isinstance(result, dict) else {},
        })

        # Merge into main mistake book
        self._merge_into_mistake_book(ref, score)

    def _on_score_error(self, idx, err):
        self.pending_count = max(0, self.pending_count - 1)
        if 0 <= idx < len(self.bubble_status):
            self.bubble_status[idx].setVisible(True)
            self.bubble_status[idx].setText(f"⚠ 评分失败: {err[:40]}")
            self.bubble_status[idx].setStyleSheet(
                f"background: transparent; border: none; padding: 0; "
                f"font-family: {FONT_FALLBACK}; font-size: 12px; color: {CLAY};"
            )

    def _merge_into_mistake_book(self, text, score):
        """Update last_score / times_practiced on the matching word/sentence in main exercise db.

        If the text does NOT exist in the db, insert it as a new sentence entry
        so the MistakePage can pick it up as an oral-practice mistake. This makes
        scenario-chat behave like the translation quiz (every attempted turn leaves
        a trace in the mistake book).
        """
        if not text:
            return
        em = self.main_window.exercise_manager
        try:
            matched = False
            for cat in ("words", "sentences"):
                for item in em.exercises.get(cat, []):
                    if item.get("text") == text:
                        item["last_score"] = score
                        item["times_practiced"] = item.get("times_practiced", 0) + 1
                        matched = True
            # 未命中词库的 B 角台词作为新的 sentence 插入，group 取当前 bank 名
            # （带"情景会话_"或"随机会话_"前缀），确保 MistakePage 能筛出来。
            if not matched:
                group = (
                    self.current_bank.get("name", "情景会话")
                    if self.current_bank
                    else "情景会话"
                )
                translation = self._find_translation_in_script(text)
                em.exercises.setdefault("sentences", []).append({
                    "text": text,
                    "translation": translation,
                    "group": group,
                    "last_score": score,
                    "times_practiced": 1,
                    "source": "scenario_session",
                })
            em.save_data()
        except Exception as e:
            print(f"[ScenarioChatPage] Merge mistake book failed: {e}")

    def _find_translation_in_script(self, text: str) -> str:
        """Return the Chinese translation matching `text` from the current script,
        or empty string if not found.
        """
        for turn in self.script:
            if turn.get("text") == text:
                return turn.get("translation", "")
        return ""

    def _flush_session_results_to_db(self):
        """Fallback: re-apply every scored B-turn result to the mistake book.

        Called after executor.shutdown(wait=True) to guarantee that even if
        signals were delivered out-of-order, all scored turns end up persisted.
        """
        for r in self.session_results:
            if r.get("score") is None:
                continue
            if r.get("role") != "B":
                continue
            self._merge_into_mistake_book(r.get("text", ""), int(r.get("score", 0)))

    # ----------------------------------------------- end-of-session -------
    def _show_finish_button(self):
        self.session_active = False  # block further auto-advance
        # Keep accepting score callbacks; they will append to results
        self._set_recorder_locked("对话结束，可点击下方按钮进入总结")
        self.btn_to_summary.setVisible(True)

    def _quit_chat_early(self):
        if self.session_active:
            reply = QMessageBox.question(
                self, "结束会话",
                "会话尚未结束，确定要进入总结吗？\n（已录制的轮次仍会进入总结）",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        self.session_active = False
        # Stop any ongoing recording
        if self.recorder_widget.is_recording:
            self.recorder_widget.reset_state()
            self.audio_recorder.stop_recording()
        # Stop TTS playback
        try:
            self.tts.player.stop()
        except Exception:
            pass
        self._enter_summary()

    def _enter_summary(self):
        self.session_active = False
        self.btn_to_summary.setVisible(False)

        # Wait briefly for in-flight scoring to complete (max ~3s)
        # Drain executor by shutting down with wait=True, then recreate.
        try:
            self.executor.shutdown(wait=True)
        except Exception:
            pass
        self.executor = ThreadPoolExecutor(max_workers=2)

        # 兜底：把 session_results 里所有已评分的 B 角重新写一遍错题库。
        # 防止异步信号在 shutdown 之前尚未派发到主线程，导致漏写。
        self._flush_session_results_to_db()

        # Compute average over scored B turns
        scored = [r for r in self.session_results if r.get("score") is not None]
        scored.sort(key=lambda r: r["turn_idx"])
        if scored:
            avg = sum(r["score"] for r in scored) / len(scored)
            avg_int = int(round(avg))
        else:
            avg_int = 0

        if avg_int >= 90:
            self.lbl_summary_score.setText(f"完成！平均分: {avg_int}")
            self.lbl_summary_score.setStyleSheet(
                f"font-family: {FONT_FALLBACK}; font-size: {SIZE_SECTION}px; font-weight: bold; "
                f"color: {LEAF}; padding: {SP_3}px;"
            )
            self.lbl_summary_encourage.setText("发音非常棒，继续保持！")
        elif avg_int >= 70:
            self.lbl_summary_score.setText(f"完成！平均分: {avg_int}")
            self.lbl_summary_score.setStyleSheet(
                f"font-family: {FONT_FALLBACK}; font-size: {SIZE_SECTION}px; font-weight: bold; "
                f"color: {MANGO_DK}; padding: {SP_3}px;"
            )
            self.lbl_summary_encourage.setText("进步很明显，再针对低分项练几遍就能更上一层楼。")
        else:
            self.lbl_summary_score.setText(f"完成！平均分: {avg_int}")
            self.lbl_summary_score.setStyleSheet(
                f"font-family: {FONT_FALLBACK}; font-size: {SIZE_SECTION}px; font-weight: bold; "
                f"color: {CLAY}; padding: {SP_3}px;"
            )
            self.lbl_summary_encourage.setText("加油！多练习几次发音会更准。")

        # Trigger LLM summary
        self.lbl_feedback.setText("AI 正在分析你的发音...")
        self.lbl_feedback.setStyleSheet(
            f"font-family: {FONT_FALLBACK}; font-size: {SIZE_UI}px; color: {INK_SOFT}; "
            f"padding: {SP_2}px; background: {DESK}; border-radius: {RADIUS_SM}px;"
        )
        title = self.current_bank.get("name", "") if self.current_bank else ""
        try:
            self.scenario_engine.summarize_session(scored, scenario_title=title)
        except Exception as e:
            self._on_summary_error(str(e))

        # Populate error table
        self._populate_error_table(scored)

        self.stack.setCurrentWidget(self.summary_view)

    # ----------------------------------------------- summary view ---------
    def _populate_error_table(self, scored_results):
        # Pick rows with score < 80 (rough "needs work" threshold)
        bad = [r for r in scored_results if r.get("score", 100) < 80]
        if not bad:
            self.error_table.setRowCount(0)
            self.error_table.setVisible(False)
            self.lbl_no_errors.setVisible(True)
            return
        self.error_table.setVisible(True)
        self.lbl_no_errors.setVisible(False)
        self.error_table.setRowCount(len(bad))
        for row, r in enumerate(bad):
            text = r.get("text", "")
            score = r.get("score", 0)
            details = r.get("details", {}) or {}
            errors = details.get("errors", []) or []
            words = details.get("words", []) or []

            # Column 0: text
            it_text = QTableWidgetItem(text)
            it_text.setFlags(it_text.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.error_table.setItem(row, 0, it_text)

            # Column 1: score
            it_score = QTableWidgetItem(str(score))
            it_score.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            it_score.setFlags(it_score.flags() & ~Qt.ItemFlag.ItemIsEditable)
            color = Qt.GlobalColor.darkRed if score < 70 else Qt.GlobalColor.darkYellow
            it_score.setForeground(color)
            self.error_table.setItem(row, 1, it_score)

            # Column 2: error phonemes (compact)
            err_summary = self._format_errors(errors, words)
            it_err = QTableWidgetItem(err_summary)
            it_err.setFlags(it_err.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.error_table.setItem(row, 2, it_err)

            # Column 3: TTS button
            btn_play = QPushButton("听")
            btn_play.setStyleSheet(
                f"QPushButton {{ background-color: {MANGO}; color: {INK}; "
                f"padding: {SP_1}px {SP_2}px; border-radius: {RADIUS_SM}px; "
                f"font-family: {FONT_FALLBACK}; font-size: {SIZE_BODY}px; }}"
                f"QPushButton:hover {{ background-color: {MANGO_DK}; }}"
            )
            btn_play.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_play.clicked.connect(lambda checked, t=text: self.tts.speak(t))
            self.error_table.setCellWidget(row, 3, btn_play)

    def _format_errors(self, errors, words):
        """Produce a compact human-readable summary of phoneme errors."""
        if errors:
            parts = []
            for e in errors[:4]:
                expected = e.get("expected", "")
                actual = e.get("actual", "")
                word = e.get("word", "")
                etype = e.get("type", "")
                if word:
                    parts.append(f"{word}: {expected}→{actual or '?'}")
                else:
                    parts.append(f"{etype}: {expected}→{actual or '?'}")
            extra = len(errors) - 4
            if extra > 0:
                parts.append(f"... 还有 {extra} 项")
            return "; ".join(parts)
        # Fallback: show worst-scoring words
        if words:
            sorted_w = sorted(words, key=lambda w: w.get("score", 100))[:3]
            return ", ".join(f"{w.get('word','')}({w.get('score',0)})" for w in sorted_w)
        return "—"

    def _on_summary_ready(self, feedback_text):
        # Only update if currently on summary_view
        if self.stack.currentWidget() is not self.summary_view:
            return
        self.lbl_feedback.setText(feedback_text)
        self.lbl_feedback.setStyleSheet(
            f"font-family: {FONT_FALLBACK}; font-size: {SIZE_UI}px; color: {INK}; "
            f"padding: {SP_2}px; background: {LEAF_SOFT}; border-radius: {RADIUS_SM}px;"
        )

    def _on_summary_error(self, err):
        if self.stack.currentWidget() is not self.summary_view:
            return
        self.lbl_feedback.setText(f"AI 反馈生成失败：{err}\n请稍后再试。")
        self.lbl_feedback.setStyleSheet(
            f"font-family: {FONT_FALLBACK}; font-size: {SIZE_UI}px; color: {CLAY}; "
            f"padding: {SP_2}px; background: {CLAY_SOFT}; border-radius: {RADIUS_SM}px;"
        )

    # ====================================================================== #
    #   NAVIGATION                                                            #
    # ====================================================================== #
    def _go_hub(self):
        self._reset_oneshot_ui()
        self.stack.setCurrentWidget(self.setup_view)
        self.main_window.stack.setCurrentWidget(self.main_window.page_oral_hub)

    def _go_home(self):
        self._reset_oneshot_ui()
        self.stack.setCurrentWidget(self.setup_view)
        self.main_window.stack.setCurrentWidget(self.main_window.page_home)
