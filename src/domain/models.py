from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
from urllib.parse import urlsplit


class ModelDeliveryError(RuntimeError):
    pass


_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
SUPPORTED_MODEL_TARGETS = {
    ("windows", "x86_64"),
    ("macos", "arm64"),
}


@dataclass(frozen=True, slots=True)
class ModelManifestEntry:
    model_id: str
    version: str
    platform: str
    architecture: str
    filename: str
    object_version: str
    size_bytes: int
    sha256: str
    download_url: str
    download_url_expires_at: datetime

    def __post_init__(self) -> None:
        for value in (
            self.model_id,
            self.version,
            self.filename,
        ):
            if not _SAFE_NAME.fullmatch(value):
                raise ModelDeliveryError("模型清单包含不安全的名称")
        if (
            not self.object_version
            or len(self.object_version) > 256
            or any(ord(character) < 32 for character in self.object_version)
        ):
            raise ModelDeliveryError("模型对象版本无效")
        if (self.platform, self.architecture) not in SUPPORTED_MODEL_TARGETS:
            raise ModelDeliveryError("模型清单平台不受支持")
        if self.size_bytes <= 0:
            raise ModelDeliveryError("模型大小无效")
        if not re.fullmatch(r"[0-9a-f]{64}", self.sha256):
            raise ModelDeliveryError("模型哈希无效")
        if self.download_url_expires_at.tzinfo is None:
            raise ModelDeliveryError("模型下载地址缺少有效期时区")
        if self.download_url_expires_at <= datetime.now(timezone.utc):
            raise ModelDeliveryError("模型下载地址已过期")
        parsed_url = urlsplit(self.download_url)
        if (
            parsed_url.scheme not in {"http", "https"}
            or not parsed_url.netloc
            or parsed_url.username
            or parsed_url.password
        ):
            raise ModelDeliveryError("模型下载地址无效")


@dataclass(frozen=True, slots=True)
class InstalledModel:
    model_id: str
    version: str
    object_version: str
    sha256: str
    size_bytes: int
    path: str


@dataclass(frozen=True, slots=True)
class ModelUpdateItemResult:
    model_id: str
    version: str
    installed: bool
    error: str | None = None


@dataclass(frozen=True, slots=True)
class ModelUpdateResult:
    items: tuple[ModelUpdateItemResult, ...]

    @property
    def installed_count(self) -> int:
        return sum(item.installed for item in self.items)

    @property
    def failed_count(self) -> int:
        return sum(item.error is not None for item in self.items)
