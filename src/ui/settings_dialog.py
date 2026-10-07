from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton, 
                             QLabel, QComboBox, QLineEdit, QGroupBox, QFormLayout, QMessageBox, QStackedWidget, QWidget, QSpinBox,
                             QListWidget, QListWidgetItem, QCheckBox, QTabWidget, QDoubleSpinBox,
                             QTableWidget, QTableWidgetItem, QHeaderView, QProgressBar, QFrame, QInputDialog, QScrollArea)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QApplication
from src.core.audio_recorder import AudioRecorder
import os
import json
import requests

from src.utils import get_user_data_path
from .styles import AppStyles, FONT_FALLBACK, PAPER, DESK, INK, INK_SOFT, MANGO, MANGO_DK, LEAF, CLAY, LEAF_SOFT, CLAY_SOFT, DESK_LINE, SP_1, SP_2, SP_3, SP_4, SP_5, RADIUS, RADIUS_SM, SIZE_BODY, SIZE_UI, SIZE_TITLE

class SettingsDialog(QDialog):
    def __init__(self, parent=None, audio_recorder=None, exercise_manager=None, quiz_engine=None, oral_engine=None, scenario_engine=None):
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.resize(650, 580)
        self.setStyleSheet(f"QDialog {{ background-color: {PAPER}; }} {AppStyles.CHECKBOX} {AppStyles.GROUP_BOX} {AppStyles.INPUT}")
        self.recorder = audio_recorder or AudioRecorder()
        self.quiz_engine = quiz_engine
        self.oral_engine = oral_engine
        self.scenario_engine = scenario_engine
        if exercise_manager:
            self.manager = exercise_manager
        else:
            from src.core.exercise_manager import ExerciseManager
            self.manager = ExerciseManager(get_user_data_path("words.json"))
            
        self.config_file = get_user_data_path("config.json")
        self._saved_stt_provider = "Local Whisper (GPU)"  # Default, will be updated on load
        
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
        
        # 学生姓名
        self.txt_student_name = QLineEdit()
        self.txt_student_name.setPlaceholderText("例如: Edward")
        self.txt_student_name.setToolTip("AI家庭教师模式中用于称呼学生的名字")
        form_audio.addRow("学生姓名:", self.txt_student_name)
        
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
        
        self.chk_auto_default = QCheckBox("默认开启自动录音（发音练习连读 / 情景会话 B 角说完即录）")
        self.chk_auto_default.setToolTip(
            "勾选后：\n"
            "  • 发音练习：题目播放完毕后自动开始录音并连续推进\n"
            "  • 情景会话：B 角（你扮演）的提示语播放完毕后自动开始录音\n"
            "可在练习页通过快捷键临时切换。"
        )
        form_audio.addRow("", self.chk_auto_default)
        
        # 评价页停留时间（0=手动）
        dwell_row = QHBoxLayout()
        self.spin_result_dwell = QSpinBox()
        self.spin_result_dwell.setRange(0, 30)
        self.spin_result_dwell.setValue(0)
        self.spin_result_dwell.setSuffix(" 秒")
        self.spin_result_dwell.setToolTip(
            "发音练习评价页自动进入下一题的停留时间。\n"
            "设为 0 表示手动模式：按空格键 / Enter / 点击按钮进入下一题。"
        )
        dwell_row.addWidget(self.spin_result_dwell)
        dwell_row.addWidget(QLabel("（0=手动，按空格切换）"))
        dwell_row.addStretch()
        form_audio.addRow("评价页停留:", dwell_row)
        
        self.combo_feedback_lang = QComboBox()
        self.combo_feedback_lang.addItem("英文（简洁有力）", "en")
        self.combo_feedback_lang.addItem("中文（可爱鼓励）", "zh")
        form_audio.addRow("鼓励语音:", self.combo_feedback_lang)
        
        self.combo_tts = QComboBox()
        self.combo_tts.addItems([
            "Auto (Best available)",
            "CosyVoice (本地中英混合 - AI家教推荐)",
            "Kokoro (Local Neural - Best Quality)", 
            "Piper (Local Fast - Low Latency)", 
            "Edge TTS (Cloud - Good Quality)", 
            "System (Offline - Robot)"
        ])
        form_audio.addRow("语音引擎:", self.combo_tts)
        
        # CosyVoice server config
        self.txt_cosyvoice_url = QLineEdit("http://localhost:50000")
        self.txt_cosyvoice_url.setPlaceholderText("CosyVoice 服务器地址")
        form_audio.addRow("CosyVoice地址:", self.txt_cosyvoice_url)
        
        self.txt_cosyvoice_spk = QLineEdit("英文女")
        self.txt_cosyvoice_spk.setPlaceholderText("说话ID，如: 英文女, 英文男, 中文女, 中文男")
        form_audio.addRow("CosyVoice音色:", self.txt_cosyvoice_spk)
        
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
        self.list_groups.setStyleSheet(AppStyles.LIST_WIDGET)
        self.list_groups.itemChanged.connect(self._on_group_check_changed)
        layout_data.addWidget(self.list_groups)
        
        hbox_data_btns = QHBoxLayout()
        btn_edit_db = QPushButton("编辑词库")
        btn_edit_db.setStyleSheet(AppStyles.CARD_BUTTON)
        btn_edit_db.clicked.connect(self.open_database_editor)
        hbox_data_btns.addWidget(btn_edit_db)
        
        btn_delete_group = QPushButton("删除选中")
        btn_delete_group.setStyleSheet(AppStyles.CARD_BUTTON)
        btn_delete_group.clicked.connect(self.delete_selected_group)
        hbox_data_btns.addWidget(btn_delete_group)
        
        btn_clear_data = QPushButton("清空全部")
        btn_clear_data.setStyleSheet(f"QPushButton {{ background-color: {CLAY_SOFT}; color: {CLAY}; border: 1px solid {CLAY}; border-radius: {RADIUS}px; padding: {SP_2}px {SP_3}px; font-family: {FONT_FALLBACK}; font-weight: 600; }} QPushButton:hover {{ background-color: {CLAY}; color: #FBFAF5; }}")
        btn_clear_data.clicked.connect(self.clear_database)
        hbox_data_btns.addWidget(btn_clear_data)
        
        btn_reset_stats = QPushButton("重置进度")
        btn_reset_stats.setStyleSheet(AppStyles.CARD_BUTTON)
        btn_reset_stats.clicked.connect(self.reset_progress)
        hbox_data_btns.addWidget(btn_reset_stats)
        
        layout_data.addLayout(hbox_data_btns)
        
        # ========== 预生成题库区域 ==========
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        layout_data.addWidget(separator)
        
        lbl_bank_title = QLabel("预生成题库")
        lbl_bank_title.setStyleSheet(f"font-family: {FONT_FALLBACK}; font-size: {SIZE_UI}px; font-weight: 700; color: {INK}; margin-top: {SP_2}px;")
        layout_data.addWidget(lbl_bank_title)
        
        # Type selector row
        type_row = QHBoxLayout()
        type_row.addWidget(QLabel("题库类型:"))
        self.combo_bank_type = QComboBox()
        self.combo_bank_type.addItems(["中英互译题库", "口语测试题库", "情景会话脚本"])
        self.combo_bank_type.setStyleSheet(f"font-family: {FONT_FALLBACK}; font-size: {SIZE_BODY}px; padding: {SP_2}px; min-width: 180px;")
        self.combo_bank_type.currentIndexChanged.connect(self._on_bank_type_changed)
        type_row.addWidget(self.combo_bank_type)
        type_row.addStretch()
        layout_data.addLayout(type_row)
        
        # Generate controls (shared row, content changes based on type)
        gen_row = QHBoxLayout()
        
        # Quiz-specific: blank count
        self.lbl_blank_count = QLabel("填空数:")
        gen_row.addWidget(self.lbl_blank_count)
        self.spin_blank_count = QSpinBox()
        self.spin_blank_count.setRange(1, 5)
        self.spin_blank_count.setValue(1)
        self.spin_blank_count.setToolTip("完形填空留几个空")
        gen_row.addWidget(self.spin_blank_count)
        self.lbl_blank_unit = QLabel("个空")
        gen_row.addWidget(self.lbl_blank_unit)
        
        gen_row.addSpacing(10)
        gen_row.addWidget(QLabel("题/句数:"))
        self.spin_bank_count = QSpinBox()
        self.spin_bank_count.setRange(5, 10000)
        self.spin_bank_count.setValue(20)
        self.spin_bank_count.setToolTip("题库包含的题目数量")
        gen_row.addWidget(self.spin_bank_count)
        self.lbl_count_unit = QLabel("题")
        gen_row.addWidget(self.lbl_count_unit)
        
        self.chk_all_bank = QCheckBox("全部")
        self.chk_all_bank.setToolTip("使用所选词库的全部词条数")
        self.chk_all_bank.toggled.connect(self._on_all_bank_toggled)
        gen_row.addWidget(self.chk_all_bank)
        
        self.btn_generate_bank = QPushButton("生成题库")
        self.btn_generate_bank.setStyleSheet(AppStyles.BIG_BUTTON)
        self.btn_generate_bank.clicked.connect(self._generate_bank)
        gen_row.addWidget(self.btn_generate_bank)
        layout_data.addLayout(gen_row)
        
        # Progress bar (hidden initially)
        self.bank_progress = QProgressBar()
        self.bank_progress.setVisible(False)
        self.bank_progress.setStyleSheet(AppStyles.PROGRESS_BAR)
        layout_data.addWidget(self.bank_progress)
        
        self.lbl_bank_status = QLabel("")
        self.lbl_bank_status.setStyleSheet(f"font-family: {FONT_FALLBACK}; color: {INK_SOFT}; font-size: {SIZE_BODY}px;")
        self.lbl_bank_status.setVisible(False)
        layout_data.addWidget(self.lbl_bank_status)
        
        # Unified bank table: Name / Type / Source / Count / Created / View / Rename / Delete
        self.table_banks = QTableWidget()
        self.table_banks.setStyleSheet(AppStyles.TABLE)
        self.table_banks.setColumnCount(8)
        self.table_banks.setHorizontalHeaderLabels(["题库名称", "类型", "来源", "题数", "创建时间", "查看", "改名", "删除"])
        self.table_banks.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in [1, 5, 6, 7]:
            self.table_banks.horizontalHeader().setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        self.table_banks.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        layout_data.addWidget(self.table_banks)
        
        self.tabs.addTab(tab_data, "题库")
        
        # --- TAB 3: AI引擎 ---
        tab_ai = QWidget()
        layout_ai = QVBoxLayout(tab_ai)
        
        form_provider = QFormLayout()

        # Top-level engine selector: which scoring engine to use.
        self.combo_assessor_engine = QComboBox()
        self.combo_assessor_engine.addItem("GOP 音素级评分（推荐）", "gop")
        self.combo_assessor_engine.addItem("Azure Speech（云端商用）", "azure")
        self.combo_assessor_engine.addItem("MiniCPM-o（Omni 多模态评分）", "omni")
        form_provider.addRow("评分引擎:", self.combo_assessor_engine)

        # STT engine (only used when LLM provider needs it; GOP has its own ASR).
        self.combo_stt = QComboBox()
        self.combo_stt.addItems(["Google Web Speech (Cloud/Free)", "Local Whisper (GPU)"])
        form_provider.addRow("语音识别引擎:", self.combo_stt)

        # Whisper model size selector
        self.combo_whisper_size = QComboBox()
        self.combo_whisper_size.addItems(["tiny", "base", "small", "medium", "large", "large-v3"])
        self.combo_whisper_size.setCurrentText("medium")
        self.combo_whisper_size.setToolTip(
            "tiny/base: 快但不准 | small: 平衡 | medium: 推荐(GPU≥5GB) | large: 最准但慢\n"
            "RTX 5070 12GB 推荐 medium"
        )
        form_provider.addRow("Whisper 模型:", self.combo_whisper_size)
        
        self.combo_provider = QComboBox()
        self.combo_provider.addItems(["Azure Speech (Recommended)", "OpenAI / GPT", "Ollama (Local)", "Custom (Local API)", "MiniCPM-o (Omni 本地多模态)"])
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
        lbl_ollama_hint.setStyleSheet(AppStyles.BODY_LABEL)
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
        self.btn_fetch_models.setStyleSheet(AppStyles.CARD_BUTTON)
        self.btn_fetch_models.clicked.connect(self.fetch_models)
        model_row.addWidget(self.btn_fetch_models)
        
        form_custom.addRow("模型:", model_row)
        
        lbl_custom_hint = QLabel("提示：支持 llama.cpp、vLLM 等 OpenAI 兼容 API。\n图片识别（多模态）需使用支持 vision 的模型。")
        lbl_custom_hint.setStyleSheet(AppStyles.BODY_LABEL)
        form_custom.addRow("", lbl_custom_hint)
        page_custom.setLayout(form_custom)
        self.stack_ai.addWidget(page_custom)

        # Page 4: MiniCPM-o (Omni)
        page_omni = QWidget()
        form_omni = QFormLayout()

        self.txt_omni_host = QLineEdit("127.0.0.1")
        form_omni.addRow("服务地址:", self.txt_omni_host)

        omni_ports_row = QHBoxLayout()
        self.spin_omni_chat_port = QSpinBox()
        self.spin_omni_chat_port.setRange(1, 65535)
        self.spin_omni_chat_port.setValue(18400)
        self.spin_omni_chat_port.setStyleSheet(AppStyles.INPUT)
        omni_ports_row.addWidget(QLabel("对话端口:"))
        omni_ports_row.addWidget(self.spin_omni_chat_port)
        self.spin_omni_auth_port = QSpinBox()
        self.spin_omni_auth_port.setRange(1, 65535)
        self.spin_omni_auth_port.setValue(18500)
        self.spin_omni_auth_port.setStyleSheet(AppStyles.INPUT)
        omni_ports_row.addWidget(QLabel("认证端口:"))
        omni_ports_row.addWidget(self.spin_omni_auth_port)
        omni_ports_row.addStretch()
        form_omni.addRow("端口:", omni_ports_row)

        self.txt_omni_username = QLineEdit("admin")
        self.txt_omni_username.setStyleSheet(AppStyles.INPUT)
        form_omni.addRow("用户名:", self.txt_omni_username)

        self.txt_omni_password = QLineEdit("admin123")
        self.txt_omni_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.txt_omni_password.setStyleSheet(AppStyles.INPUT)
        form_omni.addRow("密码:", self.txt_omni_password)

        self.txt_omni_model = QLineEdit("minicpm-o45")
        self.txt_omni_model.setStyleSheet(AppStyles.INPUT)
        form_omni.addRow("模型:", self.txt_omni_model)

        self.chk_omni_tts = QCheckBox("使用 Omni 返回的语音（而非本地 TTS 合成）")
        self.chk_omni_tts.setChecked(True)
        self.chk_omni_tts.setStyleSheet(AppStyles.CHECKBOX)
        form_omni.addRow("", self.chk_omni_tts)

        # Connection test button
        self.btn_omni_test = QPushButton("测试连接")
        self.btn_omni_test.setStyleSheet(AppStyles.CARD_BUTTON)
        self.btn_omni_test.clicked.connect(self._test_omni_connection)
        form_omni.addRow("", self.btn_omni_test)

        lbl_omni_hint = QLabel("提示：需先本地启动 MiniCPM-o 4.5 服务。Omni 可用于对话和（可选）发音评分。")
        lbl_omni_hint.setStyleSheet(AppStyles.BODY_LABEL)
        form_omni.addRow("", lbl_omni_hint)

        page_omni.setLayout(form_omni)
        self.stack_ai.addWidget(page_omni)

        layout_ai.addWidget(self.stack_ai)

        # ========== GOP 评分独立设置区 ==========
        gop_separator = QFrame()
        gop_separator.setFrameShape(QFrame.Shape.HLine)
        gop_separator.setFrameShadow(QFrame.Shadow.Sunken)
        layout_ai.addWidget(gop_separator)

        gop_title = QLabel("GOP 音素级发音评分（核心）")
        gop_title.setStyleSheet(f"font-family: {FONT_FALLBACK}; font-size: 15px; font-weight: 700; color: {INK}; padding: {SP_1}px;")
        layout_ai.addWidget(gop_title)

        form_gop = QFormLayout()

        self.combo_gop_mode = QComboBox()
        self.combo_gop_mode.addItem("本地（local）", "local")
        self.combo_gop_mode.addItem("远程（remote）", "remote")
        form_gop.addRow("运行模式:", self.combo_gop_mode)

        self.txt_gop_remote_url = QLineEdit("http://192.168.50.200:18200")
        form_gop.addRow("远程地址:", self.txt_gop_remote_url)

        self.txt_gop_remote_key = QLineEdit()
        self.txt_gop_remote_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.txt_gop_remote_key.setPlaceholderText("（可选）")
        form_gop.addRow("远程密钥:", self.txt_gop_remote_key)

        self.combo_gop_device = QComboBox()
        self.combo_gop_device.addItems(["auto", "cpu", "cuda"])
        form_gop.addRow("推理设备:", self.combo_gop_device)

        self.txt_gop_model = QLineEdit("facebook/wav2vec2-lv-60-espeak-cv-ft")
        form_gop.addRow("对齐模型:", self.txt_gop_model)

        self.txt_hf_token = QLineEdit()
        self.txt_hf_token.setEchoMode(QLineEdit.EchoMode.Password)
        self.txt_hf_token.setPlaceholderText("（可选）首次下载 HuggingFace 模型需要，填一次即可")
        form_gop.addRow("HF Token:", self.txt_hf_token)

        lbl_gop_hint = QLabel(
            "提示：本地模式首次启动会下载 wav2vec2 phoneme 模型（约 315MB）。\n"
            "若首次下载报 401/403，请在 HF Token 中填入你的 HuggingFace access token。\n"
            "远程模式需在服务器运行 src.server.gop_server（端口 18200）。\n"
            "本地与远程使用同一 schema、同一 model fingerprint，分数可交叉比对。"
        )
        lbl_gop_hint.setStyleSheet(AppStyles.BODY_LABEL)
        lbl_gop_hint.setWordWrap(True)
        form_gop.addRow("", lbl_gop_hint)

        layout_ai.addLayout(form_gop)

        # ========== GOP 打分校准（可调参数） ==========
        calib_title = QLabel("GOP 打分校准")
        calib_title.setStyleSheet(
            f"font-family: {FONT_FALLBACK}; font-size: 15px; font-weight: 700; color: {INK}; "
            f"padding: {SP_3}px 0 {SP_1}px 0;"
        )
        layout_ai.addWidget(calib_title)

        form_calib = QFormLayout()
        form_calib.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        # 1. 置信度阈值（决定多少分才算"读对"，最关键）
        self.spin_conf_threshold = QDoubleSpinBox()
        self.spin_conf_threshold.setRange(0.05, 0.60)
        self.spin_conf_threshold.setSingleStep(0.05)
        self.spin_conf_threshold.setDecimals(2)
        self.spin_conf_threshold.setValue(0.30)
        self.spin_conf_threshold.setToolTip(
            "对齐置信度低于此阈值 -> 判定为删除错误。\n"
            "调低（如 0.15）= 打分宽松，适合儿童/噪声麦克风。\n"
            "调高（如 0.45）= 打分严格，适合精读训练。"
        )
        form_calib.addRow("发音判定阈值:", self.spin_conf_threshold)

        # 2. 删除惩罚指数（整体分惩罚力度）
        self.spin_conf_exponent = QDoubleSpinBox()
        self.spin_conf_exponent.setRange(0.5, 2.0)
        self.spin_conf_exponent.setSingleStep(0.1)
        self.spin_conf_exponent.setDecimals(2)
        self.spin_conf_exponent.setValue(1.2)
        self.spin_conf_exponent.setToolTip(
            "删除错误对整体分的惩罚指数。\n"
            "0.5 = 非常宽松；1.0 = 线性；1.2 = 默认温和；2.0 = 苛刻。\n"
            "公式：overall = base × (matched/expected)^指数。"
        )
        form_calib.addRow("删除惩罚强度:", self.spin_conf_exponent)

        # 3. 低置信音素权重
        self.spin_low_conf_weight = QDoubleSpinBox()
        self.spin_low_conf_weight.setRange(0.0, 0.5)
        self.spin_low_conf_weight.setSingleStep(0.05)
        self.spin_low_conf_weight.setDecimals(2)
        self.spin_low_conf_weight.setValue(0.10)
        self.spin_low_conf_weight.setToolTip(
            "未完全读出的音素对单词分的参与权重。\n"
            "0 = 完全忽略（虚高）；0.1 = 默认；0.3 = 较强感知。"
        )
        form_calib.addRow("低置信音素权重:", self.spin_low_conf_weight)

        # 4. sigmoid K（曲线陡度）
        self.spin_sigmoid_k = QDoubleSpinBox()
        self.spin_sigmoid_k.setRange(0.3, 3.0)
        self.spin_sigmoid_k.setSingleStep(0.1)
        self.spin_sigmoid_k.setDecimals(2)
        self.spin_sigmoid_k.setValue(1.5)
        self.spin_sigmoid_k.setToolTip(
            "GOP 分数映射曲线的陡度。\n"
            "调小 = 打分宽松（更多中分）；调大 = 打分严格（两极分化）。"
        )
        form_calib.addRow("分数曲线陡度 (K):", self.spin_sigmoid_k)

        # 5. sigmoid MID（中心点）
        self.spin_sigmoid_mid = QDoubleSpinBox()
        self.spin_sigmoid_mid.setRange(-5.0, 0.0)
        self.spin_sigmoid_mid.setSingleStep(0.2)
        self.spin_sigmoid_mid.setDecimals(2)
        self.spin_sigmoid_mid.setValue(-2.0)
        self.spin_sigmoid_mid.setToolTip(
            "GOP 分数映射曲线的中心点。\n"
            "调小（如 -3）= 整体抬分；调大（如 -1）= 整体压分。"
        )
        form_calib.addRow("分数曲线中心 (Mid):", self.spin_sigmoid_mid)

        # 6. GOP 保护阈值（儿童/非专业麦克风 核心参数）
        self.spin_gop_floor = QDoubleSpinBox()
        self.spin_gop_floor.setRange(-10.0, 0.0)
        self.spin_gop_floor.setSingleStep(0.5)
        self.spin_gop_floor.setDecimals(2)
        self.spin_gop_floor.setValue(-2.0)
        self.spin_gop_floor.setToolTip(
            "GOP 保护阈值（核心参数，解决'发音标准却得低分'）。\n"
            "当 GOP 低于此值时，用目标音素自身后验概率 P(target)\n"
            "替代 GOP 对比，防止模型对整段音频不确定时系统性压低分数。\n"
            "调小（如 -5）= 保护更激进；调大（如 -1）= 更保守。\n"
            "设为 0 可完全关闭保护。"
        )
        form_calib.addRow("GOP 保护阈值:", self.spin_gop_floor)

        # 重置默认值按钮
        btn_reset_calib = QPushButton("恢复默认")
        btn_reset_calib.setStyleSheet(AppStyles.CARD_BUTTON)
        btn_reset_calib.setToolTip("将以上 5 个参数恢复为项目默认值")
        btn_reset_calib.clicked.connect(self._reset_gop_calib)
        form_calib.addRow("", btn_reset_calib)

        lbl_calib_hint = QLabel(
            "儿童/非专业麦克风 推荐：阈值 0.15、惩罚 1.0、曲线 K 0.8、Mid -3.0、GOP保护 -2.0。\n"
            "    专业录音/精读训练 推荐：阈值 0.40、惩罚 1.5、曲线 K 2.0、Mid -1.5、GOP保护 0。"
        )
        lbl_calib_hint.setStyleSheet(f"font-family: {FONT_FALLBACK}; color: {INK_SOFT}; font-size: 11px;")
        lbl_calib_hint.setWordWrap(True)
        form_calib.addRow("", lbl_calib_hint)

        layout_ai.addLayout(form_calib)

        self.lbl_info = QLabel("提示：默认使用 GOP 客观音素级评分。Azure 仅作为可选商用云端方案。")
        self.lbl_info.setStyleSheet(f"font-family: {FONT_FALLBACK}; color: {INK_SOFT}; font-style: italic; margin-top: {SP_3}px;")
        layout_ai.addWidget(self.lbl_info)
        layout_ai.addStretch()
        
        self.tabs.addTab(tab_ai, "AI引擎")

        # --- Bottom Buttons ---
        btn_box = QHBoxLayout()
        btn_box.addStretch()
        
        btn_save = QPushButton("保存设置")
        btn_save.clicked.connect(self.save_settings)
        btn_save.setStyleSheet(AppStyles.BIG_BUTTON)
        btn_box.addWidget(btn_save)
        
        main_layout.addLayout(btn_box)
        
        # Initialize
        self.refresh_group_list()
        self._refresh_bank_table()
        
        if self.quiz_engine:
            self.quiz_engine.bank_progress_update.connect(self._on_bank_progress)
            self.quiz_engine.bank_generation_done.connect(self._on_bank_done)
            self.quiz_engine.bank_generation_error.connect(self._on_bank_error)
        
        if self.oral_engine:
            self.oral_engine.bank_progress_update.connect(self._on_bank_progress)
            self.oral_engine.bank_generation_done.connect(self._on_bank_done)
            self.oral_engine.bank_generation_error.connect(self._on_bank_error)

        if self.scenario_engine:
            self.scenario_engine.bank_progress_update.connect(self._on_bank_progress)
            self.scenario_engine.bank_generation_done.connect(self._on_bank_done)
            self.scenario_engine.bank_generation_error.connect(self._on_bank_error)

    def refresh_devices(self):
        self.combo_devices.clear()
        devices = self.recorder.get_input_devices()
        for idx, name in devices:
            self.combo_devices.addItem(name, idx)
            
    def update_ai_fields(self, index):
        self.stack_ai.setCurrentIndex(index)

    def _test_omni_connection(self):
        """Test MiniCPM-o connectivity in a background thread."""
        from PyQt6.QtCore import QObject, pyqtSignal

        host = self.txt_omni_host.text().strip() or "127.0.0.1"
        chat_port = int(self.spin_omni_chat_port.value())
        auth_port = int(self.spin_omni_auth_port.value())
        user = self.txt_omni_username.text().strip() or "admin"
        pwd = self.txt_omni_password.text()
        self.btn_omni_test.setEnabled(False)
        self.btn_omni_test.setText("测试中…")

        # A QObject whose pyqtSignal crosses the thread boundary safely
        # (queued connection) — unlike QTimer.singleShot from a plain thread,
        # which has no event loop and never fires.
        class _Worker(QObject):
            finished = pyqtSignal(bool, str)

        self._omni_test_worker = _Worker()
        self._omni_test_worker.finished.connect(self._on_omni_test_done)

        def _run():
            try:
                from src.core.omni_client import OmniClient, OmniConfig
                # Short timeout so a dead server fails fast instead of hanging.
                cfg = OmniConfig(host=host, chat_port=chat_port, auth_port=auth_port,
                                 username=user, password=pwd, connect_timeout=5.0)
                client = OmniClient(cfg)
                st = client.status()
                state = st.get('state', st.get('status', 'ready'))
                self._omni_test_worker.finished.emit(True, f"连接成功！状态: {state}")
            except Exception as e:
                self._omni_test_worker.finished.emit(False, f"连接失败: {e}")

        import threading
        threading.Thread(target=_run, daemon=True).start()

    def _on_omni_test_done(self, ok: bool, msg: str):
        """Re-enable the test button and show the result (main thread)."""
        self.btn_omni_test.setEnabled(True)
        self.btn_omni_test.setText("测试连接")
        if ok:
            QMessageBox.information(self, "Omni 连接", msg)
        else:
            QMessageBox.warning(self, "Omni 连接", msg)

    def fetch_models(self):
        base_url = self.txt_custom_base.text().strip()
        api_key = self.txt_custom_key.text().strip() or "not-needed"
        
        if not base_url:
            QMessageBox.warning(self, "错误", "请先输入接口地址。")
            return
        
        # Normalize URL: remove trailing /v1 or /models, then append /v1/models
        models_url = base_url.rstrip("/")
        if models_url.endswith("/v1/models"):
            pass  # Already correct
        elif models_url.endswith("/v1"):
            models_url += "/models"
        elif models_url.endswith("/models"):
            pass  # Keep as is
        else:
            models_url += "/v1/models"
        
        self.btn_fetch_models.setEnabled(False)
        self.btn_fetch_models.setText("获取中...")
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        QApplication.processEvents()
        
        try:
            headers = {"Authorization": f"Bearer {api_key}"}
            resp = requests.get(models_url, headers=headers, timeout=10)
            
            # Show detailed error if not 200
            if resp.status_code != 200:
                QMessageBox.warning(self, "请求失败", 
                    f"请求地址: {models_url}\n"
                    f"状态码: {resp.status_code}\n"
                    f"响应内容: {resp.text[:500]}")
                return
            
            resp.raise_for_status()
            data = resp.json()
            
            # Try different response formats
            model_ids = []
            if isinstance(data, dict):
                if "data" in data:
                    model_ids = [m.get("id", "") for m in data.get("data", []) if m.get("id")]
                elif "models" in data:
                    model_ids = [m.get("id", "") for m in data.get("models", []) if m.get("id")]
                elif "model" in data:
                    model_ids = [data.get("model", "")]
            elif isinstance(data, list):
                model_ids = [m.get("id", str(m)) if isinstance(m, dict) else str(m) for m in data]
            
            # Extract just the filename (llama.cpp returns full paths like "org--model/file.gguf")
            model_ids = [mid.split("/")[-1] if "/" in mid else mid for mid in model_ids if mid]
            
            if not model_ids:
                QMessageBox.warning(self, "无模型", 
                    f"请求地址: {models_url}\n"
                    f"响应格式异常，原始内容:\n{str(data)[:500]}")
                return
            
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
            
        except requests.exceptions.ConnectionError as e:
            QMessageBox.warning(self, "连接失败", 
                f"请求地址: {models_url}\n"
                f"无法连接到 API，请检查：\n"
                f"1. 接口地址是否正确\n"
                f"2. 服务是否正在运行\n\n"
                f"详细错误: {str(e)[:200]}")
        except requests.exceptions.Timeout:
            QMessageBox.warning(self, "超时", 
                f"请求地址: {models_url}\n"
                f"请求超时，服务器可能负载过高。")
        except Exception as e:
            QMessageBox.warning(self, "错误", 
                f"请求地址: {models_url}\n"
                f"获取模型列表失败：\n{str(e)[:300]}")
        finally:
            self.btn_fetch_models.setEnabled(True)
            self.btn_fetch_models.setText("获取模型列表")
            QApplication.restoreOverrideCursor()

    def load_settings(self):
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    
                    dev_idx = config.get("device_index", 0)
                    for i in range(self.combo_devices.count()):
                        if self.combo_devices.itemData(i) == dev_idx:
                            self.combo_devices.setCurrentIndex(i)
                            break
                            
                    self.spin_count.setValue(config.get("practice_count", 20))
                    self.chk_auto_default.setChecked(config.get("auto_mode_default", True))
                    self.spin_result_dwell.setValue(config.get("result_dwell_seconds", 0))
                    self.txt_student_name.setText(config.get("student_name", ""))
                    
                    lang = config.get("feedback_language", "en")
                    idx = self.combo_feedback_lang.findData(lang)
                    if idx >= 0: self.combo_feedback_lang.setCurrentIndex(idx)
                    
                    tts = config.get("tts_engine", "Auto (Best available)")
                    idx_tts = self.combo_tts.findText(tts)
                    if idx_tts >= 0: self.combo_tts.setCurrentIndex(idx_tts)
                    
                    self.txt_cosyvoice_url.setText(config.get("cosyvoice_url", "http://localhost:50000"))
                    self.txt_cosyvoice_spk.setText(config.get("cosyvoice_spk", "英文女"))
                    
                    self.chk_random.setChecked(config.get("strategy_random", True))
                    self.chk_smart.setChecked(config.get("strategy_smart", True))
                    self.chk_no_repeat.setChecked(config.get("strategy_no_repeat", False))
                    
                    self.spin_blank_count.setValue(config.get("quiz_blank_count", 1))
                    
                    provider = config.get("ai_provider", "Azure Speech (Recommended)")
                    idx = self.combo_provider.findText(provider)
                    if idx >= 0: self.combo_provider.setCurrentIndex(idx)
                        
                    stt = config.get("stt_provider", "Local Whisper (GPU)")
                    idx_stt = self.combo_stt.findText(stt)
                    if idx_stt >= 0: self.combo_stt.setCurrentIndex(idx_stt)
                    # Save for Omni toggle
                    self._saved_stt_provider = stt
                    
                    # Whisper model size
                    whisper_size = config.get("whisper_model_size", "medium")
                    idx_ws = self.combo_whisper_size.findText(whisper_size)
                    if idx_ws >= 0: self.combo_whisper_size.setCurrentIndex(idx_ws)
                        
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

                    # MiniCPM-o (Omni) fields
                    self.txt_omni_host.setText(config.get("omni_host", "127.0.0.1"))
                    self.spin_omni_chat_port.setValue(int(config.get("omni_chat_port", 18400)))
                    self.spin_omni_auth_port.setValue(int(config.get("omni_auth_port", 18500)))
                    self.txt_omni_username.setText(config.get("omni_username", "admin"))
                    self.txt_omni_password.setText(config.get("omni_password", "admin123"))
                    self.txt_omni_model.setText(config.get("omni_model", "minicpm-o45"))
                    self.chk_omni_tts.setChecked(bool(config.get("omni_tts_enabled", True)))

                    # Assessor engine selector (gop / azure / omni)
                    engine = config.get("assessor_engine", "gop")
                    idx_eng = self.combo_assessor_engine.findData(engine)
                    if idx_eng >= 0:
                        self.combo_assessor_engine.setCurrentIndex(idx_eng)

                    # GOP fields
                    gop_mode = config.get("gop_mode", "local")
                    idx_gm = self.combo_gop_mode.findData(gop_mode)
                    if idx_gm >= 0:
                        self.combo_gop_mode.setCurrentIndex(idx_gm)

                    self.txt_gop_remote_url.setText(config.get("gop_remote_url", "http://192.168.50.200:18200"))
                    self.txt_gop_remote_key.setText(config.get("gop_remote_key", ""))

                    gop_device = config.get("gop_device", "auto")
                    idx_gd = self.combo_gop_device.findText(gop_device)
                    if idx_gd >= 0:
                        self.combo_gop_device.setCurrentIndex(idx_gd)

                    self.txt_gop_model.setText(
                        config.get("gop_model", "facebook/wav2vec2-lv-60-espeak-cv-ft")
                    )

                    # HuggingFace token（wav2vec2 模型首次下载用）
                    self.txt_hf_token.setText(config.get("hf_token", ""))

                    # GOP 打分校准参数
                    calib = config.get("gop_calib") or {}
                    self.spin_conf_threshold.setValue(float(calib.get("conf_threshold", 0.30)))
                    self.spin_conf_exponent.setValue(float(calib.get("conf_exponent", 1.20)))
                    self.spin_low_conf_weight.setValue(float(calib.get("low_conf_weight", 0.10)))
                    self.spin_sigmoid_k.setValue(float(calib.get("sigmoid_k", 1.50)))
                    self.spin_sigmoid_mid.setValue(float(calib.get("sigmoid_mid", -2.00)))
                    self.spin_gop_floor.setValue(float(calib.get("gop_floor", -2.00)))

            except Exception as e:
                print(f"[SettingsDialog] Failed to load settings: {e}")

    def save_settings(self):
        config = {
            "device_index": self.combo_devices.currentData(),
            "practice_count": self.spin_count.value(),
            "auto_mode_default": self.chk_auto_default.isChecked(),
            "result_dwell_seconds": self.spin_result_dwell.value(),
            "student_name": self.txt_student_name.text().strip(),
            "feedback_language": self.combo_feedback_lang.currentData(),
            "tts_engine": self.combo_tts.currentText(),
            "cosyvoice_url": self.txt_cosyvoice_url.text().strip(),
            "cosyvoice_spk": self.txt_cosyvoice_spk.text().strip(),
            
            "strategy_random": self.chk_random.isChecked(),
            "strategy_smart": self.chk_smart.isChecked(),
            "strategy_no_repeat": self.chk_no_repeat.isChecked(),

            "quiz_blank_count": self.spin_blank_count.value(),

            "ai_provider": self.combo_provider.currentText(),
            "stt_provider": self.combo_stt.currentText(),
            "whisper_model_size": self.combo_whisper_size.currentText(),
            
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

            # MiniCPM-o (Omni)
            "omni_host": self.txt_omni_host.text().strip() or "127.0.0.1",
            "omni_chat_port": int(self.spin_omni_chat_port.value()),
            "omni_auth_port": int(self.spin_omni_auth_port.value()),
            "omni_username": self.txt_omni_username.text().strip() or "admin",
            "omni_password": self.txt_omni_password.text(),
            "omni_model": self.txt_omni_model.text().strip() or "minicpm-o45",
            "omni_tts_enabled": self.chk_omni_tts.isChecked(),

            # GOP scoring engine
            "assessor_engine": self.combo_assessor_engine.currentData() or "gop",
            "gop_mode": self.combo_gop_mode.currentData() or "local",
            "gop_remote_url": self.txt_gop_remote_url.text().strip(),
            "gop_remote_key": self.txt_gop_remote_key.text().strip(),
            "gop_device": self.combo_gop_device.currentText().strip() or "auto",
            "gop_model": self.txt_gop_model.text().strip() or "facebook/wav2vec2-lv-60-espeak-cv-ft",
            "hf_token": self.txt_hf_token.text().strip(),

            # GOP 打分校准子字典（可调参数）
            "gop_calib": {
                "sigmoid_k": float(self.spin_sigmoid_k.value()),
                "sigmoid_mid": float(self.spin_sigmoid_mid.value()),
                "conf_threshold": float(self.spin_conf_threshold.value()),
                "substitution_conf_min": 0.50,
                "conf_exponent": float(self.spin_conf_exponent.value()),
                "low_conf_weight": float(self.spin_low_conf_weight.value()),
                "gop_floor": float(self.spin_gop_floor.value()),
            },

            # 情景会话：记住上次轮数（全局共享）
            "scenario_turn_count": int(self.spin_bank_count.value()),
            
            "active_groups": [self.list_groups.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.list_groups.count()) 
                              if self.list_groups.item(i).checkState() == Qt.CheckState.Checked]
        }
        
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f)
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "错误", str(e))

    def _reset_gop_calib(self):
        """Reset GOP calibration parameters to project defaults."""
        try:
            from src.core.gop.scorer import DEFAULT_CALIB
        except Exception:
            DEFAULT_CALIB = {
                "sigmoid_k": 1.5, "sigmoid_mid": -2.0,
                "conf_threshold": 0.30, "conf_exponent": 1.2,
                "low_conf_weight": 0.10,
            }
        self.spin_conf_threshold.setValue(float(DEFAULT_CALIB["conf_threshold"]))
        self.spin_conf_exponent.setValue(float(DEFAULT_CALIB["conf_exponent"]))
        self.spin_low_conf_weight.setValue(float(DEFAULT_CALIB["low_conf_weight"]))
        self.spin_sigmoid_k.setValue(float(DEFAULT_CALIB["sigmoid_k"]))
        self.spin_sigmoid_mid.setValue(float(DEFAULT_CALIB["sigmoid_mid"]))
        self.spin_gop_floor.setValue(float(DEFAULT_CALIB.get("gop_floor", -2.0)))

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
                with open(self.config_file, 'r', encoding='utf-8') as f:
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
        
        # Refresh bank table
        self._refresh_bank_table()
    
    def _on_group_check_changed(self, item=None):
        """Update spin_bank_count max based on total word count of checked groups.
        Scenario mode uses fixed turn-count range (8-40) and is not affected by word counts."""
        # 情景会话模式：spin_bank_count 表示对话轮数，范围固定，与词条数无关
        if hasattr(self, "combo_bank_type") and self.combo_bank_type.currentIndex() == 2:
            return

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
    
    def _on_bank_type_changed(self, index):
        """Toggle controls based on bank type selection."""
        is_quiz = (index == 0)         # 0=中英互译
        is_oral = (index == 1)         # 1=口语
        is_scenario = (index == 2)     # 2=情景会话脚本

        # 填空数仅 quiz 显示
        self.lbl_blank_count.setVisible(is_quiz)
        self.spin_blank_count.setVisible(is_quiz)
        self.lbl_blank_unit.setVisible(is_quiz)

        # 情景会话：spin_bank_count 重用为"对话轮数"，固定范围 8-40；隐藏"全部"
        self.spin_bank_count.setVisible(True)
        self.lbl_count_unit.setVisible(True)
        self.chk_all_bank.setVisible(not is_scenario)

        # 单位文字 + 范围切换
        if is_quiz:
            self.lbl_count_unit.setText("题")
            self.spin_bank_count.setToolTip("题库包含的题目数量")
            # 由 _on_group_check_changed 根据词条数动态设置上限
            self._on_group_check_changed()
        elif is_oral:
            self.lbl_count_unit.setText("句")
            self.spin_bank_count.setToolTip("题库包含的句子数量")
            self._on_group_check_changed()
        else:  # scenario
            self.lbl_count_unit.setText("轮")
            self.spin_bank_count.setToolTip("情景对话总轮数（A 与 B 各算一轮，8–60）")
            self.spin_bank_count.setRange(8, 60)
            # 记忆上次轮数（全局生效）
            try:
                with open(self.config_file, "r", encoding="utf-8") as _f:
                    _cfg = json.load(_f)
                self.spin_bank_count.setValue(int(_cfg.get("scenario_turn_count", 12)))
            except Exception:
                self.spin_bank_count.setValue(12)
            self.spin_bank_count.setEnabled(True)

        # 按钮配色 — 统一使用 mango 主色
        self.btn_generate_bank.setStyleSheet(AppStyles.BIG_BUTTON)
    
    def _refresh_bank_table(self):
        """Refresh unified bank table from quiz / oral / scenario engines."""
        all_banks = []
        
        # Collect quiz banks
        if self.quiz_engine:
            for bank in self.quiz_engine.get_all_banks():
                bank["_type"] = "quiz"
                all_banks.append(bank)
        
        # Collect oral banks
        if self.oral_engine:
            for bank in self.oral_engine.get_all_banks():
                bank["_type"] = "oral"
                all_banks.append(bank)
        
        # Collect scenario banks
        if self.scenario_engine:
            for bank in self.scenario_engine.get_all_banks():
                bank["_type"] = "scenario"
                all_banks.append(bank)
        
        # Sort by created_at descending
        all_banks.sort(key=lambda b: b.get("created_at", ""), reverse=True)
        
        # Clear old contents first to prevent widget artifacts
        self.table_banks.setRowCount(0)
        self.table_banks.setRowCount(len(all_banks))
        
        for row, bank in enumerate(all_banks):
            bank_id = bank.get("id", "")
            bank_type = bank.get("_type", "quiz")
            
            # Name
            name_item = QTableWidgetItem(bank.get("name", "未命名"))
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table_banks.setItem(row, 0, name_item)
            
            # Type tag
            if bank_type == "quiz":
                type_text = "中英互译"
            elif bank_type == "oral":
                type_text = "口语"
            else:
                type_text = "情景会话"
            type_item = QTableWidgetItem(type_text)
            type_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            # Use design-token colors via QColor
            if bank_type == "quiz":
                type_item.setForeground(QColor(MANGO_DK))
            elif bank_type == "oral":
                type_item.setForeground(QColor(LEAF))
            else:
                type_item.setForeground(QColor(MANGO))
            type_item.setFlags(type_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table_banks.setItem(row, 1, type_item)
            
            # Groups
            groups_str = ", ".join(bank.get("source_groups", []))
            groups_item = QTableWidgetItem(groups_str)
            groups_item.setFlags(groups_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table_banks.setItem(row, 2, groups_item)
            
            # Count
            if bank_type == "quiz":
                count = bank.get("question_count", 0)
                count_label = str(count)
            elif bank_type == "oral":
                count = bank.get("sentence_count", len(bank.get("sentences", [])))
                count_label = str(count)
            else:  # scenario
                count = bank.get("turn_count", len(bank.get("script", [])))
                count_label = f"{count} 轮"
            count_item = QTableWidgetItem(count_label)
            count_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            count_item.setFlags(count_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table_banks.setItem(row, 3, count_item)
            
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
            self.table_banks.setItem(row, 4, created_item)
            
            # View button (quiz / scenario have content; oral shows '—')
            if bank_type == "quiz" or bank_type == "scenario":
                btn_view = QPushButton("查看")
                accent = MANGO if bank_type == "quiz" else LEAF
                btn_view.setStyleSheet(f"QPushButton {{ color: {accent}; border: 1px solid {accent}; border-radius: {RADIUS_SM}px; padding: {SP_1}px {SP_2}px; font-family: {FONT_FALLBACK}; font-size: {SIZE_BODY}px; }} QPushButton:hover {{ background-color: {DESK}; }}")
                btn_view.setCursor(Qt.CursorShape.PointingHandCursor)
                btn_view.clicked.connect(lambda checked, bid=bank_id, bt=bank_type: self._view_bank(bid, bt))
                self.table_banks.setCellWidget(row, 5, btn_view)
            else:
                lbl_view = QLabel("—")
                lbl_view.setAlignment(Qt.AlignmentFlag.AlignCenter)
                lbl_view.setStyleSheet(f"color: {INK_SOFT}; font-family: {FONT_FALLBACK};")
                self.table_banks.setCellWidget(row, 5, lbl_view)
            
            # Rename button
            btn_rename = QPushButton("改名")
            btn_rename.setStyleSheet(f"QPushButton {{ color: {MANGO_DK}; border: 1px solid {MANGO_DK}; border-radius: {RADIUS_SM}px; padding: {SP_1}px {SP_2}px; font-family: {FONT_FALLBACK}; font-size: {SIZE_BODY}px; }} QPushButton:hover {{ background-color: {DESK}; }}")
            btn_rename.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_rename.clicked.connect(lambda checked, bid=bank_id, bt=bank_type, n=bank.get("name",""): self._rename_bank(bid, bt, n))
            self.table_banks.setCellWidget(row, 6, btn_rename)
            
            # Delete button
            btn_delete = QPushButton("删除")
            btn_delete.setStyleSheet(f"QPushButton {{ color: {CLAY}; border: 1px solid {CLAY}; border-radius: {RADIUS_SM}px; padding: {SP_1}px {SP_2}px; font-family: {FONT_FALLBACK}; font-size: {SIZE_BODY}px; }} QPushButton:hover {{ background-color: {CLAY_SOFT}; }}")
            btn_delete.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_delete.clicked.connect(lambda checked, bid=bank_id, bt=bank_type: self._delete_bank(bid, bt))
            self.table_banks.setCellWidget(row, 7, btn_delete)
    
    def _view_bank(self, bank_id, bank_type="quiz"):
        """View bank content. Dispatch by type."""
        if bank_type == "scenario":
            if not self.scenario_engine:
                return
            bank = self.scenario_engine.get_bank_by_id(bank_id)
            if not bank:
                QMessageBox.warning(self, "错误", "题库不存在。")
                return
            self._view_scenario_bank(bank)
            return
        
        if not self.quiz_engine:
            return
        bank = self.quiz_engine.get_bank_by_id(bank_id)
        if not bank:
            # Try oral engine
            if self.oral_engine:
                bank = self.oral_engine.get_bank_by_id(bank_id)
                if bank:
                    self._view_oral_bank(bank)
                    return
            QMessageBox.warning(self, "错误", "题库不存在。")
            return
        
        dialog = QDialog(self)
        dialog.setWindowTitle(f"题库内容 - {bank.get('name', '')}")
        dialog.resize(600, 500)
        layout = QVBoxLayout(dialog)
        
        # Header info
        info = QLabel(f"题库: {bank.get('name', '')}\n题数: {bank.get('question_count', 0)}")
        info.setStyleSheet(f"font-family: {FONT_FALLBACK}; font-size: {SIZE_UI}px; color: {INK}; padding: {SP_1}px; background: {DESK}; border-radius: {RADIUS_SM}px;")
        info.setWordWrap(True)
        layout.addWidget(info)

        # Scrollable question list
        scroll = QScrollArea()
        scroll.setStyleSheet(AppStyles.SCROLL_AREA)
        scroll.setWidgetResizable(True)
        content = QWidget()
        content_layout = QVBoxLayout(content)

        questions = bank.get("questions", [])
        for i, q in enumerate(questions):
            card = QFrame()
            card.setStyleSheet(f"background: {DESK}; border-radius: {RADIUS}px; padding: {SP_1}px; margin: {SP_1}px;")
            card_layout = QVBoxLayout(card)
            
            qtype = "中译英" if q.get("type") == "zh2en" else "英译中"
            q_text = q.get("question_text", "")
            
            # Question line
            lbl_q = QLabel(f"[{i+1}] [{qtype}] {q_text}")
            lbl_q.setStyleSheet(f"font-family: {FONT_FALLBACK}; font-size: {SIZE_UI}px; font-weight: 700; color: {INK};")
            lbl_q.setWordWrap(True)
            card_layout.addWidget(lbl_q)
            
            # Answer line
            if q.get("type") == "zh2en":
                answers = q.get("answers", [])
                ans_str = " / ".join(answers) if answers else q.get("answer", "")
                lbl_a = QLabel(f"答案: {ans_str}")
            else:
                lbl_a = QLabel(f"答案: {q.get('answer', '')}    选项: {' | '.join(q.get('options', []))}")
            lbl_a.setStyleSheet(f"font-family: {FONT_FALLBACK}; font-size: {SIZE_BODY}px; color: {LEAF};")
            lbl_a.setWordWrap(True)
            card_layout.addWidget(lbl_a)
            
            # Hint
            hint = q.get("chinese_hint", "")
            if hint:
                lbl_h = QLabel(f"提示: {hint}")
                lbl_h.setStyleSheet(f"font-family: {FONT_FALLBACK}; font-size: 12px; color: {INK_SOFT};")
                card_layout.addWidget(lbl_h)
            
            content_layout.addWidget(card)
        
        content_layout.addStretch()
        scroll.setWidget(content)
        layout.addWidget(scroll)
        
        # Close button
        btn_close = QPushButton("关闭")
        btn_close.setStyleSheet(AppStyles.CARD_BUTTON)
        btn_close.clicked.connect(dialog.accept)
        layout.addWidget(btn_close)
        
        dialog.exec()
    
    def _view_oral_bank(self, bank):
        """View oral test bank sentences."""
        dialog = QDialog(self)
        dialog.setWindowTitle(f"口语题库内容 - {bank.get('name', '')}")
        dialog.resize(600, 500)
        layout = QVBoxLayout(dialog)
        
        count = bank.get("sentence_count", len(bank.get("sentences", [])))
        info = QLabel(f"题库: {bank.get('name', '')}\n句数: {count}")
        info.setStyleSheet(f"font-family: {FONT_FALLBACK}; font-size: {SIZE_UI}px; color: {INK}; padding: {SP_1}px; background: {DESK}; border-radius: {RADIUS_SM}px;")
        info.setWordWrap(True)
        layout.addWidget(info)

        scroll = QScrollArea()
        scroll.setStyleSheet(AppStyles.SCROLL_AREA)
        scroll.setWidgetResizable(True)
        content = QWidget()
        content_layout = QVBoxLayout(content)

        sentences = bank.get("sentences", [])
        for i, s in enumerate(sentences):
            card = QFrame()
            card.setStyleSheet(f"background: {DESK}; border-radius: {RADIUS}px; padding: {SP_1}px; margin: {SP_1}px;")
            card_layout = QVBoxLayout(card)
            
            lbl_s = QLabel(f"[{i+1}] {s.get('text', '')}")
            lbl_s.setStyleSheet(f"font-family: {FONT_FALLBACK}; font-size: {SIZE_UI}px; font-weight: 700; color: {INK};")
            lbl_s.setWordWrap(True)
            card_layout.addWidget(lbl_s)
            
            trans = s.get("translation", "")
            if trans:
                lbl_t = QLabel(f"翻译: {trans}")
                lbl_t.setStyleSheet(f"font-family: {FONT_FALLBACK}; font-size: 12px; color: {INK_SOFT};")
                card_layout.addWidget(lbl_t)
            
            content_layout.addWidget(card)
        
        content_layout.addStretch()
        scroll.setWidget(content)
        layout.addWidget(scroll)
        
        btn_close = QPushButton("关闭")
        btn_close.setStyleSheet(AppStyles.CARD_BUTTON)
        btn_close.clicked.connect(dialog.accept)
        layout.addWidget(btn_close)
        dialog.exec()
    
    def _view_scenario_bank(self, bank):
        """View scenario bank as A/B chat bubbles."""
        dialog = QDialog(self)
        dialog.setWindowTitle(f"情景会话脚本 - {bank.get('name', '')}")
        dialog.resize(640, 560)
        layout = QVBoxLayout(dialog)
        
        script = bank.get("script", [])
        info = QLabel(
            f"题库: {bank.get('name', '')}\n"
            f"轮次: {len(script)}    来源: {', '.join(bank.get('source_groups', []))}"
        )
        info.setStyleSheet(f"font-family: {FONT_FALLBACK}; font-size: {SIZE_UI}px; color: {INK}; padding: {SP_1}px; background: {DESK}; border-radius: {RADIUS_SM}px;")
        info.setWordWrap(True)
        layout.addWidget(info)

        scroll = QScrollArea()
        scroll.setStyleSheet(AppStyles.SCROLL_AREA)
        scroll.setWidgetResizable(True)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setSpacing(SP_2)

        for i, turn in enumerate(script):
            role = turn.get("role", "A")
            text = turn.get("text", "")
            translation = turn.get("translation", "")
            
            row = QHBoxLayout()
            
            bubble = QFrame()
            bubble_layout = QVBoxLayout(bubble)
            bubble_layout.setContentsMargins(SP_3, SP_2, SP_3, SP_2)

            lbl_role = QLabel(f"{'A' if role == 'A' else 'B'} · 第 {i+1} 轮")
            lbl_role.setStyleSheet(f"font-family: {FONT_FALLBACK}; font-size: 11px; color: {INK_SOFT}; font-weight: 700;")
            bubble_layout.addWidget(lbl_role)
            
            lbl_text = QLabel(text)
            lbl_text.setStyleSheet(f"font-family: {FONT_FALLBACK}; font-size: {SIZE_UI}px; color: {INK};")
            lbl_text.setWordWrap(True)
            bubble_layout.addWidget(lbl_text)
            
            if translation:
                lbl_tr = QLabel(translation)
                lbl_tr.setStyleSheet(f"font-family: {FONT_FALLBACK}; font-size: 12px; color: {INK_SOFT};")
                lbl_tr.setWordWrap(True)
                bubble_layout.addWidget(lbl_tr)
            
            if role == "A":
                bubble.setStyleSheet(f"background: {DESK}; border-radius: {RADIUS}px;")
                bubble.setMaximumWidth(460)
                row.addWidget(bubble)
                row.addStretch()
            else:
                bubble.setStyleSheet(f"background: #FBFAF5; border: 1px solid {DESK_LINE}; border-radius: {RADIUS}px;")
                bubble.setMaximumWidth(460)
                row.addStretch()
                row.addWidget(bubble)
            
            content_layout.addLayout(row)
        
        content_layout.addStretch()
        scroll.setWidget(content)
        layout.addWidget(scroll)
        
        btn_close = QPushButton("关闭")
        btn_close.setStyleSheet(AppStyles.CARD_BUTTON)
        btn_close.clicked.connect(dialog.accept)
        layout.addWidget(btn_close)
        dialog.exec()
    
    def _rename_bank(self, bank_id, bank_type="quiz", current_name=""):
        """Rename a bank via input dialog."""
        new_name, ok = QInputDialog.getText(self, "改名", "新名称:", text=current_name)
        if ok and new_name.strip():
            if bank_type == "quiz":
                engine = self.quiz_engine
            elif bank_type == "oral":
                engine = self.oral_engine
            else:
                engine = self.scenario_engine
            if engine and engine.rename_bank(bank_id, new_name.strip()):
                self._refresh_bank_table()
    
    def _generate_bank(self):
        """Generate bank based on current type selection."""
        bank_type = self.combo_bank_type.currentIndex()  # 0=quiz, 1=oral, 2=scenario
        
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
        self.lbl_bank_status.setStyleSheet(f"font-family: {FONT_FALLBACK}; color: {INK_SOFT}; font-size: {SIZE_BODY}px;")
        self.btn_generate_bank.setEnabled(False)
        
        if bank_type == 0:  # 中英互译
            if not self.quiz_engine:
                QMessageBox.warning(self, "错误", "题库引擎不可用。")
                self.btn_generate_bank.setEnabled(True)
                self.bank_progress.setVisible(False)
                return
            self.lbl_bank_status.setText(f"正在从 {len(active_groups)} 个分组生成 {count} 道题...")
            self.quiz_engine.generate_bank(active_groups, count)
        elif bank_type == 1:  # 口语
            if not self.oral_engine:
                QMessageBox.warning(self, "错误", "口语测试引擎不可用。")
                self.btn_generate_bank.setEnabled(True)
                self.bank_progress.setVisible(False)
                return
            self.lbl_bank_status.setText(f"正在从 {len(active_groups)} 个分组生成 {count} 个句子...")
            self.oral_engine.generate_bank(active_groups, count)
        else:  # 情景会话
            if not self.scenario_engine:
                QMessageBox.warning(self, "错误", "情景会话引擎不可用。")
                self.btn_generate_bank.setEnabled(True)
                self.bank_progress.setVisible(False)
                return
            turn_count = self.spin_bank_count.value()
            self.lbl_bank_status.setText(
                f"正在从 {len(active_groups)} 个分组生成 {turn_count} 轮情景对话..."
            )
            self.scenario_engine.generate_bank(active_groups, turn_count=turn_count)
    
    def _on_bank_progress(self, generated, total):
        self.bank_progress.setMaximum(total)
        self.bank_progress.setValue(generated)
        self.lbl_bank_status.setText(f"已生成 {generated}/{total}...")
    
    def _on_bank_done(self, bank):
        self.bank_progress.setVisible(False)
        # Determine type
        if "questions" in bank:
            count = bank.get("question_count", 0)
            unit = "题"
        elif "script" in bank:
            count = bank.get("turn_count", len(bank.get("script", [])))
            unit = "轮"
        else:
            count = bank.get("sentence_count", len(bank.get("sentences", [])))
            unit = "句"
        self.lbl_bank_status.setText(f"已生成: {bank.get('name', '')} ({count} {unit})")
        self.lbl_bank_status.setStyleSheet(f"font-family: {FONT_FALLBACK}; color: {LEAF}; font-size: {SIZE_BODY}px; font-weight: 700;")
        self.btn_generate_bank.setEnabled(True)
        self._refresh_bank_table()
        QMessageBox.information(self, "成功", f"题库已生成：\n{bank.get('name', '')}\n{count} {unit}已保存。")
    
    def _on_bank_error(self, error_msg):
        self.bank_progress.setVisible(False)
        self.lbl_bank_status.setText(f"错误: {error_msg}")
        self.lbl_bank_status.setStyleSheet(f"font-family: {FONT_FALLBACK}; color: {CLAY}; font-size: {SIZE_BODY}px;")
        self.btn_generate_bank.setEnabled(True)
        QMessageBox.critical(self, "生成失败", error_msg)
    
    def _delete_bank(self, bank_id, bank_type="quiz"):
        """Delete a bank by type."""
        reply = QMessageBox.question(
            self, "删除题库",
            "确认删除此题库？不可恢复。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            if bank_type == "quiz":
                engine = self.quiz_engine
            elif bank_type == "oral":
                engine = self.oral_engine
            else:
                engine = self.scenario_engine
            if engine and engine.delete_bank(bank_id):
                self._refresh_bank_table()
    
    def get_settings(self):
        if os.path.exists(self.config_file):
            with open(self.config_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {}
