from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton, 
                             QLabel, QFileDialog, QTableWidget, QTableWidgetItem, QHeaderView, QCheckBox, QMessageBox, QLineEdit)
from src.core.content_parser import ContentParser
import os

class ImportDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Import Vocabulary")
        self.resize(600, 500)
        self.extracted_items = []
        
        self.setup_ui()
        
    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        # File Selection
        hbox = QHBoxLayout()
        self.lbl_file = QLabel("No file selected")
        btn_browse = QPushButton("Browse PDF...")
        btn_browse.clicked.connect(self.browse_file)
        hbox.addWidget(self.lbl_file)
        hbox.addWidget(btn_browse)
        layout.addLayout(hbox)
        
        # AI Option
        ai_layout = QHBoxLayout()
        self.chk_ai = QCheckBox("✨ Use AI Smart Parse")
        self.chk_ai.setChecked(False) # Default OFF, allow standard regex
        self.chk_ai.setToolTip("Uses local LLM to intelligently clean data.")
        
        self.txt_model = QLineEdit("qwen3-vl:4b")
        self.txt_model.setPlaceholderText("Model Name")
        self.txt_model.setToolTip("Ollama Model Tag (e.g. qwen3:4b or qwen3-vl:4b)")
        
        ai_layout.addWidget(self.chk_ai)
        ai_layout.addWidget(QLabel("Model:"))
        ai_layout.addWidget(self.txt_model)
        
        layout.addLayout(ai_layout)
        
        # Group Name Input
        group_layout = QHBoxLayout()
        group_layout.addWidget(QLabel("Data Source/Group (数据组):"))
        self.txt_group = QLineEdit()
        self.txt_group.setPlaceholderText("e.g. Grade 6 Textbook (六年级上册)")
        self.txt_group.setToolTip("Items will be tagged with this group name for easier management.")
        group_layout.addWidget(self.txt_group)
        layout.addLayout(group_layout)
        
        # Preview Table
        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["Word", "Phonetic", "Translation"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table)
        
        # Buttons
        btn_box = QHBoxLayout()
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        
        self.btn_import = QPushButton("Import Items")
        self.btn_import.clicked.connect(self.accept)
        self.btn_import.setEnabled(False)
        
        btn_box.addStretch()
        btn_box.addWidget(btn_cancel)
        btn_box.addWidget(self.btn_import)
        layout.addLayout(btn_box)
        
    def browse_file(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Open PDF", "", "PDF Files (*.pdf);;Text Files (*.txt)")
        if file_path:
            filename = os.path.basename(file_path)
            self.lbl_file.setText(filename)
            # Auto-fill group name with filename (minus extension)
            base_name = os.path.splitext(filename)[0]
            self.txt_group.setText(base_name)
            
            use_ai = self.chk_ai.isChecked()
            model_name = self.txt_model.text().strip()
            
            if use_ai:
                QMessageBox.information(self, "AI Processing", f"Using {model_name}...\nThis may take a minute.")
                from PyQt6.QtWidgets import QApplication
                QApplication.processEvents()
            
            try:
                self.extracted_items = ContentParser.parse_pdf(file_path, use_ai=use_ai, model_name=model_name)
                self.populate_table()
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Parsing failed: {e}")
            
    def populate_table(self):
        self.table.setRowCount(len(self.extracted_items))
        for row, item in enumerate(self.extracted_items):
            self.table.setItem(row, 0, QTableWidgetItem(item.get("text", "")))
            self.table.setItem(row, 1, QTableWidgetItem(item.get("phonetic", "")))
            self.table.setItem(row, 2, QTableWidgetItem(item.get("translation", "")))
            
        self.btn_import.setEnabled(len(self.extracted_items) > 0)
        
    def get_data(self):
        # Inject group tag
        group_name = self.txt_group.text().strip() or "Default"
        for item in self.extracted_items:
            item['group'] = group_name
        return self.extracted_items
