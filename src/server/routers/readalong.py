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
_SESSION_TTL_S = 30 * 60  # 30 分钟后清理过期会话


def _cleanup_stale_sessions() -> None:
    """删除超过 TTL 的会话（惰性清理，在 /start 和 /score 入口调用）。"""
    import time
    now = time.time()
    stale = [
        sid for sid, s in _sessions.items()
        if now - s.get("created_at", 0) > _SESSION_TTL_S
    ]
    for sid in stale:
        _sessions.pop(sid, None)


def _new_session(text: str, mode: str) -> dict:
    """创建跟读会话：拆句/段 + 翻译。"""
    import time
    config = load_config()
    segments_text = ReadAlongEngine.split_text(text, mode)
    if not segments_text:
        raise HTTPException(400, "课文解析结果为空，请检查内容")

    # 翻译失败时降级为空翻译，不阻断会话创建
    try:
        translations = ReadAlongEngine.translate_segments(segments_text, config)
    except Exception as e:
        print(f"[readalong] 翻译失败，降级为空翻译: {e}")
        translations = [""] * len(segments_text)

    segments = [
        {"text": t, "translation": tr}
        for t, tr in zip(segments_text, translations)
    ]

    session_id = str(uuid.uuid4())  # 完整 UUID，消除碰撞风险
    session = {
        "id": session_id,
        "mode": mode,
        "segments": segments,
        "results": {},       # seg_idx -> {"score": int, "retries": int}
        "current_idx": 0,
        "created_at": time.time(),
    }
    with _sessions_lock:
        _cleanup_stale_sessions()
        _sessions[session_id] = session
    return session


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.post("/parse-text")
async def parse_text(files: list[UploadFile] = File(...), use_ai: bool = Form(True)):
    """上传 PDF / 图片 / TXT（支持多张，按上传顺序合并成一篇课文）。"""
    from fastapi.concurrency import run_in_threadpool

    allowed = {".pdf", ".txt", ".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif"}
    slots: list[dict] = []   # 按上传顺序的提取任务：{"kind": "txt"|"pdf"|"image", ...}
    tmp_paths: list[str] = []
    try:
        for file in files:
            ext = os.path.splitext(file.filename or "")[1].lower()
            if ext not in allowed:
                raise HTTPException(400, f"不支持的文件类型「{ext}」，支持 PDF / TXT / 图片")
            raw = await file.read()
            if not raw:
                raise HTTPException(400, f"文件「{file.filename}」是空的")
            if len(raw) > 20 * 1024 * 1024:
                raise HTTPException(400, f"文件「{file.filename}」超过 20MB 上限")

            if ext == ".txt":
                text = raw.decode("utf-8", errors="replace").strip()
                if not text:
                    raise HTTPException(422, f"文本文件「{file.filename}」内容为空")
                slots.append({"kind": "txt", "text": text})
            else:
                fd, path = tempfile.mkstemp(prefix="readalong_", suffix=ext)
                with os.fdopen(fd, "wb") as f:
                    f.write(raw)
                tmp_paths.append(path)
                slots.append({"kind": "pdf" if ext == ".pdf" else "image", "path": path})

        if not slots:
            raise HTTPException(400, "没有收到文件")

        config = load_config()
        text = await run_in_threadpool(_extract_all, slots, config)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"解析失败：{e}")
    finally:
        for path in tmp_paths:
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
        _cleanup_stale_sessions()
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

    # 无评分结果时直接返回简单总结（用户中途退出场景）
    if not session["results"]:
        with _sessions_lock:
            _sessions.pop(req.session_id, None)
        return {
            "summary": "练习未完成，下次继续加油！",
            "avg_score": 0,
            "weak_segments": [],
            "weak_words": [],
            "total_segments": len(session["segments"]),
            "total_retries": 0,
        }

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
    """获取会话状态（含 segments，供续学恢复）。"""
    with _sessions_lock:
        session = _sessions.get(session_id)
    if not session:
        raise HTTPException(404, "会话不存在")
    return {
        "session_id": session_id,
        "current_idx": session["current_idx"],
        "total": len(session["segments"]),
        "results": session["results"],
        "mode": session["mode"],
        "segments": session["segments"],
    }


# ---------------------------------------------------------------------------
# Helpers: extract text from images/scanned PDF for readalong (not vocab)
# ---------------------------------------------------------------------------
# OCR 友好的压缩上限：长边 2000px（课本整页文字仍清晰可读）。
# 之前沿用 ContentParser 的 1024px 压缩，整页文字缩到十几像素高，模型读不出 → 课文被吞。
_OCR_MAX_SIDE = 2000
_OCR_JPEG_QUALITY = 85
# 逐张并发数（云 API 可承受小并发；顺序由结果下标保证）
_EXTRACT_CONCURRENCY = 3


def _extract_all(slots: list[dict], config: dict) -> str:
    """按上传顺序提取各文件文本，合并成一篇课文。

    图片逐张识别（见 _extract_text_from_image_list），文本按上传顺序拼接。
    """
    parts: list[str] = []
    img_batch: list[str] = []

    def flush() -> None:
        nonlocal img_batch
        if img_batch:
            t = _extract_text_from_image_list(img_batch, config)
            if t:
                parts.append(t)
            img_batch = []

    for slot in slots:
        kind = slot["kind"]
        if kind == "txt":
            flush()
            if slot["text"]:
                parts.append(slot["text"])
        elif kind == "pdf":
            flush()
            t = _pdf_extract_text(slot["path"])
            if t.strip():
                parts.append(t.strip())
            else:
                # 扫描版 PDF：渲染为图片走视觉模型
                t2 = _extract_text_from_images(slot["path"], config)
                if t2:
                    parts.append(t2)
        else:  # image
            img_batch.append(slot["path"])
    flush()

    return "\n\n".join(p for p in parts if p and p.strip()).strip()


def _pdf_extract_text(pdf_path: str) -> str:
    """用 pdfplumber 提取 PDF 文本（无文本层时返回空串）。"""
    import pdfplumber

    full_text = ""
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            t = page.extract_text()
            if t:
                full_text += t + "\n\n"
    return full_text


def _load_image_b64(image_path: str) -> tuple[str, str]:
    """读取图片为 (base64, mime)；长边超过 _OCR_MAX_SIDE 时缩到该尺寸。

    课本照片（iPad 约 3024×4032）压到 1024px 会让整页文字不可读，
    2000px 长边在可读性与 payload 大小（~0.5MB base64）间取得平衡。
    """
    import base64
    import mimetypes
    from PIL import Image
    import io

    with Image.open(image_path) as img:
        if max(img.size) > _OCR_MAX_SIDE:
            ratio = _OCR_MAX_SIDE / max(img.size)
            img = img.resize((int(img.width * ratio), int(img.height * ratio)), Image.LANCZOS)
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=_OCR_JPEG_QUALITY)
        data = base64.b64encode(buf.getvalue()).decode("utf-8")
    mime_type = "image/jpeg"
    return data, mime_type


def _extract_image_text_b64(image_b64: str, mime_type: str, config: dict) -> str:
    """单张图片（base64）→ 视觉 LLM 提取课文全文。失败抛异常，空文本返回空串。"""
    from src.core.content_parser import _get_llm_client_and_model

    prompt = (
        "Analyze this image which contains an English text passage or textbook "
        "page. Extract the FULL English text content exactly as written, from "
        "the beginning to the end of the page. Do not skip or summarize any "
        "part. Preserve paragraph structure with blank lines between "
        "paragraphs. Ignore page numbers, headers, footers, illustrations, and "
        "non-text elements. Return ONLY the extracted text, no JSON, no "
        "explanation."
    )
    messages = [{
        "role": "user",
        "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url",
             "image_url": {"url": f"data:{mime_type};base64,{image_b64}"}},
        ],
    }]
    client, model = _get_llm_client_and_model(config)
    response = client.chat.completions.create(
        model=model, messages=messages, max_tokens=4000, temperature=0.2)
    return (response.choices[0].message.content or "").strip()


def _extract_one_image(image_path: str, config: dict) -> str:
    """单张图片文件 → 课文文本。压缩版为空时用原图重试一次（仍限 4MB 内）。"""
    import base64
    import mimetypes

    try:
        b64, mime = _load_image_b64(image_path)
        try:
            t = _extract_image_text_b64(b64, mime, config)
            if t:
                return t
        except Exception as e:
            print(f"[readalong] 图片提取失败（将重试）: {e}")
        # 压缩版为空/失败 → 用原图重试（可能是压缩后文字不可读）
        if os.path.getsize(image_path) <= 4 * 1024 * 1024:
            with open(image_path, "rb") as f:
                raw = base64.b64encode(f.read()).decode("utf-8")
            mime_raw = mimetypes.guess_type(image_path)[0] or "image/jpeg"
            try:
                t = _extract_image_text_b64(raw, mime_raw, config)
                if t:
                    return t
            except Exception as e:
                print(f"[readalong] 原图重试失败: {e}")
    except Exception as e:
        print(f"[readalong] 读取图片失败: {e}")
    return ""


def _extract_text_from_image_list(image_paths: list[str], config: dict) -> str:
    """逐张提取课文并按图片顺序拼接。

    之前把多张图塞进一次 LLM 调用，弱模型常漏读后面的图导致课文缺失；
    逐张识别保证每张图都被完整处理，顺序由结果下标保证，小并发加速。
    """
    from concurrent.futures import ThreadPoolExecutor

    if not image_paths:
        return ""

    with ThreadPoolExecutor(max_workers=min(_EXTRACT_CONCURRENCY, len(image_paths))) as ex:
        results = list(ex.map(lambda p: _extract_one_image(p, config), image_paths))

    for i, r in enumerate(results):
        if not r:
            print(f"[readalong] 警告：第 {i + 1}/{len(image_paths)} 张图片未提取到文本")

    return "\n\n".join(r for r in results if r).strip()


def _extract_text_from_image(image_path: str, config: dict) -> str:
    """用视觉 LLM 从单张图片提取课文全文。"""
    return _extract_one_image(image_path, config)


def _extract_text_from_images(pdf_path: str, config: dict) -> str:
    """扫描版 PDF：渲染为图片后逐页提取全文（与多图上传同样的逐张策略）。

    LLM 失败时返回空串——应用必须在无 LLM 时仍可工作。
    """
    try:
        import fitz
        import base64
        from concurrent.futures import ThreadPoolExecutor

        doc = fitz.open(pdf_path)
        page_images: list[tuple[str, str]] = []
        for page_idx, page in enumerate(doc):
            if page_idx >= 20:
                break
            pix = page.get_pixmap(dpi=150)
            img_bytes = pix.tobytes("jpeg")
            page_images.append((base64.b64encode(img_bytes).decode("utf-8"), "image/jpeg"))
        doc.close()

        if not page_images:
            return ""

        def extract_page(item: tuple[str, str]) -> str:
            b64, mime = item
            try:
                return _extract_image_text_b64(b64, mime, config)
            except Exception as e:
                print(f"[readalong] PDF 单页提取失败: {e}")
                return ""

        with ThreadPoolExecutor(max_workers=min(_EXTRACT_CONCURRENCY, len(page_images))) as ex:
            results = list(ex.map(extract_page, page_images))

        return "\n\n".join(r for r in results if r).strip()
    except Exception as e:
        print(f"[readalong] 扫描版 PDF 提取课文失败: {e}")
        return ""
