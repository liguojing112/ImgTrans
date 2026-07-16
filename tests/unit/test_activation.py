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
    assert coordinator.current_session() == activated
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

