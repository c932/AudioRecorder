from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton, 
                             QLabel, QFileDialog, QTableWidget, QTableWidgetItem, QHeaderView, 
                             QCheckBox, QMessageBox, QLineEdit, QComboBox)
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt
from src.core.content_parser import ContentParser
from src.ui.styles import AppStyles, INK_SOFT
from src.utils import get_user_data_path
import os
import json

# Image file extensions supported for multimodal LLM analysis
IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.tif'}


class ImportDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Import Vocabulary")
        self.resize(600, 500)
        self.extracted_items = []
        self.config = self._load_config()
        
        self.setup_ui()
        self._restore_state()
        
    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        # File Selection
        hbox = QHBoxLayout()
        self.lbl_file = QLabel("No file selected")
        btn_browse = QPushButton("Browse File...")
        btn_browse.clicked.connect(self.browse_file)
        hbox.addWidget(self.lbl_file)
        hbox.addWidget(btn_browse)
        layout.addLayout(hbox)
        
        # Supported formats hint
        lbl_hint = QLabel("Supported: PDF, TXT, JPG, PNG, BMP, TIFF")
        lbl_hint.setStyleSheet(AppStyles.BODY_LABEL)
        layout.addWidget(lbl_hint)
        
        # AI Option
        ai_layout = QHBoxLayout()
        self.chk_ai = QCheckBox("✨ Use AI Smart Parse")
        self.chk_ai.setToolTip("Uses local LLM to intelligently clean data. For images, uses multimodal model.")
        self.chk_ai.toggled.connect(self._save_ai_state)
        
        # Model dropdown (editable QComboBox, reads from settings)
        self.combo_model = QComboBox()
        self.combo_model.setEditable(True)
        self.combo_model.setMinimumWidth(180)
        self.combo_model.setToolTip("Model name for AI parsing. Reads from Settings, or type a custom model.")
        self._populate_model_combo()
        
        ai_layout.addWidget(self.chk_ai)
        ai_layout.addWidget(QLabel("Model:"))
        ai_layout.addWidget(self.combo_model)
        
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
    
    def _load_config(self):
        """Load config.json for LLM provider settings."""
        config_path = get_user_data_path("config.json")
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r') as f:
                    return json.load(f)
            except Exception as e:
                print(f"[ImportDialog] Failed to load config: {e}")
        return {}
    
    def _save_config(self):
        """Save config.json."""
        config_path = get_user_data_path("config.json")
        try:
            with open(config_path, 'w') as f:
                json.dump(self.config, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"[ImportDialog] Failed to save config: {e}")
    
    def _populate_model_combo(self):
        """Populate model dropdown based on current AI provider in settings."""
        self.combo_model.clear()
        
        provider = self.config.get("ai_provider", "")
        current_model = ""
        
        if "Custom" in provider:
            current_model = self.config.get("custom_model", "")
        elif "Ollama" in provider:
            current_model = self.config.get("ollama_model", "qwen3:4b")
        elif "OpenAI" in provider:
            current_model = self.config.get("openai_model", "gpt-4o")
        
        # Add current configured model as first item
        if current_model:
            self.combo_model.addItem(current_model)
        
        # Add some common alternatives for quick selection
        common_models = ["qwen3:4b", "qwen3-vl:4b", "gpt-4o", "llama3"]
        for m in common_models:
            if m != current_model and self.combo_model.findText(m) == -1:
                self.combo_model.addItem(m)
        
        # Select the current model
        if current_model:
            idx = self.combo_model.findText(current_model)
            if idx >= 0:
                self.combo_model.setCurrentIndex(idx)
    
    def _restore_state(self):
        """Restore AI checkbox state from config."""
        self.chk_ai.setChecked(self.config.get("import_use_ai", True))
    
    def _save_ai_state(self, checked):
        """Save AI checkbox state to config immediately."""
        self.config["import_use_ai"] = checked
        self._save_config()
        
    def browse_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Open File", "",
            "All Supported (*.pdf *.txt *.jpg *.jpeg *.png *.bmp *.tiff *.tif);;"
            "PDF Files (*.pdf);;"
            "Text Files (*.txt);;"
            "Images (*.jpg *.jpeg *.png *.bmp *.tiff *.tif)"
        )
        if not file_path:
            return
        
        filename = os.path.basename(file_path)
        self.lbl_file.setText(filename)
        # Auto-fill group name with filename (minus extension)
        base_name = os.path.splitext(filename)[0]
        self.txt_group.setText(base_name)
        
        # Determine file type
        ext = os.path.splitext(file_path)[1].lower()
        is_image = ext in IMAGE_EXTS
        use_ai = self.chk_ai.isChecked()
        config = self._load_config()
        
        # For images, AI is always required (multimodal LLM)
        if is_image:
            use_ai = True
            QMessageBox.information(self, "Image Analysis", 
                f"Analyzing image with multimodal LLM...\n"
                f"This may take a moment depending on image size and model speed.")
            QApplication.processEvents()
            
            try:
                self.extracted_items = ContentParser.parse_image(file_path, config=config)
                self.populate_table()
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Image analysis failed:\n{e}")
            return
        
        # PDF / TXT
        model_name = self.combo_model.currentText().strip()
        
        if use_ai:
            QMessageBox.information(self, "AI Processing", f"Using {model_name}...\nThis may take a minute.")
            QApplication.processEvents()
        
        try:
            self.extracted_items = ContentParser.parse_pdf(
                file_path, 
                use_ai=use_ai, 
                config=config,
                model_name=model_name
            )
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
