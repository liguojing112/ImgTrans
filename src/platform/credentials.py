from __future__ import annotations

from ctypes import POINTER, Structure, byref, cast, create_string_buffer, c_char_p
from ctypes import c_uint32, c_void_p, c_wchar_p, string_at
from ctypes import wintypes
import ctypes
import platform
import re
from typing import Protocol

from src.application.activation import CredentialStore, CredentialStoreError


_KEY_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,180}$")
_WINDOWS_NOT_FOUND = 1168
_MACOS_ITEM_NOT_FOUND = -25300


class _CredentialBackend(Protocol):
    def read(self, key: str) -> str | None: ...

    def write(self, key: str, value: str) -> None: ...

    def delete(self, key: str) -> None: ...


class UnavailableCredentialStore:
    def read(self, key: str) -> str | None:
        del key
        raise CredentialStoreError("Secure credential storage is unavailable")

    def write(self, key: str, value: str) -> None:
        del key, value
        raise CredentialStoreError("Secure credential storage is unavailable")

    def delete(self, key: str) -> None:
        del key
        raise CredentialStoreError("Secure credential storage is unavailable")


class WindowsCredentialStore:
    def __init__(self, backend: _CredentialBackend | None = None) -> None:
        self._backend = backend or _WindowsCredentialBackend()

    def read(self, key: str) -> str | None:
        return self._backend.read(_credential_key(key))

    def write(self, key: str, value: str) -> None:
        _validate_value(value)
        self._backend.write(_credential_key(key), value)

    def delete(self, key: str) -> None:
        self._backend.delete(_credential_key(key))


class MacOSKeychainStore:
    def __init__(self, backend: _CredentialBackend | None = None) -> None:
        self._backend = backend or _MacSecurityBackend()

    def read(self, key: str) -> str | None:
        return self._backend.read(_credential_key(key))

    def write(self, key: str, value: str) -> None:
        _validate_value(value)
        self._backend.write(_credential_key(key), value)

    def delete(self, key: str) -> None:
        self._backend.delete(_credential_key(key))


def create_platform_credential_store(
    system: str | None = None,
) -> CredentialStore:
    current = system or platform.system()
    try:
        if current == "Windows":
            return WindowsCredentialStore()
        if current == "Darwin":
            return MacOSKeychainStore()
    except CredentialStoreError:
        return UnavailableCredentialStore()
    return UnavailableCredentialStore()


class _CredentialW(Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", c_wchar_p),
        ("Comment", c_wchar_p),
        ("LastWritten", wintypes.FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", c_void_p),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", c_void_p),
        ("TargetAlias", c_wchar_p),
        ("UserName", c_wchar_p),
    ]


class _WindowsCredentialBackend:
    def __init__(self) -> None:
        if platform.system() != "Windows":
            raise CredentialStoreError("Windows Credential Manager is unavailable")
        self._advapi = ctypes.WinDLL("Advapi32.dll", use_last_error=True)
        self._advapi.CredReadW.argtypes = [
            c_wchar_p,
            wintypes.DWORD,
            wintypes.DWORD,
            POINTER(POINTER(_CredentialW)),
        ]
        self._advapi.CredReadW.restype = wintypes.BOOL
        self._advapi.CredWriteW.argtypes = [POINTER(_CredentialW), wintypes.DWORD]
        self._advapi.CredWriteW.restype = wintypes.BOOL
        self._advapi.CredDeleteW.argtypes = [c_wchar_p, wintypes.DWORD, wintypes.DWORD]
        self._advapi.CredDeleteW.restype = wintypes.BOOL
        self._advapi.CredFree.argtypes = [c_void_p]
        self._advapi.CredFree.restype = None

    def read(self, key: str) -> str | None:
        pointer = POINTER(_CredentialW)()
        if not self._advapi.CredReadW(key, 1, 0, byref(pointer)):
            if ctypes.get_last_error() == _WINDOWS_NOT_FOUND:
                return None
            raise CredentialStoreError("Windows Credential Manager read failed")
        try:
            record = pointer.contents
            encoded = string_at(record.CredentialBlob, record.CredentialBlobSize)
            return encoded.decode("utf-8")
        except (UnicodeDecodeError, ValueError) as error:
            raise CredentialStoreError("Stored Windows credential is invalid") from error
        finally:
            self._advapi.CredFree(pointer)

    def write(self, key: str, value: str) -> None:
        encoded = value.encode("utf-8")
        blob = create_string_buffer(encoded)
        record = _CredentialW()
        record.Type = 1
        record.TargetName = key
        record.CredentialBlobSize = len(encoded)
        record.CredentialBlob = cast(blob, c_void_p)
        record.Persist = 2
        record.UserName = "ImgTrans"
        if not self._advapi.CredWriteW(byref(record), 0):
            raise CredentialStoreError("Windows Credential Manager write failed")

    def delete(self, key: str) -> None:
        if self._advapi.CredDeleteW(key, 1, 0):
            return
        if ctypes.get_last_error() != _WINDOWS_NOT_FOUND:
            raise CredentialStoreError("Windows Credential Manager delete failed")


class _MacSecurityBackend:
    def __init__(self) -> None:
        if platform.system() != "Darwin":
            raise CredentialStoreError("macOS Keychain is unavailable")
        self._security = ctypes.CDLL(
            "/System/Library/Frameworks/Security.framework/Security"
        )
        self._core = ctypes.CDLL(
            "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"
        )
        self._configure_functions()

    def read(self, key: str) -> str | None:
        status, item, encoded = self._find(key)
        try:
            if status == _MACOS_ITEM_NOT_FOUND:
                return None
            self._check(status, "read")
            try:
                return encoded.decode("utf-8")
            except UnicodeDecodeError as error:
                raise CredentialStoreError("Stored macOS credential is invalid") from error
        finally:
            self._release(item)

    def write(self, key: str, value: str) -> None:
        status, item, _ = self._find(key)
        encoded = value.encode("utf-8")
        value_buffer = create_string_buffer(encoded)
        value_pointer = cast(value_buffer, c_void_p)
        try:
            if status == _MACOS_ITEM_NOT_FOUND:
                service, account = _mac_key(key)
                status = self._security.SecKeychainAddGenericPassword(
                    None,
                    len(service),
                    service,
                    len(account),
                    account,
                    len(encoded),
                    value_pointer,
                    None,
                )
            else:
                self._check(status, "read")
                status = self._security.SecKeychainItemModifyAttributesAndData(
                    item,
                    None,
                    len(encoded),
                    value_pointer,
                )
            self._check(status, "write")
        finally:
            self._release(item)

    def delete(self, key: str) -> None:
        status, item, _ = self._find(key)
        try:
            if status == _MACOS_ITEM_NOT_FOUND:
                return
            self._check(status, "read")
            self._check(self._security.SecKeychainItemDelete(item), "delete")
        finally:
            self._release(item)

    def _find(self, key: str) -> tuple[int, c_void_p, bytes]:
        service, account = _mac_key(key)
        length = c_uint32()
        data = c_void_p()
        item = c_void_p()
        status = self._security.SecKeychainFindGenericPassword(
            None,
            len(service),
            service,
            len(account),
            account,
            byref(length),
            byref(data),
            byref(item),
        )
        encoded = b""
        if status == 0 and data.value:
            encoded = string_at(data, length.value)
            self._security.SecKeychainItemFreeContent(None, data)
        return status, item, encoded

    def _release(self, item: c_void_p) -> None:
        if item.value:
            self._core.CFRelease(item)

    @staticmethod
    def _check(status: int, operation: str) -> None:
        if status != 0:
            raise CredentialStoreError(f"macOS Keychain {operation} failed")

    def _configure_functions(self) -> None:
        self._security.SecKeychainFindGenericPassword.argtypes = [
            c_void_p,
            c_uint32,
            c_char_p,
            c_uint32,
            c_char_p,
            POINTER(c_uint32),
            POINTER(c_void_p),
            POINTER(c_void_p),
        ]
        self._security.SecKeychainFindGenericPassword.restype = ctypes.c_int32
        self._security.SecKeychainAddGenericPassword.argtypes = [
            c_void_p,
            c_uint32,
            c_char_p,
            c_uint32,
            c_char_p,
            c_uint32,
            c_void_p,
            POINTER(c_void_p),
        ]
        self._security.SecKeychainAddGenericPassword.restype = ctypes.c_int32
        self._security.SecKeychainItemModifyAttributesAndData.argtypes = [
            c_void_p,
            c_void_p,
            c_uint32,
            c_void_p,
        ]
        self._security.SecKeychainItemModifyAttributesAndData.restype = ctypes.c_int32
        self._security.SecKeychainItemDelete.argtypes = [c_void_p]
        self._security.SecKeychainItemDelete.restype = ctypes.c_int32
        self._security.SecKeychainItemFreeContent.argtypes = [c_void_p, c_void_p]
        self._security.SecKeychainItemFreeContent.restype = ctypes.c_int32
        self._core.CFRelease.argtypes = [c_void_p]
        self._core.CFRelease.restype = None


def _credential_key(key: str) -> str:
    if not _KEY_PATTERN.fullmatch(key):
        raise CredentialStoreError("Credential key is invalid")
    return f"ImgTrans/{key}"


def _mac_key(key: str) -> tuple[bytes, bytes]:
    return b"com.imgtrans.desktop", key.encode("utf-8")


def _validate_value(value: str) -> None:
    if not value or len(value.encode("utf-8")) > 512:
        raise CredentialStoreError("Credential value is invalid")
