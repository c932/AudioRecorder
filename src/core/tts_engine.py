from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from PyQt6.QtCore import QUrl
from PyQt6.QtCore import QObject

class TTSEngine(QObject):
    def __init__(self):
        super().__init__()
        self.player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.player.setAudioOutput(self.audio_output)
        self.audio_output.setVolume(1.0)
            
    def speak(self, text):
        if not text:
            return
            
        # Youdao API: type=2 is US English
        # Encode text for URL
        import urllib.parse
        encoded_text = urllib.parse.quote(text)
        url = f"https://dict.youdao.com/dictvoice?type=2&audio={encoded_text}"
        
        self.player.setSource(QUrl(url))
        self.player.play()
