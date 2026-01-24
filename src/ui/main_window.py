from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, 
                             QLabel, QPushButton, QHBoxLayout, QStackedWidget, QMessageBox, QCheckBox)
from PyQt6.QtCore import Qt, pyqtSignal, QObject, QTimer
from PyQt6.QtGui import QIcon, QFont, QPixmap
from src.ui.styles import AppStyles
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
        
        self.exercise_manager = ExerciseManager(os.path.join("src", "data", "words.json"))
        self.tts = TTSEngine()
        
        # Signals
        self.signals = ValidSignal()
        self.signals.stop_signal.connect(self.auto_stop_recording)
        
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
        
        self.stack.addWidget(self.page_home)
        self.stack.addWidget(self.page_practice)
        self.stack.addWidget(self.page_result)
        self.stack.addWidget(self.page_summary)
        self.stack.addWidget(self.page_mistakes)
        
        self.current_exercise_index = 0
        self.current_exercise_list = []
        
    def create_home_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        
        # Top Bar (Settings)
        top_layout = QHBoxLayout()
        top_layout.addStretch()
        btn_settings = QPushButton("⚙ Settings")
        btn_settings.setStyleSheet("background-color: #607D8B; color: white; border-radius: 5px; padding: 8px;")
        btn_settings.clicked.connect(self.open_settings)
        top_layout.addWidget(btn_settings)
        layout.addLayout(top_layout)
        
        # Mascot Image
        mascot_path = os.path.join("src", "resources", "images", "mascot.png")
        if os.path.exists(mascot_path):
            lbl_mascot = QLabel()
            pixmap = QPixmap(mascot_path).scaled(200, 200, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            lbl_mascot.setPixmap(pixmap)
            lbl_mascot.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(lbl_mascot)
        
        header = QLabel("Welcome to English Coach!")
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header.setStyleSheet(AppStyles.HEADER_LABEL)
        layout.addWidget(header)
        
        layout.addStretch()
        
        # Auto Mode Toggle (Active but hidden from UI, controlled by Settings)
        self.chk_auto = QCheckBox("⚡ Auto Mode")
        self.chk_auto.setVisible(False) # Hide it
        
        # Load default state
        if os.path.exists("config.json"):
             try:
                with open("config.json", 'r') as f:
                    config = json.load(f)
                    self.chk_auto.setChecked(config.get("auto_mode_default", True))
             except: pass
        
        # Main Start Button (Merged)
        btn_start = QPushButton("🚀 Start Practice")
        btn_start.setStyleSheet(AppStyles.BIG_BUTTON)
        btn_start.clicked.connect(self.start_practice)
        layout.addWidget(btn_start, alignment=Qt.AlignmentFlag.AlignCenter)
        
        # Import Button
        btn_import = QPushButton("Import from PDF 📄")
        btn_import.setStyleSheet("background-color: #795548; color: white; font-size: 16px; padding: 10px; border-radius: 8px; margin-top: 10px;")
        btn_import.clicked.connect(self.open_import_dialog)
        layout.addWidget(btn_import, alignment=Qt.AlignmentFlag.AlignCenter)
        
        # Mistake Review Button
        btn_mistakes = QPushButton("Review Mistakes ❌")
        btn_mistakes.setStyleSheet("background-color: #D32F2F; color: white; font-size: 16px; padding: 10px; border-radius: 8px; margin-top: 10px;")
        btn_mistakes.clicked.connect(self.open_mistakes_page)
        layout.addWidget(btn_mistakes, alignment=Qt.AlignmentFlag.AlignCenter)
        
        layout.addStretch()
        return page

    def open_settings(self):
        dialog = SettingsDialog(self, self.audio_recorder, self.exercise_manager)
        if dialog.exec():
            # Reload AI config
            self.ai_coach.load_config()

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
        layout = QVBoxLayout(page)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # Navigation back
        top_bar = QHBoxLayout()
        btn_back = QPushButton("⬅ Back")
        btn_back.clicked.connect(self.stop_and_home)
        btn_back.setStyleSheet("font-size: 16px; padding: 5px;")
        top_bar.addWidget(btn_back)
        top_bar.addStretch()
        layout.addLayout(top_bar)
        
        layout.addStretch()
        
        # Word Display
        self.lbl_word = QLabel("Apple")
        self.lbl_word.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_word.setStyleSheet(AppStyles.WORD_DISPLAY)
        self.lbl_word.setWordWrap(True) # SENTENCES need wrap
        layout.addWidget(self.lbl_word)
        
        self.lbl_phonetic = QLabel("/ˈæp.əl/")
        self.lbl_phonetic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_phonetic.setStyleSheet(AppStyles.PHONETIC_DISPLAY)
        layout.addWidget(self.lbl_phonetic)
        
        self.lbl_translation = QLabel("苹果")
        self.lbl_translation.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_translation.setStyleSheet("font-size: 20px; color: #666;")
        self.lbl_translation.setWordWrap(True)
        layout.addWidget(self.lbl_translation)
        
        layout.addStretch()
        
        # Recorder
        self.recorder_widget = RecordingWidget(self.audio_recorder)
        self.recorder_widget.recording_finished.connect(self.process_recording)
        layout.addWidget(self.recorder_widget)
        
        layout.addStretch()
        
        # Next Button (Hidden initially)
        self.btn_next = QPushButton("Skip / Next ➡")
        self.btn_next.clicked.connect(self.next_exercise)
        self.btn_next.setStyleSheet("font-size: 18px; padding: 10px; background-color: #ddd;")
        layout.addWidget(self.btn_next)
        
        return page
        
    def stop_and_home(self):
        self.audio_recorder.stop_recording()
        self.stack.setCurrentWidget(self.page_home)

    def create_result_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        self.lbl_score = QLabel("Score: 95")
        self.lbl_score.setStyleSheet("font-size: 36px; font-weight: bold; color: #2E7D32;")
        layout.addWidget(self.lbl_score)
        
        # Star Rating Layout
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
        self.lbl_feedback.setStyleSheet("font-size: 24px; color: #333;")
        layout.addWidget(self.lbl_feedback)
        
        # Actions
        btn_layout = QHBoxLayout()
        
        btn_play = QPushButton("🔊 Listen")
        btn_play.setStyleSheet(AppStyles.BIG_BUTTON)
        btn_play.clicked.connect(self.play_last_recording)
        btn_layout.addWidget(btn_play)
        
        btn_tts = QPushButton("🗣 Standard")
        btn_tts.setStyleSheet("background-color: #9C27B0; color: white; font-size: 20px; padding: 15px; border-radius: 10px; min-width: 150px;")
        btn_tts.clicked.connect(self.play_tts_reference)
        btn_layout.addWidget(btn_tts)
        
        btn_retry = QPushButton("Try Again 🔄")
        btn_retry.setStyleSheet(AppStyles.BIG_BUTTON)
        btn_retry.clicked.connect(lambda: self.stack.setCurrentWidget(self.page_practice))
        btn_layout.addWidget(btn_retry)
        
        layout.addLayout(btn_layout)
        
        btn_continue = QPushButton("Next Word ➡")
        btn_continue.setStyleSheet("background-color: #0288D1; color: white; font-size: 20px; padding: 15px; border-radius: 10px; margin-top: 20px;")
        btn_continue.clicked.connect(self.next_exercise)
        layout.addWidget(btn_continue)
        
        self.last_recording_path = None
        
        return page

    def open_mistakes_page(self):
        self.page_mistakes.refresh_data()
        self.stack.setCurrentWidget(self.page_mistakes)

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
        config = {}
        if os.path.exists("config.json"):
             try:
                with open("config.json", 'r') as f:
                    config = json.load(f)
             except: pass
        
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
            # Programmatically click record or call toggle
            if not self.recorder_widget.is_recording:
                # Load device idx from config
                dev_idx = None
                if os.path.exists("config.json"):
                    try:
                        with open("config.json", 'r') as f:
                             dev_idx = json.load(f).get("device_index")
                    except: 
                        pass # Ignore config error

                # Setup VAD callback
                self.audio_recorder.start_recording(
                    device_index=dev_idx,
                    volume_callback=self.recorder_widget.on_volume_data,
                    vad_enabled=True,
                    stop_callback=self.signals.stop_signal.emit
                )
                self.recorder_widget.is_recording = True
                self.recorder_widget.record_btn.setStyleSheet(AppStyles.RECORD_BUTTON_ACTIVE)
                self.recorder_widget.status_label.setText("🎙️ Listening... (Auto Stop Enabled)")
                # self.recorder_widget.device_combo.setEnabled(False) # Removed combo

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
        current_data = self.current_exercise_list[self.current_exercise_index]
        reference_text = current_data.get("text", "")
        
        result = self.ai_coach.assess(file_path, reference_text)
        score = int(result.get("accuracy_score", 0))
        feedback_text = result.get("feedback", "")
        
        
        # Save Result to Session
        self.session_results.append({
            "word": reference_text,
            "score": score
        })
        
        # Save Stats to Persistent DB
        current_data['last_score'] = score
        current_data['times_practiced'] = current_data.get('times_practiced', 0) + 1
        # Trigger save (Is this too frequent? Maybe. specific save?)
        # For safety/real-time, saving now is fine.
        self.exercise_manager.save_data()
        
        self.lbl_score.setText(f"Score: {score}")
        self.lbl_feedback.setText(feedback_text)
        self.lbl_feedback.setWordWrap(True)
        
        if score >= 90:
            self.lbl_score.setStyleSheet("font-size: 36px; font-weight: bold; color: #2E7D32;")
            stars = 3
        elif score >= 70:
            self.lbl_score.setStyleSheet("font-size: 36px; font-weight: bold; color: #F57F17;")
            # Auto Play Correct Pronunciation for mediocre scores too
            self.status_next_step("play_tts", 500)
            stars = 2
        else:
            self.lbl_score.setStyleSheet("font-size: 36px; font-weight: bold; color: #D32F2F;")
            # Auto Play Correct Pronunciation
            self.status_next_step("play_tts", 500)
            stars = 1
            
        # Update Stars
        path_on = os.path.join("src", "resources", "images", "star_gold.png")
        path_off = os.path.join("src", "resources", "images", "star_gray.png")
        if os.path.exists(path_on) and os.path.exists(path_off):
            pix_on = QPixmap(path_on).scaled(60, 60, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            pix_off = QPixmap(path_off).scaled(60, 60, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            
            for i in range(3):
                if i < stars:
                    self.star_labels[i].setPixmap(pix_on)
                else:
                    self.star_labels[i].setPixmap(pix_off)
            
        self.stack.setCurrentWidget(self.page_result)
        
        if self.auto_mode:
            # Auto next, but account for TTS time if score low
            # If we played TTS, delay should be longer
            delay = 4500 if score < 90 else 2500
            self.status_next_step("auto_next", delay)
            
    def __process_step(self, step):
        # Validation checks...
        if step == "auto_next":
            self.next_exercise()
        elif step == "auto_start":
            self.start_auto_recording()
        elif step == "play_tts":
             self.play_tts_reference()

    def play_last_recording(self):
        if self.last_recording_path and os.path.exists(self.last_recording_path):
            import winsound
            winsound.PlaySound(self.last_recording_path, winsound.SND_FILENAME | winsound.SND_ASYNC)

    def play_tts_reference(self):
        current_data = self.current_exercise_list[self.current_exercise_index]
        text = current_data.get("text", "")
        self.tts.speak(text)
    
    def start_auto_recording(self):
        if not self.recorder_widget.is_recording:
             # Load device idx from config
             dev_idx = None
             if os.path.exists("config.json"):
                 try:
                    with open("config.json", 'r') as f:
                         dev_idx = json.load(f).get("device_index")
                 except: 
                     pass
                      
             self.audio_recorder.start_recording(
                device_index=dev_idx,
                volume_callback=self.recorder_widget.on_volume_data,
                vad_enabled=True,
                stop_callback=self.signals.stop_signal.emit
             )
             self.recorder_widget.is_recording = True
             self.recorder_widget.record_btn.setStyleSheet(AppStyles.RECORD_BUTTON_ACTIVE)
             self.recorder_widget.status_label.setText("🎙️ Listening... (Auto Stop)")
