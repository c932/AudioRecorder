"""系统路由 — GPU 练习模式一键切换。

背景：NUC 的 8GB 显存装不下 strata 本地大模型(7.4GB) + qwen-tts(1.5GB) +
whisper(3GB)。练习时段需要 qwen-tts（中文音色）和 whisper（家教语音判分），
平时需要 strata。本路由通过 AI Runtime Manager 的 HTTP API 编排切换：
  on  = 停 strata → 起 qwen-tts + whisper（等就绪）
  off = 停 qwen-tts + whisper → 起 strata
切换在后台线程执行（模型加载要几十秒），前端轮询 GET 状态。
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/api/system", tags=["system"])

MANAGER_URL = os.environ.get("MANAGER_URL", "http://host.docker.internal:18500").rstrip("/")
TTS_HEALTH = os.environ.get("TTS_URL", "http://host.docker.internal:50000").rstrip("/") + "/health"
WHISPER_HEALTH = os.environ.get("WHISPER_REMOTE_URL", "http://host.docker.internal:18350").rstrip("/") + "/v1/health"

# 切换状态（单用户场景，进程内即可）
_state_lock = threading.Lock()
_state: dict = {"switching": False, "target": "", "error": "", "done_at": 0.0}


def _mgr(path: str, method: str = "GET", timeout: float = 30) -> dict:
    """调用 Manager API，返回解析后的 JSON（失败抛异常或返回错误信息）。"""
    req = urllib.request.Request(f"{MANAGER_URL}{path}", method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:200]
        raise RuntimeError(f"Manager API {path} 返回 {e.code}: {body}") from e


def _service_status(sid: str) -> str:
    try:
        # 状态查询用短超时：Manager 若不可达，设置页每 5 秒轮询不能卡 90 秒
        d = _mgr(f"/api/services/{sid}", timeout=3)
        return str(d.get("status", "unknown"))
    except Exception:
        return "unknown"


def _wait_url(url: str, timeout_s: float) -> bool:
    """轮询等某个健康检查 URL 通（模型加载要几十秒）。"""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=5) as r:
                if r.status < 500:
                    return True
        except Exception:
            pass
        time.sleep(3)
    return False


def _do_switch(mode: str) -> None:
    """后台执行切换。"""
    try:
        if mode == "on":
            _mgr("/api/services/strata/stop", "POST", timeout=60)
            time.sleep(8)  # 等显存释放
            _mgr("/api/services/qwen-tts/start", "POST", timeout=60)
            _mgr("/api/services/whisper/start", "POST", timeout=60)
            ok_tts = _wait_url(TTS_HEALTH, 150)
            ok_wh = _wait_url(WHISPER_HEALTH, 150)
            if not (ok_tts and ok_wh):
                with _state_lock:
                    _state["error"] = (
                        f"部分服务未就绪：qwen-tts={'就绪' if ok_tts else '未就绪'}，"
                        f"whisper={'就绪' if ok_wh else '未就绪'}"
                    )
        else:
            _mgr("/api/services/qwen-tts/stop", "POST", timeout=60)
            _mgr("/api/services/whisper/stop", "POST", timeout=60)
            time.sleep(8)
            _mgr("/api/services/strata/start", "POST", timeout=60)
    except Exception as e:
        with _state_lock:
            _state["error"] = str(e)
    finally:
        with _state_lock:
            _state["switching"] = False
            _state["done_at"] = time.time()


@router.get("/practice-mode")
def practice_mode_status():
    """当前练习模式相关服务状态。"""
    with _state_lock:
        switching = _state["switching"]
        target = _state["target"]
        error = _state["error"]
    return {
        "switching": switching,
        "target": target,
        "error": error,
        "manager": MANAGER_URL,
        "services": {
            "strata": _service_status("strata"),
            "qwen_tts": _service_status("qwen-tts"),
            "whisper": _service_status("whisper"),
        },
    }


class SwitchRequest(BaseModel):
    mode: str  # "on" | "off"


@router.post("/practice-mode")
def practice_mode_switch(req: SwitchRequest):
    """触发切换（后台执行，前端轮询 GET 看进度）。"""
    if req.mode not in ("on", "off"):
        from fastapi import HTTPException
        raise HTTPException(400, "mode 必须是 on 或 off")

    with _state_lock:
        if _state["switching"]:
            return {"accepted": False, "message": "切换进行中，请稍候"}
        _state["switching"] = True
        _state["target"] = req.mode
        _state["error"] = ""

    threading.Thread(target=_do_switch, args=(req.mode,), daemon=True).start()
    return {"accepted": True, "message": "已开始切换，模型加载约需 1 分钟"}
