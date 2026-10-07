# 跟读教练 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a "Read-Along Coach" subsystem that lets students upload PDF/images to extract textbook content, then guides them through sentence-by-sentence (or paragraph-by-paragraph) read-aloud practice with TTS leading, GOP scoring, LLM correction feedback, low-score retry, and auto error-book integration.

**Architecture:** New backend router + engine + frontend page. Reuses existing ContentParser (with custom prompt), PronunciationCoach (GOP), synthesize_tts (Qwen3-TTS/edge-tts), useRecorder, and ExerciseManager (error book). The frontend page implements a state machine for the read-along loop: TTS play → record → score → retry/advance.

**Tech Stack:** FastAPI (backend), React + TypeScript + Tailwind (frontend), GOP (wav2vec2), Qwen3-TTS, OpenAI-compatible LLM (for translation/correction/summary)

**Spec:** `docs/superpowers/specs/2026-10-07-readalong-coach-design.md`

## Global Constraints

- Python 3.12, FastAPI, Pydantic for backend models
- React 19, react-router-dom 7, Tailwind 4 for frontend
- All API endpoints under `/api/readalong` prefix
- GOP scoring via `PronunciationCoach.assess()` returns `accuracy_score` (0-100)
- TTS via `deps.synthesize_tts()` returns `(bytes, media_type)`
- Audio from browser: base64-encoded, format webm/ogg/mp4 (ffmpeg converts to 16kHz WAV)
- Retry threshold: `accuracy_score < 80`, max 2 retries per segment
- Error book: low-score words added via `ExerciseManager.add_exercises()` with group "跟读错误"
- UI follows "storybook desk" design tokens (see `web/src/index.css`)

---

## File Structure

| File | Responsibility |
|------|----------------|
| `src/core/readalong_engine.py` | Text splitting, LLM translation, LLM summary generation, session state management |
| `src/server/routers/readalong.py` | FastAPI router: parse-text, start, score, tts, summary, state endpoints |
| `web/src/pages/ReadAlongPage.tsx` | Full read-along UI: setup → readalong loop → summary |
| `web/src/lib/api.ts` | Add readalong API functions + TypeScript interfaces |
| `web/src/App.tsx` | Add `/readalong` route |
| `web/src/pages/HomePage.tsx` | Add "跟读教练" entry under 口语训练 |
| `src/server/web_server.py` | Register readalong router |

---

### Task 1: Core Engine — `readalong_engine.py`

**Files:**
- Create: `src/core/readalong_engine.py`

**Interfaces:**
- Consumes: `src.core.content_parser._get_llm_client_and_model(config)`, `src.utils.get_user_data_path`
- Produces:
  - `ReadAlongEngine.split_text(text: str, mode: str) -> list[str]`
  - `ReadAlongEngine.translate_segments(segments: list[str], config: dict) -> list[str]`
  - `ReadAlongEngine.generate_summary(results: list[dict], segments: list[dict], config: dict) -> dict`
  - `ReadAlongEngine.extract_words_from_segment(text: str) -> list[str]`

- [ ] **Step 1: Create `src/core/readalong_engine.py` with split_text**

```python
"""ReadAlongEngine — 课文跟读引擎：拆句/段、翻译、总结。"""
from __future__ import annotations

import re
import json


class ReadAlongEngine:
    """课文跟读引擎：拆分课文、LLM 翻译、生成总结。"""

    @staticmethod
    def split_text(text: str, mode: str = "sentence") -> list[str]:
        """拆分课文为句子或段落列表。

        sentence 模式：按句号/问号/感叹号拆分，保留缩写（如 Mr. Mrs.）。
        paragraph 模式：按空行拆分，空行内保留原文本。
        """
        text = text.strip()
        if not text:
            return []

        if mode == "paragraph":
            # 按一个或多个空行拆分段落
            paragraphs = re.split(r'\n\s*\n', text)
            return [p.strip() for p in paragraphs if p.strip()]

        # 逐句模式：按句末标点拆分，但避免缩写中的句号
        # 缩写模式：Mr. Mrs. Dr. Ms. Prof. St. etc. e.g. i.e.
        abbrevs = r'(?:Mr|Mrs|Dr|Ms|Prof|St|etc|e\.g|i\.e)\.'
        # 先保护缩写中的句号
        protected = text
        placeholder_map = {}
        for i, m in enumerate(re.finditer(abbrevs, text)):
            ph = f"__ABBR{i}__"
            placeholder_map[ph] = m.group()
            protected = protected.replace(m.group(), ph, 1)

        # 按句末标点拆分
        parts = re.split(r'(?<=[.!?])\s+', protected)
        # 按换行也拆（课文可能一行一句）
        expanded = []
        for p in parts:
            expanded.extend(p.split('\n'))

        # 还原缩写 + 清理
        result = []
        for seg in expanded:
            seg = seg.strip()
            for ph, original in placeholder_map.items():
                seg = seg.replace(ph, original)
            if seg and len(seg) > 1:
                result.append(seg)

        return result

    @staticmethod
    def extract_words_from_segment(text: str) -> list[str]:
        """从一句/段英文中提取单词列表（去重，小写，过滤短词）。"""
        words = re.findall(r"[a-zA-Z']+", text)
        seen = set()
        result = []
        for w in words:
            low = w.lower()
            if low not in seen and len(low) > 1:
                seen.add(low)
                result.append(low)
        return result

    @staticmethod
    def translate_segments(segments: list[str], config: dict) -> list[str]:
        """批量翻译英文句子/段落为中文（LLM）。"""
        from src.core.content_parser import _get_llm_client_and_model

        if not segments:
            return []

        client, model = _get_llm_client_and_model(config)

        # 分批翻译（每批最多 20 句，避免超长 prompt）
        batch_size = 20
        all_translations = []

        for i in range(0, len(segments), batch_size):
            batch = segments[i:i + batch_size]
            numbered = "\n".join(f"{j+1}. {s}" for j, s in enumerate(batch))

            prompt = (
                "请将以下英文逐句翻译为中文。保持序号对应，每行一句翻译，"
                "不要加额外解释。格式：\n"
                "1. 翻译内容\n2. 翻译内容\n\n"
                f"英文：\n{numbered}"
            )

            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=2000,
                temperature=0.3,
            )
            content = response.choices[0].message.content.strip()

            # 解析编号行
            translations = []
            for line in content.splitlines():
                line = line.strip()
                # 去掉行首编号（"1. " "1、 " "1) " 等）
                m = re.match(r'^(?:\d+)[.、)\s]+(.+)$', line)
                if m:
                    translations.append(m.group(1).strip())
                elif line:
                    translations.append(line)

            # 数量对齐：如果 LLM 少翻了，用空串补齐
            while len(translations) < len(batch):
                translations.append("")
            all_translations.extend(translations[:len(batch)])

        return all_translations

    @staticmethod
    def generate_llm_correction(score: int, reference: str, recognized: str,
                                errors: list[dict], config: dict) -> str:
        """用 LLM 生成具体的发音纠错建议（中文，30 字以内）。"""
        from src.core.content_parser import _get_llm_client_and_model

        client, model = _get_llm_client_and_model(config)

        error_desc = ""
        for e in errors[:3]:
            etype = e.get("type", "")
            exp = e.get("expected", "")
            act = e.get("actual", "")
            word = e.get("word", "")
            if etype == "substitution" and exp and act:
                error_desc += f"{word}里 /{exp}/ 读成了 /{act}/；"
            elif etype == "deletion":
                error_desc += f"{word}里 /{exp}/ 漏读了；"
            elif etype == "vowel_confusion":
                error_desc += f"{word}里元音 /{exp}/ 听起来像 /{act}/；"

        if not error_desc:
            error_desc = "整体发音可以再清晰一些。"

        prompt = (
            f"学生读「{reference}」得了 {score} 分。"
            f"问题：{error_desc}\n"
            "请用中文给出一句简短（20字以内）的发音纠正建议。"
        )

        try:
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=100,
                temperature=0.5,
            )
            return (response.choices[0].message.content or "").strip()
        except Exception as e:
            print(f"[readalong] LLM 纠错失败: {e}")
            return ""

    @staticmethod
    def generate_summary(results: list[dict], segments: list[dict],
                         config: dict) -> dict:
        """生成跟读总结，提取薄弱句和需复习词汇。

        Args:
            results: [{"seg_idx": int, "score": int, "retries": int}]
            segments: [{"text": str, "translation": str}]
            config: config dict for LLM

        Returns:
            {"summary": str, "weak_segments": [...], "weak_words": [...]}
        """
        from src.core.content_parser import _get_llm_client_and_model

        total = len(results)
        avg = sum(r["score"] for r in results) / total if total else 0
        weak = [r for r in results if r["score"] < 80]
        total_retries = sum(r.get("retries", 0) for r in results)

        weak_segments = []
        weak_words_set = set()
        for r in weak:
            idx = r["seg_idx"]
            if idx < len(segments):
                seg = segments[idx]
                weak_segments.append(seg)
                for w in ReadAlongEngine.extract_words_from_segment(seg["text"]):
                    weak_words_set.add(w)

        weak_words = sorted(weak_words_set)[:20]  # 最多 20 个词

        # LLM 总结
        summary_text = ""
        try:
            client, model = _get_llm_client_and_model(config)
            weak_text = "\n".join(
                f"- 「{s['text']}」（{r['score']}分）"
                for r, s in zip(weak, weak_segments[:5])
            )
            prompt = (
                f"学生完成了一篇 {total} 句课文的跟读练习，平均分 {avg:.0f}。"
                f"重读了 {total_retries} 次。\n"
                f"薄弱句：\n{weak_text if weak_text else '无'}\n\n"
                "请用中文写一段简短的总结评价（50字以内），鼓励学生。"
            )
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=150,
                temperature=0.5,
            )
            summary_text = (response.choices[0].message.content or "").strip()
        except Exception as e:
            print(f"[readalong] LLM 总结失败: {e}")

        if not summary_text:
            if avg >= 80:
                summary_text = f"很棒！平均 {avg:.0f} 分，继续保持！"
            else:
                summary_text = f"平均 {avg:.0f} 分，多练薄弱句会进步更快！"

        return {
            "summary": summary_text,
            "avg_score": round(avg),
            "weak_segments": weak_segments,
            "weak_words": weak_words,
            "total_segments": total,
            "total_retries": total_retries,
        }
```

- [ ] **Step 2: Verify import works**

Run: `cd /e/My_Code/AudioRecorder && python -c "from src.core.readalong_engine import ReadAlongEngine; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Quick smoke test for split_text**

Run: `cd /e/My_Code/AudioRecorder && python -c "
from src.core.readalong_engine import ReadAlongEngine
# Sentence mode
result = ReadAlongEngine.split_text('Hello world. How are you? I am fine.', 'sentence')
assert len(result) == 3, f'Expected 3, got {len(result)}: {result}'
# Paragraph mode
result = ReadAlongEngine.split_text('Para 1 line 1.\nPara 1 line 2.\n\nPara 2 line 1.', 'paragraph')
assert len(result) == 2, f'Expected 2, got {len(result)}: {result}'
# Abbreviation protection
result = ReadAlongEngine.split_text('Mr. Smith went home. Mrs. Jones stayed.', 'sentence')
assert len(result) == 2, f'Expected 2, got {len(result)}: {result}'
print('split_text OK')
"`
Expected: `split_text OK`

- [ ] **Step 4: Commit**

```bash
git add src/core/readalong_engine.py
git commit -m "feat(readalong): 跟读教练核心引擎 — 拆句、翻译、纠错、总结"
```

---

### Task 2: Backend Router — `readalong.py`

**Files:**
- Create: `src/server/routers/readalong.py`
- Modify: `src/server/web_server.py:99-122` (register new router)

**Interfaces:**
- Consumes: `src.core.readalong_engine.ReadAlongEngine`, `src.server.deps` (get_coach, save_audio_temp, cleanup_temp, synthesize_tts, load_config, get_exercise_manager), `src.core.content_parser.ContentParser`
- Produces: REST API endpoints under `/api/readalong/`

- [ ] **Step 1: Create `src/server/routers/readalong.py`**

```python
"""跟读教练路由 — 上传课文、拆句翻译、TTS 领读、评分纠错、总结。"""
from __future__ import annotations

import os
import re
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
    """用视觉 LLM 从图片提取课文全文。"""
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


def _extract_text_from_images(pdf_path: str, config: dict) -> str:
    """扫描版 PDF：渲染为图片后提取全文。"""
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
```

- [ ] **Step 2: Register router in `src/server/web_server.py`**

Add import at line ~106 (after the tutor import):
```python
from src.server.routers.readalong import router as readalong_router
```

Add to the router loop at line ~120 (after `config_router`):
```python
for r in (vocab_router, practice_router, quiz_router, oral_router,
          scenario_router, tutor_router, memorize_router, mistakes_router,
          config_router, readalong_router):
    app.include_router(r)
```

- [ ] **Step 3: Verify server starts**

Run: `cd /e/My_Code/AudioRecorder && timeout 8 python -c "
import os; os.environ['ENGLISH_COACH_HEADLESS']='1'
from src.server.web_server import app
routes = [r.path for r in app.routes if hasattr(r, 'path') and '/readalong' in r.path]
print(f'ReadAlong routes: {routes}')
assert len(routes) >= 5, f'Expected >= 5 readalong routes, got {len(routes)}'
print('OK')
"`
Expected: `ReadAlong routes: ['/api/readalong/parse-text', '/api/readalong/start', '/api/readalong/start-text', '/api/readalong/tts', '/api/readalong/score', '/api/readalong/summary', '/api/readalong/state/{session_id}']` then `OK`

- [ ] **Step 4: Commit**

```bash
git add src/server/routers/readalong.py src/server/web_server.py
git commit -m "feat(readalong): 后端跟读教练路由 — 解析课文、会话管理、评分、总结"
```

---

### Task 3: Frontend API Client — `api.ts`

**Files:**
- Modify: `web/src/lib/api.ts:1-278` (add interfaces + api methods)

**Interfaces:**
- Consumes: (none — pure TypeScript additions)
- Produces: `ReadAlongSegment`, `ReadAlongSession`, `ReadAlongScoreResult`, `ReadAlongSummary` types; `api.readalongStart()`, `api.readalongScore()`, `api.readalongSummary()`, `api.readalongParseFile()`, `api.readalongTts()` functions

- [ ] **Step 1: Add TypeScript interfaces after line 152 (after `ParsedItem`)**

```typescript
export interface ReadAlongSegment {
  text: string;
  translation: string;
}

export interface ReadAlongSession {
  session_id: string;
  segments: ReadAlongSegment[];
  total: number;
  mode: "sentence" | "paragraph";
}

export interface ReadAlongScoreResult {
  score: number;
  feedback: string;
  llm_feedback: string;
  details: ScoreResult;
  should_retry: boolean;
  retry_count: number;
}

export interface ReadAlongSummary {
  summary: string;
  avg_score: number;
  weak_segments: ReadAlongSegment[];
  weak_words: string[];
  total_segments: number;
  total_retries: number;
}
```

- [ ] **Step 2: Add readalong API methods before the closing `}` of the `api` object (before line 278)**

After the `testConfig` method, add:

```typescript
  // ── 跟读教练 ──────────────────────────────────────────────────
  readalongParseFile: (file: File, useAi: boolean) => {
    const form = new FormData();
    form.append("file", file);
    form.append("use_ai", String(useAi));
    return postForm<{ text: string }>("/api/readalong/parse-text", form);
  },
  readalongStart: (text: string, mode: "sentence" | "paragraph") =>
    req<ReadAlongSession>("POST", "/api/readalong/start", { text, mode }),
  readalongStartText: (text: string) =>
    req<ReadAlongSession>("POST", "/api/readalong/start-text", { text }),
  readalongTts: (text: string, voice?: string) => {
    const body: Record<string, string> = { text };
    if (voice) body.voice = voice;
    return fetch("/api/readalong/tts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(async (res) => {
      if (!res.ok) throw new Error("TTS 合成失败");
      const blob = await res.blob();
      return URL.createObjectURL(blob);
    });
  },
  readalongScore: (
    session_id: string,
    seg_idx: number,
    audio_b64: string,
    audio_format: string,
  ) =>
    req<ReadAlongScoreResult>("POST", "/api/readalong/score", {
      session_id,
      seg_idx,
      audio_b64,
      audio_format,
    }),
  readalongSummary: (session_id: string) =>
    req<ReadAlongSummary>("POST", "/api/readalong/summary", { session_id }),
```

- [ ] **Step 3: Verify TypeScript compiles**

Run: `cd /e/My_Code/AudioRecorder/web && npx tsc --noEmit 2>&1 | head -20`
Expected: No errors (or only pre-existing errors unrelated to readalong)

- [ ] **Step 4: Commit**

```bash
git add web/src/lib/api.ts
git commit -m "feat(readalong): 前端 API 客户端 — 跟读教练接口定义"
```

---

### Task 4: Frontend Page — `ReadAlongPage.tsx`

**Files:**
- Create: `web/src/pages/ReadAlongPage.tsx`
- Modify: `web/src/App.tsx:1-41` (add route)
- Modify: `web/src/pages/HomePage.tsx:27-31` (add nav entry)

**Interfaces:**
- Consumes: `api` (from `api.ts`), `useRecorder` (from `recorder.ts`), `speak`/`stopAudio`/`playSoundForScore` (from `audio.ts`), `RecordButton`, `ScoreResultView`, UI components, icons
- Produces: `ReadAlongPage` React component, registered at `/readalong`

- [ ] **Step 1: Create `web/src/pages/ReadAlongPage.tsx`**

```tsx
// 跟读教练 — 上传课文 → TTS 领读 → 跟读评分 → 低分重读 → 总结
import { useEffect, useRef, useState } from "react";
import {
  api, type ReadAlongSegment, type ReadAlongSession,
  type ReadAlongScoreResult, type ReadAlongSummary,
} from "../lib/api";
import { useRecorder } from "../lib/recorder";
import { playSoundForScore, speak, stopAudio } from "../lib/audio";
import RecordButton from "../components/RecordButton";
import ScoreResultView from "../components/ScoreResultView";
import {
  PageHeader, ProgressBar, Spinner, ErrorText,
  btnPrimary, btnSecondary, inputCls,
} from "../components/ui";
import { SpeakerIcon } from "../components/icons";

type Phase = "setup" | "readalong" | "summary";
type ReadState = "idle" | "playing" | "waiting" | "recording" | "scoring" | "scored";

export default function ReadAlongPage() {
  // Phase
  const [phase, setPhase] = useState<Phase>("setup");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  // Setup
  const [rawText, setRawText] = useState("");
  const [mode, setMode] = useState<"sentence" | "paragraph">("sentence");

  // Session
  const [session, setSession] = useState<ReadAlongSession | null>(null);
  const [segIdx, setSegIdx] = useState(0);
  const [scores, setScores] = useState<number[]>([]);
  const [retries, setRetries] = useState<number[]>([]);
  const [totalRetries, setTotalRetries] = useState(0);

  // Read-along state machine
  const [readState, setReadState] = useState<ReadState>("idle");
  const [scoreResult, setScoreResult] = useState<ReadAlongScoreResult | null>(null);
  const [llmFeedback, setLlmFeedback] = useState("");

  // Summary
  const [summary, setSummary] = useState<ReadAlongSummary | null>(null);

  const { recording, error: recError, start, stop } = useRecorder();
  const textAreaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => () => stopAudio(), []);

  // Auto-scroll to current segment
  const segRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    segRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [segIdx]);

  // --- File upload handler ---
  const handleFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setBusy(true);
    setError("");
    try {
      const r = await api.readalongParseFile(file, true);
      setRawText(r.text);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  // --- Start session ---
  const startSession = async () => {
    const text = rawText.trim();
    if (!text) {
      setError("请输入或上传课文内容");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const r = await api.readalongStart(text, mode);
      setSession(r);
      setSegIdx(0);
      setScores(new Array(r.total).fill(0));
      setRetries(new Array(r.total).fill(0));
      setTotalRetries(0);
      setScoreResult(null);
      setLlmFeedback("");
      setReadState("idle");
      setPhase("readalong");
      // Auto-play first segment TTS
      setTimeout(() => playCurrentSegment(r.segments, 0), 300);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  // --- Play TTS for current segment ---
  const playCurrentSegment = async (segments: ReadAlongSegment[], idx: number) => {
    if (idx >= segments.length) return;
    setReadState("playing");
    setScoreResult(null);
    setLlmFeedback("");
    try {
      await speak(segments[idx].text);
    } catch {
      // TTS 播放失败也继续
    }
    setReadState("waiting");
  };

  // --- Start recording ---
  const handleStartRecord = async () => {
    setReadState("recording");
    await start();
  };

  // --- Stop recording and score ---
  const handleStopRecord = async () => {
    const rec = await stop();
    if (!rec.b64 || !session) return;

    setReadState("scoring");
    setBusy(true);
    setError("");
    try {
      const r = await api.readalongScore(session.session_id, segIdx, rec.b64, rec.format);
      setScoreResult(r);
      setLlmFeedback(r.llm_feedback || "");
      setReadState("scored");

      // Update scores
      setScores((prev) => {
        const next = [...prev];
        next[segIdx] = Math.max(next[segIdx], r.score);
        return next;
      });
      setRetries((prev) => {
        const next = [...prev];
        if (r.score < 80) {
          next[segIdx] = r.retry_count;
          setTotalRetries((t) => t + 1);
        }
        return next;
      });

      playSoundForScore(r.score);

      // Speak LLM correction if available
      if (r.llm_feedback) {
        speak(r.llm_feedback).catch(() => {});
      }
    } catch (err) {
      setError((err as Error).message);
      setReadState("waiting");
    } finally {
      setBusy(false);
    }
  };

  // --- Advance to next segment ---
  const goNext = () => {
    if (!session) return;
    const nextIdx = segIdx + 1;
    if (nextIdx >= session.total) {
      // All done → summary
      finishSession();
    } else {
      setSegIdx(nextIdx);
      playCurrentSegment(session.segments, nextIdx);
    }
  };

  // --- Retry current segment ---
  const retrySegment = () => {
    if (!session) return;
    setScoreResult(null);
    setLlmFeedback("");
    setReadState("waiting");
  };

  // --- Re-listen TTS ---
  const reListen = () => {
    if (!session) return;
    playCurrentSegment(session.segments, segIdx);
  };

  // --- Finish session ---
  const finishSession = async () => {
    if (!session) return;
    setBusy(true);
    try {
      const s = await api.readalongSummary(session.session_id);
      setSummary(s);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
      setPhase("summary");
    }
  };

  // --- End session early ---
  const endSession = () => {
    stopAudio();
    finishSession();
  };

  // ==================== RENDER ====================

  if (phase === "setup") {
    return (
      <div className="flex flex-col gap-4">
        <PageHeader title="跟读教练" />
        <ErrorText text={error} />
        <p className="text-ui text-ink-soft">
          上传课本图片或粘贴课文，AI 老师带你逐句朗读、评分、纠错。
        </p>

        {/* File upload */}
        <div className="bg-desk border border-desk-line rounded-xl p-4 flex flex-col gap-2">
          <p className="text-ui font-bold">上传课本（PDF / 图片）</p>
          <label
            htmlFor="readalong-file"
            className="bg-card border-2 border-dashed border-desk-line rounded-lg p-6 text-center cursor-pointer hover:border-mango transition-colors"
          >
            <p className="text-ui text-ink-soft">
              点击选择文件 或 拍照上传
            </p>
            <input
              id="readalong-file"
              type="file"
              accept=".pdf,.jpg,.jpeg,.png,.bmp,.tiff,.tif"
              onChange={handleFile}
              className="hidden"
            />
          </label>
        </div>

        {/* Text input */}
        <div className="flex flex-col gap-2">
          <p className="text-ui font-bold">或者粘贴课文</p>
          <textarea
            ref={textAreaRef}
            value={rawText}
            onChange={(e) => setRawText(e.target.value)}
            placeholder="在这里粘贴英文课文内容..."
            rows={6}
            className={inputCls + " min-h-[120px]"}
          />
        </div>

        {/* Mode selection */}
        <div className="flex flex-col gap-2">
          <p className="text-ui font-bold">领读模式</p>
          <div className="flex gap-2">
            {(["sentence", "paragraph"] as const).map((m) => (
              <button
                key={m}
                type="button"
                onClick={() => setMode(m)}
                className={`px-4 py-2 rounded-lg text-ui font-bold border transition-colors ${
                  mode === m
                    ? "bg-mango border-mango-dk text-ink"
                    : "bg-card border-desk-line text-ink-soft hover:text-ink"
                }`}
              >
                {m === "sentence" ? "逐句领读" : "逐段领读"}
              </button>
            ))}
          </div>
        </div>

        <button className={btnPrimary} disabled={busy || !rawText.trim()} onClick={startSession}>
          {busy ? "AI 准备中…" : "开始跟读"}
        </button>
      </div>
    );
  }

  if (phase === "summary") {
    return (
      <div className="flex flex-col gap-4 py-6">
        <h1 className="text-section font-bold text-center">跟读完成</h1>
        {summary ? (
          <>
            <div className="text-center">
              <p className="text-score font-extrabold text-mango-dk tabular-nums animate-pop">
                {summary.avg_score}
              </p>
              <p className="text-body text-ink-soft">平均分</p>
            </div>
            <p className="text-ui text-ink-soft text-center">
              共 {summary.total_segments} {session?.mode === "paragraph" ? "段" : "句"}
              {summary.total_retries > 0 && ` · 重读 ${summary.total_retries} 次`}
            </p>
            <p className="text-ui text-center">{summary.summary}</p>

            {summary.weak_segments.length > 0 && (
              <div className="flex flex-col gap-2">
                <p className="text-ui font-bold text-clay">薄弱句</p>
                {summary.weak_segments.slice(0, 5).map((s, i) => (
                  <div
                    key={i}
                    className="bg-clay-soft border border-clay rounded-lg px-3 py-2 text-ui"
                  >
                    {s.text}
                    <span className="text-body text-ink-soft block">{s.translation}</span>
                  </div>
                ))}
              </div>
            )}

            {summary.weak_words.length > 0 && (
              <div className="flex flex-col gap-2">
                <p className="text-ui font-bold text-clay">需复习的词</p>
                <div className="flex flex-wrap gap-1.5">
                  {summary.weak_words.map((w, i) => (
                    <span
                      key={i}
                      className="text-body px-2 py-0.5 rounded bg-clay-soft border border-clay text-clay font-semibold"
                    >
                      {w}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </>
        ) : (
          <Spinner label="生成总结…" />
        )}
        <div className="flex gap-2 justify-center">
          <button className={btnSecondary} onClick={() => setPhase("setup")}>
            再练一篇
          </button>
        </div>
      </div>
    );
  }

  // readalong phase
  const segment = session?.segments[segIdx];
  const canRetry = scoreResult && scoreResult.should_retry;
  const canAdvance = scoreResult && (scoreResult.score >= 80 || !scoreResult.should_retry);

  return (
    <div className="flex flex-col gap-3">
      <PageHeader title="跟读教练" onBack={endSession} />

      {session && (
        <ProgressBar current={segIdx + 1} total={session.total} />
      )}

      {/* 课文显示区 */}
      <div className="bg-desk border border-desk-line rounded-xl p-4 max-h-[40vh] overflow-y-auto">
        {session?.segments.map((seg, i) => (
          <div
            key={i}
            ref={i === segIdx ? segRef : undefined}
            className={`mb-3 last:mb-0 transition-colors ${
              i < segIdx
                ? "text-ink-soft/60"
                : i === segIdx
                  ? "text-mango-dk"
                  : "text-ink"
            }`}
          >
            <p className={`leading-relaxed break-words ${
              i === segIdx ? "font-bold text-title" : "text-ui"
            }`}>
              {seg.text}
            </p>
            {seg.translation && (
              <p className={`text-body mt-0.5 ${
                i === segIdx ? "text-ink-soft" : "text-ink-soft/50"
              }`}>
                {seg.translation}
              </p>
            )}
          </div>
        ))}
      </div>

      {/* 领读/听标准音 按钮 */}
      {(readState === "idle" || readState === "waiting" || readState === "scored") && (
        <button
          type="button"
          onClick={reListen}
          disabled={readState === "playing"}
          className="flex items-center gap-1.5 self-center px-4 py-2 rounded-lg bg-card border border-desk-line text-ui font-bold hover:border-mango transition-colors disabled:opacity-40"
        >
          <SpeakerIcon className="w-4 h-4" />
          {readState === "playing" ? "领读中…" : "听标准音"}
        </button>
      )}

      {/* 播放中指示 */}
      {readState === "playing" && (
        <p className="text-ui text-ink-soft text-center animate-pulse">
          🔊 跟着老师读…
        </p>
      )}

      {/* 评分结果 */}
      {scoreResult && readState === "scored" && (
        <>
          <ScoreResultView result={scoreResult.details} />
          {llmFeedback && (
            <div className="bg-card border border-desk-line rounded-xl px-4 py-3">
              <p className="text-ui font-bold text-mango-dk">AI 纠错</p>
              <p className="text-ui">{llmFeedback}</p>
            </div>
          )}
          {canRetry && (
            <div className="bg-clay-soft border border-clay rounded-xl px-4 py-3">
              <p className="text-ui font-bold text-clay">
                还差一点点，再读一次吧！
              </p>
            </div>
          )}
          <div className="flex gap-2">
            {canRetry && (
              <button className={btnSecondary} onClick={retrySegment}>
                重新跟读
              </button>
            )}
            <button className={btnPrimary} onClick={goNext}>
              {segIdx + 1 >= (session?.total ?? 0) ? "看总结" : "下一句"}
            </button>
          </div>
        </>
      )}

      {/* 录音按钮 */}
      {(readState === "waiting" || readState === "recording") && !scoreResult && (
        <RecordButton
          recording={recording}
          disabled={readState === "scoring"}
          onStart={handleStartRecord}
          onStop={handleStopRecord}
          hint={
            readState === "scoring"
              ? "评分中…"
              : recError || (readState === "waiting" ? "听完后点击开始跟读" : "朗读中，点击停止")
          }
        />
      )}

      {/* 录音后直接重新跟读（scoreResult 存在但低分） */}
      {readState === "scored" && canRetry && (
        <RecordButton
          recording={recording}
          disabled={readState === "scoring"}
          onStart={handleStartRecord}
          onStop={handleStopRecord}
          hint={
            readState === "scoring"
              ? "评分中…"
              : recError || "重新跟读，点击开始"
          }
        />
      )}

      {readState === "scoring" && (
        <p className="text-ui text-ink-soft text-center">评分中…</p>
      )}

      <ErrorText text={error} />

      <button
        className={`${btnSecondary} self-center text-body`}
        onClick={endSession}
        disabled={busy}
      >
        结束跟读
      </button>
    </div>
  );
}
```

- [ ] **Step 2: Add route in `web/src/App.tsx`**

Add import after `import TutorPage` (line 9):
```typescript
import ReadAlongPage from "./pages/ReadAlongPage";
```

Add route after the tutor route (after line 31):
```typescript
<Route path="readalong" element={<ReadAlongPage />} />
```

- [ ] **Step 3: Add nav entry in `web/src/pages/HomePage.tsx`**

Add to the `children` array of the "口语训练" section (after `{ to: "/tutor", zh: "AI 家教" }` at line 29):
```typescript
{ to: "/readalong", zh: "跟读教练" },
```

- [ ] **Step 4: Verify TypeScript compiles and Vite builds**

Run: `cd /e/My_Code/AudioRecorder/web && npx tsc --noEmit 2>&1 | head -20`
Expected: No new errors

Run: `cd /e/My_Code/AudioRecorder/web && npx vite build 2>&1 | tail -5`
Expected: Build succeeds

- [ ] **Step 5: Commit**

```bash
git add web/src/pages/ReadAlongPage.tsx web/src/App.tsx web/src/pages/HomePage.tsx
git commit -m "feat(readalong): 前端跟读教练页面 + 路由 + 导航入口"
```

---

### Task 5: Integration Verification

**Files:**
- No new files — verify existing ones work together

**Interfaces:**
- Consumes: All components from Tasks 1-4
- Produces: Verified working end-to-end flow

- [ ] **Step 1: Start the dev server**

Run: `cd /e/My_Code/AudioRecorder && python run_web.py`
(Or use `npm run dev` in `web/` for frontend dev mode with proxy)

- [ ] **Step 2: Verify backend endpoints respond**

Open browser to `https://192.168.50.157:8000/api/health` — should return `{"status":"ok"}`

Test the start endpoint with a curl:
```bash
curl -X POST https://192.168.50.157:8000/api/readalong/start \
  -H "Content-Type: application/json" \
  -d '{"text":"Hello world. How are you? I am fine.", "mode":"sentence"}'
```
Expected: JSON with `session_id`, `segments` array (3 items with translations), `total: 3`

- [ ] **Step 3: Verify frontend renders**

Navigate to `https://192.168.50.157:8000/#/readalong` in browser — should show the setup phase with file upload, text input, mode selection, and start button.

- [ ] **Step 4: Quick end-to-end test**

1. Paste a short English text in the text area
2. Select "逐句领读"
3. Click "开始跟读"
4. Verify: segments display with translations, TTS plays, record button appears
5. Record audio → verify score appears
6. Complete all segments → verify summary page

- [ ] **Step 5: Commit any integration fixes**

```bash
git add -A
git commit -m "fix(readalong): 集成验证修复"
```

---

### Task 6: Deploy to NUC

**Files:**
- No local file changes — remote deployment

- [ ] **Step 1: Build frontend and push to git**

```bash
cd /e/My_Code/AudioRecorder/web && npm run build
cd /e/My_Code/AudioRecorder && git add -A && git commit -m "build(readalong): 前端构建产物"
git push
```

- [ ] **Step 2: SSH to NUC and update**

```bash
ssh manfred@192.168.50.157 "cd ~/english-coach/AudioRecorder/deploy && git pull && docker compose up -d --build"
```

- [ ] **Step 3: Verify on NUC**

Open `https://192.168.50.157:8000/#/readalong` on a device — verify the full flow works with real TTS and GOP scoring.
