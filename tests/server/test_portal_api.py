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
                    "image_url": "",
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


_PNG_DATA_URL = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def _delete_uploaded(image_url: str) -> None:
    from server.admin.portal_images import delete_portal_image

    delete_portal_image(image_url)


def test_admin_upload_image_stored_and_served() -> None:
    """后台上传图片：保存到站内目录，公开接口返回 /portal-assets/ 路径。"""

    async def scenario():
        app = _app()
        async with _client(app) as client:
            await _login(client)
            page = await client.get("/admin/portal")
            token = _csrf(page.text)
            response = await client.post(
                "/admin/portal",
                data={
                    "csrf_token": token,
                    "module_key": "wanxiang_note",
                    "title": "万象笔记",
                    "description": "",
                    "image_base64": _PNG_DATA_URL,
                    "link_url": "https://note.example.com/app",
                    "enabled": "1",
                },
                follow_redirects=False,
            )
            assert response.status_code == 303
            modules = (await client.get("/v1/portal-modules")).json()["modules"]
            image_url = modules[0]["image_url"]
            assert image_url.startswith("/portal-assets/portal-")
            try:
                asset = await client.get(image_url)
                assert asset.status_code == 200
                assert asset.content.startswith(b"\x89PNG")
            finally:
                _delete_uploaded(image_url)

    _run(scenario)


def test_admin_remove_image_clears_url() -> None:
    async def scenario():
        app = _app()
        app.state.portal_repository.upsert(
            PortalModule(
                "wanxiang_note",
                "万象笔记",
                "",
                "/portal-assets/portal-abc123.png",
                "https://note.example.com/app",
            )
        )
        async with _client(app) as client:
            await _login(client)
            page = await client.get("/admin/portal")
            token = _csrf(page.text)
            response = await client.post(
                "/admin/portal",
                data={
                    "csrf_token": token,
                    "module_key": "wanxiang_note",
                    "title": "万象笔记",
                    "remove_image": "1",
                    "link_url": "https://note.example.com/app",
                    "enabled": "1",
                },
                follow_redirects=False,
            )
            assert response.status_code == 303
            module = app.state.portal_repository.get("wanxiang_note")
            assert module is not None and module.image_url == ""

    _run(scenario)


def test_admin_upload_rejects_invalid_image() -> None:
    async def scenario():
        app = _app()
        async with _client(app) as client:
            await _login(client)
            page = await client.get("/admin/portal")
            token = _csrf(page.text)
            response = await client.post(
                "/admin/portal",
                data={
                    "csrf_token": token,
                    "module_key": "wanxiang_note",
                    "title": "万象笔记",
                    "image_base64": "data:image/png;base64,bm90LWFuLWltYWdl",
                    "enabled": "1",
                },
                follow_redirects=False,
            )
            assert response.status_code == 422

    _run(scenario)


def test_portal_module_allows_site_relative_image_path() -> None:
    module = PortalModule("k", "t", "", "/portal-assets/portal-x.png", "")
    assert module.image_url == "/portal-assets/portal-x.png"


def test_portal_images_dir_falls_back_when_unwritable(monkeypatch) -> None:
    """部署目录不可写时回退到临时目录，应用启动不崩溃。"""
    from pathlib import Path
    import tempfile

    import server.admin.portal_images as portal_images

    monkeypatch.setattr(
        portal_images, "_IMAGE_DIR", Path("Z:/no-such-drive/portal-images")
    )
    directory = portal_images.portal_images_dir()

    assert directory.is_dir()
    assert "imgtrans-portal-images" in str(directory)
    assert str(directory).startswith(tempfile.gettempdir())
