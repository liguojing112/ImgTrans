from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from hashlib import sha256
import json
from threading import RLock
from typing import Protocol
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from src.domain.activation import ActivationError, ActivationSession


class CredentialStoreError(RuntimeError):
    pass


class CredentialStore(Protocol):
    def read(self, key: str) -> str | None: ...

    def write(self, key: str, value: str) -> None: ...

    def delete(self, key: str) -> None: ...


class ActivationClient(Protocol):
    def activate(self, activation_code: str, device_id: str) -> ActivationSession: ...


class ActivationCoordinator:
    def __init__(
        self,
        client: ActivationClient,
        credentials: CredentialStore,
        backend_url: str,
    ) -> None:
        self._client = client
        self._credentials = credentials
        self._scope = _backend_scope(backend_url)
        self._device_key = f"device-id-{self._scope}"
        self._session_key = f"activation-session-{self._scope}"
        self._lock = RLock()

    def activate(self, activation_code: str) -> ActivationSession:
        normalized = activation_code.strip().upper()
        if not normalized:
            raise ActivationError("activation_code_required", "请输入激活码")
        with self._lock:
            device_id = self._device_id()
            session = self._client.activate(normalized, device_id)
            try:
                self._credentials.write(
                    self._session_key,
                    json.dumps(
                        {
                            "schema_version": 1,
                            "plan_id": session.plan_id,
                            "activated_at": session.activated_at.isoformat(),
                            "expires_at": session.expires_at.isoformat(),
                            "access_token": session.access_token,
                        },
                        separators=(",", ":"),
                    ),
                )
            except CredentialStoreError as error:
                raise ActivationError(
                    "secure_storage_unavailable",
                    "系统安全凭据存储不可用，激活信息未保存",
                ) from error
            return session

    def current_session(self) -> ActivationSession | None:
        with self._lock:
            try:
                encoded = self._credentials.read(self._session_key)
            except CredentialStoreError as error:
                raise ActivationError(
                    "secure_storage_unavailable",
                    "无法读取系统安全凭据",
                ) from error
            if encoded is None:
                return None
            session = _decode_session(encoded)
            if session is None or not session.active:
                try:
                    self._credentials.delete(self._session_key)
                except CredentialStoreError:
                    pass
                return None
            return session

    def access_token(self) -> str | None:
        session = self.current_session()
        return session.access_token if session is not None else None

    def clear(self) -> None:
        with self._lock:
            try:
                self._credentials.delete(self._session_key)
            except CredentialStoreError as error:
                raise ActivationError(
                    "secure_storage_unavailable",
                    "无法清除系统安全凭据",
                ) from error

    def _device_id(self) -> str:
        try:
            existing = self._credentials.read(self._device_key)
            if existing:
                return existing
            value = f"imgtrans-{uuid4()}"
            self._credentials.write(self._device_key, value)
            return value
        except CredentialStoreError as error:
            raise ActivationError(
                "secure_storage_unavailable",
                "系统安全凭据存储不可用，无法建立设备身份",
            ) from error


def _backend_scope(base_url: str) -> str:
    parsed = urlsplit(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Backend URL must use HTTP or HTTPS")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Backend URL cannot contain credentials, query or fragment")
    normalized = urlunsplit(
        (parsed.scheme.lower(), parsed.netloc.lower(), parsed.path.rstrip("/"), "", "")
    )
    return sha256(normalized.encode("utf-8")).hexdigest()[:24]


def _decode_session(encoded: str) -> ActivationSession | None:
    try:
        payload = json.loads(encoded)
        if not isinstance(payload, Mapping) or set(payload) != {
            "schema_version",
            "plan_id",
            "activated_at",
            "expires_at",
            "access_token",
        }:
            return None
        if payload["schema_version"] != 1:
            return None
        session = ActivationSession(
            plan_id=payload["plan_id"],
            activated_at=datetime.fromisoformat(payload["activated_at"]),
            expires_at=datetime.fromisoformat(payload["expires_at"]),
            access_token=payload["access_token"],
        )
        if session.expires_at <= datetime.now(timezone.utc):
            return None
        return session
    except (ValueError, TypeError, KeyError, json.JSONDecodeError):
        return None

