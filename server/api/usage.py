"""商品详情次数额度 API — 查询剩余 / 扣减。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from server.api.auth import require_client


usage_router = APIRouter(prefix="/v1/usage", tags=["usage"])


def _manage(request: Request):
    manage = getattr(request.app.state, "manage_usage", None)
    if manage is None:
        raise HTTPException(status_code=503, detail="用量服务未配置")
    return manage


def _token(request: Request) -> str:
    authorization = request.headers.get("Authorization", "")
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="未认证")
    return authorization[len("Bearer "):].strip()


@usage_router.get("")
def get_usage(request: Request) -> dict:
    require_client(request, "客户端认证未配置")
    total, remaining = _manage(request).get_usage(_token(request))
    return {"quota_total": total, "quota_remaining": remaining}


@usage_router.post("/consume")
def consume_usage(request: Request) -> dict:
    require_client(request, "客户端认证未配置")
    manage = _manage(request)
    token = _token(request)
    consumed, remaining = manage.consume(token, 1)
    total, _ = manage.get_usage(token)
    return {"consumed": consumed, "quota_total": total, "quota_remaining": remaining}
