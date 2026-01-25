from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, 
                             QTableWidgetItem, QPushButton, QHeaderView, QLabel, QMessageBox, QCheckBox)
from PyQt6.QtCore import Qt
import random

class MistakePage(QWidget):
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window # Reference to main window to trigger practice
        self.manager = main_window.exercise_manager
        
        self.setup_ui()
        
    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        # Header
        header_layout = QHBoxLayout()
        btn_back = QPushButton("⬅ Back")
        btn_back.clicked.connect(self.go_home)
        header_layout.addWidget(btn_back)
        
        lbl_title = QLabel("Mistake Review (错题本)")
        lbl_title.setStyleSheet("font-size: 20px; font-weight: bold; color: #D32F2F;")
        header_layout.addWidget(lbl_title)
        header_layout.addStretch()
        layout.addLayout(header_layout)
        
        # Filter (Optional, maybe score threshold?)
        # For now just list all < 90?
        
        # Table
        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(["Word", "Group", "Last Score", "Practiced", "Action", "Listen"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table)
        
        # Bottom Actions
        btn_box = QHBoxLayout()
        
        self.chk_shuffle = QCheckBox("Shuffle (打乱顺序)")
        self.chk_shuffle.setChecked(True)
        # Fix: Ensure text and indicator are visible against background
        self.chk_shuffle.setStyleSheet("QCheckBox { font-size: 16px; color: #333; }")
        btn_box.addWidget(self.chk_shuffle)
        
        btn_review_all = QPushButton("Review ALL Mistakes (复习所有错题)")
        btn_review_all.setStyleSheet("background-color: #D32F2F; color: white; padding: 10px; font-weight: bold;")
        btn_review_all.clicked.connect(self.start_review_all)
        btn_box.addWidget(btn_review_all)
        
        layout.addLayout(btn_box)
        
    def refresh_data(self):
        # 1. Gather all mistakes
        all_words = self.manager.exercises.get("words", [])
        all_sentences = self.manager.exercises.get("sentences", [])
        full_list = all_words + all_sentences
        
        # Condition: last_score < 90 AND has been practiced at least once
        self.mistakes = [
            item for item in full_list 
            if item.get('times_practiced', 0) > 0 and item.get('last_score', 0) < 90
        ]
        
        # Sort by score ascending (worst first)
        self.mistakes.sort(key=lambda x: x.get('last_score', 0))
        
        self.populate_table()
        
    def populate_table(self):
        self.table.setRowCount(len(self.mistakes))
        for row, item in enumerate(self.mistakes):
            self.table.setItem(row, 0, QTableWidgetItem(item.get("text", "")))
            self.table.setItem(row, 1, QTableWidgetItem(item.get("group", "Default")))
            
            score_item = QTableWidgetItem(str(item.get("last_score", 0)))
            score_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if item.get("last_score", 0) < 60:
                score_item.setForeground(Qt.GlobalColor.red)
            self.table.setItem(row, 2, score_item)
            
            count_item = QTableWidgetItem(str(item.get("times_practiced", 0)))
            count_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 3, count_item)
            
            # Action Button: Practice
            btn_practice = QPushButton("Practice")
            btn_practice.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_practice.clicked.connect(lambda checked, i=item: self.practice_single(i))
            self.table.setCellWidget(row, 4, btn_practice)

            # Action Button: TTS (New)
            btn_tts = QPushButton("🔊")
            btn_tts.setToolTip("Listen to Standard Pronunciation")
            btn_tts.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_tts.clicked.connect(lambda checked, i=item: self.play_tts(i))
            self.table.setCellWidget(row, 5, btn_tts)
            
    def play_tts(self, item):
        text = item.get("text", "")
        if text:
            self.main_window.tts.speak(text)
            
    def go_home(self):
        self.main_window.stack.setCurrentWidget(self.main_window.page_home)
        
    def practice_single(self, item):
        # Start practice with just this one item
        self.main_window.start_practice_with_list([item])
        
    def start_review_all(self):
        if not self.mistakes:
            QMessageBox.information(self, "No Mistakes", "Good job! No mistakes found.")
            return
            
        review_list = self.mistakes[:]
        if self.chk_shuffle.isChecked():
            random.shuffle(review_list)
            
        self.main_window.start_practice_with_list(review_list)
