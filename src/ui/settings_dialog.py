from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton, 
                             QLabel, QComboBox, QLineEdit, QGroupBox, QFormLayout, QMessageBox, QStackedWidget, QWidget, QSpinBox,
                             QListWidget, QListWidgetItem, QCheckBox)
from PyQt6.QtCore import Qt
from src.core.audio_recorder import AudioRecorder
import os
import json

class SettingsDialog(QDialog):
    def __init__(self, parent=None, audio_recorder=None, exercise_manager=None):
        super().__init__(parent)
        self.setWindowTitle("Settings 设置")
        self.resize(500, 400)
        self.recorder = audio_recorder or AudioRecorder()
        # Use passed manager or create temporary (though creation here is risky for sync, better to always pass)
        if exercise_manager:
            self.manager = exercise_manager
        else:
            from src.core.exercise_manager import ExerciseManager
            self.manager = ExerciseManager("src/data/words.json")
            
        self.config_file = "config.json"
        
        self.setup_ui()
        self.load_settings()
        
    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        # Audio Section
        grp_audio = QGroupBox("Audio Settings 音频设置")
        form_audio = QFormLayout()
        
        self.combo_devices = QComboBox()
        self.refresh_devices()
        
        form_audio.addRow("Microphone (麦克风):", self.combo_devices)
        
        # Count Setting
        self.spin_count = QSpinBox()
        self.spin_count.setRange(5, 1000)
        self.spin_count.setValue(20)
        self.spin_count.setSuffix(" words")
        self.spin_count.setSuffix(" words")
        form_audio.addRow("Practice Count (每次练习):", self.spin_count)
        
        self.chk_auto_default = QCheckBox("Enable Auto Mode by Default")
        self.chk_auto_default.setToolTip("Automatically check 'Auto Mode' when starting.")
        form_audio.addRow("Auto Mode (默认连读):", self.chk_auto_default)
        
        self.combo_feedback_lang = QComboBox()
        self.combo_feedback_lang.addItem("English (Punchy ⚡)", "en")
        self.combo_feedback_lang.addItem("Chinese (Cute 🎀)", "zh")
        form_audio.addRow("Encouragement Voice (鼓励语音):", self.combo_feedback_lang)
        
        grp_audio.setLayout(form_audio)
        layout.addWidget(grp_audio)
        
        grp_audio.setLayout(form_audio)
        grp_audio.setLayout(form_audio)
        layout.addWidget(grp_audio)
        
        # Review Strategy Settings
        grp_strategy = QGroupBox("Review Strategy 复习策略")
        layout_strategy = QVBoxLayout()
        
        self.chk_random = QCheckBox("Random Order (随机打乱)")
        self.chk_random.setToolTip("Shuffle the order of words every time.")
        
        self.chk_smart = QCheckBox("Prioritize Unpracticed/Wrong (智能优先)")
        self.chk_smart.setToolTip("Prioritize words that haven't been practiced or had low scores.")
        
        self.chk_no_repeat = QCheckBox("Exclude Recently Mastered (不重复已掌握)")
        self.chk_no_repeat.setToolTip("Don't show words scored >= 90 in the last session.")
        
        layout_strategy.addWidget(self.chk_random)
        layout_strategy.addWidget(self.chk_smart)
        layout_strategy.addWidget(self.chk_no_repeat)
        
        grp_strategy.setLayout(layout_strategy)
        layout.addWidget(grp_strategy)
        
        # Data Management Section
        grp_data = QGroupBox("Data Management 数据管理")
        layout_data = QVBoxLayout()
        
        lbl_groups = QLabel("Select Groups to Practice (选择练习题库):")
        layout_data.addWidget(lbl_groups)
        
        # Group List with Checkboxes
        self.list_groups = QListWidget()
        self.list_groups.setToolTip("Checked groups will be included in practice.\nRight-click or use button to delete.")
        layout_data.addWidget(self.list_groups)
        
        hbox_data_btns = QHBoxLayout()
        
        btn_edit_db = QPushButton("Edit Database (编辑题库)")
        btn_edit_db.clicked.connect(self.open_database_editor)
        hbox_data_btns.addWidget(btn_edit_db)
        
        btn_delete_group = QPushButton("Delete Selected (删除选中组)")
        btn_delete_group.clicked.connect(self.delete_selected_group)
        hbox_data_btns.addWidget(btn_delete_group)
        
        btn_clear_data = QPushButton("Clear ALL (清空全部)")
        btn_clear_data.setStyleSheet("background-color: #ffcccc; color: red;")
        btn_clear_data.clicked.connect(self.clear_database)
        hbox_data_btns.addWidget(btn_clear_data)
        
        btn_reset_stats = QPushButton("Reset Progress (重置进度)")
        btn_reset_stats.setStyleSheet("background-color: #FFF9C4; color: #F57F17;")
        btn_reset_stats.setToolTip("Keep words but clear scores and practice history.\n保留单词，仅清空分数和练习记录。")
        btn_reset_stats.clicked.connect(self.reset_progress)
        hbox_data_btns.addWidget(btn_reset_stats)
        
        layout_data.addLayout(hbox_data_btns)
        
        grp_data.setLayout(layout_data)
        layout.addWidget(grp_data)
        
        # Init Groups
        self.refresh_group_list()
        
        # AI Section
        grp_ai = QGroupBox("AI Engine Settings (AI 引擎)")
        layout_ai = QVBoxLayout()
        
        # Provider Selector
        form_provider = QFormLayout()
        
        self.combo_stt = QComboBox()
        self.combo_stt.addItems(["Google Web Speech (Cloud/Free)", "Local Whisper (GPU)"])
        form_provider.addRow("STT (听写) Engine:", self.combo_stt)
        
        self.combo_provider = QComboBox()
        self.combo_provider.addItems(["Azure Speech (Recommended)", "OpenAI / GPT", "Ollama (Local)"])
        self.combo_provider.currentIndexChanged.connect(self.update_ai_fields)
        form_provider.addRow("LLM (建议) Provider:", self.combo_provider)
        
        layout_ai.addLayout(form_provider)
        
        # Stacked Widget for different inputs
        self.stack_ai = QStackedWidget()
        
        # Page 0: Azure
        page_azure = QWidget()
        form_azure = QFormLayout()
        self.txt_azure_key = QLineEdit()
        self.txt_azure_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.txt_azure_region = QLineEdit()
        form_azure.addRow("Azure Key:", self.txt_azure_key)
        form_azure.addRow("Region:", self.txt_azure_region)
        page_azure.setLayout(form_azure)
        self.stack_ai.addWidget(page_azure)
        
        # Page 1: OpenAI
        page_openai = QWidget()
        form_openai = QFormLayout()
        self.txt_openai_key = QLineEdit()
        self.txt_openai_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.txt_openai_base = QLineEdit("https://api.openai.com/v1")
        self.txt_openai_model = QLineEdit("gpt-4o")
        form_openai.addRow("API Key:", self.txt_openai_key)
        form_openai.addRow("Base URL:", self.txt_openai_base)
        form_openai.addRow("Model:", self.txt_openai_model)
        page_openai.setLayout(form_openai)
        self.stack_ai.addWidget(page_openai)
        
        # Page 2: Ollama
        page_ollama = QWidget()
        form_ollama = QFormLayout()
        self.txt_ollama_base = QLineEdit("http://localhost:11434/v1")
        self.txt_ollama_model = QLineEdit("qwen2.5") 
        self.txt_ollama_model.setPlaceholderText("e.g. qwen2.5, llama3.1")
        form_ollama.addRow("Base URL:", self.txt_ollama_base)
        form_ollama.addRow("Model:", self.txt_ollama_model)
        lbl_ollama_hint = QLabel("提示：8GB显卡推荐 'qwen2.5' 或 'llama3.1' (7B/8B模型)。\n请确保已运行 'ollama pull qwen2.5'。")
        lbl_ollama_hint.setStyleSheet("color: gray; font-size: 10px;")
        form_ollama.addRow("", lbl_ollama_hint)
        page_ollama.setLayout(form_ollama)
        self.stack_ai.addWidget(page_ollama)
        
        layout_ai.addWidget(self.stack_ai)
        grp_ai.setLayout(layout_ai)
        layout.addWidget(grp_ai)
        
        # Description
        self.lbl_info = QLabel("提示：Azure 提供最精准的音素级打分。OpenAI/Ollama 模式下，将使用 Google STT 进行识别，\n并由大模型提供纠音建议（评分基于文本相似度，不如 Azure 精准）。")
        self.lbl_info.setWordWrap(True)
        self.lbl_info.setStyleSheet("color: #666; font-style: italic; margin: 10px;")
        layout.addWidget(self.lbl_info)
        
        # Buttons
        btn_box = QHBoxLayout()
        btn_box.addStretch()
        
        btn_save = QPushButton("Save 保存")
        btn_save.clicked.connect(self.save_settings)
        btn_box.addWidget(btn_save)
        
        layout.addLayout(btn_box)
        
    def refresh_devices(self):
        self.combo_devices.clear()
        devices = self.recorder.get_input_devices()
        for idx, name in devices:
            self.combo_devices.addItem(name, idx)
            
    def update_ai_fields(self, index):
        self.stack_ai.setCurrentIndex(index)

    def load_settings(self):
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r') as f:
                    config = json.load(f)
                    
                    # Device
                    dev_idx = config.get("device_index", 0)
                    for i in range(self.combo_devices.count()):
                        if self.combo_devices.itemData(i) == dev_idx:
                            self.combo_devices.setCurrentIndex(i)
                            break
                            
                    # Count
                    self.spin_count.setValue(config.get("practice_count", 20))
                    self.chk_auto_default.setChecked(config.get("auto_mode_default", True))
                    
                    lang = config.get("feedback_language", "en")
                    idx = self.combo_feedback_lang.findData(lang)
                    if idx >= 0: self.combo_feedback_lang.setCurrentIndex(idx)
                    
                    # Strategy
                    self.chk_random.setChecked(config.get("strategy_random", True))
                    self.chk_smart.setChecked(config.get("strategy_smart", True))
                    self.chk_no_repeat.setChecked(config.get("strategy_no_repeat", False))
                    
                    # AI Provider
                    provider = config.get("ai_provider", "Azure Speech (Recommended)")
                    idx = self.combo_provider.findText(provider)
                    if idx >= 0:
                        self.combo_provider.setCurrentIndex(idx)
                        
                    stt = config.get("stt_provider", "Google Web Speech (Cloud/Free)")
                    idx_stt = self.combo_stt.findText(stt)
                    if idx_stt >= 0:
                        self.combo_stt.setCurrentIndex(idx_stt)
                        
                    # Azure
                    self.txt_azure_key.setText(config.get("azure_key", ""))
                    self.txt_azure_region.setText(config.get("azure_region", ""))
                    
                    # OpenAI
                    self.txt_openai_key.setText(config.get("openai_key", ""))
                    self.txt_openai_base.setText(config.get("openai_base", "https://api.openai.com/v1"))
                    self.txt_openai_model.setText(config.get("openai_model", "gpt-4o"))
                    
                    # Ollama
                    self.txt_ollama_base.setText(config.get("ollama_base", "http://localhost:11434/v1"))
                    self.txt_ollama_model.setText(config.get("ollama_model", "qwen2"))
                    
            except Exception as e:
                print(e)
                pass
                
    def save_settings(self):
        config = {
            "device_index": self.combo_devices.currentData(),
            "device_index": self.combo_devices.currentData(),
            "practice_count": self.spin_count.value(),
            "auto_mode_default": self.chk_auto_default.isChecked(),
            "feedback_language": self.combo_feedback_lang.currentData(),
            
            "strategy_random": self.chk_random.isChecked(),
            "strategy_smart": self.chk_smart.isChecked(),
            "strategy_no_repeat": self.chk_no_repeat.isChecked(),

            "ai_provider": self.combo_provider.currentText(),
            "stt_provider": self.combo_stt.currentText(),
            
            # Azure
            "azure_key": self.txt_azure_key.text().strip(),
            "azure_key": self.txt_azure_key.text().strip(),
            "azure_region": self.txt_azure_region.text().strip(),
            
            # OpenAI
            "openai_key": self.txt_openai_key.text().strip(),
            "openai_base": self.txt_openai_base.text().strip(),
            "openai_model": self.txt_openai_model.text().strip(),
            
            # Ollama
            "ollama_base": self.txt_ollama_base.text().strip(),
            "ollama_model": self.txt_ollama_model.text().strip(),
            
            # Active Groups
            "active_groups": [self.list_groups.item(i).text() for i in range(self.list_groups.count()) 
                              if self.list_groups.item(i).checkState() == Qt.CheckState.Checked]
        }
        
        try:
            with open(self.config_file, 'w') as f:
                json.dump(config, f)
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    def clear_database(self):
        confirm = QMessageBox.question(
            self, 
            "Confirm Clear (确认清空)", 
            "Are you sure you want to delete ALL words and sentences?\nData cannot be recovered.\n\n确定要清空所有单词和句子吗？不可恢复。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if confirm == QMessageBox.StandardButton.Yes:
            # Use SHARED Manager
            self.manager.clear_all_exercises()
            
            QMessageBox.information(self, "Cleared", "Database has been cleared.\nPlease restart the application or refresh the view.\n\n数据库已清空。")
            self.refresh_group_list()

    def reset_progress(self):
        confirm = QMessageBox.question(
            self, 
            "Confirm Reset (确认重置)", 
            "Are you sure you want to RESET progress for all words?\n"
            "This will clear scores and practice counts, but keep the words.\n\n"
            "确定要重置所有进度吗？只清空分数，保留单词。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if confirm == QMessageBox.StandardButton.Yes:
            self.manager.reset_stats()
            QMessageBox.information(self, "Reset", "Progress has been reset.\nReady for a fresh start! 🚀\n\n进度已重置。")

    def refresh_group_list(self):
        # Use SHARED manager
        groups = self.manager.get_groups()
        
        # Load active groups from current config (passed in init or loaded)
        # We need to read it freshly to ensure sync
        current_config = {}
        if os.path.exists(self.config_file):
            with open(self.config_file, 'r') as f:
                current_config = json.load(f)
        
        active_groups = current_config.get("active_groups", [])
        # If active_groups is empty (first run), maybe default to ALL?
        # Let's say if None or Empty, we check ALL by default for UX.
        auto_check_all = len(active_groups) == 0
        
        self.list_groups.clear()
        
        # Special Item: "Default" might exist
        for g_name in groups:
            item = QListWidgetItem(g_name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            
            # Check state
            if g_name in active_groups or auto_check_all:
                item.setCheckState(Qt.CheckState.Checked)
            else:
                item.setCheckState(Qt.CheckState.Unchecked)
                
            self.list_groups.addItem(item)
            
    def delete_selected_group(self):
        current_item = self.list_groups.currentItem()
        if not current_item:
            QMessageBox.warning(self, "Select Group", "Please click on a group name to select it first.")
            return
            
        group_name = current_item.text()
        confirm = QMessageBox.question(self, "Confirm Delete", f"Delete group '{group_name}' and all its vocabulary?", 
                                       QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        
        if confirm == QMessageBox.StandardButton.Yes:
             self.manager.delete_group(group_name)
             self.refresh_group_list()
             self.refresh_group_list()

    def open_database_editor(self):
        from src.ui.database_editor import DatabaseEditor
        # Pass the SHARED manager
        editor = DatabaseEditor(self, manager=self.manager)
        editor.exec()
        # Refresh groups after editing (in case groups changed/deleted)
        self.refresh_group_list()
            
    def get_settings(self):
        if os.path.exists(self.config_file):
            with open(self.config_file, 'r') as f:
                return json.load(f)
        return {}
