from __future__ import annotations

from collections.abc import Callable
import hashlib
from pathlib import Path
from typing import Protocol

from src.domain.models import (
    InstalledModel,
    ModelDeliveryError,
    ModelManifestEntry,
    ModelUpdateItemResult,
    ModelUpdateResult,
)


class ModelManifestRemote(Protocol):
    def fetch(self, platform: str, architecture: str) -> tuple[ModelManifestEntry, ...]: ...


class ModelDownloader(Protocol):
    def download(
        self,
        entry: ModelManifestEntry,
        part_path: Path,
        state_path: Path,
        cancelled: Callable[[], bool],
    ) -> Path: ...


class InstalledModelRepository(Protocol):
    def active(self, model_id: str) -> InstalledModel | None: ...

    def install(self, entry: ModelManifestEntry, verified_file: Path) -> InstalledModel: ...


class EnsureModels:
    def __init__(
        self,
        remote: ModelManifestRemote,
        downloader: ModelDownloader,
        repository: InstalledModelRepository,
        download_dir: Path,
        platform: str,
        architecture: str,
    ) -> None:
        self._remote = remote
        self._downloader = downloader
        self._repository = repository
        self._download_dir = download_dir
        self._platform = platform
        self._architecture = architecture

    def execute(
        self, cancelled: Callable[[], bool] | None = None
    ) -> ModelUpdateResult:
        cancelled = cancelled or (lambda: False)
        entries = self._remote.fetch(self._platform, self._architecture)
        results: list[ModelUpdateItemResult] = []
        for entry in entries:
            if cancelled():
                raise ModelDeliveryError("模型更新已取消")
            if (
                entry.platform != self._platform
                or entry.architecture != self._architecture
            ):
                results.append(
                    ModelUpdateItemResult(
                        entry.model_id,
                        entry.version,
                        False,
                        "模型清单目标与当前平台不匹配",
                    )
                )
                continue
            active = self._repository.active(entry.model_id)
            if (
                active is not None
                and active.version == entry.version
                and active.object_version == entry.object_version
                and active.sha256 == entry.sha256
                and active.size_bytes == entry.size_bytes
                and _installed_file_is_valid(active, entry)
            ):
                results.append(ModelUpdateItemResult(entry.model_id, entry.version, False))
                continue
            safe_stem = f"{entry.model_id}-{entry.version}-{entry.platform}-{entry.architecture}"
            part_path = self._download_dir / f"{safe_stem}.part"
            state_path = self._download_dir / f"{safe_stem}.json"
            try:
                downloaded = self._downloader.download(
                    entry, part_path, state_path, cancelled
                )
                try:
                    _verify_download(downloaded, entry)
                except ModelDeliveryError:
                    part_path.unlink(missing_ok=True)
                    state_path.unlink(missing_ok=True)
                    raise
                self._repository.install(entry, downloaded)
                part_path.unlink(missing_ok=True)
                state_path.unlink(missing_ok=True)
                results.append(ModelUpdateItemResult(entry.model_id, entry.version, True))
            except (ModelDeliveryError, OSError) as error:
                results.append(
                    ModelUpdateItemResult(
                        entry.model_id,
                        entry.version,
                        False,
                        str(error),
                    )
                )
        return ModelUpdateResult(tuple(results))


def _verify_download(path: Path, entry: ModelManifestEntry) -> None:
    try:
        if path.stat().st_size != entry.size_bytes:
            raise ModelDeliveryError("模型文件大小校验失败")
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        raise ModelDeliveryError("无法读取已下载模型") from error
    if digest.hexdigest() != entry.sha256:
        raise ModelDeliveryError("模型 SHA-256 校验失败")


def _installed_file_is_valid(
    installed: InstalledModel,
    entry: ModelManifestEntry,
) -> bool:
    try:
        _verify_download(Path(installed.path), entry)
    except ModelDeliveryError:
        return False
    return True
