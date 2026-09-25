"""Oral practice hub: 中转页, splits "口语练习" into 发音练习 + 情景会话."""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QGridLayout
)
from PyQt6.QtCore import Qt
from .styles import (
    AppStyles, FONT_FALLBACK, PAPER, DESK, INK, INK_SOFT,
    MANGO, MANGO_DK, LEAF, CLAY, DESK_LINE,
    SP_3, SP_4, SP_5, RADIUS, SIZE_TITLE, SIZE_BODY, SIZE_SECTION,
)


class OralHubPage(QWidget):
    """Simple hub page that lets users pick between pronunciation practice and scenario chat."""

    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(SP_5, SP_5, SP_5, SP_5)

        # Top bar with back button
        top_bar = QHBoxLayout()
        btn_back = QPushButton("← 返回首页")
        btn_back.setStyleSheet(AppStyles.GHOST_BUTTON)
        btn_back.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_back.clicked.connect(self._go_home)
        top_bar.addWidget(btn_back)
        top_bar.addStretch()
        layout.addLayout(top_bar)

        # Title
        title = QLabel("口语练习")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(AppStyles.HEADER_LABEL)
        layout.addWidget(title)

        subtitle = QLabel("选择练习模式")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setStyleSheet(AppStyles.SUBTITLE_LABEL)
        layout.addWidget(subtitle)

        layout.addStretch()

        # Hub buttons in a row
        grid = QGridLayout()
        grid.setSpacing(SP_4)
        grid.setAlignment(Qt.AlignmentFlag.AlignCenter)

        btn_pronunciation = QPushButton("发音练习\nPronunciation")
        btn_pronunciation.setStyleSheet(AppStyles.MODULE_CARD(active=True))
        btn_pronunciation.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_pronunciation.clicked.connect(self.main_window.open_oral_test_page)
        grid.addWidget(btn_pronunciation, 0, 0)

        btn_scenario = QPushButton("情景会话\nScenario Chat")
        btn_scenario.setStyleSheet(AppStyles.MODULE_CARD())
        btn_scenario.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_scenario.clicked.connect(self.main_window.open_scenario_chat_page)
        grid.addWidget(btn_scenario, 0, 1)

        btn_tutor = QPushButton("AI家庭教师\nAI Tutor")
        btn_tutor.setStyleSheet(AppStyles.MODULE_CARD())
        btn_tutor.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_tutor.clicked.connect(self.main_window.open_tutor_page)
        grid.addWidget(btn_tutor, 1, 0, 1, 2, Qt.AlignmentFlag.AlignCenter)

        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        layout.addLayout(grid)

        # Hints
        hint = QLabel(
            "💡 发音练习：单词/句子逐个朗读，立刻获得 GOP 评分\n"
            "💡 情景会话：与 AI 进行双人对话，会话结束后给出综合反馈\n"
            "💡 AI家庭教师：围绕词库渐进式教学，自动纠正发音和语法"
        )
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setStyleSheet(AppStyles.BODY_LABEL + f"margin-top: {SP_4}px;")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        layout.addStretch()

    def _go_home(self):
        self.main_window.stack.setCurrentWidget(self.main_window.page_home)
