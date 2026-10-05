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


# ---------------------------------------------------------------------- #
# 连通性测试（用表单当前值，无需先保存）
# ---------------------------------------------------------------------- #
class ConfigTest(BaseModel):
    config: dict


def _norm_base(url: str) -> str:
    """OpenAI 兼容地址统一补 /v1（与 content_parser 同规则）。"""
    url = (url or "").strip().rstrip("/")
    if url and not url.endswith("/v1"):
        url += "/v1"
    return url


@router.post("/test")
def test_config(req: ConfigTest):
    """测试 AI 提供商连通性：LLM 走 models.list + 1 token 补全；Omni 走登录 + status。"""
    cfg = req.config or {}
    provider = str(cfg.get("ai_provider", ""))
    try:
        if "Omni" in provider or "MiniCPM" in provider:
            from src.core.omni_client import OmniClient, OmniConfig
            omni = OmniConfig(
                host=(cfg.get("omni_host") or "127.0.0.1").strip(),
                auth_port=int(cfg.get("omni_auth_port") or 18500),
                chat_port=int(cfg.get("omni_chat_port") or 18400),
                username=(cfg.get("omni_username") or "admin").strip(),
                password=cfg.get("omni_password") or "admin123",
                connect_timeout=5.0,
            )
            st = OmniClient(omni).status()
            state = st.get("state", st.get("status", "ready"))
            return {"ok": True, "message": f"Omni 连接成功，服务状态：{state}"}

        from openai import OpenAI
        if "Custom" in provider:
            base = _norm_base(str(cfg.get("custom_base", "")))
            key = cfg.get("custom_key") or "not-needed"
            model = str(cfg.get("custom_model", "")).strip()
            if not base:
                return {"ok": False, "message": "未填写接口地址（Base URL）"}
            if not model:
                return {"ok": False, "message": "未填写模型名"}
        elif "Ollama" in provider:
            base = _norm_base(str(cfg.get("ollama_base") or "http://localhost:11434/v1"))
            key = "ollama"
            model = str(cfg.get("ollama_model") or "qwen2.5").strip()
        elif "OpenAI" in provider:
            base = _norm_base(str(cfg.get("openai_base") or "https://api.openai.com/v1"))
            key = str(cfg.get("openai_key", "")).strip()
            model = str(cfg.get("openai_model") or "gpt-4o").strip()
            if not key:
                return {"ok": False, "message": "未填写 API 密钥"}
        else:
            return {"ok": False, "message": f"未识别的提供商：{provider or '（未选择）'}"}

        client = OpenAI(base_url=base, api_key=key, timeout=20)
        models: list[str] = []
        try:
            models = sorted(m.id for m in client.models.list())
        except Exception:
            pass  # 部分兼容服务不提供 /models，不算失败
        client.chat.completions.create(
            model=model, max_tokens=1,
            messages=[{"role": "user", "content": "hi"}],
        )
        msg = f"连接成功，模型 {model} 已响应"
        if models:
            msg += f"，服务共 {len(models)} 个模型"
        return {"ok": True, "message": msg, "models": models[:50]}
    except Exception as e:
        return {"ok": False, "message": f"连接失败：{e}"}
