from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import httpx

from server.app import create_app
from server.config import ServerSettings
from server.infrastructure.activation_repository import ActivationCodeRecord
from server.infrastructure.database import Base, Database


ADMIN_TOKEN = "test-admin-token-123456"
ACTIVATION_SECRET = "test-activation-pepper-1234567890abcdef"
DEVICE_A = "device-fingerprint-a-1234567890"
DEVICE_B = "device-fingerprint-b-1234567890"


def _app():
    database = Database("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(database.engine)
    app = create_app(
        ServerSettings(
            environment="test",
            admin_token=ADMIN_TOKEN,
            activation_secret=ACTIVATION_SECRET,
        ),
        database,
    )
    return app


def _request(app, method: str, path: str, **kwargs) -> httpx.Response:
    async def execute() -> httpx.Response:
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.request(method, path, **kwargs)

    return asyncio.run(execute())


def _admin_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {ADMIN_TOKEN}"}


def _create_plan(app, **changes):
    payload = {
        "name": "30 天基础版",
        "amount_minor": 1990,
        "currency": "CNY",
        "duration_days": 30,
        "enabled": True,
        **changes,
    }
    response = _request(
        app,
        "POST",
        "/v1/admin/activation/plans",
        headers=_admin_headers(),
        json=payload,
    )
    assert response.status_code == 201, response.text
    return response.json()


def _issue_code(app, plan_id: int):
    response = _request(
        app,
        "POST",
        "/v1/admin/activation/codes",
        headers=_admin_headers(),
        json={"plan_id": plan_id, "count": 1},
    )
    assert response.status_code == 201, response.text
    return response.json()["codes"][0]


def _activate(app, code: str, device_id: str = DEVICE_A):
    return _request(
        app,
        "POST",
        "/v1/activations/validate",
        json={"activation_code": code, "device_id": device_id},
    )


def test_plan_amount_is_exact_integer_and_updates_do_not_change_issued_duration() -> None:
    app = _app()
    try:
        plan = _create_plan(app)
        issued = _issue_code(app, plan["plan_id"])
        assert issued["duration_days"] == 30
        updated = _request(
            app,
            "PUT",
            f"/v1/admin/activation/plans/{plan['plan_id']}",
            headers=_admin_headers(),
            json={
                "name": "90 天基础版",
                "amount_minor": 4990,
                "currency": "CNY",
                "duration_days": 90,
                "enabled": True,
            },
        )
        assert updated.status_code == 200
        assert updated.json()["amount_minor"] == 4990
        listed_codes = _request(
            app, "GET", "/v1/admin/activation/codes", headers=_admin_headers()
        ).json()["codes"]
        assert listed_codes[0]["duration_days"] == 30
        decimal = _request(
            app,
            "POST",
            "/v1/admin/activation/plans",
            headers=_admin_headers(),
            json={
                "name": "invalid",
                "amount_minor": 19.9,
                "currency": "CNY",
                "duration_days": 30,
            },
        )
        assert decimal.status_code == 422
    finally:
        app.state.database.close()


def test_plaintext_code_is_returned_once_and_never_stored_or_listed() -> None:
    app = _app()
    try:
        plan = _create_plan(app)
        response = _request(
            app,
            "POST",
            "/v1/admin/activation/codes",
            headers=_admin_headers(),
            json={"plan_id": plan["plan_id"], "count": 100},
        )
        assert response.status_code == 201
        assert response.headers["Cache-Control"] == "no-store"
        plaintext = [item["activation_code"] for item in response.json()["codes"]]
        assert len(plaintext) == len(set(plaintext)) == 100
        assert all(code.startswith("IT-") for code in plaintext)

        listed = _request(
            app, "GET", "/v1/admin/activation/codes", headers=_admin_headers()
        )
        assert "activation_code" not in listed.text
        with app.state.database.session() as session:
            records = session.query(ActivationCodeRecord).all()
            stored_values = "|".join(
                str(getattr(record, column.name))
                for record in records
                for column in ActivationCodeRecord.__table__.columns
            )
            assert all(code not in stored_values for code in plaintext)
            assert "activation_code" not in ActivationCodeRecord.__table__.columns
            assert all(record.device_digest is None for record in records)
    finally:
        app.state.database.close()


def test_first_activation_binds_one_device_and_device_token_authorizes_client_api() -> None:
    app = _app()
    try:
        plan = _create_plan(app)
        issued = _issue_code(app, plan["plan_id"])
        activated = _activate(app, issued["activation_code"])
        assert activated.status_code == 200
        payload = activated.json()
        assert payload["status"] == "active"
        assert payload["token_type"] == "Bearer"
        assert payload["access_token"].startswith("itd_")
        assert activated.headers["Cache-Control"] == "no-store"
        duration = datetime.fromisoformat(payload["expires_at"]) - datetime.fromisoformat(
            payload["activated_at"]
        )
        assert duration == timedelta(days=30)
        with app.state.database.session() as session:
            record = session.get(ActivationCodeRecord, issued["code_id"])
            assert record.device_digest != DEVICE_A
            assert record.token_digest != payload["access_token"]

        authorized = _request(
            app,
            "GET",
            "/v1/models/manifest?platform=windows&architecture=x86_64",
            headers={"Authorization": f"Bearer {payload['access_token']}"},
        )
        assert authorized.status_code == 200
        assert authorized.json()["models"] == []
        other_device = _activate(app, issued["activation_code"], DEVICE_B)
        assert other_device.status_code == 403
        assert issued["activation_code"] not in other_device.text
    finally:
        app.state.database.close()


def test_concurrent_different_devices_have_exactly_one_binding_winner() -> None:
    app = _app()
    try:
        code = _issue_code(app, _create_plan(app)["plan_id"])["activation_code"]
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(_activate, app, code, device)
                for device in (DEVICE_A, DEVICE_B)
            ]
        statuses = sorted(future.result().status_code for future in futures)
        assert statuses == [200, 403]
        listed = _request(
            app, "GET", "/v1/admin/activation/codes", headers=_admin_headers()
        ).json()["codes"]
        assert listed[0]["bound"] is True
    finally:
        app.state.database.close()


def test_disable_revokes_device_token_and_prevents_reactivation() -> None:
    app = _app()
    try:
        issued = _issue_code(app, _create_plan(app)["plan_id"])
        grant = _activate(app, issued["activation_code"]).json()
        disabled = _request(
            app,
            "POST",
            f"/v1/admin/activation/codes/{issued['code_id']}/disable",
            headers=_admin_headers(),
        )
        assert disabled.status_code == 200
        assert disabled.json()["status"] == "disabled"
        denied = _request(
            app,
            "GET",
            "/v1/models/manifest?platform=windows&architecture=x86_64",
            headers={"Authorization": f"Bearer {grant['access_token']}"},
        )
        assert denied.status_code == 401
        assert _activate(app, issued["activation_code"]).status_code == 403
    finally:
        app.state.database.close()


def test_expired_binding_rejects_code_and_device_token() -> None:
    app = _app()
    try:
        issued = _issue_code(app, _create_plan(app, duration_days=1)["plan_id"])
        grant = _activate(app, issued["activation_code"]).json()
        with app.state.database.session() as session:
            record = session.get(ActivationCodeRecord, issued["code_id"])
            record.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        assert _activate(app, issued["activation_code"]).status_code == 403
        denied = _request(
            app,
            "GET",
            "/v1/models/manifest?platform=windows&architecture=x86_64",
            headers={"Authorization": f"Bearer {grant['access_token']}"},
        )
        assert denied.status_code == 401
    finally:
        app.state.database.close()


def test_disabled_plan_blocks_new_codes_but_does_not_revoke_existing_code() -> None:
    app = _app()
    try:
        plan = _create_plan(app)
        issued = _issue_code(app, plan["plan_id"])
        disabled_plan = _request(
            app,
            "PUT",
            f"/v1/admin/activation/plans/{plan['plan_id']}",
            headers=_admin_headers(),
            json={**{key: plan[key] for key in ("name", "amount_minor", "currency", "duration_days")}, "enabled": False},
        )
        assert disabled_plan.status_code == 200
        blocked = _request(
            app,
            "POST",
            "/v1/admin/activation/codes",
            headers=_admin_headers(),
            json={"plan_id": plan["plan_id"], "count": 1},
        )
        assert blocked.status_code == 409
        assert _activate(app, issued["activation_code"]).status_code == 200
    finally:
        app.state.database.close()


def test_activation_service_defaults_closed_without_server_secret() -> None:
    database = Database("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(database.engine)
    app = create_app(ServerSettings(environment="test", admin_token=ADMIN_TOKEN), database)
    try:
        response = _activate(app, "IT-AAAA-BBBB-CCCC-DDDD-EEEE-FFFF-GGGG-HHHH")
        assert response.status_code == 503
    finally:
        database.close()
