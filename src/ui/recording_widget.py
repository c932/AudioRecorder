from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QPushButton, QLabel,
                             QComboBox, QProgressBar, QHBoxLayout)
from PyQt6.QtCore import pyqtSignal, QSize, Qt, QThread
from PyQt6.QtGui import QIcon, QFont, QPixmap
import os
from .styles import AppStyles, FONT_FALLBACK, INK_SOFT, MANGO
from src.utils import get_resource_path

class RecordingWidget(QWidget):
    recording_finished = pyqtSignal(str) # Emits path to audio file
    volume_updated = pyqtSignal(int)   # Used to pass volume from thread to UI

    def __init__(self, audio_recorder):
        super().__init__()
        self.recorder = audio_recorder
        self.is_recording = False
        self.setup_ui()
        self.volume_updated.connect(self.update_volume_meter)

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # Helper Text
        self.status_label = QLabel("Tap the mic and say the word")
        self.status_label.setStyleSheet(AppStyles.BODY_LABEL)
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status_label)

        # Audio Device Selector (hidden, kept for backward compat)
        self.device_combo = QComboBox()
        self.device_combo.setVisible(False)

        # Icon Label (Visual Feedback)
        self.icon_label = QLabel()
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon_label.setFixedHeight(120)
        layout.addWidget(self.icon_label)

        # Record Button — the one round element (physical mic metaphor)
        self.record_btn = QPushButton("🎤")
        self.record_btn.setFixedSize(96, 96)
        self.record_btn.setStyleSheet(AppStyles.RECORD_BUTTON_IDLE)
        self.record_btn.clicked.connect(self.toggle_recording)
        self.record_btn.setFont(QFont("Segoe UI Emoji", 30))

        # Center button
        btn_container = QHBoxLayout()
        btn_container.addStretch()
        btn_container.addWidget(self.record_btn)
        btn_container.addStretch()
        layout.addLayout(btn_container)

        # Volume Meter
        self.volume_bar = QProgressBar()
        self.volume_bar.setRange(0, 100)
        self.volume_bar.setValue(0)
        self.volume_bar.setTextVisible(False)
        self.volume_bar.setFixedHeight(10)
        self.volume_bar.setStyleSheet(AppStyles.PROGRESS_BAR)
        layout.addWidget(self.volume_bar)

    def refresh_devices(self):
        self.device_combo.clear()
        devices = self.recorder.get_input_devices()
        for idx, name in devices:
            self.device_combo.addItem(name, idx)

        if self.device_combo.count() > 0:
            self.device_combo.setCurrentIndex(0)

    def toggle_recording(self):
        listening_path = get_resource_path(os.path.join("src", "resources", "images", "listening.png"))

        if not self.is_recording:
            # Start
            device_idx = self.device_combo.currentData()
            if device_idx is None:
                try:
                    from src.utils import get_user_data_path
                    import json
                    config_path = get_user_data_path("config.json")
                    if os.path.exists(config_path):
                        with open(config_path, 'r') as f:
                            device_idx = json.load(f).get("device_index")
                except Exception as e:
                    print(f"[RecordingWidget] Config read error: {e}")

            self.recorder.start_recording(device_index=device_idx, volume_callback=self.on_volume_data)
            self.is_recording = True
            self.record_btn.setStyleSheet(AppStyles.RECORD_BUTTON_ACTIVE)
            self.status_label.setText("Recording... Speak now!")
            self.device_combo.setEnabled(False)

            if os.path.exists(listening_path):
                 self.icon_label.setPixmap(QPixmap(listening_path).scaled(100, 100, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

        else:
            # Stop
            file_path = self.recorder.stop_recording()
            self.is_recording = False
            self.record_btn.setStyleSheet(AppStyles.RECORD_BUTTON_IDLE)
            self.status_label.setText("Analyzing...")
            self.device_combo.setEnabled(True)
            self.volume_bar.setValue(0)

            self.icon_label.clear()

            if file_path:
                self.recording_finished.emit(file_path)
            else:
                self.status_label.setText("Recording failed. Try again.")

    def on_volume_data(self, rms_value):
        try:
            if not self.isVisible():
                return
            level = int(rms_value * 1000)
            level = min(100, max(0, level))
            self.volume_updated.emit(level)
        except RuntimeError:
            pass

    def update_volume_meter(self, value):
        self.volume_bar.setValue(int(value))

    def reset_state(self):
        """Force reset UI state (e.g. when external stop occurs or navigating away)."""
        if self.is_recording:
             self.recorder.stop_recording()
             self.is_recording = False

        self.record_btn.setStyleSheet(AppStyles.RECORD_BUTTON_IDLE)
        self.status_label.setText("Tap the mic and say the word")
        self.device_combo.setEnabled(True)
        self.volume_bar.setValue(0)
        self.icon_label.clear()
