import time
import os
import sys

# Add project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.core.audio_recorder import AudioRecorder

def test_recorder():
    recorder = AudioRecorder()
    devices = recorder.list_devices()
    print("Devices:", devices)
    
    print("Starting recording for 3 seconds...")
    recorder.start_recording()
    time.sleep(3)
    path = recorder.stop_recording()
    
    if path and os.path.exists(path):
        print(f"Recording successful! Saved to: {path}")
        print(f"File size: {os.path.getsize(path)} bytes")
    else:
        print("Recording failed.")

if __name__ == "__main__":
    test_recorder()
