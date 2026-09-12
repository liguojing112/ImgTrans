from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.application.activation import (
    ActivationCoordinator,
    CredentialStoreError,
)
from src.domain.activation import ActivationError, ActivationSession


class _MemoryCredentials:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def read(self, key: str) -> str | None:
        return self.values.get(key)

    def write(self, key: str, value: str) -> None:
        self.values[key] = value

    def delete(self, key: str) -> None:
        self.values.pop(key, None)


class _ActivationClient:
    def __init__(self, session: ActivationSession) -> None:
        self.session = session
        self.calls: list[tuple[str, str]] = []

    def activate(self, activation_code: str, device_id: str) -> ActivationSession:
        self.calls.append((activation_code, device_id))
        return self.session


def _session(token: str = "itd_fixture_device_token_123456") -> ActivationSession:
    now = datetime.now(timezone.utc)
    return ActivationSession(7, now, now + timedelta(days=30), token)


def test_activation_uses_stable_device_id_and_secure_session() -> None:
    credentials = _MemoryCredentials()
    client = _ActivationClient(_session())
    coordinator = ActivationCoordinator(
        client,
        credentials,
        "https://api.example.test",
    )

    activated = coordinator.activate(" it-abcd ")
    coordinator.activate("IT-EFGH")

    assert client.calls[0][0] == "IT-ABCD"
    assert client.calls[0][1] == client.calls[1][1]
    assert client.calls[0][1].startswith("imgtrans-")
    session = coordinator.current_session()
    assert session is not None
    assert session.code == "IT-EFGH"
    assert session.plan_id == activated.plan_id
    assert session.expires_at == activated.expires_at
    assert coordinator.access_token() == "itd_fixture_device_token_123456"
    assert "itd_fixture_device_token_123456" not in repr(activated)
    assert all("https" not in key for key in credentials.values)


def test_invalid_or_expired_secure_session_is_removed() -> None:
    credentials = _MemoryCredentials()
    coordinator = ActivationCoordinator(
        _ActivationClient(_session()),
        credentials,
        "https://api.example.test",
    )
    coordinator.activate("IT-ABCD")
    session_key = next(key for key in credentials.values if key.startswith("activation-session"))
    credentials.values[session_key] = "not-json"

    assert coordinator.current_session() is None
    assert session_key not in credentials.values


def test_secure_storage_failure_never_returns_unsaved_token() -> None:
    class _FailingCredentials(_MemoryCredentials):
        def write(self, key: str, value: str) -> None:
            del key, value
            raise CredentialStoreError("unavailable")

    coordinator = ActivationCoordinator(
        _ActivationClient(_session()),
        _FailingCredentials(),
        "https://api.example.test",
    )

    with pytest.raises(ActivationError) as captured:
        coordinator.activate("IT-ABCD")
    assert captured.value.code == "secure_storage_unavailable"
    assert "itd_fixture" not in str(captured.value)


def test_backend_scope_rejects_embedded_credentials() -> None:
    with pytest.raises(ValueError):
        ActivationCoordinator(
            _ActivationClient(_session()),
            _MemoryCredentials(),
            "https://user:secret@example.test",
        )



class _StatusClient:
    def __init__(self, session: ActivationSession, status: bool = True,
                 fail: bool = False) -> None:
        self.session = session
        self.status_result = status
        self.fail = fail
        self.status_calls: list[tuple[str, str]] = []

    def activate(self, activation_code: str, device_id: str) -> ActivationSession:
        return self.session

    def status(self, activation_code: str, device_id: str) -> bool:
        self.status_calls.append((activation_code, device_id))
        if self.fail:
            raise ActivationError(
                "activation_service_unavailable", "网络异常"
            )
        return self.status_result


def _verified_coordinator(**session_kwargs) -> ActivationCoordinator:
    return ActivationCoordinator(
        _StatusClient(_session(), status=session_kwargs.pop("status_result", True),
                      fail=session_kwargs.pop("status_fail", False)),
        _MemoryCredentials(),
        "https://api.example.test",
    )


def test_verify_active_keeps_credentials() -> None:
    credentials = _MemoryCredentials()
    client = _StatusClient(_session())
    coordinator = ActivationCoordinator(client, credentials, "https://api.example.test")
    coordinator.activate("IT-ABCD")
    assert coordinator.verify() == "active"
    assert client.status_calls[0][0] == "IT-ABCD"
    assert coordinator.current_session() is not None


def test_verify_unbound_clears_credentials() -> None:
    credentials = _MemoryCredentials()
    client = _StatusClient(_session(), status=False)
    coordinator = ActivationCoordinator(client, credentials, "https://api.example.test")
    coordinator.activate("IT-ABCD")
    assert coordinator.verify() == "inactive"
    assert coordinator.current_session() is None
    assert not any(key.startswith("activation-session") for key in credentials.values)


def test_verify_network_error_keeps_credentials() -> None:
    credentials = _MemoryCredentials()
    client = _StatusClient(_session(), fail=True)
    coordinator = ActivationCoordinator(client, credentials, "https://api.example.test")
    coordinator.activate("IT-ABCD")
    assert coordinator.verify() == "active"
    assert coordinator.current_session() is not None


def test_verify_without_session_returns_missing() -> None:
    credentials = _MemoryCredentials()
    coordinator = ActivationCoordinator(
        _StatusClient(_session()), credentials, "https://api.example.test"
    )
    assert coordinator.verify() == "missing"


def test_verify_expired_session_reports_expired_and_clears() -> None:
    credentials = _MemoryCredentials()
    client = _StatusClient(_expired_session())
    coordinator = ActivationCoordinator(client, credentials, "https://api.example.test")
    coordinator.activate("IT-ABCD")

    assert coordinator.verify() == "expired"
    assert coordinator.current_session() is None
    # 本地已过期时直接判定，不再打扰服务端
    assert client.status_calls == []


def test_verify_invalid_session_reports_inactive_and_clears() -> None:
    credentials = _MemoryCredentials()
    coordinator = ActivationCoordinator(
        _StatusClient(_session()), credentials, "https://api.example.test"
    )
    coordinator.activate("IT-ABCD")
    session_key = next(
        key for key in credentials.values if key.startswith("activation-session")
    )
    credentials.values[session_key] = "not-json"

    assert coordinator.verify() == "inactive"
    assert session_key not in credentials.values


def _expired_session() -> ActivationSession:
    now = datetime.now(timezone.utc)
    return ActivationSession(
        7, now - timedelta(hours=2), now - timedelta(hours=1), "itd_fixture_device_token_123456"
    )
