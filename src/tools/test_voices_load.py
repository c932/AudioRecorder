
import numpy as np
import os

base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
voices_path = os.path.join(base_dir, "src", "resources", "kokoro", "voices.json")

print(f"Testing load of: {voices_path}")

try:
    print("Attempt 1: np.load(..., allow_pickle=False) (Default)")
    v = np.load(voices_path, allow_pickle=False)
    print("✅ Load Success (No pickle)")
except Exception as e:
    print(f"❌ Load Failed: {e}")

try:
    print("Attempt 2: np.load(..., allow_pickle=True)")
    v = np.load(voices_path, allow_pickle=True)
    print("✅ Load Success (With pickle)")
    print(f"Voices type: {type(v)}")
    # keys?
    # validation
except Exception as e:
    print(f"❌ Load Failed: {e}")
