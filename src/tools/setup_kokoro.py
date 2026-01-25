import os
import sys
import subprocess
import shutil

# Paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__))) # src/
RESOURCES_DIR = os.path.join(BASE_DIR, "resources")
KOKORO_DIR = os.path.join(RESOURCES_DIR, "kokoro")

def install_pkg(package):
    print(f"Installing {package}...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", package])

def main():
    if not os.path.exists(RESOURCES_DIR):
        os.makedirs(RESOURCES_DIR)
        
    if not os.path.exists(KOKORO_DIR):
        os.makedirs(KOKORO_DIR)

    # 1. Install Dependencies
    print("Checking dependencies...")
    required_pkgs = ["kokoro-onnx", "soundfile", "huggingface_hub"]
    for pkg in required_pkgs:
        try:
            __import__(pkg.replace("-", "_")) # simple check
        except ImportError:
            install_pkg(pkg)

    print("Dependencies ok.")

    # 2. Download Model & Voices using huggingface_hub (Handles LFS)
    from huggingface_hub import hf_hub_download

    # Clean up corrupt files (less than 1KB)
    model_path_target = os.path.join(KOKORO_DIR, "kokoro-v0_19.onnx")
    voices_path_target = os.path.join(KOKORO_DIR, "voices.json")
    
    if os.path.exists(model_path_target) and os.path.getsize(model_path_target) < 1024:
        print("Removing corrupt model file...")
        os.remove(model_path_target)
        
    if os.path.exists(voices_path_target) and os.path.getsize(voices_path_target) < 1024:
         print("Removing corrupt voices file...")
         os.remove(voices_path_target)

    # Download
    try:
        # Model (Use v0.19 from GitHub Releases - Proven compatibility with kokoro-onnx)
        # The v1.0 ONNX (300MB) caused pickle errors or incompatibility.
        print("Downloading Model (kokoro-v0_19.onnx, approx 80MB)...")
        model_url = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files/kokoro-v0_19.onnx"
        
        # Check if model exists and is approx correct size (Wait, v0.19 is ~80MB, so > 50MB)
        # Previous 300MB file might be there, so we should check if it's the right one? 
        # Actually, let's just force download if it's > 200MB (wrong one) or < 1KB.
        # But safest is just download if not exists or size seems wrong.
        
        should_download = True
        if os.path.exists(model_path_target):
            size = os.path.getsize(model_path_target)
            if 50 * 1024 * 1024 < size < 150 * 1024 * 1024:
                print("Model already exists and size looks correct (~80MB). Skipping.")
                should_download = False
            else:
                print(f"Existing model size ({size/1024/1024:.2f}MB) looks incorrect. Re-downloading.")
                os.remove(model_path_target)
        
        if should_download:
            import urllib.request
            # Download with progress support would be nice, but simple retry is fine for now
            print(f"Downloading from {model_url}...")
            urllib.request.urlretrieve(model_url, model_path_target)
            print(f"Model saved to: {model_path_target}")
        
        # Voices (Get from GitHub Release as it's reliable for voices.json)
        print("Downloading voices.json...")
        import urllib.request
        voices_url = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files/voices.json"
        try:
            urllib.request.urlretrieve(voices_url, voices_path_target)
            print(f"Voices saved to: {voices_path_target}")
        except Exception as e:
            print(f"GitHub voices download failed, trying huggingface fallback...")
            # Fallback
            repo_id = "remsky/Kokoro-82M"
            cached_voices = hf_hub_download(repo_id=repo_id, filename="voices.json")
            shutil.copy2(cached_voices, voices_path_target)
            print(f"Voices saved to: {voices_path_target}")
        
    except Exception as e:
        print(f"Download failed: {e}")
        sys.exit(1)

    print("\n✅ Kokoro TTS Setup Complete!")
    print(f"Location: {KOKORO_DIR}")

if __name__ == "__main__":
    main()
