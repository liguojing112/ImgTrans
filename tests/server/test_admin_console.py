from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone

import httpx
from sqlalchemy import update

from server.admin.security import SESSION_COOKIE, hash_admin_password, verify_password
from server.app import create_app
from server.config import ServerSettings
from server.infrastructure.activation_repository import ActivationCodeRecord
from server.infrastructure.database import Base, Database
from server.infrastructure.payment_repository import SqlAlchemyPaymentRepository
from server.domain.activation import ActivationPlanValues
from server.domain.payment import PaymentOrder, PaymentStatus
from server.domain.translation import TranslationProviderItem


USERNAME = "admin"
PASSWORD = "correct-horse-battery-staple"
PASSWORD_HASH = hash_admin_password(PASSWORD)
SESSION_SECRET = "test-admin-session-secret-1234567890abcdef"
ADMIN_TOKEN = "test-admin-token-123456"
ACTIVATION_SECRET = "test-activation-secret-1234567890abcdef"
TRANSLATOR_KEY = "test-translator-key-123456"


def _app(*, configured: bool = True, environment: str = "test", provider=None):
    database = Database("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(database.engine)
    settings = ServerSettings(
        environment=environment,
        admin_token=ADMIN_TOKEN,
        activation_secret=ACTIVATION_SECRET,
        translator_key=TRANSLATOR_KEY,
        admin_username=USERNAME if configured else None,
        admin_password_hash=PASSWORD_HASH if configured else None,
        admin_session_secret=SESSION_SECRET if configured else None,
    )
    return create_app(settings, database, provider)


class _Provider:
    provider_id = "admin-test-provider"

    def __init__(self):
        self.calls = []

    def translate(self, texts, source_language, target_language, correlation_id):
        self.calls.append((texts, source_language, target_language, correlation_id))
        return (TranslationProviderItem(translated_text="连接检查"),)


def _run(scenario):
    return asyncio.run(scenario())


def _csrf(html: str, name: str = "csrf_token") -> str:
    match = re.search(rf'name="{name}" value="([^"]+)"', html)
    assert match is not None, html
    return match.group(1)


async def _login(client: httpx.AsyncClient) -> str:
    page = await client.get("/admin/login")
    assert page.status_code == 200
    token = _csrf(page.text)
    response = await client.post(
        "/admin/login",
        data={"csrf_token": token, "username": USERNAME, "password": PASSWORD},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["Location"] == "/admin"
    dashboard = await client.get("/admin")
    assert dashboard.status_code == 200
    assert dashboard.headers["Cache-Control"] == "no-store"
    assert "frame-ancestors 'none'" in dashboard.headers["Content-Security-Policy"]
    assert dashboard.headers["X-Frame-Options"] == "DENY"
    return _csrf(dashboard.text)


def test_password_hash_is_salted_and_verifies_without_embedding_password() -> None:
    another = hash_admin_password(PASSWORD)
    assert PASSWORD_HASH != another
    assert PASSWORD not in PASSWORD_HASH
    assert verify_password(PASSWORD, PASSWORD_HASH)
    assert not verify_password("wrong-password-value", PASSWORD_HASH)


def test_admin_pages_serve_browser_icons_without_top_brand_bar() -> None:
    app = _app()

    async def scenario():
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            page = await client.get("/admin/login")
            assert page.status_code == 200
            assert 'href="/admin/static/favicon.ico"' in page.text
            assert 'class="topbar"' not in page.text

            favicon = await client.get("/admin/static/favicon.ico")
            assert favicon.status_code == 200
            assert favicon.headers["content-type"] in {
                "image/vnd.microsoft.icon",
                "image/x-icon",
            }
            assert favicon.content

            logo = await client.get("/admin/static/imgtrans.png")
            assert logo.status_code == 200
            assert logo.headers["content-type"] == "image/png"
            assert logo.content.startswith(b"\x89PNG\r\n\x1a\n")

    try:
        _run(scenario)
    finally:
        app.state.database.close()


def test_account_permissions_use_grouped_checkbox_picker() -> None:
    app = _app()

    async def scenario():
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            await _login(client)
            page = await client.get("/admin/users")
            assert page.status_code == 200
            assert 'href="/admin/static/admin.css?v=4"' in page.text
            assert 'class="card user-create-card"' in page.text
            assert 'class="permission-picker"' in page.text
            assert 'class="permission-grid"' in page.text
            assert 'class="permission-option"' in page.text
            assert 'class="permission-check"' not in page.text
            assert 'name="perm_image_limits"' in page.text

    try:
        _run(scenario)
    finally:
        app.state.database.close()


def test_payment_orders_show_snapshots_and_filter_refunded_orders() -> None:
    app = _app()
    repository = SqlAlchemyPaymentRepository(app.state.database)
    plan = app.state.manage_activation_plans.create(
        ActivationPlanValues(
            name="退款测试套餐",
            amount_minor=5000,
            currency="CNY",
            duration_hours=24,
            plan_type="combo",
            quota=10,
        )
    )
    issued = app.state.manage_activation_codes.issue(plan.plan_id, 1)[0]
    for order_id in ("paid-payment-order", "refunded-payment-order"):
        repository.create(
            PaymentOrder(
                order_id=order_id,
            plan_id=plan.plan_id,
            amount_minor=5000,
            currency="CNY",
            status=PaymentStatus.PAID,
            code_id=issued.activation.code_id,
            activation_code=issued.plaintext,
            created_at=datetime.now(timezone.utc),
            plan_type="combo",
            )
        )
    repository.create(
        PaymentOrder(
            order_id="legacy-payment-order",
            plan_id=plan.plan_id,
            amount_minor=5000,
            currency="CNY",
            status=PaymentStatus.PAID,
            code_id=issued.activation.code_id,
            activation_code=None,
            created_at=datetime.now(timezone.utc),
            plan_type="combo",
        )
    )

    async def scenario():
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            csrf_token = await _login(client)
            page = await client.get("/admin/payments")
            assert page.text.count(f"<code>{issued.plaintext}</code>") == 3
            assert page.text.count(f'data-copy="{issued.plaintext}"') == 3
            delattr(app.state, "refund_payment_order")
            disabled = await client.post(
                f"/admin/activation/codes/{issued.activation.code_id}/disable",
                data={
                    "csrf_token": csrf_token,
                    "order_id": "refunded-payment-order",
                    "next": "/admin/payments",
                },
                follow_redirects=False,
            )
            assert disabled.status_code == 303
            assert repository.get("paid-payment-order").status is PaymentStatus.PAID
            assert repository.get("refunded-payment-order").status is PaymentStatus.REFUNDED
            response = await client.get(
                f"/admin/payments?activation_code={issued.plaintext}&status=refunded&amount=5000"
            )
            assert response.status_code == 200
            assert "序号" in response.text
            assert "组合包" in response.text
            assert "¥50.00" in response.text
            assert "已退款" in response.text
            assert issued.plaintext in response.text

    try:
        _run(scenario)
    finally:
        app.state.database.close()


def test_admin_console_defaults_closed_and_unauthenticated_pages_redirect() -> None:
    app = _app(configured=False)

    async def scenario():
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            assert (await client.get("/admin/login")).status_code == 503
            assert (await client.get("/admin")).status_code == 503

    try:
        _run(scenario)
    finally:
        app.state.database.close()


def test_login_requires_csrf_and_uses_protected_session_cookie() -> None:
    app = _app()

    async def scenario():
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            unauthenticated = await client.get("/admin", follow_redirects=False)
            assert unauthenticated.status_code == 303
            assert unauthenticated.headers["Location"] == "/admin/login"
            rejected = await client.post(
                "/admin/login",
                data={"csrf_token": "wrong", "username": USERNAME, "password": PASSWORD},
            )
            assert rejected.status_code == 403
            page = await client.get("/admin/login")
            wrong_password = await client.post(
                "/admin/login",
                data={
                    "csrf_token": _csrf(page.text),
                    "username": USERNAME,
                    "password": "incorrect-password",
                },
            )
            assert wrong_password.status_code == 401
            assert PASSWORD not in wrong_password.text
            page = await client.get("/admin/login")
            logged_in = await client.post(
                "/admin/login",
                data={
                    "csrf_token": _csrf(page.text),
                    "username": USERNAME,
                    "password": PASSWORD,
                },
                follow_redirects=False,
            )
            cookie = logged_in.headers["Set-Cookie"]
            assert f"{SESSION_COOKIE}=" in cookie
            assert "HttpOnly" in cookie
            assert "SameSite=strict" in cookie
            assert "Path=/admin" in cookie

    try:
        _run(scenario)
    finally:
        app.state.database.close()


def test_tampered_session_and_cross_session_csrf_are_rejected() -> None:
    app = _app()

    async def scenario():
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as first:
            first_csrf = await _login(first)
            first_cookie = first.cookies.get(SESSION_COOKIE)
            first.cookies.set(SESSION_COOKIE, first_cookie + "tampered", path="/admin")
            assert (await first.get("/admin", follow_redirects=False)).status_code == 303
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as second:
            await _login(second)
            rejected = await second.post(
                "/admin/image-limits/drafts",
                data={
                    "csrf_token": first_csrf,
                    "min_width": "10",
                    "min_height": "10",
                    "max_width": "100",
                    "max_height": "100",
                    "max_bytes": "1000",
                },
            )
            assert rejected.status_code == 403

    try:
        _run(scenario)
    finally:
        app.state.database.close()


def test_csrf_protected_write_is_audited_without_request_values() -> None:
    app = _app()

    async def scenario():
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            csrf = await _login(client)
            missing = await client.post(
                "/admin/image-limits/drafts",
                data={
                    "min_width": "123",
                    "min_height": "124",
                    "max_width": "9000",
                    "max_height": "9001",
                    "max_bytes": "200000",
                },
            )
            assert missing.status_code == 403
            created = await client.post(
                "/admin/image-limits/drafts",
                data={
                    "csrf_token": csrf,
                    "min_width": "123",
                    "min_height": "124",
                    "max_width": "9000",
                    "max_height": "9001",
                    "max_bytes": "200000",
                },
                follow_redirects=False,
            )
            assert created.status_code == 303
            page = await client.get("/admin/image-limits")
            assert "200000" in page.text
            events = app.state.audit_management.list_recent()
            resources = [event.resource for event in events]
            assert "/admin/image-limits/drafts" in resources
            serialized = "|".join(
                f"{event.actor}:{event.action}:{event.resource}:{event.correlation_id}"
                for event in events
            )
            assert "200000" not in serialized
            assert all(event.correlation_id for event in events)
            assert sum(resource == "/admin/image-limits/drafts" for resource in resources) == 1

    try:
        _run(scenario)
    finally:
        app.state.database.close()


def test_all_management_pages_render_and_secrets_are_not_exposed() -> None:
    app = _app()

    async def scenario():
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            csrf = await _login(client)
            for path in (
                "/admin/image-limits",
                "/admin/translation",
                "/admin/activation",
                "/admin/audit",
            ):
                page = await client.get(path)
                assert page.status_code == 200, path
                assert TRANSLATOR_KEY not in page.text
                assert ACTIVATION_SECRET not in page.text
                assert PASSWORD_HASH not in page.text
            plan = await client.post(
                "/admin/activation/plans",
                data={
                    "csrf_token": csrf,
                    "name": "<script>alert(1)</script>",
                    "amount_minor": "1990",
                    "currency": "CNY",
                    "duration_hours": "30",
                    "enabled": "true",
                },
                follow_redirects=False,
            )
            assert plan.status_code == 303
            activation_page = await client.get("/admin/activation")
            assert "<script>alert(1)</script>" not in activation_page.text
            assert "&lt;script&gt;alert(1)&lt;/script&gt;" in activation_page.text
            csrf = _csrf(activation_page.text)
            issued = await client.post(
                "/admin/activation/codes",
                data={"csrf_token": csrf, "plan_id": "1", "count": "1"},
            )
            # PRG：发码后 303 重定向，浏览器刷新/后退不会重复提交表单
            assert issued.status_code == 303
            assert issued.headers["location"] == "/admin/activation?issued=1"
            assert issued.headers["Cache-Control"] == "no-store"
            issued_page = await client.get(issued.headers["location"])
            assert "已生成 1 个激活码" in issued_page.text
            match = re.search(
                r"IT-(?:[A-HJ-NP-Z2-9]{4}-){7}[A-HJ-NP-Z2-9]{4}", issued_page.text
            )
            assert match is not None
            plaintext = match.group(0)
            later = await client.get("/admin/activation")
            audit = await client.get("/admin/audit")
            # 明文加密入库后，激活码记录区持久显示明文（供管理员核对/复制）
            assert plaintext in later.text
            assert plaintext not in audit.text
            assert "code_digest" not in later.text
            assert "token_digest" not in later.text

    try:
        _run(scenario)
    finally:
        app.state.database.close()


def test_issue_codes_result_page_is_not_replayable() -> None:
    """PRG 回归：刷新/重访发码结果页不得再发出激活码。"""
    app = _app()

    async def scenario():
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            csrf = await _login(client)
            await client.post(
                "/admin/activation/plans",
                data={
                    "csrf_token": csrf,
                    "name": "回归套餐",
                    "amount_minor": "10",
                    "currency": "CNY",
                    "duration_hours": "24",
                    "enabled": "true",
                },
                follow_redirects=False,
            )
            page = await client.get("/admin/activation")
            issued = await client.post(
                "/admin/activation/codes",
                data={"csrf_token": _csrf(page.text), "plan_id": "1", "count": "2"},
                follow_redirects=False,
            )
            assert issued.status_code == 303
            assert len(app.state.manage_activation_codes.list_all()) == 2
            # 用户刷新发码结果页（GET）多次，不得额外发码
            for _ in range(3):
                refreshed = await client.get(issued.headers["location"])
                assert refreshed.status_code == 200
                assert "已生成 2 个激活码" in refreshed.text
            assert len(app.state.manage_activation_codes.list_all()) == 2

    try:
        _run(scenario)
    finally:
        app.state.database.close()


def test_bearer_admin_api_write_is_audited_as_api_token() -> None:
    app = _app()

    async def scenario():
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.post(
                "/v1/admin/image-limits/drafts",
                headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
                json={
                    "min_width": 10,
                    "min_height": 10,
                    "max_width": 100,
                    "max_height": 100,
                    "max_bytes": 1000,
                },
            )
            assert response.status_code == 201
            event = app.state.audit_management.list_recent()[0]
            assert event.actor == "api-token"
            assert event.action == "post"
            assert event.resource == "/v1/admin/image-limits/drafts"
            assert event.status_code == 201

    try:
        _run(scenario)
    finally:
        app.state.database.close()


def test_audit_page_formats_utc_events_as_beijing_time() -> None:
    app = _app()
    app.state.audit_management._repository.record(
        actor="admin",
        action="get",
        resource="/admin/test",
        correlation_id="audit-timezone-test",
        status_code=200,
        occurred_at=datetime(2026, 8, 8, 3, 4, 5, tzinfo=timezone.utc),
    )

    async def scenario():
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            await _login(client)
            page = await client.get("/admin/audit")
            assert page.status_code == 200
            assert "时间（北京时间）" in page.text
            assert "2026-08-08 11:04:05" in page.text
            assert "2026-08-08 03:04:05" not in page.text

    try:
        _run(scenario)
    finally:
        app.state.database.close()


def test_activation_page_formats_binding_times_as_beijing_time() -> None:
    app = _app()

    async def scenario():
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            csrf = await _login(client)
            await client.post(
                "/admin/activation/plans",
                data={
                    "csrf_token": csrf,
                    "name": "时区校验套餐",
                    "amount_minor": "10",
                    "currency": "CNY",
                    "duration_hours": "24",
                    "enabled": "true",
                },
                follow_redirects=False,
            )
            page = await client.get("/admin/activation")
            csrf = _csrf(page.text)
            issued = await client.post(
                "/admin/activation/codes",
                data={"csrf_token": csrf, "plan_id": "1", "count": "1"},
                follow_redirects=False,
            )
            issued_page = await client.get(issued.headers["location"])
            match = re.search(
                r"IT-(?:[A-HJ-NP-Z2-9]{4}-){7}[A-HJ-NP-Z2-9]{4}", issued_page.text
            )
            assert match is not None
            code = app.state.manage_activation_codes.list_all(match.group(0))[0]
            with app.state.database.session() as session:
                session.execute(
                    update(ActivationCodeRecord)
                    .where(ActivationCodeRecord.code_id == code.code_id)
                    .values(
                        device_digest="timezone-test-device",
                        activated_at=datetime(2026, 8, 8, 3, 4, 5, tzinfo=timezone.utc),
                        expires_at=datetime(2026, 8, 9, 3, 4, 5, tzinfo=timezone.utc),
                    )
                )
            page = await client.get("/admin/activation")
            assert page.status_code == 200
            # UTC 03:04:05 应显示为北京时间 11:04:05
            assert "2026-08-08 11:04:05" in page.text
            assert "2026-08-09 11:04:05" in page.text
            assert "2026-08-08 03:04:05" not in page.text

    try:
        _run(scenario)
    finally:
        app.state.database.close()


def test_admin_plan_accepts_selected_promotion_dates_and_time_range() -> None:
    app = _app()

    async def scenario():
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            csrf = await _login(client)
            response = await client.post(
                "/admin/activation/plans",
                data={
                    "csrf_token": csrf,
                    "name": "限时套餐",
                    "amount_minor": "19.90",
                    "sale_amount_minor": "9.90",
                    "currency": "CNY",
                    "duration_hours": "30",
                    "sale_dates": "2026-08-10,2026-08-15,2026-08-10",
                    "sale_start_time": "18:00",
                    "sale_end_time": "20:00",
                    "enabled": "true",
                },
                follow_redirects=False,
            )
            assert response.status_code == 303
            plan = app.state.manage_activation_plans.list_all()[0]
            assert tuple(value.isoformat() for value in plan.values.sale_dates) == (
                "2026-08-10",
                "2026-08-15",
            )
            assert plan.values.sale_start_time.isoformat(timespec="minutes") == "18:00"
            assert plan.values.sale_end_time.isoformat(timespec="minutes") == "20:00"
            page = await client.get("/admin/activation")
            assert 'data-promotion-schedule' in page.text
            assert "2026-08-10,2026-08-15" in page.text

    try:
        _run(scenario)
    finally:
        app.state.database.close()


def test_production_login_cookie_is_secure() -> None:
    app = _app(environment="production")

    async def scenario():
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="https://testserver",
        ) as client:
            page = await client.get("/admin/login")
            response = await client.post(
                "/admin/login",
                data={
                    "csrf_token": _csrf(page.text),
                    "username": USERNAME,
                    "password": PASSWORD,
                },
                follow_redirects=False,
            )
            assert "Secure" in response.headers["Set-Cookie"]
            dashboard = await client.get("/admin")
            assert dashboard.headers["Strict-Transport-Security"].startswith(
                "max-age=31536000"
            )

    try:
        _run(scenario)
    finally:
        app.state.database.close()


def test_login_and_activation_endpoints_are_rate_limited() -> None:
    app = _app()

    async def scenario():
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            for _ in range(10):
                page = await client.get("/admin/login")
                response = await client.post(
                    "/admin/login",
                    data={
                        "csrf_token": _csrf(page.text),
                        "username": USERNAME,
                        "password": "incorrect-password",
                    },
                )
                assert response.status_code == 401
            page = await client.get("/admin/login")
            limited = await client.post(
                "/admin/login",
                data={
                    "csrf_token": _csrf(page.text),
                    "username": USERNAME,
                    "password": "incorrect-password",
                },
            )
            assert limited.status_code == 429
            assert limited.headers["Retry-After"] == "300"

            invalid_code = "IT-AAAA-BBBB-CCCC-DDDD-EEEE-FFFF-GGGG-HHHH"
            for _ in range(20):
                response = await client.post(
                    "/v1/activations/validate",
                    json={
                        "activation_code": invalid_code,
                        "device_id": "device-fingerprint-1234567890",
                    },
                )
                assert response.status_code == 403
            limited_activation = await client.post(
                "/v1/activations/validate",
                json={
                    "activation_code": invalid_code,
                    "device_id": "device-fingerprint-1234567890",
                },
            )
            assert limited_activation.status_code == 429
            assert limited_activation.headers["Retry-After"] == "60"

    try:
        _run(scenario)
    finally:
        app.state.database.close()


def test_invalid_admin_form_returns_domain_error_instead_of_internal_error() -> None:
    app = _app()

    async def scenario():
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            csrf = await _login(client)
            response = await client.post(
                "/admin/image-limits/drafts",
                data={
                    "csrf_token": csrf,
                    "min_width": "100",
                    "min_height": "10",
                    "max_width": "20",
                    "max_height": "100",
                    "max_bytes": "1000",
                },
            )
            assert response.status_code == 422
            assert response.json()["error"]["code"] == "domain_error"

    try:
        _run(scenario)
    finally:
        app.state.database.close()


def test_translation_connectivity_check_uses_fixed_text_and_exposes_no_result_text() -> None:
    provider = _Provider()
    app = _app(provider=provider)

    async def scenario():
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            csrf = await _login(client)
            response = await client.post(
                "/admin/translation/test",
                data={"csrf_token": csrf},
            )
            assert response.status_code == 200
            assert "连接成功（admin-test-provider）" in response.text
            assert "连接检查" not in response.text
            assert TRANSLATOR_KEY not in response.text
            assert provider.calls[0][0] == ("connection check",)
            assert provider.calls[0][1:3] == ("en", "zh-Hans")
            events = app.state.audit_management.list_recent()
            assert events[0].resource == "/admin/translation/test"

    try:
        _run(scenario)
    finally:
        app.state.database.close()


def test_plan_hide_toggle_hides_from_client_plan_list() -> None:
    app = _app()
    plan = app.state.manage_activation_plans.create(
        ActivationPlanValues(name="月卡", amount_minor=1990, currency="CNY", duration_hours=720)
    )

    def _plan_form(page_html: str, hidden: str) -> dict:
        return {
            "csrf_token": _csrf(page_html),
            "name": "月卡",
            "amount_minor": "19.90",
            "currency": "CNY",
            "duration_hours": "720",
            "plan_type": "duration",
            "quota": "0",
            "sale_amount_minor": "0",
            "sale_dates": "",
            "sale_start_time": "00:00",
            "sale_end_time": "23:59",
            "sale_ends_at": "",
            "benefits": "",
            "enabled": "true",
            "hidden": hidden,
        }

    async def scenario():
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            await _login(client)
            page = await client.get("/admin/activation")
            assert page.status_code == 200

            # 点击“隐藏”
            response = await client.post(
                f"/admin/activation/plans/{plan.plan_id}",
                data=_plan_form(page.text, "true"),
                follow_redirects=False,
            )
            assert response.status_code == 303
            assert app.state.manage_activation_plans.list_all()[0].values.hidden is True

            # 状态列显示“已隐藏”，客户端方案列表不再包含该方案
            page = await client.get("/admin/activation")
            assert "已隐藏" in page.text
            assert 'name="hidden" value="false"' in page.text
            plans = (await client.get("/v1/payments/plans")).json()
            assert all(p["plan_id"] != plan.plan_id for p in plans)

            # 点击“显示”恢复
            response = await client.post(
                f"/admin/activation/plans/{plan.plan_id}",
                data=_plan_form(page.text, "false"),
                follow_redirects=False,
            )
            assert response.status_code == 303
            assert app.state.manage_activation_plans.list_all()[0].values.hidden is False
            plans = (await client.get("/v1/payments/plans")).json()
            assert any(p["plan_id"] == plan.plan_id for p in plans)

    try:
        _run(scenario)
    finally:
        app.state.database.close()


def test_admin_unbind_code_clears_binding_and_keeps_quota() -> None:
    app = _app()
    plan = app.state.manage_activation_plans.create(
        ActivationPlanValues(
            name="10次包", amount_minor=500, currency="CNY",
            duration_hours=1, plan_type="quota", quota=10,
        )
    )
    issued = app.state.manage_activation_codes.issue(plan.plan_id, 1)
    grant = app.state.activate_device.execute(issued[0].plaintext, "device-aaaaaaaaaaaaaaaa")
    code_id = grant.activation.code_id

    async def scenario():
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            await _login(client)
            page = await client.get("/admin/activation")
            assert "/unbind" in page.text
            response = await client.post(
                f"/admin/activation/codes/{code_id}/unbind",
                data={"csrf_token": _csrf(page.text)},
                follow_redirects=False,
            )
            assert response.status_code == 303
            # 回到未绑定状态，次数保留，token 失效
            codes, total = app.state.manage_activation_codes.list_page(1, 50, "unbound", None)
            assert total == 1 and codes[0].code_id == code_id
            assert codes[0].quota_total == 10 and codes[0].quota_remaining == 10
            assert app.state.authorize_device_token.authorize(grant.access_token) is False

    try:
        _run(scenario)
    finally:
        app.state.database.close()
