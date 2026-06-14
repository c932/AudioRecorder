from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton, 
                             QLabel, QComboBox, QLineEdit, QGroupBox, QFormLayout, QMessageBox, QStackedWidget, QWidget, QSpinBox,
                             QListWidget, QListWidgetItem, QCheckBox, QTabWidget, QDoubleSpinBox,
                             QTableWidget, QTableWidgetItem, QHeaderView, QProgressBar, QFrame, QInputDialog, QScrollArea)
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication
from src.core.audio_recorder import AudioRecorder
import os
import json
import requests

from src.utils import get_user_data_path

class SettingsDialog(QDialog):
    def __init__(self, parent=None, audio_recorder=None, exercise_manager=None, quiz_engine=None):
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.resize(650, 580)
        self.recorder = audio_recorder or AudioRecorder()
        self.quiz_engine = quiz_engine
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
        
        # --- TAB 1: 通用 ---
        tab_general = QWidget()
        layout_gen = QVBoxLayout(tab_general)
        
        # 音频与界面
        grp_audio = QGroupBox("音频与界面")
        form_audio = QFormLayout()
        
        self.combo_devices = QComboBox()
        self.refresh_devices()
        form_audio.addRow("麦克风:", self.combo_devices)
        
        count_row = QHBoxLayout()
        self.spin_count = QSpinBox()
        self.spin_count.setRange(5, 1000)
        self.spin_count.setValue(20)
        count_row.addWidget(self.spin_count)
        count_row.addWidget(QLabel("个单词"))
        count_row.addStretch()
        form_audio.addRow("每次练习:", count_row)
        
        self.chk_auto_default = QCheckBox("默认开启连读模式")
        form_audio.addRow("", self.chk_auto_default)
        
        self.combo_feedback_lang = QComboBox()
        self.combo_feedback_lang.addItem("英文（简洁有力）", "en")
        self.combo_feedback_lang.addItem("中文（可爱鼓励）", "zh")
        form_audio.addRow("鼓励语音:", self.combo_feedback_lang)
        
        self.combo_tts = QComboBox()
        self.combo_tts.addItems([
            "Auto (Best available)",
            "Kokoro (Local Neural - Best Quality)", 
            "Piper (Local Fast - Low Latency)", 
            "Edge TTS (Cloud - Good Quality)", 
            "System (Offline - Robot)"
        ])
        form_audio.addRow("语音引擎:", self.combo_tts)
        
        grp_audio.setLayout(form_audio)
        layout_gen.addWidget(grp_audio)
        
        # 复习策略
        grp_strategy = QGroupBox("复习策略")
        layout_strategy = QVBoxLayout()
        self.chk_random = QCheckBox("随机打乱顺序")
        self.chk_smart = QCheckBox("智能优先（错题/未练习的排前面）")
        self.chk_no_repeat = QCheckBox("不重复已掌握的（90分以上跳过）")
        layout_strategy.addWidget(self.chk_random)
        layout_strategy.addWidget(self.chk_smart)
        layout_strategy.addWidget(self.chk_no_repeat)
        grp_strategy.setLayout(layout_strategy)
        layout_gen.addWidget(grp_strategy)
        
        layout_gen.addStretch()
        self.tabs.addTab(tab_general, "通用")
        
        # --- TAB 2: 题库 ---
        tab_data = QWidget()
        layout_data = QVBoxLayout(tab_data)
        
        lbl_groups = QLabel("选择原始词库（勾选启用）:")
        layout_data.addWidget(lbl_groups)
        
        self.list_groups = QListWidget()
        self.list_groups.itemChanged.connect(self._on_group_check_changed)
        layout_data.addWidget(self.list_groups)
        
        hbox_data_btns = QHBoxLayout()
        btn_edit_db = QPushButton("编辑词库")
        btn_edit_db.clicked.connect(self.open_database_editor)
        hbox_data_btns.addWidget(btn_edit_db)
        
        btn_delete_group = QPushButton("删除选中")
        btn_delete_group.clicked.connect(self.delete_selected_group)
        hbox_data_btns.addWidget(btn_delete_group)
        
        btn_clear_data = QPushButton("清空全部")
        btn_clear_data.setStyleSheet("background-color: #ffcccc; color: red;")
        btn_clear_data.clicked.connect(self.clear_database)
        hbox_data_btns.addWidget(btn_clear_data)
        
        btn_reset_stats = QPushButton("重置进度")
        btn_reset_stats.setStyleSheet("background-color: #FFF9C4; color: #F57F17;")
        btn_reset_stats.clicked.connect(self.reset_progress)
        hbox_data_btns.addWidget(btn_reset_stats)
        
        layout_data.addLayout(hbox_data_btns)
        
        # ========== 生成题库区域 ==========
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        layout_data.addWidget(separator)
        
        lbl_bank_title = QLabel("预生成题库")
        lbl_bank_title.setStyleSheet("font-size: 16px; font-weight: bold; color: #1565C0; margin-top: 8px;")
        layout_data.addWidget(lbl_bank_title)
        
        # Generate row: blank count + question count + button
        gen_row = QHBoxLayout()
        
        gen_row.addWidget(QLabel("填空数:"))
        self.spin_blank_count = QSpinBox()
        self.spin_blank_count.setRange(1, 5)
        self.spin_blank_count.setValue(1)
        self.spin_blank_count.setToolTip("完形填空留几个空")
        gen_row.addWidget(self.spin_blank_count)
        gen_row.addWidget(QLabel("个空"))
        
        gen_row.addSpacing(10)
        gen_row.addWidget(QLabel("题数:"))
        self.spin_bank_count = QSpinBox()
        self.spin_bank_count.setRange(5, 10000)
        self.spin_bank_count.setValue(20)
        self.spin_bank_count.setToolTip("题库包含的题目数量（上限为所选词库的总词条数）")
        gen_row.addWidget(self.spin_bank_count)
        gen_row.addWidget(QLabel("题"))
        
        self.chk_all_bank = QCheckBox("全部")
        self.chk_all_bank.setToolTip("使用所选词库的全部词条数")
        self.chk_all_bank.toggled.connect(self._on_all_bank_toggled)
        gen_row.addWidget(self.chk_all_bank)
        
        self.btn_generate_bank = QPushButton("生成题库")
        self.btn_generate_bank.setStyleSheet("background-color: #1565C0; color: white; padding: 8px; font-weight: bold; border-radius: 5px;")
        self.btn_generate_bank.clicked.connect(self._generate_quiz_bank)
        gen_row.addWidget(self.btn_generate_bank)
        layout_data.addLayout(gen_row)
        
        # Progress bar (hidden initially)
        self.bank_progress = QProgressBar()
        self.bank_progress.setVisible(False)
        self.bank_progress.setStyleSheet("QProgressBar { border: 1px solid #90CAF9; border-radius: 4px; text-align: center; }")
        layout_data.addWidget(self.bank_progress)
        
        self.lbl_bank_status = QLabel("")
        self.lbl_bank_status.setStyleSheet("color: #666; font-size: 13px;")
        self.lbl_bank_status.setVisible(False)
        layout_data.addWidget(self.lbl_bank_status)
        
        # Bank table with 7 columns: Name / Groups / Questions / Created / View / Rename / Delete
        self.table_banks = QTableWidget()
        self.table_banks.setColumnCount(7)
        self.table_banks.setHorizontalHeaderLabels(["题库名称", "来源", "题数", "创建时间", "查看", "改名", "删除"])
        self.table_banks.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in [4, 5, 6]:
            self.table_banks.horizontalHeader().setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        self.table_banks.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        layout_data.addWidget(self.table_banks)
        
        self.tabs.addTab(tab_data, "题库")
        
        # --- TAB 3: AI引擎 ---
        tab_ai = QWidget()
        layout_ai = QVBoxLayout(tab_ai)
        
        form_provider = QFormLayout()
        self.combo_stt = QComboBox()
        self.combo_stt.addItems(["Google Web Speech (Cloud/Free)", "Local Whisper (GPU)"])
        form_provider.addRow("语音识别引擎:", self.combo_stt)
        
        self.combo_provider = QComboBox()
        self.combo_provider.addItems(["Azure Speech (Recommended)", "OpenAI / GPT", "Ollama (Local)", "Custom (Local API)"])
        self.combo_provider.currentIndexChanged.connect(self.update_ai_fields)
        form_provider.addRow("大语言模型:", self.combo_provider)
        layout_ai.addLayout(form_provider)
        
        # Stacked Widget for different inputs
        self.stack_ai = QStackedWidget()
        
        # Page 0: Azure
        page_azure = QWidget()
        form_azure = QFormLayout()
        self.txt_azure_key = QLineEdit()
        self.txt_azure_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.txt_azure_region = QLineEdit()
        form_azure.addRow("Azure 密钥:", self.txt_azure_key)
        form_azure.addRow("区域:", self.txt_azure_region)
        page_azure.setLayout(form_azure)
        self.stack_ai.addWidget(page_azure)
        
        # Page 1: OpenAI
        page_openai = QWidget()
        form_openai = QFormLayout()
        self.txt_openai_key = QLineEdit()
        self.txt_openai_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.txt_openai_base = QLineEdit("https://api.openai.com/v1")
        self.txt_openai_model = QLineEdit("gpt-4o")
        form_openai.addRow("API 密钥:", self.txt_openai_key)
        form_openai.addRow("接口地址:", self.txt_openai_base)
        form_openai.addRow("模型:", self.txt_openai_model)
        page_openai.setLayout(form_openai)
        self.stack_ai.addWidget(page_openai)
        
        # Page 2: Ollama
        page_ollama = QWidget()
        form_ollama = QFormLayout()
        self.txt_ollama_base = QLineEdit("http://localhost:11434/v1")
        self.txt_ollama_model = QLineEdit("qwen2.5") 
        form_ollama.addRow("接口地址:", self.txt_ollama_base)
        form_ollama.addRow("模型:", self.txt_ollama_model)
        lbl_ollama_hint = QLabel("提示：本地大模型需先安装 Ollama 并 pull 模型。")
        lbl_ollama_hint.setStyleSheet("color: gray;")
        form_ollama.addRow("", lbl_ollama_hint)
        page_ollama.setLayout(form_ollama)
        self.stack_ai.addWidget(page_ollama)
        
        # Page 3: Custom
        page_custom = QWidget()
        form_custom = QFormLayout()
        self.txt_custom_base = QLineEdit("http://localhost:8080/v1")
        form_custom.addRow("接口地址:", self.txt_custom_base)
        
        self.txt_custom_key = QLineEdit()
        self.txt_custom_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.txt_custom_key.setPlaceholderText("（可选）")
        form_custom.addRow("API 密钥:", self.txt_custom_key)
        
        model_row = QHBoxLayout()
        self.combo_custom_model = QComboBox()
        self.combo_custom_model.setEditable(True)
        self.combo_custom_model.setPlaceholderText("如 qwen3.6-35b-a3b")
        model_row.addWidget(self.combo_custom_model, 1)
        
        self.btn_fetch_models = QPushButton("获取模型列表")
        self.btn_fetch_models.setStyleSheet("padding: 4px 10px; background-color: #2196F3; color: white; border-radius: 4px;")
        self.btn_fetch_models.clicked.connect(self.fetch_models)
        model_row.addWidget(self.btn_fetch_models)
        
        form_custom.addRow("模型:", model_row)
        
        lbl_custom_hint = QLabel("提示：支持 llama.cpp、vLLM 等 OpenAI 兼容 API。\n图片识别（多模态）需使用支持 vision 的模型。")
        lbl_custom_hint.setStyleSheet("color: gray;")
        form_custom.addRow("", lbl_custom_hint)
        page_custom.setLayout(form_custom)
        self.stack_ai.addWidget(page_custom)
        
        layout_ai.addWidget(self.stack_ai)
        
        self.lbl_info = QLabel("提示：Azure 提供最精准的音素级打分。OpenAI/Ollama/Custom 使用混合模式。")
        self.lbl_info.setStyleSheet("color: #666; font-style: italic; margin-top: 10px;")
        layout_ai.addWidget(self.lbl_info)
        layout_ai.addStretch()
        
        self.tabs.addTab(tab_ai, "AI引擎")
        
        # --- TAB 4: 高级 ---
        tab_dev = QWidget()
        layout_dev = QVBoxLayout(tab_dev)
        
        grp_scoring = QGroupBox("评分灵敏度")
        form_scoring = QFormLayout()
        
        self.dspin_threshold = QDoubleSpinBox()
        self.dspin_threshold.setRange(0.1, 1.0)
        self.dspin_threshold.setSingleStep(0.05)
        self.dspin_threshold.setValue(0.80)
        self.dspin_threshold.setToolTip("越低越容易通过。默认 0.8")
        form_scoring.addRow("自信度门槛:", self.dspin_threshold)
        
        self.spin_penalty = QSpinBox()
        self.spin_penalty.setRange(0, 500)
        self.spin_penalty.setValue(100)
        self.spin_penalty.setToolTip("模糊发音扣分越多越严格。默认 100")
        form_scoring.addRow("模糊扣分力度:", self.spin_penalty)
        
        self.chk_strict_cap = QCheckBox("90分以上需要高自信度才能给")
        self.chk_strict_cap.setChecked(True)
        form_scoring.addRow("严选模式:", self.chk_strict_cap)
        
        grp_scoring.setLayout(form_scoring)
        layout_dev.addWidget(grp_scoring)
        
        lbl_dev_hint = QLabel("如果觉得 AI 打分太严或太松，可以调整以上参数。\n默认值：门槛 0.8 / 扣分 100")
        lbl_dev_hint.setStyleSheet("color: gray;")
        layout_dev.addWidget(lbl_dev_hint)
        
        layout_dev.addStretch()
        self.tabs.addTab(tab_dev, "高级")

        # --- Bottom Buttons ---
        btn_box = QHBoxLayout()
        btn_box.addStretch()
        
        btn_save = QPushButton("保存设置")
        btn_save.clicked.connect(self.save_settings)
        btn_save.setStyleSheet("background-color: #4CAF50; color: white; padding: 6px 15px; font-weight: bold;")
        btn_box.addWidget(btn_save)
        
        main_layout.addLayout(btn_box)
        
        # Initialize
        self.refresh_group_list()
        self._refresh_bank_table()
        
        if self.quiz_engine:
            self.quiz_engine.bank_progress_update.connect(self._on_bank_progress)
            self.quiz_engine.bank_generation_done.connect(self._on_bank_done)
            self.quiz_engine.bank_generation_error.connect(self._on_bank_error)

    def refresh_devices(self):
        self.combo_devices.clear()
        devices = self.recorder.get_input_devices()
        for idx, name in devices:
            self.combo_devices.addItem(name, idx)
            
    def update_ai_fields(self, index):
        self.stack_ai.setCurrentIndex(index)

    def fetch_models(self):
        base_url = self.txt_custom_base.text().strip()
        api_key = self.txt_custom_key.text().strip() or "not-needed"
        
        if not base_url:
            QMessageBox.warning(self, "错误", "请先输入接口地址。")
            return
        
        models_url = base_url.rstrip("/")
        if not models_url.endswith("/models"):
            models_url += "/models"
        
        self.btn_fetch_models.setEnabled(False)
        self.btn_fetch_models.setText("获取中...")
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        QApplication.processEvents()
        
        try:
            headers = {"Authorization": f"Bearer {api_key}"}
            resp = requests.get(models_url, headers=headers, timeout=10)
            resp.raise_for_status()
            
            data = resp.json()
            model_ids = [m.get("id", "") for m in data.get("data", []) if m.get("id")]
            
            current_text = self.combo_custom_model.currentText()
            self.combo_custom_model.clear()
            for mid in model_ids:
                self.combo_custom_model.addItem(mid)
            
            if current_text:
                idx = self.combo_custom_model.findText(current_text)
                if idx >= 0:
                    self.combo_custom_model.setCurrentIndex(idx)
                else:
                    self.combo_custom_model.setEditText(current_text)
            
            QMessageBox.information(self, "成功", f"找到 {len(model_ids)} 个模型。")
            
        except requests.exceptions.ConnectionError:
            QMessageBox.warning(self, "连接失败", "无法连接到 API，请检查：\n1. 接口地址是否正确\n2. 服务是否正在运行")
        except requests.exceptions.Timeout:
            QMessageBox.warning(self, "超时", "请求超时，服务器可能负载过高。")
        except Exception as e:
            QMessageBox.warning(self, "错误", f"获取模型列表失败：\n{e}")
        finally:
            self.btn_fetch_models.setEnabled(True)
            self.btn_fetch_models.setText("获取模型列表")
            QApplication.restoreOverrideCursor()

    def load_settings(self):
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r') as f:
                    config = json.load(f)
                    
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
                    
                    self.spin_blank_count.setValue(config.get("quiz_blank_count", 1))
                    
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
                    
                    self.txt_custom_base.setText(config.get("custom_base", "http://localhost:8080/v1"))
                    self.txt_custom_key.setText(config.get("custom_key", ""))
                    custom_model = config.get("custom_model", "")
                    if custom_model:
                        self.combo_custom_model.setEditText(custom_model)
                    
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

            "quiz_blank_count": self.spin_blank_count.value(),

            "ai_provider": self.combo_provider.currentText(),
            "stt_provider": self.combo_stt.currentText(),
            
            "azure_key": self.txt_azure_key.text().strip(),
            "azure_region": self.txt_azure_region.text().strip(),
            
            "openai_key": self.txt_openai_key.text().strip(),
            "openai_base": self.txt_openai_base.text().strip(),
            "openai_model": self.txt_openai_model.text().strip(),
            
            "ollama_base": self.txt_ollama_base.text().strip(),
            "ollama_model": self.txt_ollama_model.text().strip(),
            
            "custom_base": self.txt_custom_base.text().strip(),
            "custom_model": self.combo_custom_model.currentText().strip(),
            "custom_key": self.txt_custom_key.text().strip(),
            
            "scoring_threshold": self.dspin_threshold.value(),
            "scoring_penalty": self.spin_penalty.value(),
            "scoring_strict_cap": self.chk_strict_cap.isChecked(),
            
            "active_groups": [self.list_groups.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.list_groups.count()) 
                              if self.list_groups.item(i).checkState() == Qt.CheckState.Checked]
        }
        
        try:
            with open(self.config_file, 'w') as f:
                json.dump(config, f)
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "错误", str(e))

    def clear_database(self):
        confirm = QMessageBox.question(self, "确认", "删除所有词库？此操作不可恢复。", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if confirm == QMessageBox.StandardButton.Yes:
            self.manager.clear_all_exercises()
            self.refresh_group_list()

    def reset_progress(self):
        confirm = QMessageBox.question(self, "确认", "重置所有练习进度？词库内容会保留。", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if confirm == QMessageBox.StandardButton.Yes:
            self.manager.reset_stats()
            QMessageBox.information(self, "完成", "进度已重置。")

    def refresh_group_list(self):
        groups = self.manager.get_groups()
        word_counts = self.manager.get_group_word_counts()
        current_config = {}
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r') as f:
                    current_config = json.load(f)
            except Exception as e:
                print(f"[SettingsDialog] Error loading config for groups: {e}")

        active_groups = current_config.get("active_groups", [])
        auto_check = len(active_groups) == 0
        
        self.list_groups.blockSignals(True)
        self.list_groups.clear()
        for g_name in groups:
            count = word_counts.get(g_name, 0)
            item = QListWidgetItem(f"{g_name}  ({count} 条)")
            item.setData(Qt.ItemDataRole.UserRole, g_name)  # Store raw group name
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            if g_name in active_groups or auto_check:
                item.setCheckState(Qt.CheckState.Checked)
            else:
                item.setCheckState(Qt.CheckState.Unchecked)
            self.list_groups.addItem(item)
        self.list_groups.blockSignals(False)
        self._on_group_check_changed()  # Update spin max initially
    
    def _on_group_check_changed(self, item=None):
        """Update spin_bank_count max based on total word count of checked groups."""
        word_counts = self.manager.get_group_word_counts()
        total = 0
        for i in range(self.list_groups.count()):
            li = self.list_groups.item(i)
            if li.checkState() == Qt.CheckState.Checked:
                g_name = li.data(Qt.ItemDataRole.UserRole)
                total += word_counts.get(g_name, 0)
        
        if total < 5:
            total = 5
        self.spin_bank_count.setMaximum(total)
        # If "全部" is checked, set value to total
        if self.chk_all_bank.isChecked():
            self.spin_bank_count.setValue(total)
        elif self.spin_bank_count.value() > total:
            self.spin_bank_count.setValue(total)
    
    def _on_all_bank_toggled(self, checked):
        """Toggle spin_bank_count disabled when '全部' is checked."""
        self.spin_bank_count.setEnabled(not checked)
        if checked:
            # Set to current max (total word count of selected groups)
            self.spin_bank_count.setValue(self.spin_bank_count.maximum())
            
    def delete_selected_group(self):
        item = self.list_groups.currentItem()
        if item:
            g_name = item.data(Qt.ItemDataRole.UserRole)
            if QMessageBox.question(self, "删除", f"确认删除分组 '{g_name}'？") == QMessageBox.StandardButton.Yes:
                self.manager.delete_group(g_name)
                self.refresh_group_list()

    def open_database_editor(self):
        from src.ui.database_editor import DatabaseEditor
        editor = DatabaseEditor(self, manager=self.manager)
        editor.exec()
        self.refresh_group_list()

    # ========== 题库管理 ==========
    
    def _refresh_bank_table(self):
        if not self.quiz_engine:
            self.table_banks.setRowCount(0)
            return
        
        banks = self.quiz_engine.get_all_banks()
        self.table_banks.setRowCount(len(banks))
        
        for row, bank in enumerate(banks):
            bank_id = bank.get("id", "")
            
            # Name
            name_item = QTableWidgetItem(bank.get("name", "未命名"))
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table_banks.setItem(row, 0, name_item)
            
            # Groups
            groups_str = ", ".join(bank.get("source_groups", []))
            groups_item = QTableWidgetItem(groups_str)
            groups_item.setFlags(groups_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table_banks.setItem(row, 1, groups_item)
            
            # Question count
            count_item = QTableWidgetItem(str(bank.get("question_count", 0)))
            count_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            count_item.setFlags(count_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table_banks.setItem(row, 2, count_item)
            
            # Created date
            created = bank.get("created_at", "")
            if created:
                try:
                    from datetime import datetime
                    dt = datetime.fromisoformat(created)
                    created = dt.strftime("%m/%d %H:%M")
                except Exception:
                    pass
            created_item = QTableWidgetItem(created)
            created_item.setFlags(created_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table_banks.setItem(row, 3, created_item)
            
            # View button
            btn_view = QPushButton("查看")
            btn_view.setStyleSheet("color: #1565C0; border: 1px solid #1565C0; border-radius: 3px; padding: 3px 8px;")
            btn_view.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_view.clicked.connect(lambda checked, bid=bank_id: self._view_bank(bid))
            self.table_banks.setCellWidget(row, 4, btn_view)
            
            # Rename button
            btn_rename = QPushButton("改名")
            btn_rename.setStyleSheet("color: #F57F17; border: 1px solid #F57F17; border-radius: 3px; padding: 3px 8px;")
            btn_rename.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_rename.clicked.connect(lambda checked, bid=bank_id, n=bank.get("name",""): self._rename_bank(bid, n))
            self.table_banks.setCellWidget(row, 5, btn_rename)
            
            # Delete button
            btn_delete = QPushButton("删除")
            btn_delete.setStyleSheet("color: #C62828; border: 1px solid #C62828; border-radius: 3px; padding: 3px 8px;")
            btn_delete.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_delete.clicked.connect(lambda checked, bid=bank_id: self._delete_bank(bid))
            self.table_banks.setCellWidget(row, 6, btn_delete)
    
    def _view_bank(self, bank_id):
        """Open a dialog showing all questions in the bank."""
        if not self.quiz_engine:
            return
        bank = self.quiz_engine.get_bank_by_id(bank_id)
        if not bank:
            QMessageBox.warning(self, "错误", "题库不存在。")
            return
        
        dialog = QDialog(self)
        dialog.setWindowTitle(f"题库内容 - {bank.get('name', '')}")
        dialog.resize(600, 500)
        layout = QVBoxLayout(dialog)
        
        # Header info
        info = QLabel(f"题库: {bank.get('name', '')}\n题数: {bank.get('question_count', 0)}")
        info.setStyleSheet("font-size: 14px; color: #333; padding: 5px; background: #E3F2FD; border-radius: 5px;")
        info.setWordWrap(True)
        layout.addWidget(info)
        
        # Scrollable question list
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        
        questions = bank.get("questions", [])
        for i, q in enumerate(questions):
            card = QFrame()
            card.setStyleSheet(f"background: {'#E8F5E9' if q.get('type') == 'zh2en' else '#E3F2FD'}; border-radius: 6px; padding: 5px; margin: 2px;")
            card_layout = QVBoxLayout(card)
            
            qtype = "中译英" if q.get("type") == "zh2en" else "英译中"
            q_text = q.get("question_text", "")
            
            # Question line
            lbl_q = QLabel(f"[{i+1}] [{qtype}] {q_text}")
            lbl_q.setStyleSheet("font-size: 14px; font-weight: bold;")
            lbl_q.setWordWrap(True)
            card_layout.addWidget(lbl_q)
            
            # Answer line
            if q.get("type") == "zh2en":
                answers = q.get("answers", [])
                ans_str = " / ".join(answers) if answers else q.get("answer", "")
                lbl_a = QLabel(f"答案: {ans_str}")
            else:
                lbl_a = QLabel(f"答案: {q.get('answer', '')}    选项: {' | '.join(q.get('options', []))}")
            lbl_a.setStyleSheet("font-size: 13px; color: #2E7D32;")
            lbl_a.setWordWrap(True)
            card_layout.addWidget(lbl_a)
            
            # Hint
            hint = q.get("chinese_hint", "")
            if hint:
                lbl_h = QLabel(f"提示: {hint}")
                lbl_h.setStyleSheet("font-size: 12px; color: #666;")
                card_layout.addWidget(lbl_h)
            
            content_layout.addWidget(card)
        
        content_layout.addStretch()
        scroll.setWidget(content)
        layout.addWidget(scroll)
        
        # Close button
        btn_close = QPushButton("关闭")
        btn_close.clicked.connect(dialog.accept)
        layout.addWidget(btn_close)
        
        dialog.exec()
    
    def _rename_bank(self, bank_id, current_name):
        """Rename a quiz bank via input dialog."""
        new_name, ok = QInputDialog.getText(self, "改名", "新名称:", text=current_name)
        if ok and new_name.strip():
            if self.quiz_engine and self.quiz_engine.rename_bank(bank_id, new_name.strip()):
                self._refresh_bank_table()
    
    def _generate_quiz_bank(self):
        if not self.quiz_engine:
            QMessageBox.warning(self, "错误", "题库引擎不可用。")
            return
        
        active_groups = [
            self.list_groups.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.list_groups.count())
            if self.list_groups.item(i).checkState() == Qt.CheckState.Checked
        ]
        
        if not active_groups:
            QMessageBox.warning(self, "错误", "请先在上方勾选至少一个词库分组。")
            return
        
        count = self.spin_bank_count.value()
        
        self.bank_progress.setVisible(True)
        self.bank_progress.setValue(0)
        self.lbl_bank_status.setVisible(True)
        self.lbl_bank_status.setText(f"正在从 {len(active_groups)} 个分组生成 {count} 道题...")
        self.lbl_bank_status.setStyleSheet("color: #666; font-size: 13px;")
        self.btn_generate_bank.setEnabled(False)
        
        self.quiz_engine.generate_bank(active_groups, count)
    
    def _on_bank_progress(self, generated, total):
        self.bank_progress.setMaximum(total)
        self.bank_progress.setValue(generated)
        self.lbl_bank_status.setText(f"已生成 {generated}/{total} 道题...")
    
    def _on_bank_done(self, bank):
        self.bank_progress.setVisible(False)
        self.lbl_bank_status.setText(f"✅ 已生成: {bank.get('name', '')} ({bank.get('question_count', 0)} 题)")
        self.lbl_bank_status.setStyleSheet("color: #2E7D32; font-size: 13px; font-weight: bold;")
        self.btn_generate_bank.setEnabled(True)
        self._refresh_bank_table()
        QMessageBox.information(self, "成功", f"题库已生成：\n{bank.get('name', '')}\n{bank.get('question_count', 0)} 道题已保存。")
    
    def _on_bank_error(self, error_msg):
        self.bank_progress.setVisible(False)
        self.lbl_bank_status.setText(f"❌ 错误: {error_msg}")
        self.lbl_bank_status.setStyleSheet("color: #C62828; font-size: 13px;")
        self.btn_generate_bank.setEnabled(True)
        QMessageBox.critical(self, "生成失败", error_msg)
    
    def _delete_bank(self, bank_id):
        reply = QMessageBox.question(
            self, "删除题库",
            "确认删除此题库？不可恢复。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            if self.quiz_engine and self.quiz_engine.delete_bank(bank_id):
                self._refresh_bank_table()
    
    def get_settings(self):
        if os.path.exists(self.config_file):
            with open(self.config_file, 'r') as f:
                return json.load(f)
        return {}
