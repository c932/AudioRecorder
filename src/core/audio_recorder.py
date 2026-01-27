import sounddevice as sd
import soundfile as sf
import numpy as np
import threading
import queue
import os
import tempfile

class AudioRecorder:
    def __init__(self):
        self.samplerate = 16000  # Azure Speech SDK prefers 16kHz
        self.channels = 1
        self.recording = False
        self.frames = []
        self.stream = None
        self.output_filename = os.path.join(tempfile.gettempdir(), "recording.wav")
        self.error_message = None

    def list_devices(self):
        try:
            return sd.query_devices()
        except Exception as e:
            print(f"Error querying devices: {e}")
            return []

    def get_input_devices(self):
        """Returns a list of (index, name) for input devices. Filters for MME to avoid duplicates."""
        devices = []
        try:
            host_apis = sd.query_hostapis()
            all_devices = sd.query_devices()
            
            # Find the MME host API index
            mme_index = -1
            for i, api in enumerate(host_apis):
                if "MME" in api['name']:
                    mme_index = i
                    break
            
            for i, dev in enumerate(all_devices):
                if dev['max_input_channels'] > 0:
                    # Filter: Only accept MME devices to match standard Windows list
                    if dev['hostapi'] == mme_index:
                        name = dev['name']
                        # Filter out the "Sound Mapper" or "Primary Sound Capture" if you strictly want physical devs,
                        # but "Microsoft Sound Mapper" is the "Default" device, which is useful.
                        # Let's clean up the name though.
                        # Usually "Microphone (Device Name)"
                        devices.append((i, name))
                        
        except Exception as e:
            print(f"Error getting input devices: {e}")
            # Fallback
            try:
                return [(i, d['name']) for i, d in enumerate(sd.query_devices()) if d['max_input_channels'] > 0]
            except Exception:
                return []
        return devices

    def _callback(self, indata, frames, time, status):
        """This is called (from a separate thread) for each audio block."""
        if status:
            print(status, flush=True)
            
        if self.recording:
            self.frames.append(indata.copy())
            
            # Calculate volume (RMS)
            rms = np.sqrt(np.mean(indata**2))
            
            # Visualization callback
            if self.volume_callback:
                self.volume_callback(rms)
                
            # VAD Logic (Auto Stop)
            if self.vad_enabled:
                import time as t
                now = t.time()
                
                # Simple Threshold Logic
                # RMS ~0.01 is quiet room, >0.03 is speaking closer to mic
                if rms > self.vad_threshold:
                    self.last_speech_time = now
                    if not self.speech_detected:
                        self.speech_detected = True
                        print("Voice detected.")
                
                # If we have detected speech previously, and it's been silent for X seconds
                if self.speech_detected:
                    if (now - self.last_speech_time) > self.vad_silence_duration:
                        print("Silence detected, stopping...")
                        # We need to stop recording, but we are in a callback thread.
                        # We shouldn't call stop_recording() directly as it might block or be unsafe.
                        # Instead, we signal the main thread or set a flag.
                        # For simplicity in this architecture, we might need a threading Event or callback.
                        if self.stop_callback:
                            self.stop_callback()
                        
                        # Prevent multiple triggers
                        self.vad_enabled = False 

    def start_recording(self, device_index=None, volume_callback=None, 
                        vad_enabled=False, stop_callback=None):
        if self.recording:
            return
        
        self.frames = []
        self.recording = True
        self.error_message = None
        self.volume_callback = volume_callback
        
        # VAD Init
        self.vad_enabled = vad_enabled
        self.vad_threshold = 0.02 # Adjust based on mic
        self.vad_silence_duration = 1.5 # Seconds
        self.last_speech_time = 0
        self.speech_detected = False
        self.stop_callback = stop_callback
        
        if self.vad_enabled:
            import time as t
            self.last_speech_time = t.time() # Reset timer so we don't stop immediately
        
        try:
            self.stream = sd.InputStream(
                samplerate=self.samplerate,
                device=device_index,
                channels=self.channels,
                callback=self._callback
            )
            self.stream.start()
            print(f"Recording started on device {device_index}...")
        except Exception as e:
            self.recording = False
            self.error_message = str(e)
            print(f"Error starting recording: {e}")

    def stop_recording(self):
        if not self.recording:
            return None
            
        self.recording = False
        if self.stream:
            self.stream.stop()
            self.stream.close()
            self.stream = None
            print("Recording stopped.")
            
        return self.save_recording()

    def save_recording(self):
        if not self.frames:
            print("[AudioRecorder] Warning: No audio frames captured.")
            return None
            
        try:
            # Concatenate all numpy arrays
            recording_data = np.concatenate(self.frames, axis=0)

            # Check if recording is too short (less than 0.3 seconds)
            min_samples = int(self.samplerate * 0.3)
            if len(recording_data) < min_samples:
                print(f"[AudioRecorder] Warning: Recording too short ({len(recording_data)} samples).")
                return None

            # Save to WAV file
            sf.write(self.output_filename, recording_data, self.samplerate)
            return self.output_filename
        except Exception as e:
            print(f"[AudioRecorder] Error saving file: {e}")
            return None

