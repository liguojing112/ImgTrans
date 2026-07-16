from __future__ import annotations

from dataclasses import dataclass, replace
from threading import Lock
from typing import Protocol

from src.domain.image import ImageLimits


class ImageLimitsRemoteError(RuntimeError):
    pass


class ImageLimitsCacheError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ImageLimitsSnapshot:
    limits: ImageLimits
    cache_ttl_seconds: int

    def __post_init__(self) -> None:
        if self.limits.config_version is None or self.limits.config_version <= 0:
            raise ValueError("Remote image limits require a positive config version")
        if self.cache_ttl_seconds <= 0:
            raise ValueError("Cache TTL must be positive")


@dataclass(frozen=True, slots=True)
class ImageLimitsRefreshResult:
    limits: ImageLimits
    remote_applied: bool
    warning: str | None = None


class RemoteImageLimits(Protocol):
    def fetch(self) -> ImageLimitsSnapshot: ...


class ImageLimitsCache(Protocol):
    def load(self) -> ImageLimitsSnapshot | None: ...

    def save(self, snapshot: ImageLimitsSnapshot) -> None: ...


class CurrentImageLimits(Protocol):
    @property
    def current_limits(self) -> ImageLimits: ...


class ImageLimitsCoordinator:
    def __init__(
        self,
        cache: ImageLimitsCache,
        builtin: ImageLimits | None = None,
        remote: RemoteImageLimits | None = None,
    ) -> None:
        self._cache = cache
        self._builtin = builtin or ImageLimits()
        self._remote = remote
        self._lock = Lock()
        self._current = self._load_initial()

    @property
    def current_limits(self) -> ImageLimits:
        with self._lock:
            return self._current

    def refresh(self) -> ImageLimitsRefreshResult:
        if self._remote is None:
            return ImageLimitsRefreshResult(
                self.current_limits,
                False,
                "远程配置地址未设置",
            )
        try:
            snapshot = self._remote.fetch()
            self._cache.save(snapshot)
        except (ImageLimitsRemoteError, ImageLimitsCacheError, ValueError) as error:
            return ImageLimitsRefreshResult(
                self.current_limits,
                False,
                f"远程图片限制不可用：{error}",
            )
        remote_limits = replace(snapshot.limits, source="remote")
        with self._lock:
            self._current = remote_limits
        return ImageLimitsRefreshResult(remote_limits, True)

    def _load_initial(self) -> ImageLimits:
        try:
            snapshot = self._cache.load()
        except (ImageLimitsCacheError, ValueError):
            snapshot = None
        if snapshot is None:
            return self._builtin
        return replace(snapshot.limits, source="cache")
