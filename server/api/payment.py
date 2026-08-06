"""微信支付 Native API — 下单 / 轮询 / 回调 / 后台订单。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from server.api.auth import require_admin
from server.api.contracts import StrictContract
from server.domain.payment import PaymentConflict, PaymentError, PaymentNotFound


payment_router = APIRouter(prefix="/v1/payments", tags=["payments"])
admin_payment_router = APIRouter(prefix="/v1/admin/payment", tags=["admin-payment"])


class CreateOrderRequest(StrictContract):
    plan_id: int
    activation_code: str | None = None


def _create_order_use(request: Request):
    use = getattr(request.app.state, "create_payment_order", None)
    if use is None:
        raise HTTPException(status_code=503, detail="支付服务未配置")
    return use


def _get_order_use(request: Request):
    use = getattr(request.app.state, "get_payment_order", None)
    if use is None:
        raise HTTPException(status_code=503, detail="支付服务未配置")
    return use


def _raise_payment(error: PaymentError) -> None:
    if isinstance(error, PaymentNotFound):
        raise HTTPException(status_code=404, detail=str(error)) from error
    if isinstance(error, PaymentConflict):
        raise HTTPException(status_code=409, detail=str(error)) from error
    raise HTTPException(status_code=422, detail=str(error)) from error


@payment_router.get("/plans")
def list_payable_plans(request: Request) -> list[dict]:
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    plans = request.app.state.manage_activation_plans.list_all()
    return [
        {
            "plan_id": item.plan_id,
            "name": item.values.name,
            "amount_minor": item.values.amount_minor,
            "currency": item.values.currency,
            "duration_hours": item.values.duration_hours,
            "plan_type": item.values.plan_type,
            "quota": item.values.quota,
            "sale_amount_minor": item.values.sale_amount_minor,
            "sale_ends_at": item.values.sale_ends_at,
            "benefits": item.values.benefits,
            "is_on_sale": item.values.is_on_sale(now),
            "wechat_pay_configured": _wechat_pay_configured(request),
        }
        for item in plans
        if item.values.enabled
    ]


def _wechat_pay_configured(request: Request) -> bool:
    manage = getattr(request.app.state, "manage_service_settings", None)
    if manage is None:
        settings = getattr(request.app.state, "settings", None)
        return bool(settings and settings.wechat_pay_configured)
    return bool(manage.get_public().get("wechat_pay_configured"))


@payment_router.post("/orders", status_code=201)
async def create_order(request: Request) -> dict:
    body = await request.json()
    spec = CreateOrderRequest.model_validate(body)
    try:
        order, code_url = _create_order_use(request).execute(
            spec.plan_id, spec.activation_code
        )
    except PaymentError as error:
        _raise_payment(error)
    return {
        "order_id": order.order_id,
        "code_url": code_url,
        "amount_minor": order.amount_minor,
        "currency": order.currency,
        "status": order.status.value,
    }


@payment_router.get("/orders/{order_id}")
def get_order(order_id: str, request: Request) -> dict:
    try:
        order = _get_order_use(request).execute(order_id)
    except PaymentError as error:
        _raise_payment(error)
    return {
        "order_id": order.order_id,
        "plan_id": order.plan_id,
        "amount_minor": order.amount_minor,
        "currency": order.currency,
        "status": order.status.value,
        "activation_code": order.activation_code,
    }


@payment_router.post("/notify")
async def payment_notify(request: Request) -> JSONResponse:
    handler = getattr(request.app.state, "handle_payment_callback", None)
    if handler is None:
        return JSONResponse({"code": "FAIL", "message": "支付服务未配置"})
    try:
        body = await request.body()
        headers = dict(request.headers)
        handler.execute(body, headers)
    except PaymentError:
        return JSONResponse({"code": "FAIL", "message": "回调校验失败"})
    return JSONResponse({"code": "SUCCESS", "message": "成功"})


@admin_payment_router.get("/orders")
def list_orders(request: Request) -> list[dict]:
    require_admin(request)
    listing = getattr(request.app.state, "list_payment_orders", None)
    if listing is None:
        raise HTTPException(status_code=503, detail="支付服务未配置")
    orders, _ = listing.execute(page=1, page_size=1000)
    return [
        {
            "order_id": order.order_id,
            "plan_id": order.plan_id,
            "amount_minor": order.amount_minor,
            "currency": order.currency,
            "status": order.status.value,
            "code_id": order.code_id,
            "created_at": order.created_at.isoformat(),
            "paid_at": order.paid_at.isoformat() if order.paid_at else None,
        }
        for order in orders
    ]
