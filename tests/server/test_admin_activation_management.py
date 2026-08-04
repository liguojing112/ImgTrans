from __future__ import annotations

import asyncio
import os

# 避免测试在仓库生成密钥文件；用环境变量覆盖
os.environ["IMGTRANS_SETTINGS_ENCRYPTION_KEY"] = "test-settings-key-1234567890abcdefghijklmn"

from server.app import create_app
from server.config import ServerSettings
from server.domain.activation import ActivationConflict, ActivationPlanValues
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
            name="月卡", amount_minor=1990, currency="CNY", duration_days=30
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
            name="月卡", amount_minor=1990, currency="CNY", duration_days=30
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
            name="月卡", amount_minor=1990, currency="CNY", duration_days=30
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
            name="月卡", amount_minor=1990, currency="CNY", duration_days=30
        )
    )
    issued = app.state.manage_activation_codes.issue(plan.plan_id, 1)
    code_id = issued[0].activation.code_id
    assert app.state.manage_activation_codes.disable(code_id).disabled is True
    assert app.state.manage_activation_codes.enable(code_id).disabled is False


def test_delete_plan_refuses_when_codes_exist() -> None:
    app = _app()
    with_codes = app.state.manage_activation_plans.create(
        ActivationPlanValues(
            name="有码方案", amount_minor=1990, currency="CNY", duration_days=30
        )
    )
    app.state.manage_activation_codes.issue(with_codes.plan_id, 1)
    try:
        app.state.manage_activation_plans.delete(with_codes.plan_id)
        raise AssertionError("expected ActivationConflict")
    except ActivationConflict:
        pass

    empty = app.state.manage_activation_plans.create(
        ActivationPlanValues(
            name="空方案", amount_minor=990, currency="CNY", duration_days=30
        )
    )
    app.state.manage_activation_plans.delete(empty.plan_id)
    assert all(item.plan_id != empty.plan_id for item in app.state.manage_activation_plans.list_all())


def test_usage_page_lists_plaintext_and_search() -> None:
    app = _app()
    plan = app.state.manage_activation_plans.create(
        ActivationPlanValues(
            name="10次包", amount_minor=500, currency="CNY",
            duration_days=1, plan_type="quota", quota=10,
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
