from __future__ import annotations

import asyncio
import re

import httpx

from server.admin.security import hash_admin_password
from server.app import create_app
from server.config import ServerSettings
from server.infrastructure.database import Base, Database


USERNAME = "admin"
PASSWORD = "correct-horse-battery-staple"
PASSWORD_HASH = hash_admin_password(PASSWORD)
SESSION_SECRET = "test-admin-session-secret-1234567890abcdef"

SUB_USERNAME = "kefu01"
CHINESE_SUB_USERNAME = "客服01"
SUB_PASSWORD = "customer-password-123"


def _app() -> object:
    database = Database("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(database.engine)
    settings = ServerSettings(
        environment="test",
        admin_username=USERNAME,
        admin_password_hash=PASSWORD_HASH,
        admin_session_secret=SESSION_SECRET,
    )
    return create_app(settings, database)


def _run(scenario):
    return asyncio.run(scenario())


def _csrf(html: str, name: str = "csrf_token") -> str:
    match = re.search(rf'name="{name}" value="([^"]+)"', html)
    assert match is not None, html
    return match.group(1)


async def _login(client: httpx.AsyncClient, username: str, password: str) -> str:
    page = await client.get("/admin/login")
    assert page.status_code == 200
    token = _csrf(page.text)
    response = await client.post(
        "/admin/login",
        data={"csrf_token": token, "username": username, "password": password},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["Location"] == "/admin"
    dashboard = await client.get("/admin")
    assert dashboard.status_code == 200
    return _csrf(dashboard.text)


def test_seed_super_user_is_created_from_env() -> None:
    app = _app()
    users = app.state.manage_admin_users.list_all()
    assert len(users) == 1
    assert users[0].is_super
    assert users[0].username == USERNAME
    assert users[0].enabled


def test_super_admin_can_create_and_manage_subuser() -> None:
    app = _app()

    async def scenario():
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            csrf = await _login(client, USERNAME, PASSWORD)

            # 创建子账号（仅激活权限）
            create_page = await client.get("/admin/users")
            assert create_page.status_code == 200
            resp = await client.post(
                "/admin/users",
                data={
                    "csrf_token": csrf,
                    "username": SUB_USERNAME,
                    "password": SUB_PASSWORD,
                    "perm_activation": "true",
                },
                follow_redirects=False,
            )
            assert resp.status_code == 303

            users = app.state.manage_admin_users.list_all()
            assert len(users) == 2
            sub = next(u for u in users if u.username == SUB_USERNAME)
            assert sub.is_super is False
            assert sub.permissions == frozenset({"activation"})

    _run(scenario)


def test_super_admin_can_create_subuser_with_chinese_username() -> None:
    app = _app()

    async def scenario():
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            csrf = await _login(client, USERNAME, PASSWORD)
            response = await client.post(
                "/admin/users",
                data={
                    "csrf_token": csrf,
                    "username": CHINESE_SUB_USERNAME,
                    "password": SUB_PASSWORD,
                },
                follow_redirects=False,
            )
            assert response.status_code == 303
            assert any(
                user.username == CHINESE_SUB_USERNAME
                for user in app.state.manage_admin_users.list_all()
            )

    _run(scenario)


def test_subuser_login_and_permission_gating() -> None:
    app = _app()
    app.state.manage_admin_users.create_subuser(
        SUB_USERNAME, SUB_PASSWORD, frozenset({"activation"})
    )

    async def scenario():
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            await _login(client, SUB_USERNAME, SUB_PASSWORD)

            # 有 activation 权限 → 可访问
            assert (await client.get("/admin/activation")).status_code == 200
            # 无 image_limits / translation / audit → 403
            assert (await client.get("/admin/image-limits")).status_code == 403
            assert (await client.get("/admin/translation")).status_code == 403
            assert (await client.get("/admin/audit")).status_code == 403
            # 子账号不能进入账号管理
            assert (await client.get("/admin/users")).status_code == 403

            # 导航不包含无权限模块链接
            page = await client.get("/admin/activation")
            assert "/admin/users" not in page.text
            assert "修改密码" in page.text

    _run(scenario)


def test_super_admin_grants_and_revokes_permissions() -> None:
    app = _app()
    sub = app.state.manage_admin_users.create_subuser(
        SUB_USERNAME, SUB_PASSWORD, frozenset({"activation"})
    )

    async def scenario():
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            csrf = await _login(client, USERNAME, PASSWORD)

            # 授予 translation 权限
            resp = await client.post(
                f"/admin/users/{sub.user_id}/permissions",
                data={
                    "csrf_token": csrf,
                    "perm_activation": "true",
                    "perm_translation": "true",
                },
                follow_redirects=False,
            )
            assert resp.status_code == 303
            refreshed = app.state.manage_admin_users.list_all()
            target = next(u for u in refreshed if u.username == SUB_USERNAME)
            assert target.permissions == frozenset({"activation", "translation"})

            # 清空全部权限
            resp = await client.post(
                f"/admin/users/{sub.user_id}/permissions",
                data={"csrf_token": csrf},
                follow_redirects=False,
            )
            assert resp.status_code == 303
            refreshed = app.state.manage_admin_users.list_all()
            target = next(u for u in refreshed if u.username == SUB_USERNAME)
            assert target.permissions == frozenset()

    _run(scenario)


def test_super_admin_cannot_be_disabled() -> None:
    app = _app()
    super_user = app.state.manage_admin_users.list_all()[0]

    async def scenario():
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            csrf = await _login(client, USERNAME, PASSWORD)
            resp = await client.post(
                f"/admin/users/{super_user.user_id}/disable",
                data={"csrf_token": csrf},
                follow_redirects=False,
            )
            assert resp.status_code == 422
            # 超管仍可登录
            still = app.state.manage_admin_users.authenticate(USERNAME, PASSWORD)
            assert still is not None

    _run(scenario)


def test_disable_and_reenable_subuser() -> None:
    app = _app()
    sub = app.state.manage_admin_users.create_subuser(
        SUB_USERNAME, SUB_PASSWORD, frozenset({"activation"})
    )

    async def scenario():
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            csrf = await _login(client, USERNAME, PASSWORD)

            # 停用
            resp = await client.post(
                f"/admin/users/{sub.user_id}/disable",
                data={"csrf_token": csrf},
                follow_redirects=False,
            )
            assert resp.status_code == 303
            assert app.state.manage_admin_users.authenticate(SUB_USERNAME, SUB_PASSWORD) is None

            # 重新启用
            resp = await client.post(
                f"/admin/users/{sub.user_id}/enable",
                data={"csrf_token": csrf},
                follow_redirects=False,
            )
            assert resp.status_code == 303
            assert (
                app.state.manage_admin_users.authenticate(SUB_USERNAME, SUB_PASSWORD)
                is not None
            )

    _run(scenario)


def test_super_admin_resets_subuser_password() -> None:
    app = _app()
    sub = app.state.manage_admin_users.create_subuser(
        SUB_USERNAME, SUB_PASSWORD, frozenset({"activation"})
    )

    async def scenario():
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            csrf = await _login(client, USERNAME, PASSWORD)
            new_password = "new-customer-password-456"
            resp = await client.post(
                f"/admin/users/{sub.user_id}/reset-password",
                data={"csrf_token": csrf, "password": new_password},
                follow_redirects=False,
            )
            assert resp.status_code == 303
            assert (
                app.state.manage_admin_users.authenticate(SUB_USERNAME, SUB_PASSWORD)
                is None
            )
            assert (
                app.state.manage_admin_users.authenticate(SUB_USERNAME, new_password)
                is not None
            )

    _run(scenario)


def test_subuser_changes_own_password() -> None:
    app = _app()
    app.state.manage_admin_users.create_subuser(
        SUB_USERNAME, SUB_PASSWORD, frozenset({"activation"})
    )

    async def scenario():
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            csrf = await _login(client, SUB_USERNAME, SUB_PASSWORD)

            page = await client.get("/admin/change-password")
            assert page.status_code == 200
            token = _csrf(page.text)

            new_password = "my-new-own-password-789"
            resp = await client.post(
                "/admin/change-password",
                data={
                    "csrf_token": token,
                    "current_password": SUB_PASSWORD,
                    "new_password": new_password,
                },
                follow_redirects=False,
            )
            assert resp.status_code == 303
            assert (
                app.state.manage_admin_users.authenticate(SUB_USERNAME, SUB_PASSWORD)
                is None
            )
            assert (
                app.state.manage_admin_users.authenticate(SUB_USERNAME, new_password)
                is not None
            )

    _run(scenario)


def test_change_own_password_rejects_wrong_current() -> None:
    app = _app()

    async def scenario():
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            csrf = await _login(client, USERNAME, PASSWORD)
            page = await client.get("/admin/change-password")
            token = _csrf(page.text)
            resp = await client.post(
                "/admin/change-password",
                data={
                    "csrf_token": token,
                    "current_password": "wrong-current-password",
                    "new_password": "brand-new-password-111",
                },
                follow_redirects=False,
            )
            assert resp.status_code == 200  # 回到页面显示错误
            assert "当前密码不正确" in resp.text
            assert (
                app.state.manage_admin_users.authenticate(USERNAME, PASSWORD) is not None
            )

    _run(scenario)


def test_subuser_permissions_reflect_after_relogin() -> None:
    app = _app()
    sub = app.state.manage_admin_users.create_subuser(
        SUB_USERNAME, SUB_PASSWORD, frozenset({"activation"})
    )

    async def scenario():
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            await _login(client, SUB_USERNAME, SUB_PASSWORD)
            assert (await client.get("/admin/activation")).status_code == 200
            assert (await client.get("/admin/audit")).status_code == 403

            # 退出子账号，超管登录并勾选 audit 权限
            logout_page = await client.get("/admin/activation")
            token = _csrf(logout_page.text)
            await client.post("/admin/logout", data={"csrf_token": token})
            csrf = await _login(client, USERNAME, PASSWORD)
            await client.post(
                f"/admin/users/{sub.user_id}/permissions",
                data={"csrf_token": csrf, "perm_activation": "true", "perm_audit": "true"},
                follow_redirects=False,
            )
            await client.post("/admin/logout", data={"csrf_token": csrf})

            # 子账号重新登录后 audit 可用
            await _login(client, SUB_USERNAME, SUB_PASSWORD)
            assert (await client.get("/admin/audit")).status_code == 200

    _run(scenario)
