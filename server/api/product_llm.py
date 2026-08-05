"""GLM 商品详情生成代理接口 — 客户端调服务端，服务端持客户密钥调 GLM。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from server.api.auth import require_client
from server.api.contracts import StrictContract
from server.infrastructure.glm_gateway import GlmError, GlmNotConfigured

llm_router = APIRouter(prefix="/v1", tags=["llm"])


class LlmChatRequest(StrictContract):
    messages: list[dict]
    model: str | None = None
    max_tokens: int | None = None
    temperature: float | None = None


@llm_router.post("/llm/chat")
def llm_chat(payload: LlmChatRequest, request: Request) -> dict:
    require_client(request, "LLM 服务未启用")
    gateway = getattr(request.app.state, "glm_gateway", None)
    if gateway is None:
        raise HTTPException(status_code=503, detail="LLM 服务未配置")
    try:
        text = gateway.chat(
            payload.messages,
            model=payload.model,
            max_tokens=payload.max_tokens,
            temperature=payload.temperature,
        )
    except GlmNotConfigured as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except GlmError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    return {"text": text}
