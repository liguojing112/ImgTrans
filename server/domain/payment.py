"""微信支付订单领域模型。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class PaymentError(ValueError):
    pass


class PaymentNotFound(PaymentError):
    pass


class PaymentConflict(PaymentError):
    pass


class PaymentStatus(str, Enum):
    CREATED = "created"
    PAID = "paid"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class PaymentOrder:
    order_id: str  # = out_trade_no
    plan_id: int
    amount_minor: int
    currency: str
    status: PaymentStatus
    code_id: str | None
    created_at: datetime
    paid_at: datetime | None = None
    activation_code: str | None = None
