from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QPushButton, QLabel, 
                             QComboBox, QProgressBar, QHBoxLayout)
from PyQt6.QtCore import pyqtSignal, QSize, Qt, QThread
from PyQt6.QtGui import QIcon, QFont, QPixmap
import os
from .styles import AppStyles

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
        
        # Helper Text
        self.status_label = QLabel("Click Mic to Record 🎙️")
        self.status_label.setStyleSheet("font-size: 18px; color: #555;")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status_label)
        
        
        # Audio Device Selector (Removed - moved to Settings)
        # dev_layout = QHBoxLayout()
        # dev_label = QLabel("Mic:")
        self.device_combo = QComboBox() # kept as logical reference, but hidden if desired, or we just remove it fully and pass device idx
        # Actually easier to just hide it or don't add to layout, but main_window references it.
        # Let's keep the self.device_combo object but not show it, to minimize refactor, 
        # OR better: Main Window now reads config.json directly.
        
        # But wait, MainWindow code `start_auto_recording` still references `recorder_widget.device_combo`.
        # I should probably leave it but hide it, OR update MainWindow.
        # Let's hide it for now to avoid breaking references in MainWindow if I missed one.
        self.device_combo.setVisible(False) 
        
        # Icon Label (Visual Feedback)
        self.icon_label = QLabel()
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon_label.setFixedHeight(120) 
        layout.addWidget(self.icon_label)
        
        # Record Button
        self.record_btn = QPushButton("🎤")
        self.record_btn.setFixedSize(80, 80)
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
        self.volume_bar.setStyleSheet("QProgressBar::chunk { background-color: #4CAF50; }")
        layout.addWidget(self.volume_bar)
        
    def refresh_devices(self):
        self.device_combo.clear()
        devices = self.recorder.get_input_devices()
        for idx, name in devices:
            # name includes host api now
            self.device_combo.addItem(name, idx)
            
        if self.device_combo.count() > 0:
            self.device_combo.setCurrentIndex(0)
            
    def toggle_recording(self):
        listening_path = os.path.join("src", "resources", "images", "listening.png")
        
        if not self.is_recording:
            # Start
            device_idx = self.device_combo.currentData()
            self.recorder.start_recording(device_index=device_idx, volume_callback=self.on_volume_data)
            self.is_recording = True
            self.record_btn.setStyleSheet(AppStyles.RECORD_BUTTON_ACTIVE)
            self.status_label.setText("Recording... Speak now!")
            self.device_combo.setEnabled(False) # Lock device selection
            
            # Show Icon
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
            
            # Hide Icon
            self.icon_label.clear()
            
            if file_path:
                self.recording_finished.emit(file_path)
            else:
                self.status_label.setText("Recording failed. Try again.")
                
    def on_volume_data(self, rms_value):
        # Safety check: if widget is deleted (C++ object gone), this might still error if accessed property
        # Use simple try/except or check sip.isdeleted if needed, but isVisible is a good proxy in pure pyqt
        try:
            if not self.isVisible():
                return
            
            # Scale RMS is typically 0.0 to 1.0 (if float32), but can be low.
            # Log scale visual is better, but linear x 1000 might suffice for basic "is it working"
            level = int(rms_value * 1000) 
            level = min(100, max(0, level))
            self.volume_updated.emit(level)
        except RuntimeError:
            pass # Object deleted
        
    def update_volume_meter(self, value):
        self.volume_bar.setValue(int(value))
