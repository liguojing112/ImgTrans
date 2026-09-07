from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

import httpx

from server.admin.security import hash_admin_password
from server.api.payment import (
    CreateOrderRequest,
    admin_payment_router,
    payment_router,
)
from server.app import create_app
from server.application.activation import (
    ActivationSecretHasher,
    ManageActivationCodes,
    ManageActivationPlans,
)
from server.application.payment import (
    CreatePaymentOrder,
    GetPaymentOrder,
    HandlePaymentCallback,
    ListPaymentOrders,
)
from server.config import ServerSettings
from server.domain.activation import ActivationPlanValues
from server.domain.payment import PaymentConflict, PaymentOrder, PaymentStatus
from server.infrastructure.activation_repository import SqlAlchemyActivationRepository
from server.infrastructure.database import Base, Database
from server.infrastructure.payment_repository import SqlAlchemyPaymentRepository
from server.infrastructure.wechat_pay_gateway import WechatPayV3Gateway, UnavailableWechatGateway

ADMIN_TOKEN = "test-admin-token-123456"
ACTIVATION_SECRET = "test-activation-secret-1234567890abcdef"


class FakeGateway:
    """测试用假微信网关 — 记录下单、模拟回调明文。"""

    def __init__(self) -> None:
        self.orders: dict[str, dict] = {}
        self.next_notify: dict | None = None
        self.notify_calls = 0

    def native_prepay(self, order_id: str, amount_minor: int, description: str) -> str:
        self.orders[order_id] = {"amount_minor": amount_minor, "description": description}
        return f"weixin://wxpay/bizpayurl?pr={order_id}"

    def parse_notify(self, body: bytes, headers: dict[str, str]) -> dict:
        self.notify_calls += 1
        if self.next_notify is None:
            raise ValueError("no notify configured")
        return self.next_notify


def _app():
    database = Database("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(database.engine)
    settings = ServerSettings(
        environment="test",
        admin_token=ADMIN_TOKEN,
        activation_secret=ACTIVATION_SECRET,
    )
    app = create_app(settings, database)

    # 替换为 fake 微信网关，注入真实仓库
    order_repo = SqlAlchemyPaymentRepository(database)
    gateway = FakeGateway()
    app.state.create_payment_order = CreatePaymentOrder(
        gateway, app.state.manage_activation_plans, order_repo
    )
    app.state.handle_payment_callback = HandlePaymentCallback(
        gateway, order_repo, app.state.manage_activation_codes.issue
    )
    app.state.get_payment_order = GetPaymentOrder(order_repo)
    app.state.list_payment_orders = ListPaymentOrders(order_repo)
    app.state._fake_gateway = gateway
    app.state._order_repo = order_repo

    # 建一个可购套餐
    plan = app.state.manage_activation_plans.create(
        ActivationPlanValues(
            name="月卡", amount_minor=3000, currency="CNY", duration_hours=30
        )
    )
    app.state._plan_id = plan.plan_id
    return app


def _run(scenario):
    return asyncio.run(scenario())


def test_create_order_returns_code_url_and_persists() -> None:
    app = _app()

    async def scenario():
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            resp = await client.post(
                "/v1/payments/orders", json={"plan_id": app.state._plan_id}
            )
            assert resp.status_code == 201
            body = resp.json()
            assert body["order_id"]
            assert body["code_url"].startswith("weixin://")
            assert body["amount_minor"] == 3000
            # 订单已落库 created
            assert (
                app.state._order_repo.get(body["order_id"]).status
                == PaymentStatus.CREATED
            )

    _run(scenario)


def test_create_order_rejects_disabled_plan() -> None:
    app = _app()
    plan_id = app.state._plan_id
    # 停用套餐
    app.state.manage_activation_plans.update(
        plan_id,
        ActivationPlanValues(
            name="月卡", amount_minor=3000, currency="CNY", duration_hours=30, enabled=False
        ),
    )

    async def scenario():
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            resp = await client.post(
                "/v1/payments/orders", json={"plan_id": plan_id}
            )
            assert resp.status_code == 409

    _run(scenario)


def test_callback_marks_paid_and_issues_code() -> None:
    app = _app()

    async def scenario():
        order_id = app.state.create_payment_order.execute(app.state._plan_id)[0].order_id
        gateway = app.state._fake_gateway
        gateway.next_notify = {
            "out_trade_no": order_id,
            "trade_state": "SUCCESS",
            "amount": {"total": 3000},
        }
        handler = app.state.handle_payment_callback
        handler.execute(b"{}", {})
        order = app.state.get_payment_order.execute(order_id)
        assert order.status == PaymentStatus.PAID
        assert order.code_id
        assert order.activation_code
        assert order.activation_code.startswith("IT-")

    _run(scenario)


def test_callback_is_idempotent() -> None:
    app = _app()

    async def scenario():
        order_id = app.state.create_payment_order.execute(app.state._plan_id)[0].order_id
        gateway = app.state._fake_gateway
        gateway.next_notify = {
            "out_trade_no": order_id,
            "trade_state": "SUCCESS",
            "amount": {"total": 3000},
        }
        handler = app.state.handle_payment_callback
        handler.execute(b"{}", {})
        first_code = app.state.get_payment_order.execute(order_id).activation_code
        # 重复回调（幂等）：不重复发码，激活码不变
        handler.execute(b"{}", {})
        order = app.state.get_payment_order.execute(order_id)
        assert order.activation_code == first_code

    _run(scenario)


def test_callback_rejects_amount_mismatch() -> None:
    app = _app()

    async def scenario():
        order_id = app.state.create_payment_order.execute(app.state._plan_id)[0].order_id
        gateway = app.state._fake_gateway
        gateway.next_notify = {
            "out_trade_no": order_id,
            "trade_state": "SUCCESS",
            "amount": {"total": 9999},
        }
        handler = app.state.handle_payment_callback
        try:
            handler.execute(b"{}", {})
            assert False, "金额不一致应抛错"
        except Exception:
            pass
        # 订单仍为 created，未发码
        order = app.state.get_payment_order.execute(order_id)
        assert order.status == PaymentStatus.CREATED

    _run(scenario)


def test_get_order_returns_code_when_paid() -> None:
    app = _app()

    async def scenario():
        order_id = app.state.create_payment_order.execute(app.state._plan_id)[0].order_id
        gateway = app.state._fake_gateway
        gateway.next_notify = {
            "out_trade_no": order_id,
            "trade_state": "SUCCESS",
            "amount": {"total": 3000},
        }
        app.state.handle_payment_callback.execute(b"{}", {})

        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            resp = await client.get(f"/v1/payments/orders/{order_id}")
            assert resp.status_code == 200
            body = resp.json()
            assert body["status"] == "paid"
            assert body["activation_code"].startswith("IT-")

    _run(scenario)


def test_admin_lists_orders() -> None:
    app = _app()

    async def scenario():
        order_id = app.state.create_payment_order.execute(app.state._plan_id)[0].order_id
        gateway = app.state._fake_gateway
        gateway.next_notify = {
            "out_trade_no": order_id,
            "trade_state": "SUCCESS",
            "amount": {"total": 3000},
        }
        app.state.handle_payment_callback.execute(b"{}", {})

        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            resp = await client.get(
                "/v1/admin/payment/orders", headers={"Authorization": f"Bearer {ADMIN_TOKEN}"}
            )
            assert resp.status_code == 200
            orders = resp.json()
            assert len(orders) == 1
            assert orders[0]["order_id"] == order_id
            assert orders[0]["status"] == "paid"

    _run(scenario)


def test_create_order_uses_sale_price_when_on_sale() -> None:
    from datetime import datetime, timedelta, timezone

    app = _app()
    plan = app.state.manage_activation_plans.create(
        ActivationPlanValues(
            name="促销月卡", amount_minor=3000, currency="CNY", duration_hours=30,
            sale_amount_minor=1500,
            sale_ends_at=datetime.now(timezone.utc) + timedelta(days=1),
            benefits="含30天图片翻译",
        )
    )
    order, code_url = app.state.create_payment_order.execute(plan.plan_id)
    assert order.amount_minor == 1500
    assert code_url


def test_create_order_uses_original_price_after_sale_ends() -> None:
    from datetime import datetime, timedelta, timezone

    app = _app()
    plan = app.state.manage_activation_plans.create(
        ActivationPlanValues(
            name="过期促销", amount_minor=3000, currency="CNY", duration_hours=30,
            sale_amount_minor=1500,
            sale_ends_at=datetime.now(timezone.utc) - timedelta(days=1),
        )
    )
    order, _ = app.state.create_payment_order.execute(plan.plan_id)
    assert order.amount_minor == 3000


def test_order_listing_persists_type_and_filters_historical_order_data() -> None:
    database = Database("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(database.engine)
    repository = SqlAlchemyPaymentRepository(database)
    now = datetime.now(timezone.utc)
    try:
        repository.create(
            PaymentOrder(
                order_id="duration-order",
                plan_id=1,
                amount_minor=3000,
                currency="CNY",
                status=PaymentStatus.PAID,
                code_id=None,
                activation_code="IT-DURATION",
                created_at=now,
                plan_type="duration",
            )
        )
        repository.create(
            PaymentOrder(
                order_id="combo-order",
                plan_id=999,
                amount_minor=5000,
                currency="CNY",
                status=PaymentStatus.CREATED,
                code_id=None,
                activation_code="IT-COMBO",
                created_at=now,
                plan_type="combo",
            )
        )

        orders, total = repository.list_page(
            activation_code="COMBO", status="created", amount_minor=5000
        )

        assert total == 1
        assert orders[0].order_id == "combo-order"
        assert orders[0].plan_type == "combo"
        assert repository.list_amounts() == ((3000, "CNY"), (5000, "CNY"))
    finally:
        database.close()


def test_refund_marks_only_the_selected_order_when_codes_are_shared() -> None:
    database = Database("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(database.engine)
    repository = SqlAlchemyPaymentRepository(database)
    now = datetime.now(timezone.utc)
    try:
        for order_id in ("first-order", "second-order"):
            repository.create(
                PaymentOrder(
                    order_id=order_id,
                    plan_id=1,
                    amount_minor=100,
                    currency="CNY",
                    status=PaymentStatus.PAID,
                    code_id="shared-code",
                    activation_code="IT-SHARED",
                    created_at=now,
                )
            )

        assert repository.mark_refunded("second-order", "shared-code") is True
        assert repository.get("first-order").status is PaymentStatus.PAID
        assert repository.get("second-order").status is PaymentStatus.REFUNDED
        refunded, total = repository.list_page(status="refunded")
        assert total == 1
        assert refunded[0].order_id == "second-order"
    finally:
        database.close()


def test_plans_api_includes_promotion() -> None:
    from datetime import datetime, timedelta, timezone

    app = _app()
    app.state.manage_activation_plans.create(
        ActivationPlanValues(
            name="促销月卡", amount_minor=3000, currency="CNY", duration_hours=30,
            sale_amount_minor=1500,
            sale_ends_at=datetime.now(timezone.utc) + timedelta(days=1),
            benefits="含30天图片翻译",
        )
    )

    async def scenario():
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            plans = (await client.get("/v1/payments/plans")).json()
            promo = next(p for p in plans if p["name"] == "促销月卡")
            assert promo["sale_amount_minor"] == 1500
            assert promo["is_on_sale"] is True
            assert promo["benefits"] == "含30天图片翻译"

    _run(scenario)


def test_plans_api_excludes_hidden_plans() -> None:
    app = _app()
    app.state.manage_activation_plans.create(
        ActivationPlanValues(name="显示方案", amount_minor=1000, currency="CNY", duration_hours=1)
    )
    app.state.manage_activation_plans.create(
        ActivationPlanValues(name="隐藏方案", amount_minor=2000, currency="CNY", duration_hours=2, hidden=True)
    )

    async def scenario():
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            plans = (await client.get("/v1/payments/plans")).json()
            names = [p["name"] for p in plans]
            assert "显示方案" in names
            assert "隐藏方案" not in names

    _run(scenario)


def test_selected_date_promotion_uses_beijing_time_window() -> None:
    from datetime import date, datetime, time, timezone

    values = ActivationPlanValues(
        name="指定日期促销",
        amount_minor=3000,
        currency="CNY",
        duration_hours=30,
        sale_amount_minor=1500,
        sale_dates=(date(2026, 8, 10), date(2026, 8, 15), date(2026, 8, 10)),
        sale_start_time=time(18, 0),
        sale_end_time=time(20, 0),
    )

    before = datetime(2026, 8, 10, 9, 59, 59, tzinfo=timezone.utc)
    active = datetime(2026, 8, 10, 10, 0, 0, tzinfo=timezone.utc)
    ended = datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc)
    wrong_date = datetime(2026, 8, 11, 10, 30, 0, tzinfo=timezone.utc)

    assert values.sale_dates == (date(2026, 8, 10), date(2026, 8, 15))
    assert values.is_on_sale(before) is False
    assert values.is_on_sale(active) is True
    assert values.active_sale_ends_at(active) == datetime(
        2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc
    )
    assert values.is_on_sale(ended) is False
    assert values.is_on_sale(wrong_date) is False


class _FakePayClient:
    """模拟 wechatpayv3 SDK：pay() 返回 (code, message) 元组。"""

    def __init__(self, code, message):
        self._code = code
        self._message = message

    def pay(self, **kwargs):
        return self._code, self._message


def test_native_prepay_parses_tuple_ok(monkeypatch) -> None:
    gateway = WechatPayV3Gateway(lambda: {"configured": True})
    monkeypatch.setattr(
        gateway, "_pay", lambda: _FakePayClient(200, '{"code_url":"weixin://wxpay/bizpayurl?pr=abc"}')
    )
    assert gateway.native_prepay("order1", 100, "测试") == "weixin://wxpay/bizpayurl?pr=abc"


def test_native_prepay_raises_wechat_error_with_detail(monkeypatch) -> None:
    gateway = WechatPayV3Gateway(lambda: {"configured": True})
    monkeypatch.setattr(
        gateway,
        "_pay",
        lambda: _FakePayClient(500, '{"code":"SYSTEM_ERROR","message":"未知错误"}'),
    )
    try:
        gateway.native_prepay("order1", 100, "测试")
        assert False, "微信错误应抛 PaymentConflict"
    except PaymentConflict as error:
        assert "500" in str(error)


def test_native_prepay_raises_when_no_code_url(monkeypatch) -> None:
    gateway = WechatPayV3Gateway(lambda: {"configured": True})
    monkeypatch.setattr(
        gateway, "_pay", lambda: _FakePayClient(200, '{"prepay_id":"wx123"}')
    )
    try:
        gateway.native_prepay("order1", 100, "测试")
        assert False, "缺 code_url 应抛 PaymentConflict"
    except PaymentConflict as error:
        assert "付款二维码" in str(error)


def test_parse_notify_flattens_resource(monkeypatch) -> None:
    gateway = WechatPayV3Gateway(lambda: {"configured": True})

    class _FakeCallbackClient:
        def callback(self, headers, body):
            return {
                "event_type": "TRANSACTION.SUCCESS",
                "resource": {
                    "out_trade_no": "order123",
                    "trade_state": "SUCCESS",
                    "amount": {"total": 1},
                },
            }

    monkeypatch.setattr(gateway, "_pay", lambda: _FakeCallbackClient())
    notify = gateway.parse_notify(b"{}", {})
    assert notify["out_trade_no"] == "order123"
    assert notify["trade_state"] == "SUCCESS"
    assert notify["amount"]["total"] == 1
