"""Portal module API and admin console tests."""

import asyncio
import re

import httpx
import pytest

from server.admin.security import hash_admin_password
from server.app import create_app
from server.config import ServerSettings
from server.domain.portal import PortalError, PortalModule
from server.infrastructure.database import Base, Database

USERNAME = "admin"
PASSWORD = "correct-horse-battery-staple"
PASSWORD_HASH = hash_admin_password(PASSWORD)
SESSION_SECRET = "test-admin-session-secret-1234567890abcdef"
ADMIN_TOKEN = "test-admin-token-123456"


def _app():
    database = Database("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(database.engine)
    return create_app(
        ServerSettings(
            environment="test",
            admin_token=ADMIN_TOKEN,
            admin_username=USERNAME,
            admin_password_hash=PASSWORD_HASH,
            admin_session_secret=SESSION_SECRET,
        ),
        database,
    )


def _client(app) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


def _run(scenario):
    return asyncio.run(scenario())


def _csrf(html: str) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert match is not None, html
    return match.group(1)


async def _login(client: httpx.AsyncClient) -> None:
    page = await client.get("/admin/login")
    assert page.status_code == 200
    token = _csrf(page.text)
    response = await client.post(
        "/admin/login",
        data={"csrf_token": token, "username": USERNAME, "password": PASSWORD},
        follow_redirects=False,
    )
    assert response.status_code == 303


def test_portal_modules_empty_by_default() -> None:
    async def scenario():
        app = _app()
        async with _client(app) as client:
            response = await client.get("/v1/portal-modules")
            assert response.status_code == 200
            assert response.json() == {"modules": []}

    _run(scenario)


def test_admin_saves_portal_module_visible_to_clients() -> None:
    async def scenario():
        app = _app()
        async with _client(app) as client:
            await _login(client)
            page = await client.get("/admin/portal")
            assert page.status_code == 200
            token = _csrf(page.text)
            response = await client.post(
                "/admin/portal",
                data={
                    "csrf_token": token,
                    "module_key": "wanxiang_note",
                    "title": "万象笔记",
                    "description": "记录图文灵感",
                    "image_url": "https://cdn.example.com/note.png",
                    "link_url": "https://note.example.com/app",
                    "enabled": "1",
                },
                follow_redirects=False,
            )
            assert response.status_code == 303

            listing = await client.get("/v1/portal-modules")
            assert listing.status_code == 200
            assert listing.json()["modules"] == [
                {
                    "module_key": "wanxiang_note",
                    "title": "万象笔记",
                    "description": "记录图文灵感",
                    "image_url": "https://cdn.example.com/note.png",
                    "link_url": "https://note.example.com/app",
                }
            ]

    _run(scenario)


def test_disabled_module_hidden_from_clients() -> None:
    async def scenario():
        app = _app()
        app.state.portal_repository.upsert(
            PortalModule(
                "wanxiang_note",
                "万象笔记",
                "",
                "",
                "https://note.example.com/app",
                enabled=False,
            )
        )
        async with _client(app) as client:
            response = await client.get("/v1/portal-modules")
            assert response.json() == {"modules": []}

    _run(scenario)


def test_portal_module_rejects_non_http_urls() -> None:
    with pytest.raises(PortalError):
        PortalModule("k", "t", "", "ftp://x", "")
    with pytest.raises(PortalError):
        PortalModule("k", "t", "", "", "javascript:alert(1)")
    with pytest.raises(PortalError):
        PortalModule("", "t", "", "", "")
