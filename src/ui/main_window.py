from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, 
                             QLabel, QPushButton, QHBoxLayout, QStackedWidget, QMessageBox, QCheckBox, QGridLayout)
from PyQt6.QtCore import Qt, pyqtSignal, QObject, QTimer
from PyQt6.QtGui import QIcon, QFont, QPixmap
from src.ui.styles import AppStyles, FONT_FALLBACK, PAPER, DESK, INK, INK_SOFT, MANGO, LEAF, CLAY, SP_3, SP_4, SP_5, RADIUS
from src.ui.recording_widget import RecordingWidget
from src.ui.summary_page import SummaryPage
from src.ui.settings_dialog import SettingsDialog
from src.core.audio_recorder import AudioRecorder
from src.core.ai_assessor import PronunciationCoach
from src.core.exercise_manager import ExerciseManager
from src.core.tts_engine import TTSEngine
import os
import json
import threading
import time
from src.utils import get_resource_path, get_user_data_path

# Helper signal for thread-safe VAD stop
class ValidSignal(QObject):
    stop_signal = pyqtSignal()

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("English Pronunciation Coach")
        self.resize(1000, 700)
        
        # Core Components
        self.audio_recorder = AudioRecorder()
        self.ai_coach = PronunciationCoach()
        
        # Warmup AI in background (Whisper Model)
        threading.Thread(target=self.ai_coach.warmup, daemon=True).start()
        
        self.exercise_manager = ExerciseManager(get_user_data_path("words.json"))
        self.tts = TTSEngine()
        
        # Scenario dialogue engine (LLM-generated A/B chat scripts)
        from src.core.scenario_engine import ScenarioEngine
        self.scenario_engine = ScenarioEngine(self.exercise_manager)
        
        # Signals
        self.signals = ValidSignal()
        self.signals.stop_signal.connect(self.auto_stop_recording)
        
        # Connect async LLM feedback signal
        self.ai_coach.signals.feedback_ready.connect(self.update_feedback_text)
        
        # State
        self.auto_mode = False
        self.session_results = []
        
        # Central Widget & Stack
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.central_widget.setStyleSheet(AppStyles.MAIN_WINDOW_BG)
        
        self.main_layout = QVBoxLayout(self.central_widget)
        
        self.stack = QStackedWidget()
        self.main_layout.addWidget(self.stack)
        
        # Pages
        self.page_home = self.create_home_page()
        self.page_practice = self.create_practice_page()
        self.page_result = self.create_result_page()
        self.page_summary = SummaryPage(self)
        
        # Lazy load or init? Init is fine.
        from src.ui.mistake_page import MistakePage
        self.page_mistakes = MistakePage(self)
        
        from src.ui.quiz_page import QuizPage
        self.page_quiz = QuizPage(self)
        
        from src.ui.oral_test_page import OralTestPage
        self.page_oral_test = OralTestPage(self)
        
        from src.ui.oral_hub_page import OralHubPage
        self.page_oral_hub = OralHubPage(self)
        
        from src.ui.scenario_chat_page import ScenarioChatPage
        self.page_scenario = ScenarioChatPage(self)
        
        from src.ui.tutor_page import TutorPage
        self.page_tutor = TutorPage(self)

        from src.ui.memorize_page import MemorizePage
        self.page_memorize = MemorizePage(self)
        
        self.stack.addWidget(self.page_home)
        self.stack.addWidget(self.page_practice)
        self.stack.addWidget(self.page_result)
        self.stack.addWidget(self.page_summary)
        self.stack.addWidget(self.page_mistakes)
        self.stack.addWidget(self.page_quiz)
        self.stack.addWidget(self.page_oral_test)
        self.stack.addWidget(self.page_oral_hub)
        self.stack.addWidget(self.page_scenario)
        self.stack.addWidget(self.page_tutor)
        self.stack.addWidget(self.page_memorize)
        
        self.current_exercise_index = 0
        self.current_exercise_list = []
        
    def create_home_page(self):
        page = QWidget()
        page.setStyleSheet(AppStyles.MAIN_WINDOW_BG)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(SP_5, SP_5, SP_5, SP_5)
        layout.setSpacing(SP_4)

        # Top Bar — Settings, right-aligned, quiet
        top_layout = QHBoxLayout()
        top_layout.addStretch()
        btn_settings = QPushButton("Settings")
        btn_settings.setStyleSheet(AppStyles.GHOST_BUTTON)
        btn_settings.clicked.connect(self.open_settings)
        top_layout.addWidget(btn_settings)
        layout.addLayout(top_layout)

        # Mascot Image
        mascot_path = get_resource_path(os.path.join("src", "resources", "images", "mascot.png"))
        if os.path.exists(mascot_path):
            lbl_mascot = QLabel()
            pixmap = QPixmap(mascot_path).scaled(140, 140, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            lbl_mascot.setPixmap(pixmap)
            lbl_mascot.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(lbl_mascot)

        header = QLabel("Welcome to English Coach")
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header.setStyleSheet(AppStyles.HEADER_LABEL)
        layout.addWidget(header)

        sub = QLabel("Pick something to practice")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setStyleSheet(AppStyles.SUBTITLE_LABEL)
        layout.addWidget(sub)

        layout.addSpacing(SP_4)

        # Auto Mode Toggle (Active but hidden from UI, controlled by Settings)
        self.chk_auto = QCheckBox("Auto Mode")
        self.chk_auto.setVisible(False)

        # Load default state from correct config path
        config_path = get_user_data_path("config.json")
        if os.path.exists(config_path):
             try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    self.chk_auto.setChecked(config.get("auto_mode_default", True))
                    # Set TTS Mode
                    self.tts.set_mode(config.get("tts_engine", "Auto"))
                    # Set CosyVoice config
                    self.tts.set_cosyvoice_config(
                        config.get("cosyvoice_url", "http://localhost:50000"),
                        config.get("cosyvoice_spk", "英文女")
                    )
             except (json.JSONDecodeError, IOError):
                 pass

        # Module grid 2×3 — paper cards, one active (mango left border)
        grid_layout = QGridLayout()
        grid_layout.setSpacing(SP_3)
        grid_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        def _module_card(chinese, english, active=False):
            btn = QPushButton(f"{chinese}\n{english}")
            btn.setStyleSheet(AppStyles.MODULE_CARD(active))
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setMinimumHeight(110)
            return btn

        # Row 0: 口语练习 + 中英互译
        btn_practice = _module_card("口语练习", "Oral Practice", active=True)
        btn_practice.clicked.connect(self.open_oral_hub_page)
        grid_layout.addWidget(btn_practice, 0, 0)

        btn_quiz = _module_card("中英互译", "Translation Quiz")
        btn_quiz.clicked.connect(self.open_quiz_page)
        grid_layout.addWidget(btn_quiz, 0, 1)

        # Row 1: 复习错误 + 导入词库
        btn_mistakes = _module_card("复习错误", "Review Mistakes")
        btn_mistakes.clicked.connect(self.open_mistakes_page)
        grid_layout.addWidget(btn_mistakes, 1, 0)

        btn_import = _module_card("导入词库", "Import Words")
        btn_import.clicked.connect(self.open_import_dialog)
        grid_layout.addWidget(btn_import, 1, 1)

        btn_memorize = _module_card("分类速记", "28-Day Memorize")
        btn_memorize.clicked.connect(self.open_memorize_page)
        grid_layout.addWidget(btn_memorize, 2, 0)

        grid_layout.setColumnStretch(0, 1)
        grid_layout.setColumnStretch(1, 1)

        layout.addLayout(grid_layout)
        layout.addStretch()
        return page

    def open_settings(self):
        quiz_engine = self.page_quiz.quiz_engine if hasattr(self, 'page_quiz') else None
        oral_engine = self.page_oral_test.oral_engine if hasattr(self, 'page_oral_test') else None
        dialog = SettingsDialog(self, self.audio_recorder, self.exercise_manager,
                                quiz_engine=quiz_engine, oral_engine=oral_engine,
                                scenario_engine=self.scenario_engine)
        if dialog.exec():
            # Reload AI config
            self.ai_coach.load_config()
            # Reload TTS config (must use same path as settings dialog)
            try:
                config_path = get_user_data_path("config.json")
                with open(config_path, 'r', encoding='utf-8') as f:
                    cfg = json.load(f)
                self.tts.set_mode(cfg.get("tts_engine", "Auto"))
                self.tts.set_cosyvoice_config(
                    cfg.get("cosyvoice_url", "http://localhost:50000"),
                    cfg.get("cosyvoice_spk", "中文女")
                )
            except Exception:
                pass

    def open_import_dialog(self):
        from src.ui.import_dialog import ImportDialog
        dialog = ImportDialog(self)
        if dialog.exec():
            items = dialog.get_data()
            if items:
                count = self.exercise_manager.add_exercises(items, "words")
                QMessageBox.information(self, "Success", f"Imported {count} new words!")

    def create_practice_page(self):
        page = QWidget()
        page.setStyleSheet(AppStyles.MAIN_WINDOW_BG)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(SP_5, SP_5, SP_5, SP_5)
        layout.setSpacing(SP_4)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Navigation back
        top_bar = QHBoxLayout()
        btn_back = QPushButton("End Practice")
        btn_back.clicked.connect(self.stop_and_home)
        btn_back.setStyleSheet(AppStyles.GHOST_BUTTON)
        top_bar.addWidget(btn_back)
        top_bar.addStretch()
        layout.addLayout(top_bar)

        layout.addStretch()

        # Word Display — the hero
        self.lbl_word = QLabel("Apple")
        self.lbl_word.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_word.setStyleSheet(AppStyles.WORD_DISPLAY)
        self.lbl_word.setWordWrap(True)
        layout.addWidget(self.lbl_word)

        self.lbl_phonetic = QLabel("/ˈæp.əl/")
        self.lbl_phonetic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_phonetic.setStyleSheet(AppStyles.PHONETIC_DISPLAY)
        layout.addWidget(self.lbl_phonetic)

        self.lbl_translation = QLabel("苹果")
        self.lbl_translation.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_translation.setStyleSheet(f"font-family: {FONT_FALLBACK}; font-size: 20px; color: {INK_SOFT};")
        self.lbl_translation.setWordWrap(True)
        layout.addWidget(self.lbl_translation)

        layout.addStretch()

        # Recorder
        self.recorder_widget = RecordingWidget(self.audio_recorder)
        self.recorder_widget.recording_finished.connect(self.process_recording)
        layout.addWidget(self.recorder_widget)

        layout.addStretch()

        # Next Button
        self.btn_next = QPushButton("Skip / Next")
        self.btn_next.clicked.connect(self.next_exercise)
        self.btn_next.setStyleSheet(AppStyles.CARD_BUTTON)
        layout.addWidget(self.btn_next)

        return page
        
    def stop_and_home(self):
        # Force stop recorder via widget to sync UI state
        if hasattr(self, 'recorder_widget'):
            self.recorder_widget.reset_state()
            
        # Ensure underlying recorder is definitely stopped (double safety)
        self.audio_recorder.stop_recording()
        
        self.stack.setCurrentWidget(self.page_home)

    def create_result_page(self):
        page = QWidget()
        page.setStyleSheet(AppStyles.MAIN_WINDOW_BG)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(SP_5, SP_5, SP_5, SP_5)
        layout.setSpacing(SP_3)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Reference sentence
        self.lbl_result_reference = QLabel("")
        self.lbl_result_reference.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_result_reference.setStyleSheet(
            f"font-family: {FONT_FALLBACK}; font-size: 20px; font-weight: 700; "
            f"color: {INK}; background: {DESK}; padding: {SP_3}px; "
            f"border-radius: {RADIUS}px; margin: 0 40px;"
        )
        self.lbl_result_reference.setWordWrap(True)
        layout.addWidget(self.lbl_result_reference)

        self.lbl_score = QLabel("Score: 95")
        self.lbl_score.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_score.setStyleSheet(AppStyles.SCORE_LABEL("high"))
        layout.addWidget(self.lbl_score)

        # Star Rating
        self.stars_layout = QHBoxLayout()
        self.stars_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.star_labels = []
        for _ in range(3):
            l = QLabel()
            l.setFixedSize(60, 60)
            l.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.stars_layout.addWidget(l)
            self.star_labels.append(l)
        layout.addLayout(self.stars_layout)

        self.lbl_feedback = QLabel("Excellent!")
        self.lbl_feedback.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_feedback.setStyleSheet(f"font-family: {FONT_FALLBACK}; font-size: 20px; color: {INK};")
        layout.addWidget(self.lbl_feedback)

        # Actions — secondary buttons for non-primary, primary for continue
        btn_layout = QHBoxLayout()

        btn_play = QPushButton("Listen")
        btn_play.setStyleSheet(AppStyles.CARD_BUTTON)
        btn_play.clicked.connect(self.play_last_recording)
        btn_layout.addWidget(btn_play)

        btn_tts = QPushButton("Standard")
        btn_tts.setStyleSheet(AppStyles.CARD_BUTTON)
        btn_tts.clicked.connect(self.play_tts_reference)
        btn_layout.addWidget(btn_tts)

        btn_retry = QPushButton("Try Again")
        btn_retry.setStyleSheet(AppStyles.CARD_BUTTON)
        btn_retry.clicked.connect(lambda: self.stack.setCurrentWidget(self.page_practice))
        btn_layout.addWidget(btn_retry)

        layout.addLayout(btn_layout)

        # Debug Details (ghost, subtle)
        btn_details = QPushButton("Scoring Details")
        btn_details.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_details.setStyleSheet(AppStyles.GHOST_BUTTON)
        btn_details.clicked.connect(self.show_debug_details)
        layout.addWidget(btn_details)

        btn_continue = QPushButton("Next  (Space)")
        btn_continue.setStyleSheet(AppStyles.BIG_BUTTON)
        btn_continue.clicked.connect(self.next_exercise)
        layout.addWidget(btn_continue)

        self.last_recording_path = None

        return page

    def open_mistakes_page(self):
        self.page_mistakes.refresh_data()
        self.stack.setCurrentWidget(self.page_mistakes)
    
    def open_quiz_page(self):
        self.page_quiz.reset_to_setup()
        self.stack.setCurrentWidget(self.page_quiz)
    
    def open_oral_test_page(self):
        self.page_oral_test.showEvent(None)  # Refresh data
        self.stack.setCurrentWidget(self.page_oral_test)
    
    def open_oral_hub_page(self):
        self.stack.setCurrentWidget(self.page_oral_hub)
    
    def open_scenario_chat_page(self):
        self.page_scenario.reset_to_setup()
        self.stack.setCurrentWidget(self.page_scenario)

    def open_tutor_page(self):
        self.page_tutor.reset_to_setup()
        self.stack.setCurrentWidget(self.page_tutor)

    def open_memorize_page(self):
        self.page_memorize.refresh_data()
        self.stack.setCurrentWidget(self.page_memorize)

    def start_practice_with_list(self, custom_list):
        """Starts practice with a specific list of items (e.g. mistakes)."""
        if not custom_list:
            return
            
        self.current_exercise_list = custom_list
        self.current_exercise_index = 0
        self.session_results = []
        
        self.auto_mode = self.chk_auto.isChecked()
        self.load_current_exercise()
        self.stack.setCurrentWidget(self.page_practice)
        
        if self.auto_mode:
             self.recorder_widget.record_btn.setEnabled(False)
             self.status_next_step("auto_start", 1000)

    def start_practice(self):
        # 1. Load Config
        config_path = get_user_data_path("config.json")
        config = {}
        if os.path.exists(config_path):
             try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
             except (json.JSONDecodeError, IOError):
                 pass

        active_groups = config.get("active_groups", [])
        practice_count = config.get("practice_count", 20)
        
        strategy_random = config.get("strategy_random", True)
        strategy_smart = config.get("strategy_smart", True)
        strategy_no_repeat = config.get("strategy_no_repeat", False)
             
        # 2. Merge all available data
        all_words = self.exercise_manager.exercises.get("words", [])
        all_sentences = self.exercise_manager.exercises.get("sentences", [])
        full_list = all_words + all_sentences
        
        # 3. Filter by Group
        pool = []
        if active_groups:
            pool = [item for item in full_list if item.get('group', 'Default') in active_groups]
        else:
            pool = full_list
            
        if not pool:
            QMessageBox.warning(self, "Error", "No exercises found! Please import some content.")
            return

        # 4. Apply Strategies
        import random
        
        # Strategy: No Repeat (Filter out items with high score recently)
        # Assuming 'last_score' and 'mastered' flag logic (simple implementation: score >= 90)
        if strategy_no_repeat:
             pool = [item for item in pool if item.get('last_score', 0) < 90]
             if not pool:
                 QMessageBox.information(self, "Mastered", "Great job! You've mastered all items in these groups.")
                 return

        # Strategy: Smart (Prioritize unpracticed, then low scores)
        # Sort key: (times_practiced, last_score) ascending
        # So (0, 0) comes first. (1, 50) comes before (1, 100).
        if strategy_smart:
             pool.sort(key=lambda x: (x.get('times_practiced', 0), x.get('last_score', 0)))
             # If we sort, we pick the top N. But if Random is ALSO on, do we shuffle the top N? 
             # Or do we shuffle everything?
             # Usually "Smart" implies Order.
             # If Random + Smart: Maybe pick top N*2 candidates and shuffle them?
             # Let's keep it simple: Smart overrides Random for the *selection* phase.
        
        # Strategy: Random
        if strategy_random:
            # If Smart was ON, we might want to shuffle the *selected* batch, not the whole pool before selection.
            # But if Smart is OFF, we shuffle the whole pool.
            if not strategy_smart:
                 random.shuffle(pool)
        
        # 5. Limit Count
        self.current_exercise_list = pool[:practice_count]
        
        # If Smart is ON and Random is ON, shuffle the *result* so we don't always predict order
        if strategy_smart and strategy_random:
            random.shuffle(self.current_exercise_list)
            
        self.current_exercise_index = 0
        self.session_results = [] 
        
        self.auto_mode = self.chk_auto.isChecked()
        self.load_current_exercise()
        self.stack.setCurrentWidget(self.page_practice)
        
        # If auto mode, Start flow
        if self.auto_mode:
            self.recorder_widget.record_btn.setEnabled(False) 
            self.status_next_step("auto_start", 1000)

    def status_next_step(self, step, delay_ms):
        QTimer.singleShot(delay_ms, lambda: self.__process_step(step))
        
    def __process_step(self, step):
        # Safety check: if user backed out
        if self.stack.currentWidget() != self.page_practice and self.stack.currentWidget() != self.page_result:
             return
             
        if step == "auto_start":
            self.start_auto_recording()
        elif step == "auto_next":
            self.next_exercise()
        elif step == "play_tts":
            self.play_tts_reference()

    def auto_stop_recording(self):
        # This slot is called when VAD detects silence
        if self.recorder_widget.is_recording:
            self.recorder_widget.toggle_recording() # This stops it and triggers recording_finished

    def load_current_exercise(self):
        if self.current_exercise_index < len(self.current_exercise_list):
            data = self.current_exercise_list[self.current_exercise_index]
            self.lbl_word.setText(data.get("text", ""))
            self.lbl_phonetic.setText(data.get("phonetic", ""))
            self.lbl_translation.setText(data.get("translation", ""))
        else:
            # Finished
            self.page_summary.populate_results(self.session_results)
            self.stack.setCurrentWidget(self.page_summary)

    def next_exercise(self):
        self.current_exercise_index += 1
        # Check specific condition before switching widgets
        if self.current_exercise_index < len(self.current_exercise_list):
             self.load_current_exercise()
             self.stack.setCurrentWidget(self.page_practice)
        else:
             # Finished! load_current_exercise logic handles summary population
             self.load_current_exercise()
             # Logic inside load_current_exercise sets the widget, so we don't need to force it here?
             # Actually load_current_exercise sets logic. Let's rely on it or explicit here.
             # load_current_exercise sets summary widget in else block.
             pass
        
        if self.auto_mode and self.current_exercise_index < len(self.current_exercise_list):
             # Reduce delay to 500ms (was 1500ms) to feel more responsive
             self.status_next_step("auto_start", 500)
        
    def process_recording(self, file_path):
        self.last_recording_path = file_path

        # Safety check: ensure index is valid
        if self.current_exercise_index >= len(self.current_exercise_list):
            print("[MainWindow] Warning: process_recording called with invalid index.")
            return

        current_data = self.current_exercise_list[self.current_exercise_index]
        reference_text = current_data.get("text", "")
        
        # Assess synchronously (STT + scoring + rule-based feedback, fast)
        result = self.ai_coach.assess(file_path, reference_text)
        score = int(result.get("accuracy_score", 0))
        feedback_text = result.get("feedback", "")
        
        print(f"[MainWindow DEBUG] Text: {reference_text}")
        print(f"[MainWindow DEBUG] Score: {score}")
        print(f"[MainWindow DEBUG] Result Raw: {result}")
        
        self.last_details = result.get("details", {})
        self.last_reference_text = reference_text  # Track for async feedback
        
        # Save Result to Session
        self.session_results.append({
            "word": reference_text,
            "score": score
        })
        
        # Save Stats to Persistent DB (local copy)
        current_data['last_score'] = score
        current_data['times_practiced'] = current_data.get('times_practiced', 0) + 1

        # --- 同步到 exercise_manager（错题本持久化）---
        # 当 current_data 已经是 exercise_manager 中对象的引用（start_practice 流程），
        # 上面的赋值已经完成了更新，无需额外处理。
        # 当 current_data 是副本（oral_test_page / start_practice_with_list），
        # 需要找到对应条目并更新，找不到则添加。
        if not any(
            current_data is item
            for cat in self.exercise_manager.exercises
            for item in self.exercise_manager.exercises[cat]
        ):
            text = current_data.get('text', '')
            group = current_data.get('group', 'Default')
            if text:
                found = None
                for cat in self.exercise_manager.exercises:
                    for item in self.exercise_manager.exercises[cat]:
                        if item.get('text') == text and item.get('group', 'Default') == group:
                            found = item
                            break
                    if found:
                        break
                if found:
                    found['last_score'] = score
                    found['times_practiced'] = found.get('times_practiced', 0) + 1
                else:
                    new_item = {
                        'text': text,
                        'translation': current_data.get('translation', ''),
                        'group': group,
                        'phonetic': current_data.get('phonetic', ''),
                        'last_score': score,
                        'times_practiced': 1,
                    }
                    cat = 'sentences' if len(text.split()) > 2 else 'words'
                    if cat not in self.exercise_manager.exercises:
                        self.exercise_manager.exercises[cat] = []
                    self.exercise_manager.exercises[cat].append(new_item)

        self.exercise_manager.save_data()
        
        # 在评价页展示原句
        self.lbl_result_reference.setText(reference_text)
        
        # Display results immediately
        self.lbl_score.setText(f"Score: {score}")
        self.lbl_feedback.setText(feedback_text)
        self.lbl_feedback.setWordWrap(True)
        
        if score >= 90:
            self.lbl_score.setStyleSheet(AppStyles.SCORE_LABEL("high"))
            stars = 3
        elif score >= 70:
            self.lbl_score.setStyleSheet(AppStyles.SCORE_LABEL("mid"))
            self.status_next_step("play_tts", 500)
            stars = 2
        else:
            self.lbl_score.setStyleSheet(AppStyles.SCORE_LABEL("low"))
            self.status_next_step("play_tts", 500)
            stars = 1
            
        # Update Stars
        path_on = get_resource_path(os.path.join("src", "resources", "images", "star_gold.png"))
        path_off = get_resource_path(os.path.join("src", "resources", "images", "star_gray.png"))
        if os.path.exists(path_on) and os.path.exists(path_off):
            pix_on = QPixmap(path_on).scaled(60, 60, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            pix_off = QPixmap(path_off).scaled(60, 60, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            
            for i in range(3):
                if i < stars:
                    self.star_labels[i].setPixmap(pix_on)
                else:
                    self.star_labels[i].setPixmap(pix_off)
            
        self.stack.setCurrentWidget(self.page_result)
        
        # Trigger optional async LLM feedback (post-hoc explanation only).
        details = self.last_details
        self.ai_coach.generate_feedback_async(
            score=score,
            confidence=details.get("confidence", 1.0),
            reference_text=reference_text,
            recognized_text=details.get("recognized", ""),
            candidates=[]
        )
        
        # 读取配置中的停留时间（秒）
        # dwell > 0：评价页停留 dwell 秒后自动进入下一题（无论是否自动模式）
        # dwell == 0：手动模式，按空格 / Enter / 点击“下一题”
        dwell = 0
        config_path = get_user_data_path("config.json")
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    cfg = json.load(f)
                    dwell = cfg.get("result_dwell_seconds", 0)
            except (json.JSONDecodeError, IOError):
                pass

        if self.auto_mode:
            delay = 4500 if score < 90 else 2500
            if dwell > 0:
                delay = dwell * 1000
            self.status_next_step("auto_next", delay)
        elif dwell > 0:
            # 非自动模式但配置了停留时间，也自动进入下一题
            self.status_next_step("auto_next", dwell * 1000)

    def update_feedback_text(self, reference_word, feedback_text):
        """Slot for async LLM feedback. Only updates if still showing the same word."""
        # Verify we're still on the result page AND showing the same word
        if self.stack.currentWidget() != self.page_result:
            return
        if not hasattr(self, 'last_reference_text') or self.last_reference_text != reference_word:
            return
        
        self.lbl_feedback.setText(feedback_text)

    def play_last_recording(self):
        if self.last_recording_path and os.path.exists(self.last_recording_path):
            import winsound
            winsound.PlaySound(self.last_recording_path, winsound.SND_FILENAME | winsound.SND_ASYNC)

    def play_tts_reference(self):
        if self.current_exercise_index >= len(self.current_exercise_list):
            return
        current_data = self.current_exercise_list[self.current_exercise_index]
        text = current_data.get("text", "")
        self.tts.speak(text)
    
    def start_auto_recording(self):
        if not self.recorder_widget.is_recording:
             # Load device idx from config
             dev_idx = None
             config_path = get_user_data_path("config.json")
             if os.path.exists(config_path):
                 try:
                    with open(config_path, 'r', encoding='utf-8') as f:
                         dev_idx = json.load(f).get("device_index")
                 except Exception as e:
                     print(f"[MainWindow] Config read error: {e}")

             self.audio_recorder.start_recording(
                device_index=dev_idx,
                volume_callback=self.recorder_widget.on_volume_data,
                vad_enabled=True,
                stop_callback=self.signals.stop_signal.emit
             )
             self.recorder_widget.is_recording = True
             self.recorder_widget.record_btn.setStyleSheet(AppStyles.RECORD_BUTTON_ACTIVE)
             self.recorder_widget.status_label.setText("🎙️ Listening... (Auto Stop)")

    def show_debug_details(self):
        if hasattr(self, 'last_details') and self.last_details:
            d = self.last_details
            scoring_method = d.get('scoring_method', 'N/A')

            lines = [
                f" Scoring Method: {scoring_method}",
                f" Reference: {d.get('reference', '')}",
                f" Recognized (ASR): {d.get('recognized', '')}",
                f" Overall Score: {d.get('overall_score', 'N/A')}",
            ]

            # GOP-specific details (words / errors / fingerprint).
            if scoring_method.startswith("gop"):
                lines.append(f" Model Fingerprint: {d.get('model_fingerprint', '')}")
                lines.append(f" Pipeline Version: {d.get('pipeline_version', '')}")
                lines.append(f" Elapsed: {d.get('elapsed_ms', 0)} ms")
                words = d.get('words') or []
                if words:
                    word_str = ", ".join(f"{w.get('word','')}={w.get('score',0)}" for w in words)
                    lines.append(f" Word Scores: {word_str}")
                errors = d.get('errors') or []
                if errors:
                    err_str = "; ".join(
                        f"{e.get('type','')}({e.get('expected','')}->{e.get('actual','')}@{e.get('word','')})"
                        for e in errors[:6]
                    )
                    lines.append(f" Errors: {err_str}")

            if d.get("error"):
                lines.append(f" Error: {d['error']}")

            QMessageBox.information(self, "Scoring Logic (Debug)", "\n".join(lines))
        else:
            QMessageBox.information(self, "Debug", "No details available for this recording.")

    # ========== 全局快捷键 ==========
    def keyPressEvent(self, event):
        """Handle global keyboard shortcuts.

        - 评价页：按空格键 / Enter 键进入下一题
        """
        # Space / Enter on result page -> next exercise
        if self.stack.currentWidget() == self.page_result:
            if event.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self.next_exercise()
                return
        super().keyPressEvent(event)
