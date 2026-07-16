from __future__ import annotations

import pytest

from src.application.activation import CredentialStoreError
from src.platform.credentials import (
    MacOSKeychainStore,
    UnavailableCredentialStore,
    WindowsCredentialStore,
    create_platform_credential_store,
)


class _Backend:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def read(self, key: str) -> str | None:
        return self.values.get(key)

    def write(self, key: str, value: str) -> None:
        self.values[key] = value

    def delete(self, key: str) -> None:
        self.values.pop(key, None)


@pytest.mark.parametrize("store_type", [WindowsCredentialStore, MacOSKeychainStore])
def test_platform_store_namespaces_records_and_delegates(store_type) -> None:
    backend = _Backend()
    store = store_type(backend)

    assert store.read("device-id-scope") is None
    store.write("device-id-scope", "safe-value")
    assert store.read("device-id-scope") == "safe-value"
    assert backend.values == {"ImgTrans/device-id-scope": "safe-value"}
    store.delete("device-id-scope")
    assert backend.values == {}


def test_platform_store_rejects_unsafe_keys_and_oversized_values() -> None:
    store = WindowsCredentialStore(_Backend())
    with pytest.raises(CredentialStoreError):
        store.write("../token", "value")
    with pytest.raises(CredentialStoreError):
        store.write("token", "x" * 4097)


def test_unsupported_platform_has_no_plaintext_fallback() -> None:
    store = create_platform_credential_store("Linux")
    assert isinstance(store, UnavailableCredentialStore)
    with pytest.raises(CredentialStoreError):
        store.write("token", "not-written")

