from __future__ import annotations

from pathlib import Path
import shutil

from src.domain.image import ImageDocument, ImageFileFormat, ImageLimits, ImageValidationError
from src.infrastructure.pillow_image_codec import PillowImageCodec


class PngBatchResultStore:
    def __init__(
        self,
        root: Path,
        codec: PillowImageCodec | None = None,
        limits: ImageLimits | None = None,
    ) -> None:
        try:
            root.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise ImageValidationError(
                "cache_unavailable",
                "批量缓存不可用，请检查磁盘空间和目录权限",
            ) from error
        self._root = root.resolve()
        self._codec = codec or PillowImageCodec()
        self._limits = limits or ImageLimits(
            min_width=1,
            min_height=1,
            max_bytes=512 * 1024 * 1024,
        )

    def save(self, batch_id: str, item_id: str, document: ImageDocument) -> str:
        if not item_id.startswith("item-") or any(
            value in item_id for value in ("/", "\\", "..")
        ):
            raise ValueError("Invalid batch item ID")
        directory = self._batch_directory(batch_id)
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise ImageValidationError(
                "cache_unavailable",
                "批量缓存不可用，请检查磁盘空间和目录权限",
            ) from error
        target = directory / f"{item_id}.png"
        self._codec.save(document, target, ImageFileFormat.PNG)
        return str(target)

    def load(self, result_ref: str) -> ImageDocument:
        target = Path(result_ref).resolve()
        if self._root not in target.parents:
            raise ValueError("Batch result reference is outside the cache")
        return self._codec.load(target, self._limits)

    def clear(self, batch_id: str) -> None:
        directory = self._batch_directory(batch_id)
        if directory.is_dir():
            try:
                shutil.rmtree(directory)
            except OSError as error:
                raise ImageValidationError(
                    "cache_cleanup_failed",
                    "无法清理批量缓存，请检查目录权限",
                ) from error

    def _batch_directory(self, batch_id: str) -> Path:
        if not batch_id.startswith("batch-") or any(
            value in batch_id for value in ("/", "\\", "..")
        ):
            raise ValueError("Invalid batch ID")
        directory = (self._root / batch_id).resolve()
        if directory.parent != self._root:
            raise ValueError("Batch directory is outside the cache")
        return directory
