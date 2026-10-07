from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from PyQt6.QtCore import QUrl, QObject, QThread, pyqtSignal
import os
import asyncio
import tempfile
import edge_tts
import numpy as np # Critical: Needed for silence padding

import subprocess

class KokoroWorker(QThread):
    finished = pyqtSignal(str)
    error = pyqtSignal(str)
    
    def __init__(self, kokoro_instance, text, voice="af_bella"):
        super().__init__()
        self.kokoro = kokoro_instance
        self.text = text
        self.voice = voice # af_bella is a good American Female voice in Kokoro
        
    def run(self):
        try:
            import hashlib
            import soundfile as sf
            
            # Use hash for cache
            # Use hash for cache
            text_hash = hashlib.md5(self.text.encode()).hexdigest()
            # Changed suffix to _padded.wav to invalidate old cache (missing padding)
            filename = f"kokoro_{text_hash}_padded.wav"
            output_file = os.path.join(tempfile.gettempdir(), filename)
            
            if os.path.exists(output_file) and os.path.getsize(output_file) > 1000:
                self.finished.emit(output_file)
                return

            # Generate
            # create_audio returns (samples, sample_rate)
            # Disable trim AND add explicit padding (0.4s) to fix "missing start" issue
            samples, sample_rate = self.kokoro.create(self.text, voice=self.voice, speed=1.0, lang="en-us", trim=False)
            
            # Add 0.4s silence at the start (Sample rate is usually 24000)
            padding_size = int(sample_rate * 0.4)
            silence = np.zeros(padding_size, dtype=np.float32)
            samples = np.concatenate((silence, samples))
            
            # Save to WAV
            sf.write(output_file, samples, sample_rate)
            
            if os.path.exists(output_file):
                self.finished.emit(output_file)
            else:
                self.error.emit("Kokoro generation failed to write file.")
                
        except Exception as e:
            self.error.emit(str(e))

class PiperWorker(QThread):
    finished = pyqtSignal(str)
    error = pyqtSignal(str)
    
    def __init__(self, text, piper_path, model_path):
        super().__init__()
        self.text = text
        self.piper_path = piper_path
        self.model_path = model_path
        
    def run(self):
        try:
            import hashlib
            # Use hash for cache
            text_hash = hashlib.md5(self.text.encode()).hexdigest()
            filename = f"piper_{text_hash}.wav"
            output_file = os.path.join(tempfile.gettempdir(), filename)
            
            if os.path.exists(output_file) and os.path.getsize(output_file) > 1000:
                self.finished.emit(output_file)
                return

            # Run Piper via subprocess
            # echo "text" | piper.exe -m model.onnx -f output.wav
            cmd = [
                self.piper_path,
                "--model", self.model_path,
                "--output_file", output_file
            ]
            
            # Windows: input via stdin requires proper encoding
            p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
            # Encode text to utf-8
            out, err = p.communicate(input=self.text.encode('utf-8'))
            
            if p.returncode == 0 and os.path.exists(output_file):
                self.finished.emit(output_file)
            else:
                self.error.emit(f"Piper failed: {err.decode('utf-8', errors='ignore')}")
                
        except Exception as e:
            self.error.emit(str(e))

class CosyVoiceWorker(QThread):
    """Worker that calls CosyVoice FastAPI server for TTS.

    CosyVoice2-0.5B 使用 inference_cross_lingual（仅需 prompt_wav）。
    注意：inference_instruct2 的 instruct_text 会被模型当作朗读内容输出，不可用。
    音色由 cosyvoice_prompt.wav 参考音频决定。
    """
    finished = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, text, server_url="http://localhost:50000", spk_id="英文女"):
        super().__init__()
        self.text = text
        self.server_url = server_url.rstrip("/")
        self.spk_id = spk_id

    def run(self):
        try:
            import hashlib
            import requests
            import wave

            # Cache by text hash
            text_hash = hashlib.md5(self.text.encode()).hexdigest()
            filename = f"cosyvoice_{text_hash}.wav"
            output_file = os.path.join(tempfile.gettempdir(), filename)

            if os.path.exists(output_file) and os.path.getsize(output_file) > 1000:
                self.finished.emit(output_file)
                return

            prompt_wav = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                       "data", "cosyvoice_prompt.wav")
            if not os.path.exists(prompt_wav):
                self.error.emit(f"CosyVoice 参考音频不存在: {prompt_wav}")
                return

            # inference_cross_lingual：tts_text + prompt_wav，无 instruct_text
            with open(prompt_wav, "rb") as f:
                resp = requests.post(
                    f"{self.server_url}/inference_cross_lingual",
                    data={"tts_text": self.text},
                    files={"prompt_wav": ("prompt.wav", f, "audio/wav")},
                    timeout=60,
                )
            if resp.status_code != 200:
                self.error.emit(f"CosyVoice 返回 {resp.status_code}: {resp.text[:200]}")
                return
            pcm_data = resp.content
            if len(pcm_data) < 100:
                self.error.emit("CosyVoice 返回空音频")
                return

            # 写 WAV 文件
            sample_rate = 24000
            with wave.open(output_file, 'wb') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)  # 16-bit
                wf.setframerate(sample_rate)
                wf.writeframes(pcm_data)

            if os.path.exists(output_file) and os.path.getsize(output_file) > 100:
                self.finished.emit(output_file)
            else:
                self.error.emit("CosyVoice: output file is empty")

        except requests.exceptions.ConnectionError:
            self.error.emit("CosyVoice server not running. Start it with: python server.py --model_dir pretrained_models/CosyVoice2-0.5B")
        except Exception as e:
            self.error.emit(f"CosyVoice error: {str(e)}")


def _has_chinese(text: str) -> bool:
    """Check if text contains Chinese characters."""
    return any('\u4e00' <= c <= '\u9fff' for c in text)


class EdgeTTSWorker(QThread):
    finished = pyqtSignal(str) # Emits path to generated file
    error = pyqtSignal(str)

    def __init__(self, text, voice=None):
        super().__init__()
        self.text = text
        # Auto-select voice: Chinese voice for Chinese+English mixed text
        if voice is None:
            self.voice = "zh-CN-XiaoxiaoNeural" if _has_chinese(text) else "en-US-AriaNeural"
        else:
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
    MAX_FAILURES = 2
    
    def __init__(self):
        super().__init__()
        self.player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.player.setAudioOutput(self.audio_output)
        self.audio_output.setVolume(1.0)
        
        # Keep track of worker to prevent GC
        self.worker = None
        self.last_text = ""
        
        # Check for Piper
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.piper_exe = os.path.join(base_dir, "resources", "piper", "piper", "piper.exe")
        self.piper_model = os.path.join(base_dir, "resources", "piper", "voices", "en_US-amy-medium.onnx")
        self.use_piper = os.path.exists(self.piper_exe) and os.path.exists(self.piper_model)
        
        if self.use_piper:
            print(f"[TTSEngine] 🚀 Piper TTS found! Using high-quality offline model.")
            
        # Check for Kokoro
        self.kokoro_onnx_path = os.path.join(base_dir, "resources", "kokoro", "kokoro-v0_19.onnx")
        self.kokoro_voices_path = os.path.join(base_dir, "resources", "kokoro", "voices.json")
        self.kokoro_instance = None
        self.use_kokoro = False
        
        if os.path.exists(self.kokoro_onnx_path) and os.path.exists(self.kokoro_voices_path):
            try:
                from kokoro_onnx import Kokoro
                import numpy as np
                import onnxruntime as rt
                from kokoro_onnx.config import KoKoroConfig
                from kokoro_onnx.tokenizer import Tokenizer
                
                # Subclass to safely load pickled OR json voices.json
                class SafeKokoro(Kokoro):
                    def __init__(self, model_path, voices_path, espeak_config=None, vocab_config=None):
                        # Re-implement __init__ to support JSON voices
                        
                        # Basic Setup
                        self.config = KoKoroConfig(model_path, voices_path, espeak_config)
                        self.config.validate()
                        
                        # GPU Detection for ONNX Runtime
                        available_providers = rt.get_available_providers()
                        print(f"[Kokoro] Available ONNX providers: {available_providers}")

                        # Try CUDA first, with fallback if CUDA libs are missing
                        self.sess = None

                        if "CUDAExecutionProvider" in available_providers:
                            try:
                                providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
                                self.sess = rt.InferenceSession(model_path, providers=providers)
                                print("[Kokoro] ✅ Using CUDA GPU acceleration (RTX 2050)")
                            except Exception as cuda_err:
                                print(f"[Kokoro] ⚠️ CUDA init failed (missing CUDA Toolkit?)")
                                print(f"[Kokoro]    Install CUDA 12.x: https://developer.nvidia.com/cuda-downloads")
                                self.sess = None

                        if self.sess is None and "DmlExecutionProvider" in available_providers:
                            try:
                                providers = ["DmlExecutionProvider", "CPUExecutionProvider"]
                                self.sess = rt.InferenceSession(model_path, providers=providers)
                                print("[Kokoro] ✅ Using DirectML GPU acceleration")
                            except Exception as dml_err:
                                print(f"[Kokoro] ⚠️ DirectML init failed")
                                self.sess = None

                        if self.sess is None:
                            providers = ["CPUExecutionProvider"]
                            self.sess = rt.InferenceSession(model_path, providers=providers)
                            print("[Kokoro] Using CPU mode")

                        # THE CLUTCH FIX: Support both Pickle and JSON
                        import json
                        try:
                            # Try loading as JSON first (since we downloaded .json)
                            with open(voices_path, 'r', encoding='utf-8') as f:
                                voices_data = json.load(f)
                                print("[TTSEngine] Loaded voices.json as JSON text.")
                                # Convert lists to numpy arrays if needed (kokoro expects arrays)
                                # Actually, kokoro-onnx expects self.voices to be a dict-like where keys are names
                                # and values are numpy arrays of style (?)
                                # Let's convert to dict of numpy arrays
                                self.voices = {k: np.array(v, dtype=np.float32) for k, v in voices_data.items()}
                        except (json.JSONDecodeError, UnicodeDecodeError):
                            # Fallback to pickle
                            print("[TTSEngine] voices.json is not text, trying pickle...")
                            self.voices = np.load(voices_path, allow_pickle=True)
                        
                        vocab = self._load_vocab(vocab_config)
                        self.tokenizer = Tokenizer(espeak_config, vocab=vocab)

                print(f"[TTSEngine] 🚀 Kokoro TTS found! Loading model (this may take 1s)...")
                self.kokoro_instance = SafeKokoro(self.kokoro_onnx_path, self.kokoro_voices_path)
                self.use_kokoro = True
                print(f"[TTSEngine] Kokoro loaded successfully with Safe Pickle Patch.")
            except ImportError as e:
                 print(f"[TTSEngine] Kokoro files found but libs missing: {e}")
            except Exception as e:
                 print(f"[TTSEngine] Failed to load Kokoro: {e}")
        
        # Signals
        self.player.errorOccurred.connect(self._on_player_error)
        
        self.failure_count = 0
        self.engine_mode = "Auto" # Default
        
        # CosyVoice server config
        self.cosyvoice_url = "http://localhost:50000"
        self.cosyvoice_spk = "英文女"

    def set_mode(self, mode_str):
        # mode_str comes from UI combo box, e.g. "Kokoro (Local Neural...)"
        if "CosyVoice" in mode_str: self.engine_mode = "CosyVoice"
        elif "Kokoro" in mode_str: self.engine_mode = "Kokoro"
        elif "Piper" in mode_str: self.engine_mode = "Piper"
        elif "Edge" in mode_str: self.engine_mode = "Edge"
        elif "System" in mode_str: self.engine_mode = "System"
        else: self.engine_mode = "Auto"
        print(f"[TTSEngine] Mode set to: {self.engine_mode}")

    def set_cosyvoice_config(self, url: str, spk_id: str = ""):
        """Set CosyVoice server URL and speaker ID."""
        if url:
            self.cosyvoice_url = url.rstrip("/")
        if spk_id:
            self.cosyvoice_spk = spk_id
        print(f"[TTSEngine] CosyVoice config: url={self.cosyvoice_url}, spk={self.cosyvoice_spk}")

    def speak(self, text):
        if not text:
            return
            
        self.last_text = text
        
        # Decide which engine to use
        use_cosyvoice = (self.engine_mode == "CosyVoice")
        use_kokoro = (self.engine_mode == "Kokoro") or (self.engine_mode == "Auto" and self.use_kokoro)
        use_piper = (self.engine_mode == "Piper") or (self.engine_mode == "Auto" and self.use_piper and not self.use_kokoro)
        use_edge = (self.engine_mode == "Edge") or (self.engine_mode == "Auto" and not self.use_piper and not self.use_kokoro)
        # System is fallback for all, or forced
        
        if self.engine_mode == "System":
             self._fallback_offline(text)
             return
        
        # 0. CosyVoice (Local server, Chinese+English)
        if use_cosyvoice:
            print(f"[TTSEngine] Requesting CosyVoice TTS for: {text[:50]}...")
            self.worker = CosyVoiceWorker(text, self.cosyvoice_url, self.cosyvoice_spk)
            self.worker.finished.connect(self._play_file)
            self.worker.error.connect(self._on_cosyvoice_error)
            self.worker.start()
            return
        
        # 1. Kokoro
        if use_kokoro:
            if self.kokoro_instance:
                print(f"[TTSEngine] Requesting Kokoro TTS for: {text}")
                self.worker = KokoroWorker(self.kokoro_instance, text)
                self.worker.finished.connect(self._play_file)
                self.worker.error.connect(self._on_kokoro_error)
                self.worker.start()
                return
            elif self.engine_mode == "Kokoro":
                print("[TTSEngine] Kokoro selected but not loaded. Fallback.")

        # 2. Piper
        if use_piper:
            if self.use_piper:  # Binary exists logic
                print(f"[TTSEngine] Requesting Piper TTS for: {text}")
                self.worker = PiperWorker(text, self.piper_exe, self.piper_model)
                self.worker.finished.connect(self._play_file)
                self.worker.error.connect(self._on_piper_error)
                self.worker.start()
                return
            elif self.engine_mode == "Piper":
                print("[TTSEngine] Piper selected but not found. Fallback.")

        # 3. Edge TTS
        if use_edge:
             if self.failure_count >= self.MAX_FAILURES and self.engine_mode == "Auto":
                 print(f"[TTSEngine] Circuit breaker open. Skipping Edge TTS.")
                 self._fallback_offline(text)
                 return
                 
             print(f"[TTSEngine] Requesting Edge TTS for: {text}")
             self.worker = EdgeTTSWorker(text)
             self.worker.finished.connect(self._play_file)
             self.worker.error.connect(self._on_edge_error)
             self.worker.start()
             return

        # Fallback if nothing matched or failed
        self._fallback_offline(text)
        
    def _on_kokoro_error(self, error):
        print(f"[TTSEngine] Kokoro Failed: {error}. Falling back.")
        self._fallback_offline(self.last_text)

    def _on_cosyvoice_error(self, error):
        print(f"[TTSEngine] CosyVoice Failed: {error}. Falling back to Edge TTS.")
        # Fallback to Edge TTS for Chinese+English
        self.worker = EdgeTTSWorker(self.last_text, voice="zh-CN-XiaoxiaoNeural")
        self.worker.finished.connect(self._play_file)
        self.worker.error.connect(self._on_edge_error)
        self.worker.start()

    def _on_piper_error(self, error):
        print(f"[TTSEngine] Piper Failed: {error}. Falling back to offline.")
        self._fallback_offline(self.last_text)

    def _play_file(self, file_path):
        print(f"[TTSEngine] Playing generated file: {file_path}")
        # Success! Reset failure count
        self.failure_count = 0 
        self.player.setSource(QUrl.fromLocalFile(file_path))
        self.player.play()

    def _on_edge_error(self, error_msg):
        print(f"[TTSEngine] Edge TTS failed: {error_msg}")
        self.failure_count += 1
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
            except ImportError:
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
