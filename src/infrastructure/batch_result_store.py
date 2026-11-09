from __future__ import annotations

import gzip
import pickle
from pathlib import Path
import shutil

from src.domain.image import ImageDocument, ImageFileFormat, ImageLimits, ImageValidationError
from src.infrastructure.pillow_image_codec import PillowImageCodec


_EDITABLE_SUFFIX = ".edit.gz"


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

    def save_editable(
        self, batch_id: str, item_id: str, state: object
    ) -> None:
        # 用 pickle 保存本机翻译流水线自己产出的对象（含像素缓冲）；
        # 文件只落在应用自己的批量缓存目录，不读取外部传入的文件。
        if not item_id.startswith("item-") or any(
            value in item_id for value in ("/", "\\", "..")
        ):
            raise ValueError("Invalid batch item ID")
        directory = self._batch_directory(batch_id)
        try:
            directory.mkdir(parents=True, exist_ok=True)
            target = directory / f"{item_id}{_EDITABLE_SUFFIX}"
            temporary = directory / f"{item_id}{_EDITABLE_SUFFIX}.tmp"
            with gzip.open(temporary, "wb") as handle:
                pickle.dump(state, handle, protocol=pickle.HIGHEST_PROTOCOL)
            temporary.replace(target)
        except OSError as error:
            raise ImageValidationError(
                "cache_unavailable",
                "批量缓存不可用，请检查磁盘空间和目录权限",
            ) from error

    def load_editable(self, result_ref: str) -> object | None:
        """读回批量项的可编辑状态；旧批次或损坏缓存返回 None。"""
        target = Path(result_ref).resolve()
        if self._root not in target.parents:
            raise ValueError("Batch result reference is outside the cache")
        state_path = target.with_name(f"{target.stem}{_EDITABLE_SUFFIX}")
        if not state_path.is_file():
            return None
        try:
            with gzip.open(state_path, "rb") as handle:
                return pickle.load(handle)
        except (OSError, EOFError, pickle.UnpicklingError, AttributeError):
            return None

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
