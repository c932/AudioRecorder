"""MemorizePage - 分类速记模块

基于《初中英语核心话题1600词汇分类速记表》的28天记忆模块：
- 按天浏览词汇分类与词条
- 艾宾浩斯遗忘曲线复习计划（学习后第1/2/4/7/15天复习）
- 记忆卡片导出（A4每页2张，每张6词，PDF/DOCX）
- 中英互译测验
"""
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QTableWidget,
                             QTableWidgetItem, QPushButton, QHeaderView, QLabel,
                             QMessageBox, QSplitter, QListWidget, QListWidgetItem,
                             QStackedWidget, QProgressBar, QComboBox, QFileDialog,
                             QGridLayout, QFrame)
from PyQt6.QtCore import Qt, QTimer
from datetime import date

from src.core.memorize_engine import MemorizeEngine, REVIEW_INTERVALS
from src.ui.styles import (AppStyles, FONT_FALLBACK, PAPER, DESK, INK, INK_SOFT,
                            MANGO, MANGO_DK, LEAF, CLAY, LEAF_SOFT, CLAY_SOFT,
                            DESK_LINE, SP_1, SP_2, SP_3, SP_4, SP_5, RADIUS, SIZE_BODY,
                            SIZE_UI, SIZE_TITLE, SIZE_SECTION, SIZE_HEADER)


class MemorizePage(QWidget):
    def __init__(self, main_window):
        super().__init__()
        self.setStyleSheet(f"background-color: {PAPER};")
        self.main_window = main_window
        self.engine = MemorizeEngine()
        self.current_day = 1

        # 测验状态
        self.quiz_questions = []
        self.quiz_index = 0
        self.quiz_score = 0
        self.quiz_day = None

        self._build_ui()
        self.refresh_data()

    # ================= UI 构建 =================

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # 顶部栏
        header = QHBoxLayout()
        btn_back = QPushButton("Back")
        btn_back.setStyleSheet(AppStyles.GHOST_BUTTON)
        btn_back.clicked.connect(self.go_home)
        header.addWidget(btn_back)

        lbl_title = QLabel("分类速记（28天）")
        lbl_title.setStyleSheet(AppStyles.HEADER_LABEL)
        header.addWidget(lbl_title)
        header.addStretch()

        self.btn_due = QPushButton("今日待复习")
        self.btn_due.setStyleSheet(AppStyles.BIG_BUTTON)
        self.btn_due.clicked.connect(self.show_plan_view)
        header.addWidget(self.btn_due)
        layout.addLayout(header)

        # 左右分栏
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # 左侧：模块列表
        self.day_list = QListWidget()
        self.day_list.setFixedWidth(230)
        self.day_list.setStyleSheet(AppStyles.LIST_WIDGET)
        self.day_list.currentItemChanged.connect(self.on_day_selected)
        splitter.addWidget(self.day_list)

        # 右侧：子视图栈
        self.detail_stack = QStackedWidget()
        self.detail_stack.addWidget(self._build_detail_view())   # 0 词条浏览
        self.detail_stack.addWidget(self._build_quiz_view())     # 1 测验
        self.detail_stack.addWidget(self._build_plan_view())     # 2 复习计划
        splitter.addWidget(self.detail_stack)

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter, 1)

    def _build_detail_view(self):
        view = QWidget()
        view.setStyleSheet(f"background-color: {PAPER};")
        layout = QVBoxLayout(view)

        info_row = QHBoxLayout()
        info_col = QVBoxLayout()
        self.lbl_day_title = QLabel("")
        self.lbl_day_title.setStyleSheet(AppStyles.TITLE_LABEL)
        info_col.addWidget(self.lbl_day_title)

        self.lbl_day_progress = QLabel("")
        self.lbl_day_progress.setStyleSheet(AppStyles.BODY_LABEL)
        info_col.addWidget(self.lbl_day_progress)
        info_row.addLayout(info_col)
        info_row.addStretch()

        btn_start = QPushButton("开始学习计划")
        btn_start.setStyleSheet(AppStyles.BIG_BUTTON)
        btn_start.clicked.connect(self.start_module_plan)
        info_row.addWidget(btn_start)
        self.btn_start_plan = btn_start
        layout.addLayout(info_row)

        # 操作行
        action_row = QHBoxLayout()

        lbl_count = QLabel("题数")
        lbl_count.setStyleSheet(AppStyles.BODY_LABEL)
        action_row.addWidget(lbl_count)
        self.combo_count = QComboBox()
        for n in (10, 15, 20, 30):
            self.combo_count.addItem(str(n), n)
        self.combo_count.addItem("全部", 999)
        self.combo_count.setCurrentIndex(0)
        action_row.addWidget(self.combo_count)

        lbl_mode = QLabel("模式")
        lbl_mode.setStyleSheet(AppStyles.BODY_LABEL)
        action_row.addWidget(lbl_mode)
        self.combo_mode = QComboBox()
        self.combo_mode.addItem("英译中", "en2cn")
        self.combo_mode.addItem("中译英", "cn2en")
        self.combo_mode.addItem("混合", "mixed")
        action_row.addWidget(self.combo_mode)

        btn_quiz = QPushButton("开始测验")
        btn_quiz.setStyleSheet(AppStyles.BIG_BUTTON)
        btn_quiz.clicked.connect(self.start_quiz)
        action_row.addWidget(btn_quiz)

        btn_practice = QPushButton("跟读练习")
        btn_practice.setStyleSheet(AppStyles.CARD_BUTTON)
        btn_practice.clicked.connect(self.start_oral_practice)
        action_row.addWidget(btn_practice)

        btn_pdf = QPushButton("导出PDF卡片")
        btn_pdf.setStyleSheet(AppStyles.CARD_BUTTON)
        btn_pdf.clicked.connect(lambda: self.export_cards("pdf"))
        action_row.addWidget(btn_pdf)

        btn_docx = QPushButton("导出DOCX卡片")
        btn_docx.setStyleSheet(AppStyles.CARD_BUTTON)
        btn_docx.clicked.connect(lambda: self.export_cards("docx"))
        action_row.addWidget(btn_docx)

        action_row.addStretch()
        layout.addLayout(action_row)

        # 词条表
        self.table_entries = QTableWidget()
        self.table_entries.setStyleSheet(AppStyles.TABLE)
        self.table_entries.setColumnCount(5)
        self.table_entries.setHorizontalHeaderLabels(["词条", "词性", "中文释义", "分类", "🔊"])
        self.table_entries.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table_entries.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table_entries.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table_entries.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table_entries.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.table_entries.setWordWrap(True)
        self.table_entries.setAlternatingRowColors(True)
        layout.addWidget(self.table_entries, 1)

        self.lbl_entry_count = QLabel("")
        self.lbl_entry_count.setStyleSheet(AppStyles.BODY_LABEL)
        layout.addWidget(self.lbl_entry_count)
        return view

    def _build_quiz_view(self):
        view = QWidget()
        view.setStyleSheet(f"background-color: {PAPER};")
        layout = QVBoxLayout(view)
        layout.setSpacing(SP_3)

        top = QHBoxLayout()
        self.btn_quiz_back = QPushButton("Back")
        self.btn_quiz_back.setStyleSheet(AppStyles.GHOST_BUTTON)
        self.btn_quiz_back.clicked.connect(self.back_to_detail)
        top.addWidget(self.btn_quiz_back)
        top.addStretch()
        self.lbl_quiz_progress = QLabel("")
        self.lbl_quiz_progress.setStyleSheet(f"""
            font-family: {FONT_FALLBACK};
            font-size: {SIZE_BODY}px;
            font-weight: 700;
            color: {INK};
        """)
        top.addWidget(self.lbl_quiz_progress)
        layout.addLayout(top)

        self.quiz_bar = QProgressBar()
        self.quiz_bar.setStyleSheet(AppStyles.PROGRESS_BAR)
        layout.addWidget(self.quiz_bar)

        self.lbl_quiz_hint = QLabel("")
        self.lbl_quiz_hint.setStyleSheet(AppStyles.BODY_LABEL)
        layout.addWidget(self.lbl_quiz_hint)

        self.lbl_quiz_question = QLabel("")
        self.lbl_quiz_question.setStyleSheet(f"""
            font-family: {FONT_FALLBACK};
            font-size: {SIZE_SECTION}px;
            font-weight: 800;
            color: {INK};
            background: {DESK};
            border-radius: {RADIUS}px;
            padding: {SP_4}px;
        """)
        self.lbl_quiz_question.setWordWrap(True)
        self.lbl_quiz_question.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_quiz_question.setMinimumHeight(90)
        layout.addWidget(self.lbl_quiz_question)

        grid = QGridLayout()
        self.quiz_option_buttons = []
        for i in range(4):
            btn = QPushButton()
            btn.setStyleSheet(AppStyles.QUIZ_OPTION_BUTTON)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda checked, idx=i: self.answer_quiz(idx))
            grid.addWidget(btn, i // 2, i % 2)
            self.quiz_option_buttons.append(btn)
        grid.setSpacing(10)
        layout.addLayout(grid, 1)

        self.lbl_quiz_feedback = QLabel("")
        self.lbl_quiz_feedback.setStyleSheet(f"""
            font-family: {FONT_FALLBACK};
            font-size: {SIZE_UI}px;
            font-weight: 700;
        """)
        self.lbl_quiz_feedback.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.lbl_quiz_feedback)

        result_row = QHBoxLayout()
        result_row.addStretch()
        self.btn_quiz_retry = QPushButton("再测一次")
        self.btn_quiz_retry.setStyleSheet(AppStyles.BIG_BUTTON)
        self.btn_quiz_retry.clicked.connect(self.start_quiz)
        result_row.addWidget(self.btn_quiz_retry)
        self.btn_quiz_finish = QPushButton("完成并返回")
        self.btn_quiz_finish.setStyleSheet(AppStyles.CARD_BUTTON)
        self.btn_quiz_finish.clicked.connect(self.back_to_detail)
        result_row.addWidget(self.btn_quiz_finish)
        result_row.addStretch()
        layout.addLayout(result_row)
        return view

    def _build_plan_view(self):
        view = QWidget()
        view.setStyleSheet(f"background-color: {PAPER};")
        layout = QVBoxLayout(view)

        top = QHBoxLayout()
        btn_back = QPushButton("Back")
        btn_back.setStyleSheet(AppStyles.GHOST_BUTTON)
        btn_back.clicked.connect(self.back_to_detail)
        top.addWidget(btn_back)

        lbl = QLabel("复习计划（艾宾浩斯遗忘曲线：学习后第 1/2/4/7/15 天各复习一次）")
        lbl.setStyleSheet(f"""
            font-family: {FONT_FALLBACK};
            font-size: {SIZE_UI}px;
            font-weight: 700;
            color: {MANGO_DK};
        """)
        top.addWidget(lbl)
        top.addStretch()

        btn_reset = QPushButton("重置全部进度")
        btn_reset.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {CLAY};
                font-family: {FONT_FALLBACK};
                font-size: {SIZE_BODY}px;
                padding: {SP_1}px {SP_2}px;
                border: none;
            }}
            QPushButton:hover {{ color: #A55A4A; }}
        """)
        btn_reset.clicked.connect(self.reset_progress)
        top.addWidget(btn_reset)
        layout.addLayout(top)

        self.table_plan = QTableWidget()
        self.table_plan.setStyleSheet(AppStyles.TABLE)
        self.table_plan.setColumnCount(6)
        self.table_plan.setHorizontalHeaderLabels(["模块", "开始日期", "复习阶段", "下次复习", "状态", "操作"])
        self.table_plan.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table_plan.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        self.table_plan.setAlternatingRowColors(True)
        layout.addWidget(self.table_plan, 1)
        return view

    # ================= 数据刷新 =================

    def refresh_data(self):
        self._populate_day_list()
        self._refresh_due_banner()
        self.show_day(self.current_day)

    def _populate_day_list(self):
        self.day_list.blockSignals(True)
        self.day_list.clear()

        plan_item = QListWidgetItem("我的复习计划")
        plan_item.setData(Qt.ItemDataRole.UserRole, -1)
        self.day_list.addItem(plan_item)

        today = date.today()
        due_days = {d["day"] for d in self.engine.get_due_reviews(today)}
        for day in self.engine.get_days():
            no = day["day"]
            prog = self.engine.get_module_progress(no)
            if prog is None:
                icon = "⬜"
            elif prog["stage"] >= prog["total_stages"]:
                icon = "✅"
            elif prog["next_due"] and prog["next_due"] <= today.isoformat():
                icon = "🔔"
            else:
                icon = "🔄"
            item = QListWidgetItem(f"{icon} Day {no}  {day['title']}")
            item.setData(Qt.ItemDataRole.UserRole, no)
            self.day_list.addItem(item)

        self.day_list.blockSignals(False)
        target_row = 1 if self.current_day == -1 else self._find_day_row(self.current_day)
        self.day_list.setCurrentRow(max(target_row, 0))

    def _find_day_row(self, day_no):
        for i in range(self.day_list.count()):
            if self.day_list.item(i).data(Qt.ItemDataRole.UserRole) == day_no:
                return i
        return 1

    def _refresh_due_banner(self):
        due = self.engine.get_due_reviews()
        n = len(due)
        self.btn_due.setText(f"今日待复习（{n}）")
        self.btn_due.setVisible(n > 0)

    # ================= 导航 =================

    def on_day_selected(self, current, previous):
        if current is None:
            return
        role = current.data(Qt.ItemDataRole.UserRole)
        if role == -1:
            self.show_plan_view()
        else:
            self.show_day(role)

    def show_plan_view(self):
        self._populate_plan_table()
        self.detail_stack.setCurrentIndex(2)

    def back_to_detail(self):
        self.refresh_data()
        self.detail_stack.setCurrentIndex(0)

    def go_home(self):
        self.main_window.stack.setCurrentWidget(self.main_window.page_home)

    def show_day(self, day_no):
        if self.engine.get_day(day_no) is None:
            return
        self.current_day = day_no
        day = self.engine.get_day(day_no)
        entries = self.engine.get_day_entries(day_no)

        self.lbl_day_title.setText(f"Day {day_no} · {day['title']}")

        prog = self.engine.get_module_progress(day_no)
        if prog is None:
            self.lbl_day_progress.setText(f"共 {len(entries)} 个词条 · {len(day['categories'])} 个分类 · 未开始学习")
            self.btn_start_plan.setVisible(True)
        else:
            stage = prog["stage"]
            total = prog["total_stages"]
            if stage >= total:
                status = "已完成全部复习"
            else:
                status = f"下次复习：{prog['next_due']}"
            last_test = prog["last_test"]
            test_info = f" · 上次测验 {last_test['score']}/{last_test['total']}" if last_test else ""
            self.lbl_day_progress.setText(
                f"共 {len(entries)} 个词条 · 复习进度 {stage}/{total} · {status}{test_info}")
            self.btn_start_plan.setVisible(False)

        self.table_entries.setRowCount(len(entries))
        for row, e in enumerate(entries):
            self.table_entries.setItem(row, 0, QTableWidgetItem(e["text"]))
            self.table_entries.setItem(row, 1, QTableWidgetItem(e["pos"]))
            self.table_entries.setItem(row, 2, QTableWidgetItem(e["translation"]))
            self.table_entries.setItem(row, 3, QTableWidgetItem(e["category"]))

            btn_tts = QPushButton("🔊")
            btn_tts.setToolTip("听发音")
            btn_tts.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_tts.clicked.connect(lambda checked, t=e["text"]: self.main_window.tts.speak(t))
            self.table_entries.setCellWidget(row, 4, btn_tts)

        self.lbl_entry_count.setText(f"共 {len(entries)} 个词条")

    # ================= 学习计划 =================

    def start_module_plan(self):
        self.engine.start_module(self.current_day)
        self.refresh_data()
        QMessageBox.information(
            self, "已开始",
            f"Day {self.current_day} 学习计划已启动！\n\n"
            "将按艾宾浩斯遗忘曲线在第 1/2/4/7/15 天提醒复习。")

    def _populate_plan_table(self):
        modules = self.engine.progress.get("modules", {})
        today_str = date.today().isoformat()
        rows = []
        for key in sorted(modules, key=int):
            no = int(key)
            prog = self.engine.get_module_progress(no)
            if prog["stage"] >= prog["total_stages"]:
                status = "✅ 已完成"
            elif prog["next_due"] <= today_str:
                overdue = self._overdue_days(prog["next_due"])
                status = f"🔔 今日到期" if overdue == 0 else f"⏰ 已逾期 {overdue} 天"
            else:
                status = "⏳ 未到期"
            rows.append((no, prog))

        self.table_plan.setRowCount(len(rows))
        for row, (no, prog) in enumerate(rows):
            self.table_plan.setItem(row, 0, QTableWidgetItem(f"Day {no} {self.engine.get_day(no)['title']}"))
            self.table_plan.setItem(row, 1, QTableWidgetItem(prog["start_date"]))
            self.table_plan.setItem(row, 2, QTableWidgetItem(f"{prog['stage']}/{prog['total_stages']}"))
            due_text = prog["next_due"] if prog["next_due"] else "—"
            self.table_plan.setItem(row, 3, QTableWidgetItem(due_text))
            self.table_plan.setItem(row, 4, QTableWidgetItem(self._plan_status(prog)))

            ops = QWidget()
            ops_layout = QHBoxLayout(ops)
            ops_layout.setContentsMargins(2, 2, 2, 2)
            if prog["stage"] < prog["total_stages"] and prog["next_due"] and prog["next_due"] <= today_str:
                btn_done = QPushButton("完成复习")
                btn_done.setStyleSheet(f"""
                    QPushButton {{
                        font-family: {FONT_FALLBACK};
                        font-size: {SIZE_BODY}px;
                        padding: {SP_1}px {SP_2}px;
                        background: {LEAF};
                        color: white;
                        border: none;
                        border-radius: {RADIUS}px;
                        font-weight: 700;
                    }}
                    QPushButton:hover {{ background-color: #4A7A49; }}
                """)
                btn_done.clicked.connect(lambda checked, d=no: self.complete_review(d))
                ops_layout.addWidget(btn_done)
            btn_quiz = QPushButton("测验")
            btn_quiz.setStyleSheet(f"""
                QPushButton {{
                    font-family: {FONT_FALLBACK};
                    font-size: {SIZE_BODY}px;
                    padding: {SP_1}px {SP_2}px;
                    background: {DESK};
                    color: {INK};
                    border: 1px solid {DESK_LINE};
                    border-radius: {RADIUS}px;
                    font-weight: 600;
                }}
                QPushButton:hover {{ background-color: #D9D3C2; }}
            """)
            btn_quiz.clicked.connect(lambda checked, d=no: self.start_quiz_for_day(d))
            ops_layout.addWidget(btn_quiz)
            self.table_plan.setCellWidget(row, 5, ops)

    def _plan_status(self, prog):
        today_str = date.today().isoformat()
        if prog["stage"] >= prog["total_stages"]:
            return "✅ 已完成"
        if prog["next_due"] <= today_str:
            overdue = self._overdue_days(prog["next_due"])
            return "🔔 今日到期" if overdue == 0 else f"⏰ 已逾期 {overdue} 天"
        return "⏳ 未到期"

    def _overdue_days(self, due_str):
        try:
            due = date.fromisoformat(due_str)
            return (date.today() - due).days
        except ValueError:
            return 0

    def complete_review(self, day_no):
        self.engine.complete_review(day_no)
        self._populate_plan_table()
        self._populate_day_list()
        self._refresh_due_banner()

    def reset_progress(self):
        reply = QMessageBox.question(
            self, "确认重置",
            "将清除全部 28 天模块的学习与复习进度，确定继续吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self.engine.reset_all_progress()
            self.refresh_data()
            self.detail_stack.setCurrentIndex(0)

    # ================= 测验 =================

    def start_quiz(self):
        self.start_quiz_for_day(self.current_day)

    def start_quiz_for_day(self, day_no):
        count = self.combo_count.currentData() if day_no == self.current_day else 10
        mode = self.combo_mode.currentData() if day_no == self.current_day else "mixed"
        if day_no != self.current_day:
            self.show_day(day_no)

        questions = self.engine.generate_quiz(day_no, count=count, mode=mode)
        if not questions:
            QMessageBox.information(self, "提示", "该模块没有可生成测验的词条。")
            return

        self.quiz_day = day_no
        self.quiz_questions = questions
        self.quiz_index = 0
        self.quiz_score = 0
        self.detail_stack.setCurrentIndex(1)
        self._show_current_question()

    def _show_current_question(self):
        q = self.quiz_questions[self.quiz_index]
        total = len(self.quiz_questions)
        self.lbl_quiz_progress.setText(f"第 {self.quiz_index + 1}/{total} 题 · 得分 {self.quiz_score}")
        self.quiz_bar.setMaximum(total)
        self.quiz_bar.setValue(self.quiz_index)

        hint = "请选择正确的中文意思" if q["direction"] == "en2cn" else "请选择对应的英文"
        self.lbl_quiz_hint.setText(hint)
        self.lbl_quiz_question.setText(q["question"])

        for i, btn in enumerate(self.quiz_option_buttons):
            if i < len(q["options"]):
                btn.setText(q["options"][i])
                btn.setVisible(True)
                btn.setEnabled(True)
                btn.setStyleSheet(AppStyles.QUIZ_OPTION_BUTTON)
            else:
                btn.setVisible(False)
        self.lbl_quiz_feedback.setText("")

    def answer_quiz(self, idx):
        q = self.quiz_questions[self.quiz_index]
        correct = (idx == q["answer_index"])
        for i, btn in enumerate(self.quiz_option_buttons):
            btn.setEnabled(False)
            if q["options"][i] == q["options"][q["answer_index"]]:
                btn.setStyleSheet(AppStyles.QUIZ_CORRECT)
            elif i == idx:
                btn.setStyleSheet(AppStyles.QUIZ_WRONG)

        if correct:
            self.quiz_score += 1
            self.lbl_quiz_feedback.setText("回答正确！")
            self.lbl_quiz_feedback.setStyleSheet(f"""
                font-family: {FONT_FALLBACK};
                font-size: {SIZE_UI}px;
                font-weight: 700;
                color: {LEAF};
            """)
        else:
            answer = q["options"][q["answer_index"]]
            self.lbl_quiz_feedback.setText(f"正确答案：{answer}")
            self.lbl_quiz_feedback.setStyleSheet(f"""
                font-family: {FONT_FALLBACK};
                font-size: {SIZE_UI}px;
                font-weight: 700;
                color: {CLAY};
            """)

        QTimer.singleShot(900, self._quiz_next)

    def _quiz_next(self):
        self.quiz_index += 1
        if self.quiz_index < len(self.quiz_questions):
            self._show_current_question()
        else:
            self._quiz_finished()

    def _quiz_finished(self):
        total = len(self.quiz_questions)
        self.engine.record_test(self.quiz_day, self.quiz_score, total)
        self.quiz_bar.setValue(total)
        self.lbl_quiz_progress.setText(f"测验完成 · 得分 {self.quiz_score}/{total}")
        self.lbl_quiz_hint.setText("")
        self.lbl_quiz_question.setText(
            f"测验完成！\nDay {self.quiz_day} · {self.quiz_score}/{total} 正确")
        for btn in self.quiz_option_buttons:
            btn.setVisible(False)
        self.lbl_quiz_feedback.setText("")

    # ================= 卡片导出 =================

    def export_cards(self, fmt):
        day_no = self.current_day
        default_name = f"分类速记_Day{day_no}_记忆卡片.{fmt}"
        if fmt == "pdf":
            filter_ = "PDF 文件 (*.pdf)"
        else:
            filter_ = "Word 文档 (*.docx)"
        path, _ = QFileDialog.getSaveFileName(self, "保存记忆卡片", default_name, filter_)
        if not path:
            return
        try:
            if fmt == "pdf":
                self.engine.export_cards_pdf(day_no, path)
            else:
                self.engine.export_cards_docx(day_no, path)
            cards = len(self.engine.build_cards(day_no))
            pages = (cards + 1) // 2
            QMessageBox.information(
                self, "导出成功",
                f"已导出 Day {day_no} 记忆卡片：{cards} 张卡片（{pages} 页 A4）。\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "导出失败", f"生成卡片文件时出错：\n{e}")

    # ================= 跟读练习 =================

    def start_oral_practice(self):
        practice_list = self.engine.to_practice_list(self.current_day)
        if not practice_list:
            QMessageBox.information(self, "提示", "该模块没有可练习的词条。")
            return
        self.main_window.start_practice_with_list(practice_list)
