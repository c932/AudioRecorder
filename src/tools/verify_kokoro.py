
import os
import sys
import time

# Add src to path
sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))

def verify():
    try:
        from kokoro_onnx import Kokoro
        import soundfile as sf
    except ImportError:
        print("❌ 'kokoro-onnx' or 'soundfile' not installed.")
        return

    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    model_path = os.path.join(base_dir, "src", "resources", "kokoro", "kokoro-v0_19.onnx")
    voices_path = os.path.join(base_dir, "src", "resources", "kokoro", "voices.json")

    print(f"Model Path: {model_path}")
    print(f"Voices Path: {voices_path}")

    if not os.path.exists(model_path):
        print("❌ Model file missing.")
        return
    if not os.path.exists(voices_path):
        print("❌ Voices file missing.")
        return

    print("Loading Kokoro...")
    
    # Debug: Try loading with onnxruntime directly
    try:
        import onnxruntime as ort
        print(f"Testing direct ONNX load: {model_path}")
        sess = ort.InferenceSession(model_path)
        print("✅ Direct ONNX load successful!")
    except Exception as e:
        print(f"❌ Direct ONNX load failed: {e}")
        # If this fails, the file is definitely not a valid ONNX
    
    print("Loading Kokoro with SafeKokoro logic...")
    start = time.time()
    try:
        # Mimic SafeKokoro from tts_engine.py
        from kokoro_onnx import Kokoro
        from kokoro_onnx.config import KoKoroConfig
        from kokoro_onnx.tokenizer import Tokenizer
        import onnxruntime as rt
        import numpy as np
        import json

        class SafeKokoro(Kokoro):
            def __init__(self, model_path, voices_path, espeak_config=None, vocab_config=None):
                self.config = KoKoroConfig(model_path, voices_path, espeak_config)
                self.config.validate()
                self.sess = rt.InferenceSession(model_path, providers=["CPUExecutionProvider"])
                
                # Try JSON load first
                try:
                    with open(voices_path, 'r', encoding='utf-8') as f:
                        voices_data = json.load(f)
                        print("✅ Loaded voices.json as JSON text.")
                        self.voices = {k: np.array(v, dtype=np.float32) for k, v in voices_data.items()}
                except:
                    print("⚠️ JSON load failed, trying pickle...")
                    self.voices = np.load(voices_path, allow_pickle=True)
                
                vocab = self._load_vocab(vocab_config)
                self.tokenizer = Tokenizer(espeak_config, vocab=vocab)

        kokoro = SafeKokoro(model_path, voices_path)
        print(f"✅ Loaded in {time.time() - start:.2f}s")
    except Exception as e:
        print(f"❌ Failed to load model: {e}")
        return

    print("Generating audio...")
    text = "Hello, this is a test of the Kokoro TTS engine."
    try:
        samples, sample_rate = kokoro.create(text, voice="af_bella", speed=1.0, lang="en-us")
        print(f"✅ Generated {len(samples)} samples at {sample_rate}Hz")
        
        output_file = "test_kokoro.wav"
        sf.write(output_file, samples, sample_rate)
        print(f"Saved to {output_file}")
    except Exception as e:
        print(f"❌ Generation failed: {e}")

if __name__ == "__main__":
    verify()
