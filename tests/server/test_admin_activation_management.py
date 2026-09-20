from __future__ import annotations

import asyncio
import os
import re

# 避免测试在仓库生成密钥文件；用环境变量覆盖
os.environ["IMGTRANS_SETTINGS_ENCRYPTION_KEY"] = "test-settings-key-1234567890abcdefghijklmn"

import httpx

from server.admin.security import hash_admin_password
from server.app import create_app
from server.config import ServerSettings
from server.domain.activation import ActivationPlanValues
from server.infrastructure.database import Base, Database

ACTIVATION_SECRET = "test-activation-secret-1234567890abcdef"
DEVICE = "device-aaaaaaaaaaaaaaaa"


def _app():
    database = Database("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(database.engine)
    settings = ServerSettings(environment="test", activation_secret=ACTIVATION_SECRET)
    return create_app(settings, database)


def _run(scenario):
    return asyncio.run(scenario())


def test_issued_code_plaintext_roundtrips() -> None:
    app = _app()
    plan = app.state.manage_activation_plans.create(
        ActivationPlanValues(
            name="月卡", amount_minor=1990, currency="CNY", duration_hours=30
        )
    )
    issued = app.state.manage_activation_codes.issue(plan.plan_id, 2)
    plaintexts = {item.plaintext for item in issued}
    codes, total = app.state.manage_activation_codes.list_page(1, 50, None, None)
    assert total == 2
    assert {item.plaintext for item in codes} == plaintexts


def test_code_search_by_plaintext() -> None:
    app = _app()
    plan = app.state.manage_activation_plans.create(
        ActivationPlanValues(
            name="月卡", amount_minor=1990, currency="CNY", duration_hours=30
        )
    )
    issued = app.state.manage_activation_codes.issue(plan.plan_id, 1)
    plaintext = issued[0].plaintext
    codes, total = app.state.manage_activation_codes.list_page(1, 50, None, plaintext)
    assert total == 1
    assert codes[0].plaintext == plaintext
    # 搜不存在的码 → 0 条
    _, total = app.state.manage_activation_codes.list_page(1, 50, None, "IT-AAAA-BBBB-CCCC-DDDD-EEEE-FFFF-GGGG-HHHH")
    assert total == 0


def test_status_tabs_filter() -> None:
    app = _app()
    plan = app.state.manage_activation_plans.create(
        ActivationPlanValues(
            name="月卡", amount_minor=1990, currency="CNY", duration_hours=30
        )
    )
    issued = app.state.manage_activation_codes.issue(plan.plan_id, 3)
    bound_id = issued[0].activation.code_id
    disabled_id = issued[1].activation.code_id
    # 绑定 1 个、停用 1 个，剩 1 个未绑定
    app.state.activate_device.execute(issued[0].plaintext, DEVICE)
    app.state.manage_activation_codes.disable(disabled_id)

    codes, total = app.state.manage_activation_codes.list_page(1, 50, "bound", None)
    assert total == 1 and codes[0].code_id == bound_id
    _, total = app.state.manage_activation_codes.list_page(1, 50, "unbound", None)
    assert total == 1
    _, total = app.state.manage_activation_codes.list_page(1, 50, "disabled", None)
    assert total == 1
    _, total = app.state.manage_activation_codes.list_page(1, 50, None, None)
    assert total == 3


def test_enable_code_after_disable() -> None:
    app = _app()
    plan = app.state.manage_activation_plans.create(
        ActivationPlanValues(
            name="月卡", amount_minor=1990, currency="CNY", duration_hours=30
        )
    )
    issued = app.state.manage_activation_codes.issue(plan.plan_id, 1)
    code_id = issued[0].activation.code_id
    assert app.state.manage_activation_codes.disable(code_id).disabled is True
    assert app.state.manage_activation_codes.enable(code_id).disabled is False


def test_delete_plan_cascades_codes() -> None:
    app = _app()
    with_codes = app.state.manage_activation_plans.create(
        ActivationPlanValues(
            name="有码方案", amount_minor=1990, currency="CNY", duration_hours=30
        )
    )
    issued = app.state.manage_activation_codes.issue(with_codes.plan_id, 1)
    code_id = issued[0].activation.code_id
    app.state.manage_activation_plans.delete(with_codes.plan_id)
    # 方案删除后，其激活码一并被删
    codes, _ = app.state.manage_activation_codes.list_page(1, 50, None, None)
    assert all(item.code_id != code_id for item in codes)
    assert all(
        item.plan_id != with_codes.plan_id
        for item in app.state.manage_activation_plans.list_all()
    )

    empty = app.state.manage_activation_plans.create(
        ActivationPlanValues(
            name="空方案", amount_minor=990, currency="CNY", duration_hours=30
        )
    )
    app.state.manage_activation_plans.delete(empty.plan_id)
    assert all(item.plan_id != empty.plan_id for item in app.state.manage_activation_plans.list_all())


def test_usage_page_lists_plaintext_and_search() -> None:
    app = _app()
    plan = app.state.manage_activation_plans.create(
        ActivationPlanValues(
            name="10次包", amount_minor=500, currency="CNY",
            duration_hours=1, plan_type="quota", quota=10,
        )
    )
    issued = app.state.manage_activation_codes.issue(plan.plan_id, 1)
    plaintext = issued[0].plaintext
    grant = app.state.activate_device.execute(plaintext, DEVICE)
    app.state.manage_usage.consume(grant.access_token)
    app.state.manage_usage.consume(grant.access_token)

    records, total = app.state.manage_usage.list_page(1, 50, plaintext)
    assert total == 2
    assert all(record.plaintext == plaintext for record in records)
    # 搜不存在的码 → 0 条
    _, total = app.state.manage_usage.list_page(1, 50, "IT-XXXX-XXXX")
    assert total == 0


def test_renew_code_adds_duration_and_quota() -> None:
    app = _app()
    plan = app.state.manage_activation_plans.create(
        ActivationPlanValues(
            name="次数包", amount_minor=500, currency="CNY",
            duration_hours=1, plan_type="quota", quota=10,
        )
    )
    issued = app.state.manage_activation_codes.issue(plan.plan_id, 1)
    code_id = issued[0].activation.code_id
    before = app.state.manage_activation_codes.list_page(1, 50, None, None)[0][0]
    assert before.quota_total == 10

    app.state.manage_activation_codes.renew_by_code_id(code_id, 5, 20)

    after = app.state.manage_activation_codes.list_page(1, 50, None, None)[0][0]
    assert after.quota_total == 30, after.quota_total
    assert after.quota_remaining == 30


def _admin_app():
    database = Database("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(database.engine)
    settings = ServerSettings(
        environment="test",
        activation_secret=ACTIVATION_SECRET,
        admin_username="admin",
        admin_password_hash=hash_admin_password("correct-horse-battery-staple"),
        admin_session_secret="test-admin-session-secret-1234567890abcdef",
    )
    return create_app(settings, database)


def _csrf(html: str) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert match is not None
    return match.group(1)


async def _login(client: httpx.AsyncClient) -> None:
    page = await client.get("/admin/login")
    response = await client.post(
        "/admin/login",
        data={
            "csrf_token": _csrf(page.text),
            "username": "admin",
            "password": "correct-horse-battery-staple",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303


def test_admin_plan_form_persists_watermark_daily_limit() -> None:
    app = _admin_app()

    async def scenario():
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            await _login(client)
            page = await client.get("/admin/activation")
            assert "强化翻译（张/日）" in page.text
            create = await client.post(
                "/admin/activation/plans",
                data={
                    "csrf_token": _csrf(page.text),
                    "name": "水印测试套餐",
                    "plan_type": "combo",
                    "amount_minor": "30",
                    "currency": "CNY",
                    "duration_hours": "24",
                    "quota": "10",
                    "watermark_daily_limit": "5",
                    "enabled": "true",
                },
                follow_redirects=False,
            )
            assert create.status_code == 303
            plans = app.state.manage_activation_plans.list_all()
            plan = next(p for p in plans if p.values.name == "水印测试套餐")
            assert plan.values.watermark_daily_limit == 5
            # 页面回显可编辑输入
            page = await client.get("/admin/activation")
            assert (
                f'name="watermark_daily_limit" form="edit-{plan.plan_id}" '
                'type="number" min="0" max="1000000" value="5"'
            ) in page.text
            # 行内编辑改为 8
            update = await client.post(
                f"/admin/activation/plans/{plan.plan_id}",
                data={
                    "csrf_token": _csrf(page.text),
                    "name": "水印测试套餐",
                    "amount_minor": "30",
                    "currency": "CNY",
                    "duration_hours": "24",
                    "plan_type": "combo",
                    "quota": "10",
                    "watermark_daily_limit": "8",
                    "benefits": "",
                    "enabled": "true",
                    "hidden": "false",
                },
                follow_redirects=False,
            )
            assert update.status_code == 303
            plan = next(
                p for p in app.state.manage_activation_plans.list_all()
                if p.plan_id == plan.plan_id
            )
            assert plan.values.watermark_daily_limit == 8
            # 激活码按所属套餐实时取上限（存量码也生效）
            issued = app.state.manage_activation_codes.issue(plan.plan_id, 1)
            grant = app.state.activate_device.execute(
                issued[0].plaintext, "device-cccccccccccccccc"
            )
            assert grant.activation.watermark_daily_limit == 8
            # 套餐表再调整 → 该码额度同步变化
            plan2 = next(
                p for p in app.state.manage_activation_plans.list_all()
                if p.plan_id == plan.plan_id
            )
            from dataclasses import replace

            app.state.manage_activation_plans.update(
                plan.plan_id, replace(plan2.values, watermark_daily_limit=12)
            )
            assert (
                app.state.manage_usage.get_watermark(grant.access_token)[0]
                == 12
            )

    _run(scenario)
