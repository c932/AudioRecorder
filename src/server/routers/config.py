"""配置读写路由。"""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from src.server.deps import load_config, save_config, get_coach

router = APIRouter(prefix="/api/config", tags=["config"])


@router.get("")
def get_config():
    return load_config()


class ConfigUpdate(BaseModel):
    config: dict


@router.put("")
def put_config(req: ConfigUpdate):
    save_config(req.config)
    # 让评分器重载配置（provider / assessor_engine 等变化生效）
    get_coach().load_config()
    return {"ok": True}
