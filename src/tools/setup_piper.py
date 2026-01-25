import os
import sys
import zipfile
import urllib.request
import shutil

# Paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__))) # src/
RESOURCES_DIR = os.path.join(BASE_DIR, "resources")
PIPER_DIR = os.path.join(RESOURCES_DIR, "piper")

# URLs
PIPER_URL = "https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_windows_amd64.zip"
VOICE_ONNX = "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/amy/medium/en_US-amy-medium.onnx?download=true"
VOICE_JSON = "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/amy/medium/en_US-amy-medium.onnx.json?download=true"

def download_file(url, target_path):
    print(f"Downloading {url}...")
    try:
        urllib.request.urlretrieve(url, target_path)
        print(f"Saved to {target_path}")
    except Exception as e:
        print(f"Error downloading {url}: {e}")
        sys.exit(1)

def main():
    if not os.path.exists(RESOURCES_DIR):
        os.makedirs(RESOURCES_DIR)
        
    if not os.path.exists(PIPER_DIR):
        os.makedirs(PIPER_DIR)

    # 1. Download Piper Binary
    zip_path = os.path.join(PIPER_DIR, "piper.zip")
    piper_exe = os.path.join(PIPER_DIR, "piper", "piper.exe")
    
    # Check if already installed
    if os.path.exists(piper_exe):
        print("Piper executable already exists. Skipping binary download.")
    else:
        # Download Zip
        if not os.path.exists(zip_path):
            download_file(PIPER_URL, zip_path)
            
        # Extract
        print("Extracting Piper...")
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(PIPER_DIR)
        
        # Cleanup
        os.remove(zip_path)
    
    # 2. Download Voice Model
    voice_dir = os.path.join(PIPER_DIR, "voices")
    if not os.path.exists(voice_dir):
        os.makedirs(voice_dir)
        
    onnx_path = os.path.join(voice_dir, "en_US-amy-medium.onnx")
    json_path = os.path.join(voice_dir, "en_US-amy-medium.onnx.json")
    
    if not os.path.exists(onnx_path):
        download_file(VOICE_ONNX, onnx_path)
    else:
        print("Voice ONNX exists.")
        
    if not os.path.exists(json_path):
        download_file(VOICE_JSON, json_path)
    else:
        print("Voice JSON exists.")

    print("\n✅ Piper TTS Setup Complete!")
    print(f"Location: {PIPER_DIR}")

if __name__ == "__main__":
    main()
