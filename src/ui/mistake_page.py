"""
MistakePage - Split layout for oral practice mistakes and translation quiz mistakes.
Left table: oral practice mistakes (last_score < 90)
Right table: translation quiz mistakes (quiz_wrong > 0)
"""
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QTableWidget,
                             QTableWidgetItem, QPushButton, QHeaderView, QLabel,
                             QMessageBox, QSplitter, QFrame)
from PyQt6.QtCore import Qt
import random
from .styles import (AppStyles, FONT_FALLBACK, PAPER, DESK, INK, INK_SOFT,
                     MANGO, MANGO_DK, LEAF, CLAY, DESK_LINE, SP_3, SP_4,
                     SP_5, RADIUS)


class MistakePage(QWidget):
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self.manager = main_window.exercise_manager

        self.oral_mistakes = []
        self.quiz_mistakes = []

        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)

        # Page background
        self.setStyleSheet(f"background-color: {PAPER};")

        # Header
        header_layout = QHBoxLayout()
        btn_back = QPushButton("Back")
        btn_back.setStyleSheet(AppStyles.GHOST_BUTTON)
        btn_back.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_back.clicked.connect(self.go_home)
        header_layout.addWidget(btn_back)

        lbl_title = QLabel("错题本")
        lbl_title.setStyleSheet(AppStyles.TITLE_LABEL)
        header_layout.addWidget(lbl_title)
        header_layout.addStretch()
        layout.addLayout(header_layout)

        # Splitter for left/right tables
        self.splitter = QSplitter(Qt.Orientation.Horizontal)

        # ===== LEFT: Oral Practice Mistakes =====
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)

        lbl_oral = QLabel("口语错题")
        lbl_oral.setStyleSheet(AppStyles.SECTION_LABEL)
        left_layout.addWidget(lbl_oral)

        self.table_oral = QTableWidget()
        self.table_oral.setStyleSheet(AppStyles.TABLE)
        self.table_oral.setColumnCount(5)
        self.table_oral.setHorizontalHeaderLabels([
            "单词", "分组", "得分", "次数", "听音"
        ])
        self.table_oral.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table_oral.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        left_layout.addWidget(self.table_oral)

        # Summary + Review button
        self.lbl_oral_count = QLabel("0 道口语错题")
        self.lbl_oral_count.setStyleSheet(AppStyles.BODY_LABEL)
        left_layout.addWidget(self.lbl_oral_count)

        btn_review_oral = QPushButton("复习口语错题")
        btn_review_oral.setStyleSheet(AppStyles.BIG_BUTTON)
        btn_review_oral.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_review_oral.clicked.connect(self.start_review_oral)
        left_layout.addWidget(btn_review_oral)

        self.splitter.addWidget(left_panel)

        # ===== RIGHT: Translation Quiz Mistakes =====
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)

        lbl_quiz = QLabel("翻译错题")
        lbl_quiz.setStyleSheet(AppStyles.SECTION_LABEL)
        right_layout.addWidget(lbl_quiz)

        self.table_quiz = QTableWidget()
        self.table_quiz.setStyleSheet(AppStyles.TABLE)
        self.table_quiz.setColumnCount(5)
        self.table_quiz.setHorizontalHeaderLabels([
            "单词", "分组", "答对", "答错", "听音"
        ])
        self.table_quiz.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table_quiz.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        right_layout.addWidget(self.table_quiz)

        # Summary + Review button
        self.lbl_quiz_count = QLabel("0 道翻译错题")
        self.lbl_quiz_count.setStyleSheet(AppStyles.BODY_LABEL)
        right_layout.addWidget(self.lbl_quiz_count)

        btn_review_quiz = QPushButton("复习翻译错题")
        btn_review_quiz.setStyleSheet(AppStyles.BIG_BUTTON)
        btn_review_quiz.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_review_quiz.clicked.connect(self.start_review_quiz)
        right_layout.addWidget(btn_review_quiz)

        self.splitter.addWidget(right_panel)

        layout.addWidget(self.splitter, 1)  # stretch factor 1 = fill remaining space

    def refresh_data(self):
        """Refresh both tables from exercise data."""
        all_words = self.manager.exercises.get("words", [])
        all_sentences = self.manager.exercises.get("sentences", [])
        full_list = all_words + all_sentences

        # Oral mistakes: practiced and score < 80
        self.oral_mistakes = [
            item for item in full_list
            if item.get('times_practiced', 0) > 0 and item.get('last_score', 0) < 80
        ]
        self.oral_mistakes.sort(key=lambda x: x.get('last_score', 999))

        # Quiz mistakes: quiz_wrong > 0
        self.quiz_mistakes = [
            item for item in full_list
            if item.get('quiz_wrong', 0) > 0
        ]
        self.quiz_mistakes.sort(key=lambda x: -x.get('quiz_wrong', 0))

        self._populate_oral_table()
        self._populate_quiz_table()

    def _populate_oral_table(self):
        """Fill the left table with oral practice mistakes."""
        self.table_oral.setRowCount(len(self.oral_mistakes))
        self.lbl_oral_count.setText(f"{len(self.oral_mistakes)} 道口语错题")

        for row, item in enumerate(self.oral_mistakes):
            self.table_oral.setItem(row, 0, QTableWidgetItem(item.get("text", "")))
            self.table_oral.setItem(row, 1, QTableWidgetItem(item.get("group", "Default")))

            last_score = item.get("last_score", 0)
            score_item = QTableWidgetItem(str(last_score))
            score_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if last_score < 60:
                score_item.setForeground(Qt.GlobalColor.red)
            elif last_score >= 80:
                score_item.setForeground(Qt.GlobalColor.darkGreen)
            self.table_oral.setItem(row, 2, score_item)

            count_item = QTableWidgetItem(str(item.get("times_practiced", 0)))
            count_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table_oral.setItem(row, 3, count_item)

            # Listen button
            btn_tts = QPushButton("🔊")
            btn_tts.setToolTip("听标准发音")
            btn_tts.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_tts.setStyleSheet(f"""
                QPushButton {{
                    background: transparent; border: none;
                    font-size: {SP_3}px;
                    font-family: {FONT_FALLBACK};
                }}
                QPushButton:hover {{ background-color: {DESK}; border-radius: {RADIUS}px; }}
            """)
            btn_tts.clicked.connect(lambda checked, i=item: self.play_tts(i))
            self.table_oral.setCellWidget(row, 4, btn_tts)

    def _populate_quiz_table(self):
        """Fill the right table with translation quiz mistakes."""
        self.table_quiz.setRowCount(len(self.quiz_mistakes))
        self.lbl_quiz_count.setText(f"{len(self.quiz_mistakes)} 道翻译错题")

        for row, item in enumerate(self.quiz_mistakes):
            self.table_quiz.setItem(row, 0, QTableWidgetItem(item.get("text", "")))
            self.table_quiz.setItem(row, 1, QTableWidgetItem(item.get("group", "Default")))

            quiz_correct = item.get("quiz_correct", 0)
            correct_item = QTableWidgetItem(str(quiz_correct) if quiz_correct > 0 else "-")
            correct_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if quiz_correct > 0:
                correct_item.setForeground(Qt.GlobalColor.darkGreen)
            self.table_quiz.setItem(row, 2, correct_item)

            quiz_wrong = item.get("quiz_wrong", 0)
            wrong_item = QTableWidgetItem(str(quiz_wrong))
            wrong_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            wrong_item.setForeground(Qt.GlobalColor.red)
            self.table_quiz.setItem(row, 3, wrong_item)

            # Listen button
            btn_tts = QPushButton("🔊")
            btn_tts.setToolTip("听标准发音")
            btn_tts.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_tts.setStyleSheet(f"""
                QPushButton {{
                    background: transparent; border: none;
                    font-size: {SP_3}px;
                    font-family: {FONT_FALLBACK};
                }}
                QPushButton:hover {{ background-color: {DESK}; border-radius: {RADIUS}px; }}
            """)
            btn_tts.clicked.connect(lambda checked, i=item: self.play_tts(i))
            self.table_quiz.setCellWidget(row, 4, btn_tts)

    def play_tts(self, item):
        text = item.get("text", "")
        if text:
            self.main_window.tts.speak(text)

    def go_home(self):
        self.main_window.stack.setCurrentWidget(self.main_window.page_home)

    def start_review_oral(self):
        """Start oral practice with oral mistake list."""
        if not self.oral_mistakes:
            QMessageBox.information(self, "提示", "没有口语错题，太棒了！")
            return

        review_list = self.oral_mistakes[:]
        random.shuffle(review_list)
        self.main_window.start_practice_with_list(review_list)

    def start_review_quiz(self):
        """Start translation quiz review using quiz mistakes from saved banks."""
        if not self.quiz_mistakes:
            QMessageBox.information(self, "提示", "没有翻译错题。")
            return

        # Get wrong word texts
        wrong_texts = [item.get("text", "") for item in self.quiz_mistakes]

        # Find matching questions from quiz banks
        quiz_engine = self.main_window.page_quiz.quiz_engine
        questions = quiz_engine.find_questions_for_words(wrong_texts)

        if not questions:
            QMessageBox.warning(
                self, "未找到题目",
                f"在这些错题词中未找到对应的题库题目（共 {len(wrong_texts)} 个词）。\n\n"
                "请先到设置 > 题库页生成包含这些词库的题库。"
            )
            return

        # Navigate to quiz page with review questions
        self.main_window.page_quiz.start_review_quiz(questions)
        self.main_window.stack.setCurrentWidget(self.main_window.page_quiz)
