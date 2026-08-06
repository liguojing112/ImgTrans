from __future__ import annotations

import asyncio
import os
from pathlib import Path

import httpx

# 避免测试在仓库生成密钥文件；用环境变量覆盖
os.environ["IMGTRANS_SETTINGS_ENCRYPTION_KEY"] = "test-settings-encryption-key-1234567890"

from server.admin.security import hash_admin_password
from server.app import create_app
from server.application.service_settings import DEFAULT_WECHAT_NOTIFY_URL
from server.config import ServerSettings
from server.infrastructure.database import Base, Database
from server.infrastructure.secrets_cipher import SecretsCipher

ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "correct-horse-battery-staple"
ADMIN_PASSWORD_HASH = hash_admin_password(ADMIN_PASSWORD)
SESSION_SECRET = "test-admin-session-secret-1234567890abcdef"
ACTIVATION_SECRET = "test-activation-secret-1234567890abcdef"

WECHAT = {
    "wechat_appid": "wx1234567890abcdef",
    "wechat_mchid": "1900000111",
    "wechat_apiv3_key": "aA1Bb2Cc3Dd4Ee5Ff6Gg7Hh8Ii9Jj0Kk",
    "wechat_private_key": "-----BEGIN PRIVATE KEY-----\nMIIEvQ==\n-----END PRIVATE KEY-----",
    "wechat_serial_no": "1234567890ABCDEF",
    "wechat_platform_cert": "-----BEGIN PUBLIC KEY-----\nMIIBIjANBg==\n-----END PUBLIC KEY-----",
    "wechat_public_key_id": "PUB_KEY_ID_TEST0001",
    "wechat_notify_url": "https://imgtrans.rchtop.top/v1/payments/notify",
}


def _app():
    database = Database("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(database.engine)
    settings = ServerSettings(
        environment="test",
        admin_username=ADMIN_USERNAME,
        admin_password_hash=ADMIN_PASSWORD_HASH,
        admin_session_secret=SESSION_SECRET,
        activation_secret=ACTIVATION_SECRET,
    )
    return create_app(settings, database)


def _run(scenario):
    return asyncio.run(scenario())


def _csrf(html: str) -> str:
    import re

    match = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert match is not None
    return match.group(1)


async def _login(client: httpx.AsyncClient) -> str:
    page = await client.get("/admin/login")
    token = _csrf(page.text)
    resp = await client.post(
        "/admin/login",
        data={"csrf_token": token, "username": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    dashboard = await client.get("/admin")
    return _csrf(dashboard.text)


def test_cipher_roundtrip(tmp_path: Path) -> None:
    os.environ.pop("IMGTRANS_SETTINGS_ENCRYPTION_KEY", None)
    try:
        cipher = SecretsCipher.load(tmp_path / "key.bin")
        encrypted = cipher.encrypt("secret-value")
        assert encrypted != "secret-value"
        assert cipher.decrypt(encrypted) == "secret-value"
        assert (tmp_path / "key.bin").exists()
        # 权限 0600（仅 Unix 有效；Windows 无此语义）
        if os.name != "nt":
            mode = (tmp_path / "key.bin").stat().st_mode & 0o777
            assert mode == 0o600
    finally:
        os.environ["IMGTRANS_SETTINGS_ENCRYPTION_KEY"] = "test-settings-encryption-key-1234567890"


def test_save_wechat_no_plaintext_in_public() -> None:
    app = _app()
    manage = app.state.manage_service_settings
    public = manage.save_wechat(WECHAT)
    assert public["wechat_pay_configured"] is True
    assert public["wechat_apiv3_key_configured"] is True
    # 公开配置绝不含密钥明文
    text = str(public)
    assert "aA1Bb2Cc3" not in text
    assert "BEGIN PRIVATE KEY" not in text


def test_sensitive_field_blank_keeps_previous() -> None:
    app = _app()
    manage = app.state.manage_service_settings
    manage.save_wechat(WECHAT)
    # 提交空 apiv3_key → 保留原值
    partial = dict(WECHAT, wechat_apiv3_key="")
    manage.save_wechat(partial)
    loaded = manage.load_wechat_settings()
    assert loaded["apiv3_key"] == WECHAT["wechat_apiv3_key"]


def test_load_wechat_settings_decrypts_full() -> None:
    app = _app()
    manage = app.state.manage_service_settings
    manage.save_wechat(WECHAT)
    loaded = manage.load_wechat_settings()
    assert loaded["appid"] == WECHAT["wechat_appid"]
    assert loaded["mchid"] == WECHAT["wechat_mchid"]
    assert loaded["apiv3_key"] == WECHAT["wechat_apiv3_key"]
    assert loaded["private_key"] == WECHAT["wechat_private_key"]
    assert loaded["platform_cert"] == WECHAT["wechat_platform_cert"]
    assert loaded["public_key_id"] == WECHAT["wechat_public_key_id"]
    # 回调 URL 固定写死，忽略表单提交值
    assert loaded["notify_url"] == DEFAULT_WECHAT_NOTIFY_URL


def test_crlf_private_key_normalized_to_lf() -> None:
    app = _app()
    manage = app.state.manage_service_settings
    crlf = {
        **WECHAT,
        "wechat_private_key": (
            "-----BEGIN PRIVATE KEY-----\r\nMIIEvQ==\r\n-----END PRIVATE KEY-----"
        ),
        "wechat_platform_cert": (
            "-----BEGIN PUBLIC KEY-----\r\nMIIBIjANBg==\r\n-----END PUBLIC KEY-----"
        ),
    }
    manage.save_wechat(crlf)
    loaded = manage.load_wechat_settings()
    assert (
        loaded["private_key"]
        == "-----BEGIN PRIVATE KEY-----\nMIIEvQ==\n-----END PRIVATE KEY-----"
    )
    assert "\r" not in loaded["private_key"]
    assert "\r" not in loaded["platform_cert"]


def test_notify_url_is_fixed_and_ignores_submitted_value() -> None:
    app = _app()
    manage = app.state.manage_service_settings
    submitted = dict(WECHAT, wechat_notify_url="https://evil.example.com/notify")
    manage.save_wechat(submitted)
    public = manage.get_public()
    assert public["wechat_notify_url"] == DEFAULT_WECHAT_NOTIFY_URL
    assert "evil.example.com" not in public["wechat_notify_url"]
    loaded = manage.load_wechat_settings()
    assert loaded["notify_url"] == DEFAULT_WECHAT_NOTIFY_URL


def test_settings_page_super_only() -> None:
    app = _app()
    app.state.manage_service_settings.save_wechat(WECHAT)
    app.state.manage_admin_users.create_subuser(
        "kefu01", "customer-password-123", frozenset({"activation"})
    )

    async def scenario():
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        # 子账号：访问 /admin/settings 返回 403
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as sub:
            page = await sub.get("/admin/login")
            token = _csrf(page.text)
            resp = await sub.post(
                "/admin/login",
                data={"csrf_token": token, "username": "kefu01", "password": "customer-password-123"},
                follow_redirects=False,
            )
            assert resp.status_code == 303
            assert (await sub.get("/admin/settings")).status_code == 403

        # 超管：独立连接访问设置页 + 提交表单
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as admin:
            csrf = await _login(admin)
            page = await admin.get("/admin/settings")
            assert page.status_code == 200
            assert "aA1Bb2Cc3" not in page.text
            assert "BEGIN PRIVATE KEY" not in page.text
            assert "已配置" in page.text
            resp = await admin.post(
                "/admin/settings",
                data={**WECHAT, "csrf_token": csrf},
                follow_redirects=False,
            )
            assert resp.status_code == 303

    _run(scenario)


def test_plans_expose_wechat_pay_configured() -> None:
    from server.domain.activation import ActivationPlanValues

    app = _app()
    app.state.manage_activation_plans.create(
        ActivationPlanValues(
            name="monthly", amount_minor=3000, currency="CNY", duration_hours=30
        )
    )
    app.state.manage_service_settings.save_wechat(WECHAT)

    async def scenario():
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            plans = (await client.get("/v1/payments/plans")).json()
            assert isinstance(plans, list) and plans
            assert plans[0]["wechat_pay_configured"] is True

    _run(scenario)


def test_glm_settings_roundtrip() -> None:
    app = _app()
    manage = app.state.manage_service_settings
    manage.save_glm({"glm_api_key": "glm-test-key-123456", "glm_model": "glm-4v-flash"})
    loaded = manage.load_glm_settings()
    assert loaded["api_key"] == "glm-test-key-123456"
    assert loaded["model"] == "glm-4v-flash"


def test_glm_no_plaintext_in_public() -> None:
    app = _app()
    manage = app.state.manage_service_settings
    public = manage.save_glm({"glm_api_key": "glm-secret-key-789", "glm_model": "glm-4v"})
    assert public["glm_configured"] is True
    assert "glm-secret-key-789" not in str(public)


def test_glm_blank_keeps_previous() -> None:
    app = _app()
    manage = app.state.manage_service_settings
    manage.save_glm({"glm_api_key": "glm-secret-key-789", "glm_model": "glm-4v"})
    manage.save_glm({"glm_api_key": "", "glm_model": "glm-5v"})
    loaded = manage.load_glm_settings()
    assert loaded["api_key"] == "glm-secret-key-789"
    assert loaded["model"] == "glm-5v"
