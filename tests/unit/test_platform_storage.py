from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import src.platform.paths as paths_module
from src.platform.paths import PlatformPathError, PlatformPaths
from src.platform.storage import StorageGuard, StorageUnavailableError


def test_storage_guard_checks_existing_ancestor_and_reserved_capacity(
    tmp_path: Path,
) -> None:
    captured = {}

    def usage(path: Path):
        captured["path"] = path
        return SimpleNamespace(total=1000, used=400, free=600)

    guard = StorageGuard(usage)
    capacity = guard.ensure_available(
        tmp_path / "not-created" / "nested",
        required_bytes=400,
        reserve_bytes=200,
    )
    assert captured["path"] == tmp_path.resolve()
    assert capacity.free == 600

    with pytest.raises(StorageUnavailableError) as error:
        guard.ensure_available(tmp_path, required_bytes=401, reserve_bytes=200)
    assert error.value.code == "disk_full"
    assert str(tmp_path) not in str(error.value)


def test_storage_guard_maps_probe_failure_without_disclosing_path(tmp_path: Path) -> None:
    def fail(_path: Path):
        raise OSError(f"offline volume {tmp_path}")

    with pytest.raises(StorageUnavailableError) as error:
        StorageGuard(fail).ensure_available(tmp_path, 1)
    assert error.value.code == "storage_unavailable"
    assert str(tmp_path) not in str(error.value)


def test_platform_paths_verify_writable_and_remove_probe(tmp_path: Path) -> None:
    paths = PlatformPaths(tmp_path / "data", tmp_path / "cache")
    paths.ensure()
    assert paths.data_dir.is_dir() and paths.cache_dir.is_dir()
    assert not tuple(tmp_path.rglob(".imgtrans-write-test-*.tmp"))


def test_platform_path_error_is_sanitized(tmp_path: Path, monkeypatch) -> None:
    def fail(_directory: Path) -> None:
        raise PermissionError(f"private path: {tmp_path}")

    monkeypatch.setattr(paths_module, "_verify_writable", fail)
    with pytest.raises(PlatformPathError) as error:
        PlatformPaths(tmp_path / "data", tmp_path / "cache").ensure()
    assert str(tmp_path) not in str(error.value)

