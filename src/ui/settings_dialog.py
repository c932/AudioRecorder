from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton, 
                             QLabel, QComboBox, QLineEdit, QGroupBox, QFormLayout, QMessageBox, QStackedWidget, QWidget, QSpinBox,
                             QListWidget, QListWidgetItem, QCheckBox, QTabWidget, QDoubleSpinBox)
from PyQt6.QtCore import Qt
from src.core.audio_recorder import AudioRecorder
import os
import json

from src.utils import get_user_data_path

class SettingsDialog(QDialog):
    def __init__(self, parent=None, audio_recorder=None, exercise_manager=None):
        super().__init__(parent)
        self.setWindowTitle("Settings 设置")
        self.resize(600, 500) # Slightly larger for tabs
        self.recorder = audio_recorder or AudioRecorder()
        # Use passed manager or create temporary
        if exercise_manager:
            self.manager = exercise_manager
        else:
            from src.core.exercise_manager import ExerciseManager
            self.manager = ExerciseManager(get_user_data_path("words.json"))
            
        self.config_file = get_user_data_path("config.json")
        
        self.setup_ui()
        self.load_settings()
        
    def setup_ui(self):
        main_layout = QVBoxLayout(self)
        
        self.tabs = QTabWidget()
        main_layout.addWidget(self.tabs)
        
        # --- TAB 1: General (Audio & Practice) ---
        tab_general = QWidget()
        layout_gen = QVBoxLayout(tab_general)
        
        # Audio Section
        grp_audio = QGroupBox("Audio & Interface 音频与界面")
        form_audio = QFormLayout()
        
        self.combo_devices = QComboBox()
        self.refresh_devices()
        form_audio.addRow("Microphone (麦克风):", self.combo_devices)
        
        self.spin_count = QSpinBox()
        self.spin_count.setRange(5, 1000)
        self.spin_count.setValue(20)
        self.spin_count.setSuffix(" words")
        form_audio.addRow("Practice Count (每次练习):", self.spin_count)
        
        self.chk_auto_default = QCheckBox("Enable Auto Mode by Default (默认开启连读模式)")
        self.chk_auto_default.setToolTip("Automatically check 'Auto Mode' when starting.")
        form_audio.addRow("", self.chk_auto_default)
        
        self.combo_feedback_lang = QComboBox()
        self.combo_feedback_lang.addItem("English (Punchy ⚡)", "en")
        self.combo_feedback_lang.addItem("Chinese (Cute 🎀)", "zh")
        form_audio.addRow("Encouragement Voice (鼓励语音):", self.combo_feedback_lang)
        
        self.combo_tts = QComboBox()
        self.combo_tts.addItems([
            "Auto (Best available)",
            "Kokoro (Local Neural - Best Quality)", 
            "Piper (Local Fast - Low Latency)", 
            "Edge TTS (Cloud - Good Quality)", 
            "System (Offline - Robot)"
        ])
        form_audio.addRow("TTS Engine (语音引擎):", self.combo_tts)
        
        grp_audio.setLayout(form_audio)
        layout_gen.addWidget(grp_audio)
        
        # Strategy Section
        grp_strategy = QGroupBox("Review Strategy 复习策略")
        layout_strategy = QVBoxLayout()
        self.chk_random = QCheckBox("Random Order (随机打乱)")
        self.chk_smart = QCheckBox("Prioritize Unpracticed/Wrong (智能优先 - 错题/生词)")
        self.chk_no_repeat = QCheckBox("Exclude Recently Mastered (不重复已掌握 - 90分以上)")
        layout_strategy.addWidget(self.chk_random)
        layout_strategy.addWidget(self.chk_smart)
        layout_strategy.addWidget(self.chk_no_repeat)
        grp_strategy.setLayout(layout_strategy)
        layout_gen.addWidget(grp_strategy)
        
        layout_gen.addStretch()
        self.tabs.addTab(tab_general, "General 通用")
        
        # --- TAB 2: Data Management ---
        tab_data = QWidget()
        layout_data = QVBoxLayout(tab_data)
        
        lbl_groups = QLabel("Select Groups to Practice (选择练习题库):")
        layout_data.addWidget(lbl_groups)
        
        self.list_groups = QListWidget()
        layout_data.addWidget(self.list_groups)
        
        hbox_data_btns = QHBoxLayout()
        btn_edit_db = QPushButton("Edit Database (编辑题库)")
        btn_edit_db.clicked.connect(self.open_database_editor)
        hbox_data_btns.addWidget(btn_edit_db)
        
        btn_delete_group = QPushButton("Delete Selected (删除选中)")
        btn_delete_group.clicked.connect(self.delete_selected_group)
        hbox_data_btns.addWidget(btn_delete_group)
        
        btn_clear_data = QPushButton("Clear ALL (清空全部)")
        btn_clear_data.setStyleSheet("background-color: #ffcccc; color: red;")
        btn_clear_data.clicked.connect(self.clear_database)
        hbox_data_btns.addWidget(btn_clear_data)
        
        btn_reset_stats = QPushButton("Reset Progress (重置进度)")
        btn_reset_stats.setStyleSheet("background-color: #FFF9C4; color: #F57F17;")
        btn_reset_stats.clicked.connect(self.reset_progress)
        hbox_data_btns.addWidget(btn_reset_stats)
        
        layout_data.addLayout(hbox_data_btns)
        self.tabs.addTab(tab_data, "Data 数据")
        
        # --- TAB 3: AI Engine ---
        tab_ai = QWidget()
        layout_ai = QVBoxLayout(tab_ai)
        
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
        form_ollama.addRow("Base URL:", self.txt_ollama_base)
        form_ollama.addRow("Model:", self.txt_ollama_model)
        lbl_ollama_hint = QLabel("提示：本地大模型需先安装 Ollama 并 pull 模型。")
        lbl_ollama_hint.setStyleSheet("color: gray;")
        form_ollama.addRow("", lbl_ollama_hint)
        page_ollama.setLayout(form_ollama)
        self.stack_ai.addWidget(page_ollama)
        
        layout_ai.addWidget(self.stack_ai)
        
        self.lbl_info = QLabel("提示：Azure 提供最精准的音素级打分。OpenAI/Ollama 使用 Hybrid 模式。")
        self.lbl_info.setStyleSheet("color: #666; font-style: italic; margin-top: 10px;")
        layout_ai.addWidget(self.lbl_info)
        layout_ai.addStretch()
        
        self.tabs.addTab(tab_ai, "AI Engine")
        
        # --- TAB 4: Developer / Scoring ---
        tab_dev = QWidget()
        layout_dev = QVBoxLayout(tab_dev)
        
        grp_scoring = QGroupBox("Scoring Sensitivity (High Precision Whisper) 评分灵敏度")
        form_scoring = QFormLayout()
        
        self.dspin_threshold = QDoubleSpinBox()
        self.dspin_threshold.setRange(0.1, 1.0)
        self.dspin_threshold.setSingleStep(0.05)
        self.dspin_threshold.setValue(0.80)
        self.dspin_threshold.setToolTip("Lower = Easier (Less strict about confidence). Default 0.8.")
        form_scoring.addRow("Confidence Threshold (自信度门槛):", self.dspin_threshold)
        
        self.spin_penalty = QSpinBox()
        self.spin_penalty.setRange(0, 500)
        self.spin_penalty.setValue(100)
        self.spin_penalty.setToolTip("Higher = More punishment for blurry sound. Default 100.")
        form_scoring.addRow("Penalty Factor (模糊扣分力度):", self.spin_penalty)
        
        self.chk_strict_cap = QCheckBox("Enable Excellence Cap (90+ requires High Confidence)")
        self.chk_strict_cap.setChecked(True)
        self.chk_strict_cap.setToolTip("If enabled, prevents scores > 90 unless confidence is very high.")
        form_scoring.addRow("90+ Lock (严选模式):", self.chk_strict_cap)
        
        grp_scoring.setLayout(form_scoring)
        layout_dev.addWidget(grp_scoring)
        
        lbl_dev_hint = QLabel("Adjust these if you feel the AI is too strict or too loose.\nThreshold 0.8 / Penalty 100 is the 'Strict' standard.")
        lbl_dev_hint.setStyleSheet("color: gray;")
        layout_dev.addWidget(lbl_dev_hint)
        
        layout_dev.addStretch()
        self.tabs.addTab(tab_dev, "Advanced 高级")


        # --- Bottom Buttons ---
        btn_box = QHBoxLayout()
        btn_box.addStretch()
        
        btn_save = QPushButton("Save Settings 保存设置")
        btn_save.clicked.connect(self.save_settings)
        btn_save.setStyleSheet("background-color: #4CAF50; color: white; padding: 6px 15px; font-weight: bold;")
        btn_box.addWidget(btn_save)
        
        main_layout.addLayout(btn_box)
        
        # Initialize
        self.refresh_group_list()

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
                    
                    # General
                    dev_idx = config.get("device_index", 0)
                    for i in range(self.combo_devices.count()):
                        if self.combo_devices.itemData(i) == dev_idx:
                            self.combo_devices.setCurrentIndex(i)
                            break
                            
                    self.spin_count.setValue(config.get("practice_count", 20))
                    self.chk_auto_default.setChecked(config.get("auto_mode_default", True))
                    
                    lang = config.get("feedback_language", "en")
                    idx = self.combo_feedback_lang.findData(lang)
                    if idx >= 0: self.combo_feedback_lang.setCurrentIndex(idx)
                    
                    tts = config.get("tts_engine", "Auto (Best available)")
                    idx_tts = self.combo_tts.findText(tts)
                    if idx_tts >= 0: self.combo_tts.setCurrentIndex(idx_tts)
                    
                    self.chk_random.setChecked(config.get("strategy_random", True))
                    self.chk_smart.setChecked(config.get("strategy_smart", True))
                    self.chk_no_repeat.setChecked(config.get("strategy_no_repeat", False))
                    
                    # AI
                    provider = config.get("ai_provider", "Azure Speech (Recommended)")
                    idx = self.combo_provider.findText(provider)
                    if idx >= 0: self.combo_provider.setCurrentIndex(idx)
                        
                    stt = config.get("stt_provider", "Google Web Speech (Cloud/Free)")
                    idx_stt = self.combo_stt.findText(stt)
                    if idx_stt >= 0: self.combo_stt.setCurrentIndex(idx_stt)
                        
                    self.txt_azure_key.setText(config.get("azure_key", ""))
                    self.txt_azure_region.setText(config.get("azure_region", ""))
                    self.txt_openai_key.setText(config.get("openai_key", ""))
                    self.txt_openai_base.setText(config.get("openai_base", "https://api.openai.com/v1"))
                    self.txt_openai_model.setText(config.get("openai_model", "gpt-4o"))
                    self.txt_ollama_base.setText(config.get("ollama_base", "http://localhost:11434/v1"))
                    self.txt_ollama_model.setText(config.get("ollama_model", "qwen2"))
                    
                    # Scoring (New)
                    self.dspin_threshold.setValue(config.get("scoring_threshold", 0.80))
                    self.spin_penalty.setValue(config.get("scoring_penalty", 100))
                    self.chk_strict_cap.setChecked(config.get("scoring_strict_cap", True))
                    
            except Exception as e:
                print(f"[SettingsDialog] Failed to load settings: {e}")

    def save_settings(self):
        config = {
            "device_index": self.combo_devices.currentData(),
            "practice_count": self.spin_count.value(),
            "auto_mode_default": self.chk_auto_default.isChecked(),
            "feedback_language": self.combo_feedback_lang.currentData(),
            "tts_engine": self.combo_tts.currentText(),
            
            "strategy_random": self.chk_random.isChecked(),
            "strategy_smart": self.chk_smart.isChecked(),
            "strategy_no_repeat": self.chk_no_repeat.isChecked(),

            "ai_provider": self.combo_provider.currentText(),
            "stt_provider": self.combo_stt.currentText(),
            
            "azure_key": self.txt_azure_key.text().strip(),
            "azure_region": self.txt_azure_region.text().strip(),
            
            "openai_key": self.txt_openai_key.text().strip(),
            "openai_base": self.txt_openai_base.text().strip(),
            "openai_model": self.txt_openai_model.text().strip(),
            
            "ollama_base": self.txt_ollama_base.text().strip(),
            "ollama_model": self.txt_ollama_model.text().strip(),
            
            # Scoring
            "scoring_threshold": self.dspin_threshold.value(),
            "scoring_penalty": self.spin_penalty.value(),
            "scoring_strict_cap": self.chk_strict_cap.isChecked(),
            
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
        confirm = QMessageBox.question(self, "Confirm", "Delete ALL words? Cannot recover.", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if confirm == QMessageBox.StandardButton.Yes:
            self.manager.clear_all_exercises()
            self.refresh_group_list()

    def reset_progress(self):
        confirm = QMessageBox.question(self, "Confirm", "Reset progress stats? Words will keep.", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if confirm == QMessageBox.StandardButton.Yes:
            self.manager.reset_stats()
            QMessageBox.information(self, "Reset", "Progress reset.")

    def refresh_group_list(self):
        groups = self.manager.get_groups()
        current_config = {}
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r') as f:
                    current_config = json.load(f)
            except Exception as e:
                print(f"[SettingsDialog] Error loading config for groups: {e}")

        active_groups = current_config.get("active_groups", [])
        auto_check = len(active_groups) == 0
        
        self.list_groups.clear()
        for g_name in groups:
            item = QListWidgetItem(g_name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            if g_name in active_groups or auto_check:
                item.setCheckState(Qt.CheckState.Checked)
            else:
                item.setCheckState(Qt.CheckState.Unchecked)
            self.list_groups.addItem(item)
            
    def delete_selected_group(self):
        item = self.list_groups.currentItem()
        if item and QMessageBox.question(self, "Delete", f"Delete group '{item.text()}'?") == QMessageBox.StandardButton.Yes:
            self.manager.delete_group(item.text())
            self.refresh_group_list()

    def open_database_editor(self):
        from src.ui.database_editor import DatabaseEditor
        editor = DatabaseEditor(self, manager=self.manager)
        editor.exec()
        self.refresh_group_list()

    def get_settings(self):
        if os.path.exists(self.config_file):
            with open(self.config_file, 'r') as f:
                return json.load(f)
        return {}
