"""模型仓库 — data_dir 已安装模型的管理（文件级查询/安装）。"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from uuid import uuid4
import json
import os
import shutil

from src.domain.models import InstalledModel, ModelDeliveryError, ModelManifestEntry
from src.platform.storage import StorageGuard, StorageUnavailableError


_CHUNK_SIZE = 1024 * 1024


class FileModelRepository:
    def __init__(
        self,
        root: Path,
        storage_guard: StorageGuard | None = None,
    ) -> None:
        self._root = root
        self._storage_guard = storage_guard or StorageGuard()

    def active(self, model_id: str) -> InstalledModel | None:
        _validate_safe_name(model_id)
        pointer = self._root / model_id / "current.json"
        if not pointer.is_file():
            return None
        try:
            payload = json.loads(pointer.read_text(encoding="utf-8"))
            if set(payload) != {"schema_version", "model_id", "version", "object_version", "sha256", "size_bytes", "path"}:
                raise ValueError
            if payload["schema_version"] != 1 or payload["model_id"] != model_id:
                raise ValueError
            candidate = (self._root / payload["path"]).resolve()
            candidate.relative_to(self._root.resolve())
            if not candidate.is_file():
                return None
            return InstalledModel(
                model_id=model_id,
                version=payload["version"],
                object_version=payload["object_version"],
                sha256=payload["sha256"],
                size_bytes=payload["size_bytes"],
                path=str(candidate),
            )
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            return None

    def install(self, entry: ModelManifestEntry, verified_file: Path) -> InstalledModel:
        target_dir = self._root / entry.model_id / entry.version
        target = target_dir / entry.filename
        temporary = target_dir / f".{entry.filename}.{uuid4().hex}.tmp"
        pointer = self._root / entry.model_id / "current.json"
        try:
            self._storage_guard.ensure_available(
                target_dir,
                required_bytes=entry.size_bytes,
                reserve_bytes=64 * 1024 * 1024,
            )
            target_dir.mkdir(parents=True, exist_ok=True)
            with verified_file.open("rb") as source, temporary.open("wb") as output:
                shutil.copyfileobj(source, output, _CHUNK_SIZE)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, target)
            relative = target.relative_to(self._root).as_posix()
            _atomic_json(
                pointer,
                {
                    "schema_version": 1,
                    "model_id": entry.model_id,
                    "version": entry.version,
                    "object_version": entry.object_version,
                    "sha256": entry.sha256,
                    "size_bytes": entry.size_bytes,
                    "path": relative,
                },
            )
        except (OSError, StorageUnavailableError) as error:
            raise ModelDeliveryError("模型安装失败，请检查磁盘空间和目录权限") from error
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
        return InstalledModel(
            entry.model_id,
            entry.version,
            entry.object_version,
            entry.sha256,
            entry.size_bytes,
            str(target.resolve()),
        )


def _atomic_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        with temporary.open("wb") as output:
            output.write(encoded)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _validate_safe_name(value: str) -> None:
    if not value or any(character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-" for character in value):
        raise ModelDeliveryError("模型标识不安全")
