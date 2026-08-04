"""第三方配置密钥加密 — Fernet。

密钥自动生成存服务器文件（0600）；可用环境变量 IMGTRANS_SETTINGS_ENCRYPTION_KEY 覆盖。
"""

from __future__ import annotations

import base64
import hashlib
import os
from pathlib import Path
import secrets

from cryptography.fernet import Fernet


ENV_KEY_NAME = "IMGTRANS_SETTINGS_ENCRYPTION_KEY"


class SecretsCipher:
    def __init__(self, key: bytes) -> None:
        self._fernet = Fernet(key)

    def encrypt(self, plaintext: str) -> str:
        return self._fernet.encrypt(plaintext.encode("utf-8")).decode("ascii")

    def decrypt(self, token: str) -> str:
        try:
            return self._fernet.decrypt(token.encode("ascii")).decode("utf-8")
        except Exception as error:
            raise ValueError("无法解密配置：加密密钥可能已更换") from error

    @classmethod
    def load(cls, key_path: Path) -> "SecretsCipher":
        return cls(_load_key(key_path))


def _load_key(key_path: Path) -> bytes:
    env_value = os.environ.get(ENV_KEY_NAME)
    if env_value:
        raw = hashlib.sha256(env_value.encode("utf-8")).digest()
    elif key_path.exists():
        raw = key_path.read_bytes()
        if len(raw) != 32:
            raise ValueError("配置加密密钥文件无效")
    else:
        raw = secrets.token_bytes(32)
        key_path.parent.mkdir(parents=True, exist_ok=True)
        key_path.write_bytes(raw)
        try:
            os.chmod(key_path, 0o600)
        except OSError:
            pass
    return base64.urlsafe_b64encode(raw)
