import pytest

from server.config import ServerSettings, ServerSettingsError
from server.admin.security import hash_admin_password


def test_settings_are_read_from_environment_without_exposing_database_url() -> None:
    settings = ServerSettings.from_env(
        {
            "IMGTRANS_ENVIRONMENT": "test",
            "IMGTRANS_DATABASE_URL": "postgresql+psycopg://user:secret@db/imgtrans",
            "IMGTRANS_SERVER_HOST": "0.0.0.0",
            "IMGTRANS_SERVER_PORT": "9123",
            "IMGTRANS_LOG_LEVEL": "warning",
            "IMGTRANS_DOCS_ENABLED": "false",
            "IMGTRANS_CLIENT_CONFIG_TTL_SECONDS": "600",
            "IMGTRANS_ADMIN_TOKEN": "test-admin-token-123456",
            "IMGTRANS_CLIENT_API_TOKEN": "test-client-token-123456",
            "IMGTRANS_TRANSLATOR_KEY": "test-translator-key-123456",
            "IMGTRANS_TRANSLATOR_REGION": "westus",
            "IMGTRANS_OBJECT_STORAGE_ENDPOINT": "https://storage.example.test",
            "IMGTRANS_OBJECT_STORAGE_REGION": "us-east-1",
            "IMGTRANS_OBJECT_STORAGE_BUCKET": "imgtrans-models",
            "IMGTRANS_OBJECT_STORAGE_ACCESS_KEY": "test-access-key-123456",
            "IMGTRANS_OBJECT_STORAGE_SECRET_KEY": "test-secret-key-123456",
            "IMGTRANS_MODEL_DOWNLOAD_URL_TTL_SECONDS": "600",
            "IMGTRANS_ACTIVATION_SECRET": "test-activation-secret-1234567890abcdef",
            "IMGTRANS_ADMIN_USERNAME": "admin.user",
            "IMGTRANS_ADMIN_PASSWORD_HASH": hash_admin_password(
                "correct-horse-battery-staple"
            ),
            "IMGTRANS_ADMIN_SESSION_SECRET": "test-admin-session-secret-1234567890abcdef",
            "IMGTRANS_ADMIN_SESSION_TTL_SECONDS": "3600",
        }
    )
    assert settings.database_url.endswith("@db/imgtrans")
    assert settings.port == 9123
    assert settings.log_level == "WARNING"
    assert not settings.docs_enabled
    with pytest.raises(ServerSettingsError):
        ServerSettings.from_env(
            {
                "IMGTRANS_ENVIRONMENT": "production",
                "IMGTRANS_DATABASE_URL": "postgresql+psycopg://user:pass@db/imgtrans",
                "IMGTRANS_ADMIN_TOKEN": "production-admin-token-123456",
            }
        )
    assert settings.client_config_ttl_seconds == 600
    assert settings.admin_token == "test-admin-token-123456"
    assert settings.client_api_token == "test-client-token-123456"
    assert settings.translator_key == "test-translator-key-123456"
    assert settings.translator_region == "westus"
    assert settings.object_storage_bucket == "imgtrans-models"
    assert settings.model_download_url_ttl_seconds == 600
    assert settings.activation_secret == "test-activation-secret-1234567890abcdef"
    assert settings.admin_username == "admin.user"
    assert settings.admin_session_ttl_seconds == 3600
    assert settings.public_summary()["admin_console_configured"] is True
    assert "database_url" not in settings.public_summary()
    assert "secret" not in str(settings.public_summary())
    assert "admin_token" not in settings.public_summary()
    assert "secret" not in repr(settings)
    assert settings.admin_token not in repr(settings)
    assert settings.client_api_token not in repr(settings)
    assert settings.translator_key not in repr(settings)
    assert settings.object_storage_access_key not in repr(settings)
    assert settings.object_storage_secret_key not in repr(settings)
    assert settings.activation_secret not in repr(settings)
    assert settings.admin_password_hash not in repr(settings)
    assert settings.admin_session_secret not in repr(settings)


@pytest.mark.parametrize(
    ("name", "value"),
    (
        ("IMGTRANS_SERVER_PORT", "0"),
        ("IMGTRANS_SERVER_PORT", "invalid"),
        ("IMGTRANS_LOG_LEVEL", "verbose"),
        ("IMGTRANS_DOCS_ENABLED", "maybe"),
    ),
)
def test_invalid_settings_fail_before_server_start(name: str, value: str) -> None:
    with pytest.raises(ServerSettingsError):
        ServerSettings.from_env({name: value})


def test_production_requires_postgresql_and_disables_docs_by_default() -> None:
    with pytest.raises(ServerSettingsError):
        ServerSettings.from_env({"IMGTRANS_ENVIRONMENT": "production"})
    with pytest.raises(ServerSettingsError):
        ServerSettings.from_env(
            {
                "IMGTRANS_ENVIRONMENT": "production",
                "IMGTRANS_DATABASE_URL": "sqlite+pysqlite:///:memory:",
            }
        )
    settings = ServerSettings.from_env(
        {
            "IMGTRANS_ENVIRONMENT": "production",
            "IMGTRANS_DATABASE_URL": "postgresql+psycopg://user:pass@db/imgtrans",
        }
    )
    assert not settings.docs_enabled


def test_partial_or_weak_admin_console_configuration_is_rejected() -> None:
    with pytest.raises(ServerSettingsError):
        ServerSettings.from_env({"IMGTRANS_ADMIN_USERNAME": "admin"})
    with pytest.raises(ServerSettingsError):
        ServerSettings.from_env(
            {
                "IMGTRANS_ADMIN_USERNAME": "admin",
                "IMGTRANS_ADMIN_PASSWORD_HASH": hash_admin_password(
                    "correct-horse-battery-staple"
                ),
                "IMGTRANS_ADMIN_SESSION_SECRET": "too-short",
            }
        )
