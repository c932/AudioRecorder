"""
QuizPage - Translation quiz UI with setup, quiz, and result views.
"""
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
                             QLabel, QStackedWidget, QComboBox, QCheckBox,
                             QLineEdit, QProgressBar, QScrollArea,
                             QFrame, QMessageBox, QGroupBox, QSpinBox)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont
from src.ui.styles import (AppStyles, FONT_FALLBACK, PAPER, DESK, INK,
                            INK_SOFT, MANGO, MANGO_DK, LEAF, CLAY,
                            LEAF_SOFT, CLAY_SOFT, DESK_LINE,
                            SP_3, SP_4, SP_5, RADIUS,
                            SIZE_BODY, SIZE_UI, SIZE_TITLE, SIZE_SECTION)
from src.core.quiz_engine import QuizEngine


class QuizPage(QWidget):
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self.quiz_engine = QuizEngine(main_window.exercise_manager)
        
        # Connect signals
        self.quiz_engine.questions_ready.connect(self._on_questions_ready)
        self.quiz_engine.generation_error.connect(self._on_generation_error)
        self.quiz_engine.progress_update.connect(self._on_progress_update)
        
        self.current_question_idx = 0
        self.questions = []
        
        self.setup_ui()
    
    def setup_ui(self):
        self.layout = QVBoxLayout(self)

        # Page background
        self.setStyleSheet(f"background-color: {PAPER};")

        self.inner_stack = QStackedWidget()
        self.layout.addWidget(self.inner_stack)
        
        # Create three views
        self.setup_view = self._create_setup_view()
        self.quiz_view = self._create_quiz_view()
        self.result_view = self._create_result_view()
        
        self.inner_stack.addWidget(self.setup_view)
        self.inner_stack.addWidget(self.quiz_view)
        self.inner_stack.addWidget(self.result_view)
    
    # ========== SETUP VIEW ==========
    def _create_setup_view(self):
        page = QWidget()
        page.setStyleSheet(f"background-color: {PAPER};")
        layout = QVBoxLayout(page)
        
        # Top bar
        top_bar = QHBoxLayout()
        btn_back = QPushButton("Back")
        btn_back.clicked.connect(self._go_home)
        btn_back.setStyleSheet(AppStyles.GHOST_BUTTON)
        top_bar.addWidget(btn_back)
        top_bar.addStretch()
        layout.addLayout(top_bar)
        
        layout.addStretch()
        
        # Title
        title = QLabel("📝 中英互译练习")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(AppStyles.HEADER_LABEL)
        layout.addWidget(title)
        
        layout.addSpacing(20)
        
        # Quiz bank selector
        bank_group = QGroupBox("选择题库")
        bank_group.setStyleSheet(AppStyles.GROUP_BOX)
        bank_layout = QVBoxLayout(bank_group)
        
        combo_row = QHBoxLayout()
        self.combo_bank = QComboBox()
        self.combo_bank.setStyleSheet(AppStyles.INPUT + f"\nQComboBox {{ min-width: 300px; }}")
        self.combo_bank.currentIndexChanged.connect(self._on_bank_selected)
        combo_row.addWidget(self.combo_bank, 1)
        bank_layout.addLayout(combo_row)
        
        # Bank details label
        self.lbl_bank_details = QLabel("")
        self.lbl_bank_details.setWordWrap(True)
        self.lbl_bank_details.setStyleSheet(f"font-family: {FONT_FALLBACK}; font-size: {SIZE_BODY}px; color: {INK_SOFT}; padding: 5px; background: {DESK}; border-radius: {RADIUS}px;")
        self.lbl_bank_details.setVisible(False)
        bank_layout.addWidget(self.lbl_bank_details)
        
        layout.addWidget(bank_group)
        
        layout.addSpacing(10)
        
        # Question count selector
        count_group = QGroupBox("题目数量")
        count_group.setStyleSheet(AppStyles.GROUP_BOX)
        count_layout = QHBoxLayout(count_group)
        count_layout.addWidget(QLabel("抽取:"))
        self.spin_count = QSpinBox()
        self.spin_count.setRange(1, 200)
        self.spin_count.setValue(10)
        self.spin_count.setStyleSheet(AppStyles.INPUT)
        self.spin_count.setToolTip("从题库中抽取的题目数量")
        count_layout.addWidget(self.spin_count)
        count_layout.addWidget(QLabel("题"))
        
        self.chk_all = QCheckBox("全部")
        self.chk_all.setStyleSheet(AppStyles.CHECKBOX)
        self.chk_all.toggled.connect(self._on_all_toggled)
        count_layout.addWidget(self.chk_all)
        count_layout.addStretch()
        layout.addWidget(count_group)
        
        layout.addSpacing(15)
        
        # Start button
        self.btn_start = QPushButton("开始测验")
        self.btn_start.setStyleSheet(AppStyles.BIG_BUTTON)
        self.btn_start.clicked.connect(self._start_quiz)
        self.btn_start.setEnabled(False)
        layout.addWidget(self.btn_start, alignment=Qt.AlignmentFlag.AlignCenter)
        
        # Empty state hint
        self.lbl_empty_hint = QLabel("暂无题库，请在设置 > 题库页生成")
        self.lbl_empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_empty_hint.setStyleSheet(f"font-family: {FONT_FALLBACK}; font-size: {SIZE_UI}px; color: {CLAY}; padding: 15px; background: {CLAY_SOFT}; border-radius: {RADIUS}px;")
        self.lbl_empty_hint.setVisible(False)
        layout.addWidget(self.lbl_empty_hint)
        
        layout.addStretch()
        return page
    
    # ========== QUIZ VIEW ==========
    def _create_quiz_view(self):
        page = QWidget()
        page.setStyleSheet(f"background-color: {PAPER};")
        layout = QVBoxLayout(page)
        
        # Top bar
        top_bar = QHBoxLayout()
        btn_quit = QPushButton("Quit")
        btn_quit.clicked.connect(self._confirm_quit)
        btn_quit.setStyleSheet(AppStyles.CARD_BUTTON)
        top_bar.addWidget(btn_quit)
        
        self.lbl_progress = QLabel("1/10")
        self.lbl_progress.setStyleSheet(f"font-family: {FONT_FALLBACK}; font-size: {SIZE_UI}px; font-weight: bold; color: {MANGO_DK};")
        top_bar.addWidget(self.lbl_progress)
        top_bar.addStretch()
        layout.addLayout(top_bar)
        
        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setStyleSheet(AppStyles.QUIZ_PROGRESS_BAR)
        self.progress_bar.setMaximum(100)
        layout.addWidget(self.progress_bar)
        
        layout.addSpacing(10)
        
        # Question type indicator
        self.lbl_type = QLabel("中英互译")
        self.lbl_type.setStyleSheet(f"font-family: {FONT_FALLBACK}; font-size: {SIZE_BODY}px; color: {PAPER}; background: {MANGO}; padding: 5px; border-radius: {RADIUS}px;")
        self.lbl_type.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.lbl_type)
        
        # Question display area
        self.lbl_question = QLabel("")
        self.lbl_question.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_question.setStyleSheet(f"font-family: {FONT_FALLBACK}; font-size: {SIZE_SECTION}px; font-weight: bold; color: {INK}; padding: 20px;")
        self.lbl_question.setWordWrap(True)
        layout.addWidget(self.lbl_question)
        
        # Chinese hint (for fill-in-blank)
        self.lbl_hint = QLabel("")
        self.lbl_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_hint.setStyleSheet(f"font-family: {FONT_FALLBACK}; font-size: {SIZE_TITLE}px; color: {INK_SOFT};")
        self.lbl_hint.setWordWrap(True)
        layout.addWidget(self.lbl_hint)
        
        layout.addSpacing(10)
        
        # Answer input area (zh2en: dynamic input boxes)
        self.input_container = QWidget()
        self.input_container_layout = QVBoxLayout(self.input_container)
        self.input_container_layout.setContentsMargins(0, 0, 0, 0)
        self.input_container_layout.setSpacing(8)
        self.answer_inputs = []  # Will be populated dynamically
        layout.addWidget(self.input_container)
        
        self.btn_submit = QPushButton("提交")
        self.btn_submit.setStyleSheet(AppStyles.BIG_BUTTON)
        self.btn_submit.clicked.connect(self._submit_text_answer)
        layout.addWidget(self.btn_submit)
        
        # Answer options area (en2zh: 4 buttons)
        self.option_buttons = []
        self.option_container = QWidget()
        opt_layout = QVBoxLayout(self.option_container)
        opt_layout.setSpacing(8)
        for i in range(4):
            btn = QPushButton("")
            btn.setStyleSheet(AppStyles.QUIZ_OPTION_BUTTON)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda checked, idx=i: self._submit_choice(idx))
            opt_layout.addWidget(btn)
            self.option_buttons.append(btn)
        layout.addWidget(self.option_container)
        
        # Feedback label
        self.lbl_feedback = QLabel("")
        self.lbl_feedback.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_feedback.setStyleSheet(f"font-family: {FONT_FALLBACK}; font-size: {SIZE_TITLE}px; font-weight: bold; padding: 10px;")
        self.lbl_feedback.setVisible(False)
        layout.addWidget(self.lbl_feedback)
        
        # Next button (hidden until answered)
        self.btn_next = QPushButton("下一题")
        self.btn_next.setStyleSheet(AppStyles.BIG_BUTTON)
        self.btn_next.clicked.connect(self._next_question)
        self.btn_next.setVisible(False)
        layout.addWidget(self.btn_next)
        
        return page
    
    # ========== RESULT VIEW ==========
    def _create_result_view(self):
        page = QWidget()
        page.setStyleSheet(f"background-color: {PAPER};")
        layout = QVBoxLayout(page)
        
        # Title
        title = QLabel("测验完成！")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(f"font-family: {FONT_FALLBACK}; font-size: {SIZE_SECTION}px; font-weight: bold; color: {MANGO_DK}; margin: 10px;")
        layout.addWidget(title)
        
        # Scroll area for results
        scroll = QScrollArea()
        scroll.setStyleSheet(AppStyles.SCROLL_AREA)
        scroll.setWidgetResizable(True)
        self.result_scroll_content = QWidget()
        self.result_scroll_layout = QVBoxLayout(self.result_scroll_content)
        scroll.setWidget(self.result_scroll_content)
        layout.addWidget(scroll)
        
        # Buttons
        btn_layout = QHBoxLayout()
        
        btn_home = QPushButton("返回首页")
        btn_home.setStyleSheet(AppStyles.BIG_BUTTON)
        btn_home.clicked.connect(self._go_home)
        btn_layout.addWidget(btn_home)
        
        btn_retry = QPushButton("再来一次")
        btn_retry.setStyleSheet(AppStyles.BIG_BUTTON)
        btn_retry.clicked.connect(self._retry_quiz)
        btn_layout.addWidget(btn_retry)
        
        layout.addLayout(btn_layout)
        return page
    
    # ========== NAVIGATION & LOGIC ==========
    def reset_to_setup(self):
        """Reset page to setup view and refresh quiz bank list."""
        self._refresh_bank_combo()
        self.inner_stack.setCurrentWidget(self.setup_view)
    
    def _refresh_bank_combo(self):
        """Refresh the quiz bank combo box from saved data."""
        self.combo_bank.blockSignals(True)
        self.combo_bank.clear()
        
        banks = self.quiz_engine.get_all_banks()
        
        if not banks:
            self.combo_bank.addItem("（暂无题库）", None)
            self.combo_bank.setEnabled(False)
            self.btn_start.setEnabled(False)
            self.lbl_empty_hint.setVisible(True)
            self.lbl_bank_details.setVisible(False)
        else:
            self.combo_bank.setEnabled(True)
            self.lbl_empty_hint.setVisible(False)
            for bank in banks:
                name = bank.get("name", "未命名")
                count = bank.get("question_count", 0)
                label = f"{name}  [{count} 题]"
                self.combo_bank.addItem(label, bank.get("id"))
            self._on_bank_selected(0)  # Show details for first bank
        
        self.combo_bank.blockSignals(False)
    
    def _on_bank_selected(self, index):
        """Show details for the selected bank."""
        bank_id = self.combo_bank.currentData()
        if not bank_id:
            self.lbl_bank_details.setVisible(False)
            self.btn_start.setEnabled(False)
            return
        
        # Find the bank data
        banks = self.quiz_engine.get_all_banks()
        bank = None
        for b in banks:
            if b.get("id") == bank_id:
                bank = b
                break
        
        if bank:
            groups_str = ", ".join(bank.get("source_groups", []))
            created = bank.get("created_at", "")
            try:
                from datetime import datetime
                dt = datetime.fromisoformat(created)
                created = dt.strftime("%Y-%m-%d %H:%M")
            except Exception:
                pass
            
            # Count question types
            questions = bank.get("questions", [])
            zh2en = sum(1 for q in questions if q.get("type") == "zh2en")
            en2zh = sum(1 for q in questions if q.get("type") == "en2zh")
            
            details = (
                f"来源分组: {groups_str}\n"
                f"创建时间: {created}\n"
                f"题目: {len(questions)} 道（中译英: {zh2en}，英译中: {en2zh}）"
            )
            self.lbl_bank_details.setText(details)
            self.lbl_bank_details.setVisible(True)
            self.btn_start.setEnabled(True)
            
            # Update spinbox max
            self.spin_count.setMaximum(len(questions))
            if self.spin_count.value() > len(questions):
                self.spin_count.setValue(len(questions))
        else:
            self.lbl_bank_details.setVisible(False)
            self.btn_start.setEnabled(False)
    
    def _go_home(self):
        self.main_window.stack.setCurrentWidget(self.main_window.page_home)
    
    def _open_settings(self):
        """Open Settings dialog to manage active groups."""
        self.main_window.open_settings()
        # Refresh groups display after settings close
        self.reset_to_setup()
    
    def _on_all_toggled(self, checked):
        """Toggle between using all questions or a specific count."""
        self.spin_count.setEnabled(not checked)
    
    def _start_quiz(self):
        """Start quiz from selected bank with optional count limit."""
        bank_id = self.combo_bank.currentData()
        if not bank_id:
            QMessageBox.warning(self, "错误", "请先选择题库。")
            return
        
        # Get question count
        if self.chk_all.isChecked():
            count = 0  # 0 = all
        else:
            count = self.spin_count.value()
        
        self.btn_start.setEnabled(False)
        self.quiz_engine.start_quiz_from_bank(bank_id, count)
    
    def start_review_quiz(self, questions):
        """Start a review quiz with pre-built question list (from mistake review). Skips setup view."""
        if not questions:
            QMessageBox.warning(self, "错误", "没有可复习的题目。")
            return
        self.quiz_engine.start_quiz_with_questions(questions)
    
    def _on_progress_update(self, generated, total):
        # No longer needed for bank-based quizzes (kept for compatibility)
        pass
    
    def _on_questions_ready(self, questions):
        self.questions = questions
        self.current_question_idx = 0
        
        if not questions:
            QMessageBox.warning(self, "错误", "没有生成任何题目。")
            self.btn_start.setEnabled(True)
            return
        
        # Switch to quiz view
        self.inner_stack.setCurrentWidget(self.quiz_view)
        self._show_question()
    
    def _on_generation_error(self, error_msg):
        self.btn_start.setEnabled(True)
        QMessageBox.critical(self, "错误", f"测验失败：\n{error_msg}")
    
    def _show_question(self):
        """Display the current question."""
        if self.current_question_idx >= len(self.questions):
            self._show_results()
            return
        
        q = self.questions[self.current_question_idx]
        total = len(self.questions)
        current = self.current_question_idx + 1
        
        # Update progress
        self.lbl_progress.setText(f"{current}/{total}")
        self.progress_bar.setValue(int(current / total * 100))
        
        # Reset UI state
        self.lbl_feedback.setVisible(False)
        self.btn_next.setVisible(False)
        self.btn_submit.setEnabled(True)
        
        # Clear dynamic input boxes
        self._clear_answer_inputs()
        
        # Reset option button styles
        for btn in self.option_buttons:
            btn.setStyleSheet(AppStyles.QUIZ_OPTION_BUTTON)
            btn.setEnabled(True)
        
        if q["type"] == "zh2en":
            # Chinese to English
            self.lbl_type.setText("中译英 - 拼写/填空")
            self.lbl_type.setStyleSheet(f"font-family: {FONT_FALLBACK}; font-size: {SIZE_BODY}px; color: {PAPER}; background: {MANGO_DK}; padding: 5px; border-radius: {RADIUS}px;")
            self.lbl_question.setText(q["question_text"])
            
            if q.get("chinese_hint"):
                self.lbl_hint.setText(f"提示: {q['chinese_hint']}")
                self.lbl_hint.setVisible(True)
            else:
                self.lbl_hint.setVisible(False)
            
            # Create N input boxes based on answers count
            answers = q.get("answers", [])
            num_blanks = max(1, len(answers))
            self._create_answer_inputs(num_blanks)
            
            # Show input container, hide options
            self.input_container.setVisible(True)
            self.btn_submit.setVisible(True)
            self.option_container.setVisible(False)
            if self.answer_inputs:
                self.answer_inputs[0].setFocus()
            
        else:
            # English to Chinese - multiple choice
            self.lbl_type.setText("英译中 - 选择题")
            self.lbl_type.setStyleSheet(f"font-family: {FONT_FALLBACK}; font-size: {SIZE_BODY}px; color: {PAPER}; background: {LEAF}; padding: 5px; border-radius: {RADIUS}px;")
            self.lbl_question.setText(q["question_text"])
            self.lbl_hint.setVisible(False)
            
            # Hide text input, show options
            self.input_container.setVisible(False)
            self.btn_submit.setVisible(False)
            self.option_container.setVisible(True)
            
            for i, btn in enumerate(self.option_buttons):
                if i < len(q.get("options", [])):
                    btn.setText(f"  {chr(65+i)}. {q['options'][i]}")
                    btn.setVisible(True)
                else:
                    btn.setVisible(False)
    
    def _clear_answer_inputs(self):
        """Remove all dynamic answer input widgets."""
        for inp in self.answer_inputs:
            inp.setParent(None)
            inp.deleteLater()
        self.answer_inputs.clear()
    
    def _create_answer_inputs(self, n: int):
        """Create n input boxes for fill-in-the-blank."""
        self._clear_answer_inputs()
        for i in range(n):
            inp = QLineEdit()
            inp.setStyleSheet(AppStyles.QUIZ_INPUT)
            inp.setPlaceholderText(f"第{i+1}空...")
            inp.returnPressed.connect(self._submit_text_answer)
            self.input_container_layout.addWidget(inp)
            self.answer_inputs.append(inp)
    
    def _submit_text_answer(self):
        """Handle text answer submission for zh2en."""
        if self.current_question_idx >= len(self.questions):
            return
        
        q = self.questions[self.current_question_idx]
        
        # Collect answers from all input boxes
        if len(self.answer_inputs) == 1:
            user_answer = self.answer_inputs[0].text().strip()
        else:
            user_answer = [inp.text().strip() for inp in self.answer_inputs]
        
        is_correct = self.quiz_engine.validate_answer(q, user_answer)
        self.quiz_engine.record_result(q, is_correct, user_answer)
        
        # Determine correct answer text for display
        answers = q.get("answers", [])
        if answers:
            correct_display = " / ".join(answers)
        else:
            correct_display = q.get("answer", "")
        
        # Show feedback
        self._show_answer_feedback(is_correct, correct_display)
        
        # Disable inputs
        for inp in self.answer_inputs:
            inp.setEnabled(False)
        self.btn_submit.setEnabled(False)
    
    def _submit_choice(self, index):
        """Handle multiple-choice selection for en2zh."""
        if self.current_question_idx >= len(self.questions):
            return
        
        q = self.questions[self.current_question_idx]
        selected_text = q["options"][index] if index < len(q["options"]) else ""
        
        is_correct = (index == q["correct_index"])
        self.quiz_engine.record_result(q, is_correct, selected_text)
        
        # Highlight correct/wrong
        for i, btn in enumerate(self.option_buttons):
            btn.setEnabled(False)
            if i == q["correct_index"]:
                btn.setStyleSheet(AppStyles.QUIZ_CORRECT)
            elif i == index and not is_correct:
                btn.setStyleSheet(AppStyles.QUIZ_WRONG)
        
        # Show feedback
        correct_answer = q["answer"]
        self._show_answer_feedback(is_correct, correct_answer)
    
    def _show_answer_feedback(self, is_correct, correct_answer):
        """Show correct/wrong feedback."""
        self.lbl_feedback.setVisible(True)
        self.btn_next.setVisible(True)
        
        if is_correct:
            self.lbl_feedback.setText("✅ 正确！")
            self.lbl_feedback.setStyleSheet(f"font-family: {FONT_FALLBACK}; font-size: {SIZE_TITLE}px; font-weight: bold; padding: 10px; color: {LEAF}; background: {LEAF_SOFT}; border-radius: {RADIUS}px;")
            # Auto advance after 1.5s for correct answers
            QTimer.singleShot(1500, self._auto_next)
        else:
            self.lbl_feedback.setText(f"❌ 错误！正确答案: {correct_answer}")
            self.lbl_feedback.setStyleSheet(f"font-family: {FONT_FALLBACK}; font-size: {SIZE_TITLE}px; font-weight: bold; padding: 10px; color: {CLAY}; background: {CLAY_SOFT}; border-radius: {RADIUS}px;")
            self.lbl_feedback.setWordWrap(True)
            # Auto advance after 5s for wrong answers (give time to study)
            QTimer.singleShot(5000, self._auto_next)
    
    def _auto_next(self):
        """Auto-advance to next question if still on same question."""
        if self.btn_next.isVisible():
            self._next_question()
    
    def _next_question(self):
        self.btn_next.setVisible(False)
        self.current_question_idx += 1
        self._show_question()
    
    def _confirm_quit(self):
        reply = QMessageBox.question(
            self, "退出测验",
            "退出并将已答题的错题保存到错题库？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            # Save already-recorded results to disk (record_result already updated stats)
            if self.quiz_engine.session_results:
                wrong_count = sum(1 for r in self.quiz_engine.session_results if not r["is_correct"])
                self.quiz_engine.save_results()
                if wrong_count > 0:
                    QMessageBox.information(self, "已保存", f"{wrong_count} 道错题已保存到错题库")
            
            self._go_home()
    
    def _show_results(self):
        """Display quiz results."""
        # Save to disk
        self.quiz_engine.save_results()
        
        summary = self.quiz_engine.get_session_summary()
        
        # Clear previous results
        for i in reversed(range(self.result_scroll_layout.count())):
            item = self.result_scroll_layout.itemAt(i)
            if item.widget():
                item.widget().setParent(None)
            else:
                self.result_scroll_layout.removeItem(item)
        
        # Score card
        score_pct = summary["score_pct"]
        if score_pct >= 90:
            emoji, color = "🏆", LEAF
        elif score_pct >= 70:
            emoji, color = "👍", MANGO_DK
        else:
            emoji, color = "💪", CLAY

        score_label = QLabel(f"{emoji} 得分: {summary['correct']}/{summary['total']} ({score_pct:.0f}%)")
        score_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        score_label.setStyleSheet(f"font-family: {FONT_FALLBACK}; font-size: {SIZE_SECTION}px; font-weight: bold; color: {color}; padding: 15px; border: 2px dashed {color}; border-radius: {RADIUS}px;")
        self.result_scroll_layout.addWidget(score_label)
        
        # Breakdown by type
        breakdown = QLabel(
            f"中译英: {summary['zh2en_correct']}/{summary['zh2en_total']}    "
            f"英译中: {summary['en2zh_correct']}/{summary['en2zh_total']}"
        )
        breakdown.setAlignment(Qt.AlignmentFlag.AlignCenter)
        breakdown.setStyleSheet(f"font-family: {FONT_FALLBACK}; font-size: {SIZE_TITLE}px; color: {INK_SOFT}; padding: 10px;")
        self.result_scroll_layout.addWidget(breakdown)
        
        # Wrong answers
        wrong_items = summary.get("wrong_items", [])
        if wrong_items:
            wrong_header = QLabel(f"错题: {len(wrong_items)} 道")
            wrong_header.setStyleSheet(f"font-family: {FONT_FALLBACK}; font-size: {SIZE_TITLE}px; font-weight: bold; color: {CLAY}; margin-top: 15px;")
            self.result_scroll_layout.addWidget(wrong_header)
            
            for r in wrong_items:
                q = r["question"]
                card = QFrame()
                card.setStyleSheet(f"background: {PAPER}; border-radius: {RADIUS}px; border-left: 6px solid {CLAY}; padding: 8px; margin: 3px;")
                card_layout = QVBoxLayout(card)
                
                # Question info
                q_type = "中译英" if q["type"] == "zh2en" else "英译中"
                q_text = q.get("question_text", "")
                card_layout.addWidget(QLabel(f"[{q_type}] {q_text}"))
                
                # Your answer vs correct
                your_ans = r.get("user_answer", "")
                answers_arr = q.get("answers", [])
                correct_ans = " / ".join(answers_arr) if answers_arr else q.get("answer", "")
                
                your_label = QLabel(f"你的答案: {your_ans}")
                your_label.setStyleSheet(f"font-family: {FONT_FALLBACK}; color: {CLAY};")
                card_layout.addWidget(your_label)
                
                correct_label = QLabel(f"正确答案: {correct_ans}")
                correct_label.setStyleSheet(f"font-family: {FONT_FALLBACK}; color: {LEAF}; font-weight: bold;")
                card_layout.addWidget(correct_label)
                
                self.result_scroll_layout.addWidget(card)
        
        self.result_scroll_layout.addStretch()
        self.inner_stack.setCurrentWidget(self.result_view)
    
    def _retry_quiz(self):
        """Retry: go back to setup and start from same bank."""
        self.reset_to_setup()
