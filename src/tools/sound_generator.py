import os
import subprocess
import asyncio
import nest_asyncio

# Patch asyncio to allow nested event loops (if running in IDLE/Jupyter, though script usually runs direct)
# But standard script doesn't need it. 

async def generate_single(text, voice, filename, speed_scale):
    """
    Uses edge-tts to generate mp3, then ffmpeg to convert/speed up to wav.
    """
    import edge_tts
    
    out_dir = os.path.join("src", "resources", "sounds")
    mp3_path = os.path.join(out_dir, "temp.mp3")
    wav_path = os.path.join(out_dir, filename)
    
    print(f"Generating '{text}' using {voice}...")
    
    # 1. Generate MP3 (Neural is natively fast, but we might want extra punch)
    communicate = edge_tts.Communicate(text, voice) # rate="+20%" can be set here directly!
    
    # Let's set rate in Communicate directly for better quality than ffmpeg atempo
    # edge-tts supports rate="+20%" syntax
    rate_str = f"+{int((speed_scale-1)*100)}%"
    if speed_scale <= 1.0: rate_str = "+0%"
    
    communicate = edge_tts.Communicate(text, voice, rate=rate_str)
    
    await communicate.save(mp3_path)
    
    # 2. Convert to WAV (Standard 16-bit PCM for compatibility)
    print(f"Converting to {filename}...")
    subprocess.run(['ffmpeg', '-y', '-v', 'error', '-i', mp3_path, wav_path], check=True)
    
    if os.path.exists(mp3_path):
        os.remove(mp3_path)
    
    print(f"Success: {filename}")

async def main():
    out_dir = os.path.join("src", "resources", "sounds")
    os.makedirs(out_dir, exist_ok=True)
    
    # Tasks: (Text, Voice, Filename, SpeedFactor-approx)
    # Using edge-tts rate parameter is better than ffmpeg atempo
    
    tasks = [
        # EN: en-US-AriaNeural (Energetic Female) or en-US-GuyNeural (Male)
        # Using Aria for consistency
        ("Wow! Amazing!", "en-US-AriaNeural", "perfect_en.wav", 1.2),
        ("Excellent!", "en-US-AriaNeural", "excellent_en.wav", 1.2),
        ("Good Job!", "en-US-AriaNeural", "good_en.wav", 1.2),
        ("Keep Going!", "en-US-AriaNeural", "encourage_en.wav", 1.1),
        
        # ZH: zh-CN-XiaoxiaoNeural (The standard "Cute Girl")
        ("哇塞！完美发音！你就是传说中的英语小天才！", "zh-CN-XiaoxiaoNeural", "perfect_zh.wav", 1.2),
        ("太棒啦！发音超级标准，给你比心心！", "zh-CN-XiaoxiaoNeural", "excellent_zh.wav", 1.2),
        ("不错哟！进步很大，继续加油！", "zh-CN-XiaoxiaoNeural", "good_zh.wav", 1.2),
        ("别灰心，多练几遍你一定行！", "zh-CN-XiaoxiaoNeural", "encourage_zh.wav", 1.2)
    ]
    
    for text, voice, fname, speed in tasks:
        try:
            await generate_single(text, voice, fname, speed)
        except Exception as e:
            print(f"Error on {fname}: {e}")

if __name__ == "__main__":
    asyncio.run(main())
