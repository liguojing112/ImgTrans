from __future__ import annotations

import asyncio
import re

import httpx

from server.admin.security import SESSION_COOKIE, hash_admin_password, verify_password
from server.app import create_app
from server.config import ServerSettings
from server.infrastructure.database import Base, Database
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
                    "max_bytes": "9876543",
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
                    "max_bytes": "9876543",
                },
                follow_redirects=False,
            )
            assert created.status_code == 303
            page = await client.get("/admin/image-limits")
            assert "9876543" in page.text
            events = app.state.audit_management.list_recent()
            resources = [event.resource for event in events]
            assert "/admin/image-limits/drafts" in resources
            serialized = "|".join(
                f"{event.actor}:{event.action}:{event.resource}:{event.correlation_id}"
                for event in events
            )
            assert "9876543" not in serialized
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
                "/admin/models",
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
                    "duration_days": "30",
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
            assert issued.status_code == 200
            match = re.search(r"IT-(?:[A-HJ-NP-Z2-9]{4}-){7}[A-HJ-NP-Z2-9]{4}", issued.text)
            assert match is not None
            plaintext = match.group(0)
            assert issued.headers["Cache-Control"] == "no-store"
            later = await client.get("/admin/activation")
            audit = await client.get("/admin/audit")
            assert plaintext not in later.text
            assert plaintext not in audit.text
            assert "code_digest" not in later.text
            assert "token_digest" not in later.text

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
