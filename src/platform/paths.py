from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import platform
from uuid import uuid4
from typing import Mapping


@dataclass(frozen=True, slots=True)
class PlatformPaths:
    data_dir: Path
    cache_dir: Path

    @classmethod
    def discover(
        cls,
        system: str | None = None,
        environ: Mapping[str, str] | None = None,
        home: Path | None = None,
    ) -> "PlatformPaths":
        system = system or platform.system()
        environ = environ or os.environ
        home = home or Path.home()
        if system == "Windows":
            local = Path(environ.get("LOCALAPPDATA", home / "AppData" / "Local"))
            root = local / "ImgTrans"
            return cls(data_dir=root, cache_dir=root / "Cache")
        if system == "Darwin":
            return cls(
                data_dir=home / "Library" / "Application Support" / "ImgTrans",
                cache_dir=home / "Library" / "Caches" / "ImgTrans",
            )
        data_root = Path(environ.get("XDG_DATA_HOME", home / ".local" / "share"))
        cache_root = Path(environ.get("XDG_CACHE_HOME", home / ".cache"))
        return cls(data_dir=data_root / "ImgTrans", cache_dir=cache_root / "ImgTrans")

    def ensure(self) -> None:
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            _verify_writable(self.data_dir)
            _verify_writable(self.cache_dir)
        except OSError as error:
            raise PlatformPathError(
                "无法使用应用数据目录，请检查磁盘空间和目录权限"
            ) from error


class PlatformPathError(RuntimeError):
    pass


def _verify_writable(directory: Path) -> None:
    probe = directory / f".imgtrans-write-test-{uuid4().hex}.tmp"
    try:
        with probe.open("xb") as stream:
            stream.write(b"ok")
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        probe.unlink(missing_ok=True)


def discover_model_target(
    system: str | None = None,
    machine: str | None = None,
) -> tuple[str, str]:
    system = system or platform.system()
    machine = (machine or platform.machine()).lower()
    if system == "Windows" and machine in {"amd64", "x86_64"}:
        return "windows", "x86_64"
    if system == "Darwin" and machine in {"arm64", "aarch64"}:
        return "macos", "arm64"
    raise RuntimeError(f"Unsupported model target: {system} {machine}")
