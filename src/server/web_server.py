"""FastAPI web server — 少儿英语发音教练 Web 版主应用。

启动：python run_web.py  或  uvicorn src.server.web_server:app --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import json
import os
import re

# 无 GUI 服务器：强制 qt_compat 使用轻量信号 shim（跨线程直接投递）。
# 必须在导入任何 src.core 引擎模块之前设置。
os.environ.setdefault("ENGLISH_COACH_HEADLESS", "1")


# ---------------------------------------------------------------------- #
# Docker 部署支持：config.json 回环地址改写
# ---------------------------------------------------------------------- #
_URL_KEYS = ("custom_base", "ollama_base", "openai_base", "cosyvoice_url")
_HOST_KEYS = ("omni_host",)
_LOOPBACK = ("127.0.0.1", "localhost")
_URL_RE = re.compile(r"^(https?://)(127\.0\.0\.1|localhost)(?::(\d+))?(.*)$")


def rewrite_loopback_hosts(cfg: dict, host: str) -> int:
    """把 cfg 中指向 127.0.0.1/localhost 的服务地址改写为 host，返回改动数。"""
    changed = 0
    for key in _URL_KEYS:
        val = cfg.get(key)
        if isinstance(val, str):
            m = _URL_RE.match(val)
            if m:
                new = f"{m.group(1)}{host}" + (f":{m.group(3)}" if m.group(3) else "") + m.group(4)
                if new != val:
                    cfg[key] = new
                    changed += 1
    for key in _HOST_KEYS:
        val = cfg.get(key)
        if isinstance(val, str) and val.strip() in _LOOPBACK:
            cfg[key] = host
            changed += 1
    return changed


def _rewrite_loopback_config() -> None:
    """容器内 127.0.0.1 指向容器自身，宿主机上的 MiniCPM-o / LLM 会失联。

    设置 ENGLISH_COACH_REWRITE_HOST（如 host.docker.internal）后，启动时把
    config.json 里的回环服务地址改写到宿主机。幂等：已改写的不重复改动；
    指向局域网 IP 的地址（如 192.168.50.200）不受影响。
    """
    host = os.environ.get("ENGLISH_COACH_REWRITE_HOST", "").strip()
    if not host:
        return
    from src.utils import get_user_data_path
    path = get_user_data_path("config.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except (OSError, json.JSONDecodeError):
        return  # 无配置或损坏：跳过，各引擎用自身默认值
    if rewrite_loopback_hosts(cfg, host):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        print(f"[web_server] config.json 回环地址已改写为 {host}")


_rewrite_loopback_config()

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

# 直接从子模块导入 router，绕过 __init__.py 避免包初始化时序问题
from src.server.routers.vocab import router as vocab_router
from src.server.routers.practice import router as practice_router
from src.server.routers.quiz import router as quiz_router
from src.server.routers.oral import router as oral_router
from src.server.routers.scenario import router as scenario_router
from src.server.routers.tutor import router as tutor_router
from src.server.routers.memorize import router as memorize_router
from src.server.routers.mistakes import router as mistakes_router
from src.server.routers.config import router as config_router

app = FastAPI(title="少儿英语发音教练 Web", version="1.0")

# CORS：开发时前端跑在 Vite dev server（不同端口）；局域网同源部署时无影响
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# API routers
for r in (vocab_router, practice_router, quiz_router, oral_router,
          scenario_router, tutor_router, memorize_router, mistakes_router, config_router):
    app.include_router(r)


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/cert/root-ca")
def download_root_ca():
    """下载局域网 HTTPS 根 CA 证书（iPad/手机安装后可录音）。"""
    # 容器内 mkcert 的根证书在 /certs/rootCA.pem（需手动放入 deploy/certs/）
    # 或宿主机 ~/.local/share/mkcert/rootCA.pem
    candidates = [
        "/certs/rootCA.pem",
        os.path.expanduser("~/.local/share/mkcert/rootCA.pem"),
    ]
    for p in candidates:
        if os.path.isfile(p):
            from fastapi.responses import FileResponse
            return FileResponse(
                p,
                media_type="application/x-pem-file",
                filename="rootCA.pem",
                headers={"Content-Disposition": 'attachment; filename="rootCA.pem"'},
            )
    raise HTTPException(status_code=404, detail="根证书未找到，请先将 rootCA.pem 放入 deploy/certs/")


# 静态托管 React 构建产物（若 web/dist 已构建）
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_DIST = os.path.join(_ROOT, "web", "dist")
if os.path.isdir(_DIST):
    app.mount("/", StaticFiles(directory=_DIST, html=True), name="static")