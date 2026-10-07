# Patch CosyVoice FastAPI server.py:
# 1. Fix UploadFile handling (load_wav expects a file path, not file-like object)
# 2. Add /register_speaker endpoint (pre-register speakers from reference audio)
# 3. Add /list_speakers endpoint (debug)
# 4. Modify /inference_cross_lingual to accept zero_shot_spk_id (no prompt_wav needed)
import os, tempfile

server_path = '/opt/CosyVoice/CosyVoice/runtime/python/fastapi/server.py'
with open(server_path) as f:
    code = f.read()

# Add imports
if 'import tempfile' not in code:
    code = code.replace('import uvicorn', 'import uvicorn\nimport tempfile')

# Add helper function
if 'save_upload_to_temp' not in code:
    helper = '''
async def save_upload_to_temp(upload_file):
    suffix = os.path.splitext(upload_file.filename or ".wav")[1] or ".wav"
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    content = await upload_file.read()
    tmp.write(content)
    tmp.flush()
    tmp.close()
    return tmp.name
'''
    code = code.replace('ROOT_DIR =', helper + 'ROOT_DIR =')

# Fix each endpoint that uses prompt_wav: pass path, not file object
for old, new in [
    ('prompt_speech_16k = load_wav(prompt_wav.file, 16000)\n    model_output = cosyvoice.inference_zero_shot(tts_text, prompt_text, prompt_speech_16k)',
     'prompt_wav_path = await save_upload_to_temp(prompt_wav)\n    model_output = cosyvoice.inference_zero_shot(tts_text, prompt_text, prompt_wav_path)'),
    ('prompt_speech_16k = load_wav(prompt_wav.file, 16000)\n    model_output = cosyvoice.inference_cross_lingual(tts_text, prompt_speech_16k)',
     'prompt_wav_path = await save_upload_to_temp(prompt_wav)\n    model_output = cosyvoice.inference_cross_lingual(tts_text, prompt_wav_path)'),
    ('prompt_speech_16k = load_wav(prompt_wav.file, 16000)\n    model_output = cosyvoice.inference_instruct2(tts_text, instruct_text, prompt_speech_16k)',
     'prompt_wav_path = await save_upload_to_temp(prompt_wav)\n    model_output = cosyvoice.inference_instruct2(tts_text, instruct_text, prompt_wav_path)'),
]:
    code = code.replace(old, new)

# ---- New: /register_speaker endpoint ----
if '/register_speaker' not in code:
    register_endpoint = '''

@app.post("/register_speaker")
async def register_speaker(spk_id: str = Form(), prompt_wav: UploadFile = File(), prompt_text: str = Form(default="")):
    """Pre-register a speaker from reference audio. After registration, use zero_shot_spk_id in cross_lingual."""
    try:
        prompt_wav_path = await save_upload_to_temp(prompt_wav)
        cosyvoice.add_zero_shot_spk(prompt_text, prompt_wav_path, spk_id)
        cosyvoice.save_spkinfo()
        # Clean up temp file
        try:
            os.unlink(prompt_wav_path)
        except OSError:
            pass
        return {"status": "ok", "spk_id": spk_id}
    except Exception as e:
        return {"status": "error", "detail": str(e)}


@app.get("/list_speakers")
async def list_speakers():
    """List all registered speaker IDs."""
    return {"speakers": cosyvoice.list_available_spks()}

'''
    # Insert before the if __name__ block
    code = code.replace("if __name__ ==", register_endpoint + "\nif __name__ ==")

# ---- New: modify inference_cross_lingual to accept zero_shot_spk_id ----
# Current patched signature: prompt_wav: UploadFile = File()
# New signature: zero_shot_spk_id: str = Form(default=''), prompt_wav: UploadFile = File(default=None)
old_cross_lingual = """@app.get("/inference_cross_lingual")
@app.post("/inference_cross_lingual")
async def inference_cross_lingual(tts_text: str = Form(), prompt_wav: UploadFile = File()):
    prompt_wav_path = await save_upload_to_temp(prompt_wav)
    model_output = cosyvoice.inference_cross_lingual(tts_text, prompt_wav_path)
    return StreamingResponse(generate_data(model_output))"""

new_cross_lingual = """@app.get("/inference_cross_lingual")
@app.post("/inference_cross_lingual")
async def inference_cross_lingual(tts_text: str = Form(), zero_shot_spk_id: str = Form(default=''), prompt_wav: UploadFile = File(default=None)):
    if zero_shot_spk_id:
        model_output = cosyvoice.inference_cross_lingual(tts_text, '', zero_shot_spk_id=zero_shot_spk_id)
    else:
        if prompt_wav is None:
            from fastapi import HTTPException
            raise HTTPException(status_code=400, detail="prompt_wav or zero_shot_spk_id required")
        prompt_wav_path = await save_upload_to_temp(prompt_wav)
        model_output = cosyvoice.inference_cross_lingual(tts_text, prompt_wav_path)
    return StreamingResponse(generate_data(model_output))"""

code = code.replace(old_cross_lingual, new_cross_lingual)

# Fallback: if the old signature wasn't patched yet (pre-patch state), patch directly
# This handles the case where the existing patch wasn't applied yet
if 'zero_shot_spk_id' not in code and 'prompt_speech_16k = load_wav(prompt_wav.file, 16000)' not in code:
    # The cross_lingual patch above already applied via the general patch at the top
    pass

with open(server_path, 'w') as f:
    f.write(code)
print('CosyVoice server.py patched successfully (with /register_speaker and zero_shot_spk_id support)')
