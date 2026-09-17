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
    """商品详情生成（视觉模型）— 走商品详情大模型配置。"""
    return _chat_with(request, "glm_gateway", payload)


@llm_router.post("/llm/translation")
def llm_translation(payload: LlmChatRequest, request: Request) -> dict:
    """图片翻译（文本模型）— 与商品详情分开配置，可各自指定模型与接口地址。"""
    return _chat_with(request, "translation_llm_gateway", payload)


def _chat_with(request: Request, state_name: str, payload: LlmChatRequest) -> dict:
    require_client(request, "LLM 服务未启用")
    gateway = getattr(request.app.state, state_name, None)
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
