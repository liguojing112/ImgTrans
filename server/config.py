from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping
import os
import re
from urllib.parse import urlsplit


class ServerSettingsError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ServerSettings:
    environment: str = "development"
    database_url: str = field(
        default="sqlite+pysqlite:///:memory:",
        repr=False,
    )
    host: str = "127.0.0.1"
    port: int = 8000
    log_level: str = "INFO"
    docs_enabled: bool = True
    client_config_ttl_seconds: int = 3600
    admin_token: str | None = field(default=None, repr=False)
    client_api_token: str | None = field(default=None, repr=False)
    translator_endpoint: str = (
        "https://api.cognitive.microsofttranslator.com/translate"
    )
    translator_key: str | None = field(default=None, repr=False)
    translator_region: str | None = None
    translator_timeout_seconds: float = 10.0
    object_storage_endpoint: str | None = None
    object_storage_region: str | None = None
    object_storage_bucket: str | None = None
    object_storage_access_key: str | None = field(default=None, repr=False)
    object_storage_secret_key: str | None = field(default=None, repr=False)
    model_download_url_ttl_seconds: int = 900
    activation_secret: str | None = field(default=None, repr=False)
    admin_username: str | None = None
    admin_password_hash: str | None = field(default=None, repr=False)
    admin_session_secret: str | None = field(default=None, repr=False)
    admin_session_ttl_seconds: int = 28_800

    @classmethod
    def from_env(
        cls, environ: Mapping[str, str] | None = None
    ) -> "ServerSettings":
        values = environ if environ is not None else os.environ
        environment = values.get("IMGTRANS_ENVIRONMENT", "development").strip()
        if not environment:
            raise ServerSettingsError("IMGTRANS_ENVIRONMENT cannot be empty")
        production = environment.lower() in {"production", "prod"}
        configured_database_url = values.get("IMGTRANS_DATABASE_URL")
        if production and configured_database_url is None:
            raise ServerSettingsError(
                "IMGTRANS_DATABASE_URL is required in production"
            )
        database_url = (
            configured_database_url or "sqlite+pysqlite:///:memory:"
        ).strip()
        if not database_url:
            raise ServerSettingsError("IMGTRANS_DATABASE_URL cannot be empty")
        if production and not database_url.startswith("postgresql+"):
            raise ServerSettingsError(
                "Production database must use a PostgreSQL driver"
            )
        host = values.get("IMGTRANS_SERVER_HOST", "127.0.0.1").strip()
        if not host:
            raise ServerSettingsError("IMGTRANS_SERVER_HOST cannot be empty")
        try:
            port = int(values.get("IMGTRANS_SERVER_PORT", "8000"))
        except ValueError as error:
            raise ServerSettingsError(
                "IMGTRANS_SERVER_PORT must be an integer"
            ) from error
        if not 1 <= port <= 65535:
            raise ServerSettingsError(
                "IMGTRANS_SERVER_PORT must be between 1 and 65535"
            )
        log_level = values.get("IMGTRANS_LOG_LEVEL", "INFO").strip().upper()
        if log_level not in {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}:
            raise ServerSettingsError("IMGTRANS_LOG_LEVEL is invalid")
        docs_enabled = _parse_bool(
            values.get("IMGTRANS_DOCS_ENABLED", "false" if production else "true"),
            "IMGTRANS_DOCS_ENABLED",
        )
        try:
            client_config_ttl_seconds = int(
                values.get("IMGTRANS_CLIENT_CONFIG_TTL_SECONDS", "3600")
            )
        except ValueError as error:
            raise ServerSettingsError(
                "IMGTRANS_CLIENT_CONFIG_TTL_SECONDS must be an integer"
            ) from error
        if not 60 <= client_config_ttl_seconds <= 86_400:
            raise ServerSettingsError(
                "IMGTRANS_CLIENT_CONFIG_TTL_SECONDS must be between 60 and 86400"
            )
        admin_token = values.get("IMGTRANS_ADMIN_TOKEN")
        if admin_token is not None:
            admin_token = admin_token.strip()
            if len(admin_token) < 16:
                raise ServerSettingsError(
                    "IMGTRANS_ADMIN_TOKEN must contain at least 16 characters"
                )
        if production and admin_token is not None:
            raise ServerSettingsError(
                "IMGTRANS_ADMIN_TOKEN is disabled in production; use the administrator console"
            )
        client_api_token = _optional_secret(
            values.get("IMGTRANS_CLIENT_API_TOKEN"),
            "IMGTRANS_CLIENT_API_TOKEN",
        )
        translator_key = _optional_secret(
            values.get("IMGTRANS_TRANSLATOR_KEY"),
            "IMGTRANS_TRANSLATOR_KEY",
        )
        translator_region = values.get("IMGTRANS_TRANSLATOR_REGION")
        if translator_region is not None:
            translator_region = translator_region.strip() or None
        translator_endpoint = values.get(
            "IMGTRANS_TRANSLATOR_ENDPOINT",
            "https://api.cognitive.microsofttranslator.com/translate",
        ).strip()
        parsed_endpoint = urlsplit(translator_endpoint)
        if (
            parsed_endpoint.scheme not in {"http", "https"}
            or not parsed_endpoint.netloc
            or parsed_endpoint.username
            or parsed_endpoint.password
            or parsed_endpoint.query
            or parsed_endpoint.fragment
            or not parsed_endpoint.path.rstrip("/").endswith("/translate")
        ):
            raise ServerSettingsError("IMGTRANS_TRANSLATOR_ENDPOINT is invalid")
        if production and parsed_endpoint.scheme != "https":
            raise ServerSettingsError(
                "Production translator endpoint must use HTTPS"
            )
        try:
            translator_timeout_seconds = float(
                values.get("IMGTRANS_TRANSLATOR_TIMEOUT_SECONDS", "10")
            )
        except ValueError as error:
            raise ServerSettingsError(
                "IMGTRANS_TRANSLATOR_TIMEOUT_SECONDS must be numeric"
            ) from error
        if not 1 <= translator_timeout_seconds <= 60:
            raise ServerSettingsError(
                "IMGTRANS_TRANSLATOR_TIMEOUT_SECONDS must be between 1 and 60"
            )
        object_storage_endpoint = _optional_url(
            values.get("IMGTRANS_OBJECT_STORAGE_ENDPOINT"),
            "IMGTRANS_OBJECT_STORAGE_ENDPOINT",
            require_https=production,
        )
        object_storage_region = values.get("IMGTRANS_OBJECT_STORAGE_REGION")
        if object_storage_region is not None:
            object_storage_region = object_storage_region.strip() or None
        object_storage_bucket = values.get("IMGTRANS_OBJECT_STORAGE_BUCKET")
        if object_storage_bucket is not None:
            object_storage_bucket = object_storage_bucket.strip() or None
        object_storage_access_key = _optional_secret(
            values.get("IMGTRANS_OBJECT_STORAGE_ACCESS_KEY"),
            "IMGTRANS_OBJECT_STORAGE_ACCESS_KEY",
        )
        object_storage_secret_key = _optional_secret(
            values.get("IMGTRANS_OBJECT_STORAGE_SECRET_KEY"),
            "IMGTRANS_OBJECT_STORAGE_SECRET_KEY",
        )
        storage_values = (
            object_storage_endpoint,
            object_storage_bucket,
            object_storage_access_key,
            object_storage_secret_key,
        )
        if any(storage_values) and not all(storage_values):
            raise ServerSettingsError(
                "Object storage endpoint, bucket and credentials must be configured together"
            )
        try:
            model_download_url_ttl_seconds = int(
                values.get("IMGTRANS_MODEL_DOWNLOAD_URL_TTL_SECONDS", "900")
            )
        except ValueError as error:
            raise ServerSettingsError(
                "IMGTRANS_MODEL_DOWNLOAD_URL_TTL_SECONDS must be an integer"
            ) from error
        if not 60 <= model_download_url_ttl_seconds <= 3600:
            raise ServerSettingsError(
                "IMGTRANS_MODEL_DOWNLOAD_URL_TTL_SECONDS must be between 60 and 3600"
            )
        activation_secret = values.get("IMGTRANS_ACTIVATION_SECRET")
        if activation_secret is not None:
            activation_secret = activation_secret.strip()
            if len(activation_secret) < 32:
                raise ServerSettingsError(
                    "IMGTRANS_ACTIVATION_SECRET must contain at least 32 characters"
                )
        admin_username = _optional_text(values.get("IMGTRANS_ADMIN_USERNAME"))
        admin_password_hash = _optional_text(
            values.get("IMGTRANS_ADMIN_PASSWORD_HASH")
        )
        admin_session_secret = _optional_text(
            values.get("IMGTRANS_ADMIN_SESSION_SECRET")
        )
        admin_console_values = (
            admin_username,
            admin_password_hash,
            admin_session_secret,
        )
        if any(admin_console_values) and not all(admin_console_values):
            raise ServerSettingsError(
                "Administrator username, password hash and session secret must be configured together"
            )
        if admin_username is not None and not re.fullmatch(
            r"[A-Za-z0-9._-]{1,64}", admin_username
        ):
            raise ServerSettingsError("IMGTRANS_ADMIN_USERNAME is invalid")
        if admin_password_hash is not None and not re.fullmatch(
            r"scrypt\$16384\$8\$1\$[A-Za-z0-9_-]{22}\$[A-Za-z0-9_-]{43}",
            admin_password_hash,
        ):
            raise ServerSettingsError("IMGTRANS_ADMIN_PASSWORD_HASH is invalid")
        if admin_session_secret is not None and len(admin_session_secret) < 32:
            raise ServerSettingsError(
                "IMGTRANS_ADMIN_SESSION_SECRET must contain at least 32 characters"
            )
        try:
            admin_session_ttl_seconds = int(
                values.get("IMGTRANS_ADMIN_SESSION_TTL_SECONDS", "28800")
            )
        except ValueError as error:
            raise ServerSettingsError(
                "IMGTRANS_ADMIN_SESSION_TTL_SECONDS must be an integer"
            ) from error
        if not 900 <= admin_session_ttl_seconds <= 86_400:
            raise ServerSettingsError(
                "IMGTRANS_ADMIN_SESSION_TTL_SECONDS must be between 900 and 86400"
            )
        return cls(
            environment=environment,
            database_url=database_url,
            host=host,
            port=port,
            log_level=log_level,
            docs_enabled=docs_enabled,
            client_config_ttl_seconds=client_config_ttl_seconds,
            admin_token=admin_token,
            client_api_token=client_api_token,
            translator_endpoint=translator_endpoint,
            translator_key=translator_key,
            translator_region=translator_region,
            translator_timeout_seconds=translator_timeout_seconds,
            object_storage_endpoint=object_storage_endpoint,
            object_storage_region=object_storage_region,
            object_storage_bucket=object_storage_bucket,
            object_storage_access_key=object_storage_access_key,
            object_storage_secret_key=object_storage_secret_key,
            model_download_url_ttl_seconds=model_download_url_ttl_seconds,
            activation_secret=activation_secret,
            admin_username=admin_username,
            admin_password_hash=admin_password_hash,
            admin_session_secret=admin_session_secret,
            admin_session_ttl_seconds=admin_session_ttl_seconds,
        )

    def public_summary(self) -> dict[str, str | int | bool]:
        return {
            "environment": self.environment,
            "host": self.host,
            "port": self.port,
            "log_level": self.log_level,
            "docs_enabled": self.docs_enabled,
            "client_config_ttl_seconds": self.client_config_ttl_seconds,
            "translator_configured": self.translator_key is not None,
            "object_storage_configured": self.object_storage_endpoint is not None,
            "activation_configured": self.activation_secret is not None,
            "admin_console_configured": self.admin_session_secret is not None,
        }


def _parse_bool(value: str, name: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ServerSettingsError(f"{name} must be a boolean")


def _optional_secret(value: str | None, name: str) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if len(value) < 16:
        raise ServerSettingsError(f"{name} must contain at least 16 characters")
    return value


def _optional_url(
    value: str | None,
    name: str,
    *,
    require_https: bool,
) -> str | None:
    if value is None:
        return None
    value = value.strip().rstrip("/")
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ServerSettingsError(f"{name} is invalid")
    if require_https and parsed.scheme != "https":
        raise ServerSettingsError(f"{name} must use HTTPS in production")
    return value


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip() or None
