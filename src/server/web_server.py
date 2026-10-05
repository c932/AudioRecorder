"""FastAPI web server — 少儿英语发音教练 Web 版主应用。

启动：python run_web.py  或  uvicorn src.server.web_server:app --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import os

# 无 GUI 服务器：强制 qt_compat 使用轻量信号 shim（跨线程直接投递）。
# 必须在导入任何 src.core 引擎模块之前设置。
os.environ.setdefault("ENGLISH_COACH_HEADLESS", "1")

from fastapi import FastAPI
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


# 静态托管 React 构建产物（若 web/dist 已构建）
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_DIST = os.path.join(_ROOT, "web", "dist")
if os.path.isdir(_DIST):
    app.mount("/", StaticFiles(directory=_DIST, html=True), name="static")