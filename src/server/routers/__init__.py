"""Web API routers — 按功能拆分的 FastAPI APIRouter 模块。
各模块独立定义 router，由 web_server.py 显式 include。
"""
from . import (
    vocab,
    practice,
    quiz,
    oral,
    scenario,
    tutor,
    memorize,
    mistakes,
    config,
    readalong,
)

__all__ = [
    "vocab", "practice", "quiz", "oral", "scenario",
    "tutor", "memorize", "mistakes", "config", "readalong",
]
