"""Versioned image-limit API integration tests."""

import asyncio

import httpx

from server.app import create_app
from server.config import ServerSettings
from server.infrastructure.database import Base, Database


ADMIN_TOKEN = "test-admin-token-123456"
LIMITS = {
    "min_width": 80,
    "min_height": 90,
    "max_width": 9000,
    "max_height": 10000,
    "max_bytes": 40 * 1024 * 1024,
}


def _app():
    database = Database("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(database.engine)
    app = create_app(
        ServerSettings(
            environment="test",
            admin_token=ADMIN_TOKEN,
            client_config_ttl_seconds=600,
        ),
        database,
    )
    return app


def _request(app, method: str, path: str, **kwargs) -> httpx.Response:
    async def execute() -> httpx.Response:
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            return await client.request(method, path, **kwargs)

    return asyncio.run(execute())


def _admin_headers(token: str = ADMIN_TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_draft_publish_and_client_config_contract() -> None:
    app = _app()
    try:
        unavailable = _request(app, "GET", "/v1/client-config")
        assert unavailable.status_code == 503

        draft = _request(
            app,
            "POST",
            "/v1/admin/image-limits/drafts",
            headers=_admin_headers(),
            json=LIMITS,
        )
        assert draft.status_code == 201
        assert draft.json()["status"] == "draft"
        version = draft.json()["version"]

        published = _request(
            app,
            "POST",
            f"/v1/admin/image-limits/drafts/{version}/publish",
            headers=_admin_headers(),
        )
        assert published.status_code == 200
        assert published.json()["status"] == "published"

        client = _request(app, "GET", "/v1/client-config")
        assert client.status_code == 200
        assert client.json() == {
            "schema_version": 1,
            "config_version": version,
            "cache_ttl_seconds": 600,
            "image_limits": LIMITS,
        }
        assert client.headers["Cache-Control"] == "public, max-age=600"
        assert client.headers["ETag"] == f'W/"image-limits-{version}"'
    finally:
        app.state.database.close()


def test_second_publish_and_rollback_preserve_immutable_history() -> None:
    app = _app()
    try:
        first = _request(
            app,
            "POST",
            "/v1/admin/image-limits/drafts",
            headers=_admin_headers(),
            json=LIMITS,
        ).json()
        _request(
            app,
            "POST",
            f"/v1/admin/image-limits/drafts/{first['version']}/publish",
            headers=_admin_headers(),
        )
        changed = {**LIMITS, "max_width": 8000}
        second = _request(
            app,
            "POST",
            "/v1/admin/image-limits/drafts",
            headers=_admin_headers(),
            json=changed,
        ).json()
        _request(
            app,
            "POST",
            f"/v1/admin/image-limits/drafts/{second['version']}/publish",
            headers=_admin_headers(),
        )

        rollback = _request(
            app,
            "POST",
            f"/v1/admin/image-limits/versions/{first['version']}/rollback",
            headers=_admin_headers(),
        )
        assert rollback.status_code == 201
        assert rollback.json()["source_version"] == first["version"]
        assert rollback.json()["version"] > second["version"]
        assert rollback.json()["max_width"] == LIMITS["max_width"]

        versions = _request(
            app,
            "GET",
            "/v1/admin/image-limits/versions",
            headers=_admin_headers(),
        ).json()["versions"]
        assert [item["status"] for item in versions].count("published") == 1
        assert [item["status"] for item in versions].count("superseded") == 2
        assert versions[0]["version"] == rollback.json()["version"]
    finally:
        app.state.database.close()


def test_published_versions_cannot_be_edited_or_published_twice() -> None:
    app = _app()
    try:
        draft = _request(
            app,
            "POST",
            "/v1/admin/image-limits/drafts",
            headers=_admin_headers(),
            json=LIMITS,
        ).json()
        path = f"/v1/admin/image-limits/drafts/{draft['version']}/publish"
        assert _request(app, "POST", path, headers=_admin_headers()).status_code == 200
        assert _request(app, "POST", path, headers=_admin_headers()).status_code == 409
        assert (
            _request(
                app,
                "PUT",
                f"/v1/admin/image-limits/drafts/{draft['version']}",
                headers=_admin_headers(),
                json={**LIMITS, "max_width": 7000},
            ).status_code
            == 409
        )
    finally:
        app.state.database.close()


def test_admin_routes_require_configured_valid_bearer_token() -> None:
    database = Database("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(database.engine)
    app = create_app(ServerSettings(environment="test"), database)
    try:
        disabled = _request(
            app,
            "POST",
            "/v1/admin/image-limits/drafts",
            json=LIMITS,
        )
        assert disabled.status_code == 503
    finally:
        database.close()

    app = _app()
    try:
        rejected = _request(
            app,
            "POST",
            "/v1/admin/image-limits/drafts",
            headers=_admin_headers("wrong-token-value"),
            json=LIMITS,
        )
        assert rejected.status_code == 401
        assert rejected.headers["WWW-Authenticate"] == "Bearer"
        assert ADMIN_TOKEN not in rejected.text
    finally:
        app.state.database.close()


def test_invalid_limit_ranges_are_rejected_without_creating_a_version() -> None:
    app = _app()
    try:
        invalid = _request(
            app,
            "POST",
            "/v1/admin/image-limits/drafts",
            headers=_admin_headers(),
            json={**LIMITS, "min_width": 9001, "max_width": 9000},
        )
        assert invalid.status_code == 422
        listed = _request(
            app,
            "GET",
            "/v1/admin/image-limits/versions",
            headers=_admin_headers(),
        )
        assert listed.json() == {"versions": []}
    finally:
        app.state.database.close()
