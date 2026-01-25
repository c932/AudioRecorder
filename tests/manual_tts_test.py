import sys
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QUrl
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
import time

app = QApplication(sys.argv)
player = QMediaPlayer()
audio_output = QAudioOutput()
player.setAudioOutput(audio_output)
audio_output.setVolume(1.0)

def on_status_changed(status):
    print(f"Status: {status}")
    if status == QMediaPlayer.MediaStatus.EndOfMedia:
        print("Finished.")
        app.quit()

def on_error(error):
    print(f"Error: {player.errorString()}")
    app.quit()

player.mediaStatusChanged.connect(on_status_changed)
player.errorOccurred.connect(on_error)

# Test Youdao
text = "Hello"
url = f"https://dict.youdao.com/dictvoice?type=2&audio={text}"
print(f"Testing URL: {url}")

player.setSource(QUrl(url))
player.play()

print("Playing...")
sys.exit(app.exec())
