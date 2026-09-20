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
            duration_hours=1, plan_type="quota", quota=100,
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
            duration_hours=1, plan_type="quota", quota=3,
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
            duration_hours=1, plan_type="quota", quota=5,
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
            name="30天", amount_minor=3000, currency="CNY", duration_hours=30
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
            duration_hours=1, plan_type="quota", quota=2,
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


def _plan_with_watermark(limit: int) -> ActivationPlanValues:
    return ActivationPlanValues(
        name="去水印套餐", amount_minor=3000, currency="CNY",
        duration_hours=24, plan_type="combo", quota=10,
        watermark_daily_limit=limit,
    )


def test_watermark_daily_limit_validation() -> None:
    import pytest

    from server.domain.activation import ActivationError

    with pytest.raises(ActivationError):
        ActivationPlanValues(
            name="x", amount_minor=1, currency="CNY",
            duration_hours=1, watermark_daily_limit=-1,
        )
    with pytest.raises(ActivationError):
        ActivationPlanValues(
            name="x", amount_minor=1, currency="CNY",
            duration_hours=1, watermark_daily_limit=1_000_001,
        )


def test_watermark_limit_follows_plan_live() -> None:
    from datetime import datetime, timezone

    from server.application.activation import ActivationSecretHasher
    from server.infrastructure.activation_repository import (
        SqlAlchemyActivationRepository,
    )

    app = _app()
    # 套餐初始不含去水印，存量激活码已签发
    plan = app.state.manage_activation_plans.create(
        ActivationPlanValues(
            name="月卡", amount_minor=3000, currency="CNY", duration_hours=24
        )
    )
    _code, grant = _issue_and_activate(app, plan.plan_id, DEVICE_A)
    assert grant.activation.watermark_daily_limit == 0
    repo = SqlAlchemyActivationRepository(app.state.database)
    digest = ActivationSecretHasher(ACTIVATION_SECRET).digest_token(
        grant.access_token
    )
    now = datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc)
    assert repo.get_watermark_usage(digest, now) == (0, 0, 0)
    # 后台在套餐页设置上限后，存量激活码立即生效
    updated = ActivationPlanValues(
        name="月卡", amount_minor=3000, currency="CNY", duration_hours=24,
        watermark_daily_limit=5,
    )
    app.state.manage_activation_plans.update(plan.plan_id, updated)
    assert repo.get_watermark_usage(digest, now) == (5, 0, 5)
    assert grant is not None  # 激活凭证本身无需变化


def test_consume_watermark_daily_cap_and_beijing_reset() -> None:
    from datetime import datetime, timedelta, timezone

    from server.application.activation import ActivationSecretHasher
    from server.infrastructure.activation_repository import (
        SqlAlchemyActivationRepository,
    )

    app = _app()
    plan = app.state.manage_activation_plans.create(_plan_with_watermark(5))
    _code, grant = _issue_and_activate(app, plan.plan_id, DEVICE_A)
    repo = SqlAlchemyActivationRepository(app.state.database)
    digest = ActivationSecretHasher(ACTIVATION_SECRET).digest_token(
        grant.access_token
    )
    day1 = datetime(2026, 9, 19, 15, 30, tzinfo=timezone.utc)  # 北京 23:30
    assert repo.get_watermark_usage(digest, day1) == (5, 0, 5)
    assert repo.consume_watermark(digest, 3, day1) == (True, 5, 3, 2)
    assert repo.consume_watermark(digest, 2, day1) == (True, 5, 5, 0)
    assert repo.consume_watermark(digest, 1, day1) == (False, 5, 5, 0)
    # UTC 仍是 9-19，北京时间已跨日（9-20 00:30）→ 计数清零
    day2 = day1 + timedelta(hours=1)
    assert repo.get_watermark_usage(digest, day2) == (5, 0, 5)
    assert repo.consume_watermark(digest, 1, day2) == (True, 5, 1, 4)
    # 上限 0（套餐不含）一律拒绝
    plain = app.state.manage_activation_plans.create(
        ActivationPlanValues(
            name="时长包2", amount_minor=100, currency="CNY", duration_hours=1
        )
    )
    _c3, grant3 = _issue_and_activate(app, plain.plan_id, DEVICE_B)
    digest3 = ActivationSecretHasher(ACTIVATION_SECRET).digest_token(
        grant3.access_token
    )
    assert repo.get_watermark_usage(digest3, day1) == (0, 0, 0)
    assert repo.consume_watermark(digest3, 1, day1) == (False, 0, 0, 0)


def test_watermark_usage_api() -> None:
    app = _app()
    plan = app.state.manage_activation_plans.create(_plan_with_watermark(5))
    _code, grant = _issue_and_activate(app, plan.plan_id, DEVICE_A)
    token = grant.access_token

    async def scenario():
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            headers = {"Authorization": f"Bearer {token}"}
            resp = await client.get("/v1/usage/watermark", headers=headers)
            assert resp.status_code == 200
            assert resp.json() == {
                "watermark_daily_limit": 5,
                "watermark_used_today": 0,
                "watermark_remaining": 5,
            }
            resp = await client.post(
                "/v1/usage/watermark/consume", headers=headers, json={"amount": 2}
            )
            assert resp.status_code == 200
            body = resp.json()
            assert body["consumed"] is True
            assert body["watermark_used_today"] == 2
            assert body["watermark_remaining"] == 3
            # 批量超过剩余 → 拒绝且不动计数
            resp = await client.post(
                "/v1/usage/watermark/consume", headers=headers, json={"amount": 4}
            )
            body = resp.json()
            assert body["consumed"] is False
            assert body["watermark_used_today"] == 2
            assert body["watermark_remaining"] == 3
            # 无 body → 默认扣 1
            resp = await client.post("/v1/usage/watermark/consume", headers=headers)
            body = resp.json()
            assert body["consumed"] is True
            assert body["watermark_remaining"] == 2

    _run(scenario)


def test_payment_plans_include_type_and_quota() -> None:
    app = _app()
    app.state.manage_activation_plans.create(
        ActivationPlanValues(
            name="月卡", amount_minor=3000, currency="CNY", duration_hours=30
        )
    )
    app.state.manage_activation_plans.create(
        ActivationPlanValues(
            name="100次包", amount_minor=5000, currency="CNY",
            duration_hours=1, plan_type="quota", quota=100,
        )
    )

    async def scenario():
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            plans = (await client.get("/v1/payments/plans")).json()
            by_id = {p["plan_id"]: p for p in plans}
            duration = [p for p in plans if p["plan_type"] == "duration"]
            quota = [p for p in plans if p["plan_type"] == "quota"]
            assert len(duration) == 1 and duration[0]["duration_hours"] == 30
            assert len(quota) == 1 and quota[0]["quota"] == 100

    _run(scenario)
