from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
import shutil


class StorageUnavailableError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class StorageCapacity:
    total: int
    used: int
    free: int


class StorageGuard:
    def __init__(
        self,
        usage_provider: Callable[[Path], object] = shutil.disk_usage,
    ) -> None:
        self._usage_provider = usage_provider

    def ensure_available(
        self,
        directory: Path,
        required_bytes: int,
        reserve_bytes: int = 0,
    ) -> StorageCapacity:
        if required_bytes < 0 or reserve_bytes < 0:
            raise ValueError("Storage byte requirements cannot be negative")
        probe = _existing_ancestor(directory)
        try:
            usage = self._usage_provider(probe)
            capacity = StorageCapacity(
                total=int(usage.total),
                used=int(usage.used),
                free=int(usage.free),
            )
        except (OSError, AttributeError, TypeError, ValueError) as error:
            raise StorageUnavailableError(
                "storage_unavailable",
                "无法检查存储空间，请检查目标磁盘是否可用",
            ) from error
        if capacity.free < required_bytes + reserve_bytes:
            raise StorageUnavailableError(
                "disk_full",
                "可用磁盘空间不足，请释放空间后重试",
            )
        return capacity


def _existing_ancestor(path: Path) -> Path:
    current = path.expanduser().resolve(strict=False)
    while not current.exists() and current != current.parent:
        current = current.parent
    if not current.is_dir():
        current = current.parent
    return current

