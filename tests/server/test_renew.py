from __future__ import annotations

import asyncio
from datetime import timedelta

from server.admin.security import hash_admin_password
from server.app import create_app
from server.application.activation import ActivationSecretHasher
from server.application.payment import (
    CreatePaymentOrder,
    HandlePaymentCallback,
)
from server.config import ServerSettings
from server.domain.activation import ActivationPlanValues
from server.domain.payment import PaymentConflict
from server.infrastructure.database import Base, Database
from server.infrastructure.payment_repository import SqlAlchemyPaymentRepository

ACTIVATION_SECRET = "test-activation-secret-1234567890abcdef"
DEVICE = "device-renew-aaaa"


class _FakeGateway:
    def __init__(self) -> None:
        self.next_notify: dict | None = None

    def native_prepay(self, order_id: str, amount_minor: int, description: str) -> str:
        return f"weixin://wxpay/bizpayurl?pr={order_id}"

    def parse_notify(self, body: bytes, headers: dict[str, str]) -> dict:
        if self.next_notify is None:
            raise ValueError("no notify configured")
        return self.next_notify


def _app():
    database = Database("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(database.engine)
    settings = ServerSettings(
        environment="test",
        activation_secret=ACTIVATION_SECRET,
        admin_username="admin",
        admin_password_hash=hash_admin_password("correct-horse-battery-staple"),
        admin_session_secret="x" * 40,
    )
    app = create_app(settings, database)
    gateway = _FakeGateway()
    repo = SqlAlchemyPaymentRepository(database)
    app.state.create_payment_order = CreatePaymentOrder(
        gateway,
        app.state.manage_activation_plans,
        repo,
        activation_codes=app.state.manage_activation_codes,
    )
    app.state.handle_payment_callback = HandlePaymentCallback(
        gateway,
        repo,
        app.state.manage_activation_codes.issue,
        app.state.manage_activation_plans,
        renew_code=app.state.manage_activation_codes.renew_by_code_id,
    )
    app.state._gw = gateway
    return app


def _run(scenario):
    return asyncio.run(scenario())


def test_renew_adds_quota_and_hours() -> None:
    app = _app()
    plan = app.state.manage_activation_plans.create(
        ActivationPlanValues(
            name="组合包", amount_minor=5000, currency="CNY",
            duration_hours=2, plan_type="combo", quota=10,
        )
    )
    issued = app.state.manage_activation_codes.issue(plan.plan_id, 1)
    code = issued[0].plaintext

    quota_plan = app.state.manage_activation_plans.create(
        ActivationPlanValues(
            name="次数包", amount_minor=1000, currency="CNY",
            duration_hours=0, plan_type="quota", quota=20,
        )
    )
    app.state.manage_activation_codes.renew(
        code, quota_plan.values.duration_hours, quota_plan.values.quota
    )
    rec = app.state.manage_activation_codes.get_by_activation_code(code)
    assert rec.quota_total == 30
    assert rec.quota_remaining == 30

    dur_plan = app.state.manage_activation_plans.create(
        ActivationPlanValues(
            name="时长包", amount_minor=2000, currency="CNY",
            duration_hours=3, plan_type="duration", quota=0,
        )
    )
    from datetime import datetime, timezone

    before = datetime.now(timezone.utc)
    renewed = app.state.manage_activation_codes.renew(
        code, dur_plan.values.duration_hours, 0
    )
    assert (renewed.expires_at - before).total_seconds() > 3 * 3600 - 5
    assert (renewed.expires_at - before).total_seconds() < 3 * 3600 + 5


def test_renew_extends_active_expiry() -> None:
    app = _app()
    plan = app.state.manage_activation_plans.create(
        ActivationPlanValues(
            name="时长包", amount_minor=2000, currency="CNY",
            duration_hours=2, plan_type="duration", quota=0,
        )
    )
    issued = app.state.manage_activation_codes.issue(plan.plan_id, 1)
    code = issued[0].plaintext
    app.state.activate_device.execute(code, DEVICE)
    before = app.state.manage_activation_codes.get_by_activation_code(code).expires_at

    renewed = app.state.manage_activation_codes.renew(code, 2, 0)
    # 未过期则延长 2 小时
    assert (renewed.expires_at - before).total_seconds() == 2 * 3600


def test_quota_plan_order_rejected_without_code() -> None:
    app = _app()
    quota_plan = app.state.manage_activation_plans.create(
        ActivationPlanValues(
            name="次数包", amount_minor=1000, currency="CNY",
            duration_hours=0, plan_type="quota", quota=10,
        )
    )
    try:
        app.state.create_payment_order.execute(quota_plan.plan_id)
        raise AssertionError("expected PaymentConflict")
    except PaymentConflict as error:
        assert "时长包" in str(error)


def test_quota_plan_order_rejected_without_active_duration() -> None:
    app = _app()
    quota_plan = app.state.manage_activation_plans.create(
        ActivationPlanValues(
            name="次数包", amount_minor=1000, currency="CNY",
            duration_hours=0, plan_type="quota", quota=10,
        )
    )
    # 组合码（有时长）但未激活（expires_at 为空）→ 视为无活跃时长
    combo = app.state.manage_activation_plans.create(
        ActivationPlanValues(
            name="组合包", amount_minor=5000, currency="CNY",
            duration_hours=2, plan_type="combo", quota=5,
        )
    )
    issued = app.state.manage_activation_codes.issue(combo.plan_id, 1)
    code = issued[0].plaintext
    try:
        app.state.create_payment_order.execute(quota_plan.plan_id, code)
        raise AssertionError("expected PaymentConflict")
    except PaymentConflict as error:
        assert "时长包" in str(error)


def test_callback_renews_existing_code() -> None:
    app = _app()
    combo = app.state.manage_activation_plans.create(
        ActivationPlanValues(
            name="组合包", amount_minor=5000, currency="CNY",
            duration_hours=2, plan_type="combo", quota=10,
        )
    )
    quota_plan = app.state.manage_activation_plans.create(
        ActivationPlanValues(
            name="次数包", amount_minor=1000, currency="CNY",
            duration_hours=0, plan_type="quota", quota=20,
        )
    )
    issued = app.state.manage_activation_codes.issue(combo.plan_id, 1)
    code = issued[0].plaintext
    app.state.activate_device.execute(code, DEVICE)

    order, _ = app.state.create_payment_order.execute(quota_plan.plan_id, code)
    app.state._gw.next_notify = {
        "out_trade_no": order.order_id,
        "trade_state": "SUCCESS",
        "amount": {"total": quota_plan.values.amount_minor},
    }
    app.state.handle_payment_callback.execute(b"{}", {})

    rec = app.state.manage_activation_codes.get_by_activation_code(code)
    assert rec.quota_total == 30
    assert rec.quota_remaining == 30
