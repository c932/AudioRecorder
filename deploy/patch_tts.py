#!/usr/bin/env python3
"""Patch TTS server to support temperature/repetition_penalty for short text."""

with open('/home/manfred/AI/services/qwen-tts/server.py', 'r') as f:
    content = f.read()

# 1. Add temperature/repetition_penalty params to /tts endpoint
old_tts_sig = '''@app.post("/tts")
async def tts(
    text: str = Form(),
    speaker: str = Form(default=""),
    language: str = Form(default=""),
    instruct: str = Form(default=""),
):'''

new_tts_sig = '''@app.post("/tts")
async def tts(
    text: str = Form(),
    speaker: str = Form(default=""),
    language: str = Form(default=""),
    instruct: str = Form(default=""),
    temperature: float = Form(default=0.0),
    repetition_penalty: float = Form(default=1.0),
):'''

content = content.replace(old_tts_sig, new_tts_sig)

# 2. Add gen kwargs to generate_custom_voice call
old_gen = '''        wavs, sr = model.generate_custom_voice(
            text=text,
            language=lang,
            speaker=spk,
            instruct=instruct,
        )'''

new_gen = '''        # Build generation kwargs for short text optimization
        gen_kwargs = {}
        word_count = len(text.split())
        if temperature > 0:
            gen_kwargs["temperature"] = temperature
        elif word_count <= 3:
            # Short text (words/short phrases): low temperature for clear pronunciation
            gen_kwargs["temperature"] = 0.3
        if repetition_penalty > 1.0:
            gen_kwargs["repetition_penalty"] = repetition_penalty
        elif word_count <= 3:
            # Reduce repetition (prevents drawn-out sounds on single words)
            gen_kwargs["repetition_penalty"] = 1.2

        wavs, sr = model.generate_custom_voice(
            text=text,
            language=lang,
            speaker=spk,
            instruct=instruct,
            **gen_kwargs,
        )'''

content = content.replace(old_gen, new_gen)

with open('/home/manfred/AI/services/qwen-tts/server.py', 'w') as f:
    f.write(content)
print("PATCHED OK")
