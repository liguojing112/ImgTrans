"""exe 内置模型仓库 — 打包的 OCR/修复模型直接加载，无需复制或下载。

打包时模型放入 `bundled_models/<model_id>/<filename>`；客户端优先读
data_dir 已安装模型，缺失则回退到内置目录，实现开箱即用。
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from src.domain.models import InstalledModel


class BundledModelRepository:
    """优先读 data_dir 已安装模型；缺失时回退到 exe 内置模型目录。"""

    def __init__(self, primary, bundled_root: Path | None) -> None:
        self._primary = primary
        self._bundled_root = bundled_root

    def active(self, model_id: str) -> InstalledModel | None:
        installed = self._primary.active(model_id)
        if installed is not None:
            return installed
        if self._bundled_root is None:
            return None
        model_dir = self._bundled_root / model_id
        if not model_dir.is_dir():
            return None
        onnx_files = tuple(model_dir.glob("*.onnx"))
        if len(onnx_files) != 1:
            return None
        source = onnx_files[0]
        digest = _sha256(source)
        return InstalledModel(
            model_id=model_id,
            version="bundled",
            object_version=f"bundled:{digest[:12]}",
            sha256=digest,
            size_bytes=source.stat().st_size,
            path=str(source),
        )

    def install(self, entry, verified_file):
        return self._primary.install(entry, verified_file)


def bundled_models_root() -> Path | None:
    """frozen exe 返回 _MEIPASS/bundled_models；开发环境返回 None。"""
    import sys

    if not getattr(sys, "frozen", False):
        return None
    root = Path(getattr(sys, "_MEIPASS", "")) / "bundled_models"
    return root if root.is_dir() else None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
