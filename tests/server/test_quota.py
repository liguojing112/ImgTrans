from __future__ import annotations

import asyncio

import httpx

from server.app import create_app
from server.config import ServerSettings
from server.domain.activation import ActivationPlanValues
from server.infrastructure.database import Base, Database

ACTIVATION_SECRET = "test-activation-secret-1234567890abcdef"
DEVICE_A = "device-aaaaaaaaaaaaaaaa"
DEVICE_B = "device-bbbbbbbbbbbbbbbb"


def _app():
    database = Database("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(database.engine)
    settings = ServerSettings(environment="test", activation_secret=ACTIVATION_SECRET)
    return create_app(settings, database)


def _issue_and_activate(app, plan_id: int, device_id: str):
    issued = app.state.manage_activation_codes.issue(plan_id, 1)
    code = issued[0].plaintext
    grant = app.state.activate_device.execute(code, device_id)
    return code, grant


def _run(scenario):
    return asyncio.run(scenario())


def test_quota_plan_issues_code_with_quota() -> None:
    app = _app()
    plan = app.state.manage_activation_plans.create(
        ActivationPlanValues(
            name="100次包", amount_minor=5000, currency="CNY",
            duration_days=1, plan_type="quota", quota=100,
        )
    )
    code, grant = _issue_and_activate(app, plan.plan_id, DEVICE_A)
    assert grant.activation.quota_total == 100
    assert grant.activation.quota_remaining == 100


def test_consume_decrements_and_stops_at_zero() -> None:
    app = _app()
    plan = app.state.manage_activation_plans.create(
        ActivationPlanValues(
            name="3次包", amount_minor=300, currency="CNY",
            duration_days=1, plan_type="quota", quota=3,
        )
    )
    _code, grant = _issue_and_activate(app, plan.plan_id, DEVICE_A)
    token = grant.access_token
    assert app.state.manage_usage.get_usage(token) == (3, 3)

    consumed, remaining = app.state.manage_usage.consume(token)
    assert consumed and remaining == 2
    assert app.state.manage_usage.consume(token) == (True, 1)
    assert app.state.manage_usage.consume(token) == (True, 0)
    # 扣到 0 后不再扣
    assert app.state.manage_usage.consume(token) == (False, 0)
    # 用量记录 3 条
    assert len(app.state.manage_usage.list_usage()) == 3


def test_unbind_allows_rebind_and_keeps_quota() -> None:
    app = _app()
    plan = app.state.manage_activation_plans.create(
        ActivationPlanValues(
            name="5次包", amount_minor=500, currency="CNY",
            duration_days=1, plan_type="quota", quota=5,
        )
    )
    code, grant = _issue_and_activate(app, plan.plan_id, DEVICE_A)
    # 用掉 2 次
    app.state.manage_usage.consume(grant.access_token)
    app.state.manage_usage.consume(grant.access_token)

    # 解绑 → 换设备重新激活
    assert app.state.manage_activation_codes.unbind(code) is True
    grant2 = app.state.activate_device.execute(code, DEVICE_B)
    assert grant2.activation.quota_remaining == 3  # 保留剩余次数


def test_rebind_extends_duration() -> None:
    app = _app()
    plan = app.state.manage_activation_plans.create(
        ActivationPlanValues(
            name="30天", amount_minor=3000, currency="CNY", duration_days=30
        )
    )
    code, grant = _issue_and_activate(app, plan.plan_id, DEVICE_A)
    original_expiry = grant.activation.expires_at
    # 解绑 → 换设备重新激活 → 时长延续（不重置）
    app.state.manage_activation_codes.unbind(code)
    grant2 = app.state.activate_device.execute(code, DEVICE_B)
    assert grant2.activation.expires_at == original_expiry


def test_usage_api_and_unbind_endpoint() -> None:
    app = _app()
    plan = app.state.manage_activation_plans.create(
        ActivationPlanValues(
            name="2次包", amount_minor=200, currency="CNY",
            duration_days=1, plan_type="quota", quota=2,
        )
    )
    code, grant = _issue_and_activate(app, plan.plan_id, DEVICE_A)
    token = grant.access_token

    async def scenario():
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            headers = {"Authorization": f"Bearer {token}"}
            # 查询
            resp = await client.get("/v1/usage", headers=headers)
            assert resp.status_code == 200
            assert resp.json() == {"quota_total": 2, "quota_remaining": 2}
            # 扣减
            resp = await client.post("/v1/usage/consume", headers=headers)
            assert resp.json()["consumed"] is True
            assert resp.json()["quota_remaining"] == 1
            assert resp.json()["quota_total"] == 2
            # 解绑
            resp = await client.post(
                "/v1/activations/unbind", json={"activation_code": code}
            )
            assert resp.status_code == 200
            assert resp.json() == {"unbound": True}

    _run(scenario)


def test_payment_plans_include_type_and_quota() -> None:
    app = _app()
    app.state.manage_activation_plans.create(
        ActivationPlanValues(
            name="月卡", amount_minor=3000, currency="CNY", duration_days=30
        )
    )
    app.state.manage_activation_plans.create(
        ActivationPlanValues(
            name="100次包", amount_minor=5000, currency="CNY",
            duration_days=1, plan_type="quota", quota=100,
        )
    )

    async def scenario():
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            plans = (await client.get("/v1/payments/plans")).json()
            by_id = {p["plan_id"]: p for p in plans}
            duration = [p for p in plans if p["plan_type"] == "duration"]
            quota = [p for p in plans if p["plan_type"] == "quota"]
            assert len(duration) == 1 and duration[0]["duration_days"] == 30
            assert len(quota) == 1 and quota[0]["quota"] == 100

    _run(scenario)
