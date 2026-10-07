"""跟读教练路由 — 上传课文、拆句翻译、TTS 领读、评分纠错、总结。"""
from __future__ import annotations

import os
import tempfile
import uuid
import threading
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from src.server.deps import (
    get_coach, load_config, save_audio_temp, cleanup_temp,
    synthesize_tts, get_exercise_manager,
)
from src.core.readalong_engine import ReadAlongEngine

router = APIRouter(prefix="/api/readalong", tags=["readalong"])

# ---------------------------------------------------------------------------
# In-memory session store (single-user LAN scenario)
# ---------------------------------------------------------------------------
_sessions: dict[str, dict] = {}
_sessions_lock = threading.Lock()


def _new_session(text: str, mode: str) -> dict:
    """创建跟读会话：拆句/段 + 翻译。"""
    config = load_config()
    segments_text = ReadAlongEngine.split_text(text, mode)
    if not segments_text:
        raise HTTPException(400, "课文解析结果为空，请检查内容")

    translations = ReadAlongEngine.translate_segments(segments_text, config)
    segments = [
        {"text": t, "translation": tr}
        for t, tr in zip(segments_text, translations)
    ]

    session_id = str(uuid.uuid4())[:8]
    session = {
        "id": session_id,
        "mode": mode,
        "segments": segments,
        "results": {},       # seg_idx -> {"score": int, "retries": int}
        "current_idx": 0,
    }
    with _sessions_lock:
        _sessions[session_id] = session
    return session


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.post("/parse-text")
async def parse_text(file: UploadFile = File(...), use_ai: bool = Form(True)):
    """上传 PDF / 图片 → 提取课文全文（不是词汇表）。"""
    from fastapi.concurrency import run_in_threadpool

    ext = os.path.splitext(file.filename or "")[1].lower()
    allowed = {".pdf", ".txt", ".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif"}
    if ext not in allowed:
        raise HTTPException(400, f"不支持的文件类型「{ext}」，支持 PDF / TXT / 图片")

    raw = await file.read()
    if not raw:
        raise HTTPException(400, "文件是空的")
    if len(raw) > 20 * 1024 * 1024:
        raise HTTPException(400, "文件超过 20MB 上限")

    config = load_config()
    path = None
    try:
        if ext == ".txt":
            text = raw.decode("utf-8", errors="replace").strip()
            if not text:
                raise HTTPException(422, "文本文件内容为空")
        else:
            fd, path = tempfile.mkstemp(prefix="readalong_", suffix=ext)
            with os.fdopen(fd, "wb") as f:
                f.write(raw)

            # 使用 ContentParser 提取，但 prompt 改为提取课文全文
            from src.core.content_parser import ContentParser, _get_llm_client_and_model

            if ext == ".pdf":
                # 先尝试 pdfplumber 提取文本
                import pdfplumber
                full_text = ""
                with pdfplumber.open(path) as pdf:
                    for page in pdf.pages:
                        t = page.extract_text()
                        if t:
                            full_text += t + "\n\n"

                if full_text.strip():
                    text = full_text.strip()
                else:
                    # 扫描版 PDF：用视觉模型提取
                    text = await run_in_threadpool(
                        _extract_text_from_images, path, config)
            else:
                # 图片：用视觉模型提取
                text = await run_in_threadpool(
                    _extract_text_from_image, path, config)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"解析失败：{e}")
    finally:
        if path:
            try:
                os.remove(path)
            except OSError:
                pass

    if not text or not text.strip():
        raise HTTPException(422, "未能提取到课文内容")

    return {"text": text.strip()}


class StartRequest(BaseModel):
    text: str
    mode: str = "sentence"  # "sentence" | "paragraph"


@router.post("/start")
def start(req: StartRequest):
    """开始跟读会话：拆句/段 + LLM 翻译。"""
    if not req.text.strip():
        raise HTTPException(400, "课文内容为空")
    if req.mode not in ("sentence", "paragraph"):
        raise HTTPException(400, "mode 必须是 sentence 或 paragraph")

    session = _new_session(req.text, req.mode)
    return {
        "session_id": session["id"],
        "segments": session["segments"],
        "total": len(session["segments"]),
        "mode": session["mode"],
    }


class TextOnlyRequest(BaseModel):
    text: str


@router.post("/start-text")
def start_text(req: TextOnlyRequest):
    """直接用文本开始跟读会话（粘贴课文场景）。"""
    if not req.text.strip():
        raise HTTPException(400, "课文内容为空")
    session = _new_session(req.text, "sentence")
    return {
        "session_id": session["id"],
        "segments": session["segments"],
        "total": len(session["segments"]),
        "mode": session["mode"],
    }


class TTSRequest(BaseModel):
    text: str
    voice: Optional[str] = None


@router.post("/tts")
def tts(req: TTSRequest):
    """合成指定文本的 TTS 音频。"""
    if not req.text.strip():
        raise HTTPException(400, "text 为空")
    try:
        audio, media_type = synthesize_tts(req.text, voice=req.voice)
    except Exception as e:
        raise HTTPException(500, detail=f"TTS 失败: {e}")
    return Response(content=audio, media_type=media_type)


class ScoreRequest(BaseModel):
    session_id: str
    seg_idx: int
    audio_b64: str
    audio_format: str = "wav"


@router.post("/score")
def score(req: ScoreRequest):
    """录音评分 + LLM 纠错。"""
    with _sessions_lock:
        session = _sessions.get(req.session_id)
    if not session:
        raise HTTPException(404, "会话不存在")

    if req.seg_idx < 0 or req.seg_idx >= len(session["segments"]):
        raise HTTPException(400, "seg_idx 越界")

    reference = session["segments"][req.seg_idx]["text"]
    if not reference.strip():
        raise HTTPException(400, "参考文本为空")

    # GOP 评分
    path = save_audio_temp(req.audio_b64, req.audio_format)
    try:
        result = get_coach().assess(path, reference)
    except Exception as e:
        raise HTTPException(500, detail=f"评分失败: {e}")
    finally:
        cleanup_temp(path)

    score_val = int(result.get("accuracy_score", 0))
    feedback = result.get("feedback", "")
    details = result.get("details", {})
    errors = details.get("errors", [])
    recognized = details.get("recognized", "")

    # 记录得分
    with _sessions_lock:
        prev = session["results"].get(req.seg_idx, {"score": 0, "retries": 0})
        retries = prev["retries"]
        if score_val < 80:
            retries += 1
        session["results"][req.seg_idx] = {"score": score_val, "retries": retries}

    # LLM 纠错建议（分数 < 95 时生成）
    llm_feedback = ""
    if score_val < 95:
        try:
            config = load_config()
            llm_feedback = ReadAlongEngine.generate_llm_correction(
                score_val, reference, recognized, errors, config)
        except Exception as e:
            print(f"[readalong] LLM 纠错失败: {e}")

    should_retry = score_val < 80 and retries < 2

    return {
        "score": score_val,
        "feedback": feedback,
        "llm_feedback": llm_feedback,
        "details": result,
        "should_retry": should_retry,
        "retry_count": retries,
    }


class SummaryRequest(BaseModel):
    session_id: str


@router.post("/summary")
def summary(req: SummaryRequest):
    """生成跟读总结 + 写入错题本。"""
    with _sessions_lock:
        session = _sessions.get(req.session_id)
    if not session:
        raise HTTPException(404, "会话不存在")

    results_list = [
        {"seg_idx": idx, "score": r["score"], "retries": r["retries"]}
        for idx, r in sorted(session["results"].items())
    ]

    config = load_config()
    summary_data = ReadAlongEngine.generate_summary(
        results_list, session["segments"], config)

    # 写入错题本：低分句中的词汇
    weak_words = summary_data.get("weak_words", [])
    if weak_words:
        try:
            mgr = get_exercise_manager()
            items = [{"text": w, "group": "跟读错误"} for w in weak_words]
            mgr.add_exercises(items, "words")
            # 标记最低分
            for w in weak_words:
                for word_entry in mgr.exercises.get("words", []):
                    if word_entry.get("text") == w and word_entry.get("group") == "跟读错误":
                        word_entry["last_score"] = 50  # 标记低分
                        break
            mgr.save_data()
        except Exception as e:
            print(f"[readalong] 写入错题本失败: {e}")

    # 清理会话
    with _sessions_lock:
        _sessions.pop(req.session_id, None)

    return summary_data


@router.get("/state/{session_id}")
def state(session_id: str):
    """获取会话状态。"""
    with _sessions_lock:
        session = _sessions.get(session_id)
    if not session:
        raise HTTPException(404, "会话不存在")
    return {
        "current_idx": session["current_idx"],
        "total": len(session["segments"]),
        "results": session["results"],
        "mode": session["mode"],
    }


# ---------------------------------------------------------------------------
# Helpers: extract text from images/scanned PDF for readalong (not vocab)
# ---------------------------------------------------------------------------
def _extract_text_from_image(image_path: str, config: dict) -> str:
    """用视觉 LLM 从图片提取课文全文。

    LLM 失败时返回空串——应用必须在无 LLM 时仍可工作。
    """
    try:
        import base64
        import mimetypes
        from src.core.content_parser import _get_llm_client_and_model

        file_size = os.path.getsize(image_path)
        MAX_SIZE = 2 * 1024 * 1024
        if file_size > MAX_SIZE:
            from src.core.content_parser import ContentParser
            image_data = ContentParser._compress_image(image_path)
        else:
            with open(image_path, "rb") as f:
                image_data = base64.b64encode(f.read()).decode("utf-8")

        mime_type = mimetypes.guess_type(image_path)[0] or "image/jpeg"

        prompt = """Analyze this image which contains an English text passage or textbook page.
Extract the FULL English text content exactly as written.
Preserve paragraph structure with blank lines between paragraphs.
Ignore page numbers, headers, footers, illustrations, and non-text elements.
Return ONLY the extracted text, no JSON, no explanation."""

        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{mime_type};base64,{image_data}"
                        }
                    }
                ]
            }
        ]

        client, model = _get_llm_client_and_model(config)
        response = client.chat.completions.create(
            model=model, messages=messages, max_tokens=3000, temperature=0.2)
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"[readalong] 图片提取课文失败: {e}")
        return ""


def _extract_text_from_images(pdf_path: str, config: dict) -> str:
    """扫描版 PDF：渲染为图片后提取全文。

    LLM 失败时返回空串——应用必须在无 LLM 时仍可工作。
    """
    try:
        import fitz
        import base64
        from src.core.content_parser import _get_llm_client_and_model

        doc = fitz.open(pdf_path)
        page_images = []
        for page_idx, page in enumerate(doc):
            if page_idx >= 20:
                break
            pix = page.get_pixmap(dpi=150)
            img_bytes = pix.tobytes("jpeg")
            page_images.append(base64.b64encode(img_bytes).decode("utf-8"))
        doc.close()

        if not page_images:
            return ""

        prompt = """Analyze these PDF page images which contain an English text passage.
Extract the FULL English text content exactly as written.
Preserve paragraph structure with blank lines between paragraphs.
Ignore page numbers, headers, footers, and non-text elements.
Return ONLY the extracted text, no JSON, no explanation."""

        content_parts = [{"type": "text", "text": prompt}]
        for img_b64 in page_images:
            content_parts.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}
            })

        messages = [{"role": "user", "content": content_parts}]
        client, model = _get_llm_client_and_model(config)
        response = client.chat.completions.create(
            model=model, messages=messages, max_tokens=5000, temperature=0.2)
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"[readalong] 扫描版 PDF 提取课文失败: {e}")
        return ""
