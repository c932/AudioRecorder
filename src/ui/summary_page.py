from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QPushButton, QLabel, 
                             QScrollArea, QFrame, QHBoxLayout)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
from .styles import AppStyles

class SummaryPage(QWidget):
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self.setup_ui()
        
    def setup_ui(self):
        self.layout = QVBoxLayout(self)
        
        header = QLabel("🎉 Practice Complete! 🎉")
        header.setStyleSheet("font-size: 28px; font-weight: bold; color: #E91E63; margin: 20px;")
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.layout.addWidget(header)
        
        # Scroll Area for results
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.scroll_content = QWidget()
        self.scroll_layout = QVBoxLayout(self.scroll_content)
        scroll.setWidget(self.scroll_content)
        self.layout.addWidget(scroll)
        
        # Button
        btn_home = QPushButton("🏠 Back to Home")
        btn_home.setStyleSheet(AppStyles.BIG_BUTTON)
        btn_home.clicked.connect(lambda: self.main_window.stack.setCurrentWidget(self.main_window.page_home))
        self.layout.addWidget(btn_home, alignment=Qt.AlignmentFlag.AlignCenter)
        
    def populate_results(self, results):
        # Clear previous
        for i in reversed(range(self.scroll_layout.count())): 
            item = self.scroll_layout.itemAt(i)
            if item.widget():
                item.widget().setParent(None)
            else:
                self.scroll_layout.removeItem(item)
        
        # Calculate Stats
        total_score = 0
        count = len(results)
        
        if count > 0:
            total_score = sum(r.get("score", 0) for r in results)
            avg_score = total_score / count
            
            # Message Logic & Sound
            sound_file = None
            
            # Load config to check preferred language
            import json
            import os
            lang_suffix = "_en" # Default
            if os.path.exists("config.json"):
                try:
                    with open("config.json", 'r') as f:
                        cfg = json.load(f)
                        if cfg.get("feedback_language") == "zh":
                            lang_suffix = "_zh"
                except: pass
            
            if avg_score >= 95:
                msg = "🏆 哇塞！完美发音！你就是英语小天才！(Genius!)"
                color = "#2E7D32" # Green
                sound_file = f"perfect{lang_suffix}.wav"
            elif avg_score >= 90:
                msg = "🌟 太棒啦！发音超级标准，给你比心心！(Excellent!)"
                color = "#2E7D32" 
                sound_file = f"excellent{lang_suffix}.wav"
            elif avg_score >= 80:
                msg = "👍 不错哟！进步很大，继续加油！(Good Job!)"
                color = "#F57F17" # Orange
                sound_file = f"good{lang_suffix}.wav"
            else:
                msg = "💪 别灰心，多练几遍你一定行！(Keep Going!)"
                color = "#5D4037" # Brown
                sound_file = f"encourage{lang_suffix}.wav"
                
            # Display Trophy or Mascot
            img_file = "trophy.png" if avg_score >= 80 else "mascot.png"
            img_path = os.path.join("src", "resources", "images", img_file)
            
            if os.path.exists(img_path):
                lbl_img = QLabel()
                pix = QPixmap(img_path).scaled(150, 150, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                lbl_img.setPixmap(pix)
                lbl_img.setAlignment(Qt.AlignmentFlag.AlignCenter)
                self.scroll_layout.addWidget(lbl_img)
                
            report_card = QLabel(f"{msg}\n平均分 (Average Score): {avg_score:.1f}")
            report_card.setAlignment(Qt.AlignmentFlag.AlignCenter)
            report_card.setStyleSheet(f"font-size: 24px; font-weight: bold; color: {color}; margin-bottom: 20px; border: 2px dashed {color}; padding: 15px; border-radius: 10px;")
            self.scroll_layout.addWidget(report_card)
            
            # Play Sound or TTS
            self.play_feedback_sound(sound_file, msg)
        
        for res in results:
            word = res.get("word", "Unknown")
            score = res.get("score", 0)
            
            # Color code
            color = "#4CAF50" if score >= 85 else ("#FF9800" if score >= 60 else "#F44336")
            
            row = QFrame()
            row.setStyleSheet(f"background-color: white; border-radius: 10px; border-left: 10px solid {color}; padding: 10px; margin-bottom: 5px;")
            row_layout = QHBoxLayout(row)
            
            lbl_word = QLabel(f"{word}")
            lbl_word.setStyleSheet("font-size: 20px; font-weight: bold;")
            
            lbl_score = QLabel(f"{score}")
            lbl_score.setStyleSheet(f"font-size: 20px; color: {color}; font-weight: bold;")
            
            row_layout.addWidget(lbl_word)
            row_layout.addStretch()
            row_layout.addWidget(lbl_score)
            
            self.scroll_layout.addWidget(row)
            
        self.scroll_layout.addStretch()

    def play_feedback_sound(self, filename, text_msg):
        """Plays a wav file from src/resources/sounds/ or falls back to TTS."""
        import os
        import winsound
        
        # Check defaults first
        sound_dir = os.path.join("src", "resources", "sounds")
        if not os.path.exists(sound_dir):
            try:
                os.makedirs(sound_dir)
            except: pass
            
        full_path = os.path.join(sound_dir, filename) if filename else ""
        
        if full_path and os.path.exists(full_path):
            try:
                winsound.PlaySound(full_path, winsound.SND_FILENAME | winsound.SND_ASYNC)
                return
            except:
                pass
        
        # Fallback: Use TTS to speak the Chinese message
        # We need access to TTS engine. It's in main_window.tts
        # Just speak the Chinese part (before the parenthesis if any)
        speak_text = text_msg.split('(')[0]
        if self.main_window and hasattr(self.main_window, 'tts'):
            self.main_window.tts.speak(speak_text)
