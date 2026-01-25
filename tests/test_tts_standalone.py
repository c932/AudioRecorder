import sys
import asyncio
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer

# Add src to path
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

from core.tts_engine import TTSEngine

def test_tts():
    app = QApplication(sys.argv)
    
    engine = TTSEngine()
    
    print("Testing Edge TTS...")
    engine.speak("Hello! This is a test of the Microsoft Edge Text to Speech engine.")
    
    # Run for 5 seconds then exit
    QTimer.singleShot(7000, app.quit)
    
    app.exec()
    print("Test finished.")

if __name__ == "__main__":
    test_tts()
