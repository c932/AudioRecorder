from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from PyQt6.QtCore import QUrl, QObject, QThread, pyqtSignal
import os
import asyncio
import tempfile
import edge_tts

class EdgeTTSWorker(QThread):
    finished = pyqtSignal(str) # Emits path to generated file
    error = pyqtSignal(str)

    def __init__(self, text, voice="en-US-AriaNeural"):
        super().__init__()
        self.text = text
        self.voice = voice

    def run(self):
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            import time
            import hashlib
            # Use hash of text for uniqueness AND caching benefit 
            # (though QMediaPlayer might still need Help disconnecting)
            text_hash = hashlib.md5(self.text.encode()).hexdigest()
            filename = f"tts_{text_hash}.mp3"
            output_file = os.path.join(tempfile.gettempdir(), filename)
            communicate = edge_tts.Communicate(self.text, self.voice)
            
            # Run the async save function
            loop.run_until_complete(communicate.save(output_file))
            loop.close()
            
            if os.path.exists(output_file) and os.path.getsize(output_file) > 0:
                self.finished.emit(output_file)
            else:
                self.error.emit("Generated file is empty or missing.")
                
        except Exception as e:
            self.error.emit(str(e))

class TTSEngine(QObject):
    def __init__(self):
        super().__init__()
        self.player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.player.setAudioOutput(self.audio_output)
        self.audio_output.setVolume(1.0)
        
        # Keep track of worker to prevent GC
        self.worker = None
        self.last_text = ""
        
        # Error handling for player (e.g. file format issues)
        self.player.errorOccurred.connect(self._on_player_error)

    def speak(self, text):
        if not text:
            return
            
        self.last_text = text
        print(f"[TTSEngine] Requesting Edge TTS for: {text}")

        # Start background generation
        self.worker = EdgeTTSWorker(text)
        self.worker.finished.connect(self._play_file)
        self.worker.error.connect(self._on_edge_error)
        self.worker.start()

    def _play_file(self, file_path):
        print(f"[TTSEngine] Playing generated file: {file_path}")
        self.player.setSource(QUrl.fromLocalFile(file_path))
        self.player.play()

    def _on_edge_error(self, error_msg):
        print(f"[TTSEngine] Edge TTS failed: {error_msg}")
        self._fallback_offline(self.last_text)
        
    def _on_player_error(self):
        print(f"[TTSEngine] Player Error: {self.player.errorString()}")
        # Only fallback if not already playing locally (prevent loops)
        # But here it's likely a file error, so fallback is safe
        self._fallback_offline(self.last_text)

    def _fallback_offline(self, text):
        print(f"[TTSEngine] Using Offline Fallback (pyttsx3) for: {text}")
        import threading
        t = threading.Thread(target=self._offline_worker, args=(text,), daemon=True)
        t.start()

    def _offline_worker(self, text):
        try:
            # Important for Windows SAPI5 in a thread
            try:
                import pythoncom
                pythoncom.CoInitialize()
            except:
                pass
            
            import pyttsx3
            engine = pyttsx3.init()
            engine.setProperty('rate', 130) # Slower for teaching
            
            # Try to set a good English voice if available
            voices = engine.getProperty('voices')
            for v in voices:
                if "english" in v.name.lower():
                    engine.setProperty('voice', v.id)
                    break
                    
            engine.say(text)
            engine.runAndWait()
        except Exception as e:
            print(f"[TTSEngine] Offline worker error: {e}")

