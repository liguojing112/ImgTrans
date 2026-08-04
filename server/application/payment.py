"""微信支付 Native 用例 — 下单 / 回调发码 / 订单查询。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Protocol
from uuid import uuid4

from server.domain.payment import (
    PaymentConflict,
    PaymentNotFound,
    PaymentOrder,
    PaymentStatus,
)


class WechatPayGateway(Protocol):
    """微信支付 API v3 网关抽象（便于测试注入 fake）。"""

    def native_prepay(self, order_id: str, amount_minor: int, description: str) -> str:
        """Native 下单，返回 code_url（二维码串）。"""
        ...

    def parse_notify(self, body: bytes, headers: dict[str, str]) -> dict:
        """验签并解密微信支付回调，返回交易信息 dict；验签失败抛 PaymentError。"""
        ...


class PaymentRepository(Protocol):
    def create(self, order: PaymentOrder) -> PaymentOrder: ...
    def get(self, order_id: str) -> PaymentOrder | None: ...
    def mark_paid_if_created(self, order_id: str, now: datetime) -> bool: ...
    def set_activation_code(
        self, order_id: str, code_id: str, activation_code: str, now: datetime
    ) -> None: ...
    def list_recent(self, limit: int = 100) -> list[PaymentOrder]: ...


class CreatePaymentOrder:
    """客户端选套餐 → Native 下单 → 建订单。"""

    def __init__(self, gateway, plans, order_repository: PaymentRepository) -> None:
        self._gateway = gateway
        self._plans = plans
        self._orders = order_repository

    def execute(self, plan_id: int) -> tuple[PaymentOrder, str]:
        plan = next(
            (item for item in self._plans.list_all() if item.plan_id == plan_id),
            None,
        )
        if plan is None or not plan.values.enabled:
            raise PaymentConflict("套餐不存在或已停用")
        now = datetime.now(timezone.utc)
        order_id = uuid4().hex
        # 有效促销期用促销价，否则原价（订单创建时锁定金额）
        amount = (
            plan.values.sale_amount_minor
            if plan.values.is_on_sale(now)
            else plan.values.amount_minor
        )
        order = PaymentOrder(
            order_id=order_id,
            plan_id=plan_id,
            amount_minor=amount,
            currency=plan.values.currency,
            status=PaymentStatus.CREATED,
            code_id=None,
            created_at=now,
        )
        self._orders.create(order)
        code_url = self._gateway.native_prepay(
            order_id, order.amount_minor, plan.values.name
        )
        return order, code_url


class HandlePaymentCallback:
    """微信支付回调 — 验签 + 金额核对 + 幂等发码。"""

    def __init__(
        self, gateway, order_repository: PaymentRepository, issue_codes
    ) -> None:
        self._gateway = gateway
        self._orders = order_repository
        self._issue_codes = issue_codes

    def execute(self, body: bytes, headers: dict[str, str]) -> None:
        notify = self._gateway.parse_notify(body, headers)
        out_trade_no = notify.get("out_trade_no")
        if not out_trade_no:
            raise PaymentConflict("回调缺少订单号")
        order = self._orders.get(out_trade_no)
        if order is None:
            raise PaymentNotFound("订单不存在")
        if notify.get("trade_state") != "SUCCESS":
            return
        total = (notify.get("amount") or {}).get("total")
        if total != order.amount_minor:
            raise PaymentConflict("支付金额与订单不一致")
        now = datetime.now(timezone.utc)
        if not self._orders.mark_paid_if_created(order.order_id, now):
            return  # 已处理过，幂等返回
        issued = self._issue_codes(order.plan_id, 1)
        item = issued[0]
        self._orders.set_activation_code(
            order.order_id, item.activation.code_id, item.plaintext, now
        )


class GetPaymentOrder:
    def __init__(self, order_repository: PaymentRepository) -> None:
        self._orders = order_repository

    def execute(self, order_id: str) -> PaymentOrder:
        order = self._orders.get(order_id)
        if order is None:
            raise PaymentNotFound("订单不存在")
        return order


class ListPaymentOrders:
    def __init__(self, order_repository: PaymentRepository) -> None:
        self._orders = order_repository

    def execute(self, limit: int = 100) -> list[PaymentOrder]:
        return self._orders.list_recent(limit)
