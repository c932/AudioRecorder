"""
OralTestPage - UI for oral reading test with LLM-generated sentences.

Bank generation has been removed from this page; banks are now generated only
from Settings → Banks (centralized). This page is purely a launcher.
"""
import random

from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
                             QLabel, QComboBox, QGroupBox, QMessageBox, QSpinBox)
from PyQt6.QtCore import Qt
from src.ui.styles import (AppStyles, FONT_FALLBACK, PAPER, DESK, INK, INK_SOFT,
                           MANGO, MANGO_DK, LEAF, CLAY, CLAY_SOFT, DESK_LINE,
                           SP_2, SP_3, SP_4, SP_5, RADIUS, SIZE_BODY, SIZE_UI)
from src.core.oral_test_engine import OralTestEngine


class OralTestPage(QWidget):
    """Oral reading test page — bank selection + practice launcher."""

    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self.oral_engine = OralTestEngine(main_window.exercise_manager)

        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(SP_5, SP_5, SP_5, SP_5)
        layout.setSpacing(SP_3)

        # Top bar
        top_bar = QHBoxLayout()
        btn_back = QPushButton("Back")
        btn_back.clicked.connect(self._go_back)
        btn_back.setStyleSheet(AppStyles.GHOST_BUTTON)
        top_bar.addWidget(btn_back)
        top_bar.addStretch()
        layout.addLayout(top_bar)

        layout.addStretch()

        # Title
        title = QLabel("Oral Reading Test")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(AppStyles.HEADER_LABEL)
        layout.addWidget(title)

        subtitle = QLabel("Select a bank to start reading practice")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setStyleSheet(AppStyles.SUBTITLE_LABEL)
        layout.addWidget(subtitle)

        layout.addSpacing(SP_4)

        # Bank selector
        bank_group = QGroupBox("Select oral test bank")
        bank_group.setStyleSheet(AppStyles.GROUP_BOX)
        bank_layout = QVBoxLayout(bank_group)

        self.combo_bank = QComboBox()
        self.combo_bank.setStyleSheet(AppStyles.INPUT)
        self.combo_bank.currentIndexChanged.connect(self._on_bank_selected)
        bank_layout.addWidget(self.combo_bank)

        self.lbl_bank_info = QLabel("")
        self.lbl_bank_info.setWordWrap(True)
        self.lbl_bank_info.setStyleSheet(
            f"font-family: {FONT_FALLBACK}; font-size: {SIZE_BODY}px; color: {INK_SOFT}; "
            f"padding: {SP_2}px; background: {DESK}; border-radius: {RADIUS}px;"
        )
        self.lbl_bank_info.setVisible(False)
        bank_layout.addWidget(self.lbl_bank_info)

        layout.addWidget(bank_group)

        layout.addSpacing(SP_3)

        # Start button + count selector
        start_group = QGroupBox("Practice settings")
        start_group.setStyleSheet(AppStyles.GROUP_BOX)
        start_layout = QVBoxLayout(start_group)

        count_row = QHBoxLayout()
        count_label = QLabel("Questions per session:")
        count_label.setStyleSheet(AppStyles.BODY_LABEL)
        count_row.addWidget(count_label)
        self.spin_count = QSpinBox()
        self.spin_count.setRange(1, 1000)
        self.spin_count.setValue(10)
        self.spin_count.setToolTip("每次练习的题目数量。如果超过题库总数则练习全部。")
        self.spin_count.setStyleSheet(AppStyles.INPUT)
        count_row.addWidget(self.spin_count)
        count_row.addStretch()
        start_layout.addLayout(count_row)

        hint_count = QLabel("Questions are shuffled each session.")
        hint_count.setStyleSheet(AppStyles.BODY_LABEL)
        start_layout.addWidget(hint_count)

        layout.addWidget(start_group)

        layout.addSpacing(SP_3)

        # Start button
        self.btn_start = QPushButton("Start Oral Test")
        self.btn_start.setStyleSheet(AppStyles.BIG_BUTTON)
        self.btn_start.clicked.connect(self._start_test)
        self.btn_start.setEnabled(False)
        layout.addWidget(self.btn_start, alignment=Qt.AlignmentFlag.AlignCenter)

        # Empty hint
        self.lbl_empty_hint = QLabel("No oral test banks yet.\nGenerate one in Settings → Banks.")
        self.lbl_empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_empty_hint.setStyleSheet(
            f"font-family: {FONT_FALLBACK}; font-size: {SIZE_UI}px; color: {CLAY}; "
            f"padding: {SP_3}px; background: {CLAY_SOFT}; border-radius: {RADIUS}px;"
        )
        self.lbl_empty_hint.setVisible(False)
        layout.addWidget(self.lbl_empty_hint)

        layout.addStretch()

    # ========== SLOTS ==========
    def showEvent(self, event):
        """Refresh banks each time page is shown."""
        super().showEvent(event)
        self._refresh_banks()

    def _refresh_banks(self):
        """Reload bank list into combo."""
        self.combo_bank.blockSignals(True)
        self.combo_bank.clear()
        self.combo_bank.addItem("-- Select a bank --", None)

        banks = self.oral_engine.get_all_banks()
        for bank in banks:
            name = bank.get("name", "Unnamed")
            count = bank.get("sentence_count", len(bank.get("sentences", [])))
            self.combo_bank.addItem(f"{name} ({count} sentences)", bank.get("id"))

        self.combo_bank.blockSignals(False)

        has_banks = len(banks) > 0
        self.btn_start.setEnabled(False)
        self.lbl_empty_hint.setVisible(not has_banks)
        self.lbl_bank_info.setVisible(False)

    def _on_bank_selected(self, index):
        bank_id = self.combo_bank.currentData()
        if not bank_id:
            self.btn_start.setEnabled(False)
            self.lbl_bank_info.setVisible(False)
            return

        bank = self.oral_engine.get_bank_by_id(bank_id)
        if not bank:
            self.btn_start.setEnabled(False)
            self.lbl_bank_info.setVisible(False)
            return

        count = bank.get("sentence_count", len(bank.get("sentences", [])))
        groups = ", ".join(bank.get("source_groups", []))
        created = bank.get("created_at", "")[:10]

        self.lbl_bank_info.setText(f"Sentences: {count} | Groups: {groups} | Created: {created}")
        self.lbl_bank_info.setVisible(True)
        self.btn_start.setEnabled(True)
        self.lbl_empty_hint.setVisible(False)

        # 根据题库规模调整题目数默认值（上限不超过题库总数）
        if count > 0:
            default_count = min(10, count)
            self.spin_count.setRange(1, count)
            self.spin_count.setValue(default_count)

    def _start_test(self):
        """Launch oral test with selected bank."""
        bank_id = self.combo_bank.currentData()
        if not bank_id:
            QMessageBox.warning(self, "提示", "请先选择一个口语测试题库。")
            return

        sentences = self.oral_engine.load_bank_sentences(bank_id)
        if not sentences:
            QMessageBox.warning(self, "提示", "题库为空。")
            return

        # 随机打乱顺序（避免总是练习开头的几题）
        sentences = sentences[:]
        random.shuffle(sentences)

        # 限制题目数量
        practice_count = self.spin_count.value()
        sentences = sentences[:practice_count]

        practice_list = []
        for s in sentences:
            practice_list.append({
                "text": s.get("text", ""),
                "translation": s.get("translation", ""),
                "group": s.get("source_group", "OralTest"),
                "phonetic": "",
            })

        self.main_window.start_practice_with_list(practice_list)

    def _go_back(self):
        """Return to oral hub if available, else home."""
        if hasattr(self.main_window, "page_oral_hub"):
            self.main_window.stack.setCurrentWidget(self.main_window.page_oral_hub)
        else:
            self.main_window.stack.setCurrentWidget(self.main_window.page_home)
