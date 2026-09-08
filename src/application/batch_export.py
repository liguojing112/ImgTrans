from __future__ import annotations

from dataclasses import dataclass, replace as dataclass_replace
from enum import Enum
from pathlib import Path
import re

from PIL import Image

from src.application.composition import apply_watermark_template
from src.application.image_io import ExportImage
from src.application.ports import BatchResultStore
from src.domain.batch import BatchItemStatus, BatchSnapshot
from src.domain.image import ExportOptions, ImageDocument, ImageFileFormat
from src.domain.layout import TextStyle


class BatchResizeMode(str, Enum):
    ORIGINAL = "original"
    PERCENT = "percent"
    MAX_EDGE = "max_edge"


@dataclass(frozen=True, slots=True)
class BatchWatermarkOptions:
    kind: str
    opacity: float = 0.55
    tiled: bool = False
    position: str = "center"
    text: str = ""
    style: TextStyle | None = None
    image: ImageDocument | None = None

    def __post_init__(self) -> None:
        if self.kind not in {"text", "image"}:
            raise ValueError("Batch watermark kind must be text or image")
        if not 0 <= self.opacity <= 1:
            raise ValueError("Batch watermark opacity must be between zero and one")
        if self.kind == "text" and (not self.text.strip() or self.style is None):
            raise ValueError("Text batch watermark requires text and style")
        if self.kind == "image" and self.image is None:
            raise ValueError("Image batch watermark requires an image")


@dataclass(frozen=True, slots=True)
class BatchExportOptions:
    quality: int = 95
    resize_mode: BatchResizeMode = BatchResizeMode.ORIGINAL
    resize_value: int = 100
    preserve_alpha: bool = True
    watermark: BatchWatermarkOptions | None = None
    subdirectory_name: str | None = None

    def __post_init__(self) -> None:
        if not 1 <= self.quality <= 100:
            raise ValueError("Batch export quality must be between 1 and 100")
        if self.resize_mode is BatchResizeMode.PERCENT:
            if not 10 <= self.resize_value <= 100:
                raise ValueError("Batch resize percentage must be between 10 and 100")
        elif self.resize_mode is BatchResizeMode.MAX_EDGE:
            if self.resize_value < 64:
                raise ValueError("Batch maximum edge must be at least 64 pixels")
        if self.subdirectory_name is not None:
            name = self.subdirectory_name.strip()
            if (
                not name
                or name in {".", ".."}
                or re.search(r'[<>:"/\\|?*]', name)
                or name.endswith((".", " "))
            ):
                raise ValueError("Batch export subdirectory name is invalid")


@dataclass(frozen=True, slots=True)
class BatchExportItemResult:
    item_id: str
    source: Path
    target: Path | None
    error: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.target is not None and self.error is None


@dataclass(frozen=True, slots=True)
class BatchExportResult:
    items: tuple[BatchExportItemResult, ...]

    @property
    def succeeded_count(self) -> int:
        return sum(item.succeeded for item in self.items)

    @property
    def failed_count(self) -> int:
        return len(self.items) - self.succeeded_count


class ExportBatchSelection:
    def __init__(
        self,
        result_store: BatchResultStore,
        export_image: ExportImage,
    ) -> None:
        self._result_store = result_store
        self._export_image = export_image

    def execute(
        self,
        snapshot: BatchSnapshot,
        selected_item_ids: tuple[str, ...],
        target_directory: Path,
        suffix: str,
        options: BatchExportOptions | None = None,
    ) -> BatchExportResult:
        if not selected_item_ids:
            raise ValueError("请至少选择一张成功图片")
        if not target_directory.is_dir():
            raise ValueError("批量导出目录不存在")
        selected_options = options or BatchExportOptions()
        export_directory = target_directory
        if selected_options.subdirectory_name is not None:
            export_directory = (
                target_directory / selected_options.subdirectory_name.strip()
            )
            export_directory.mkdir(exist_ok=True)
        ImageFileFormat.from_output_suffix(suffix)
        selected = set(selected_item_ids)
        if len(selected) != len(selected_item_ids):
            raise ValueError("批量导出选择中存在重复项目")
        items_by_id = {item.item_id: item for item in snapshot.items}
        unknown = selected.difference(items_by_id)
        if unknown:
            raise ValueError("批量导出选择包含未知项目")
        results: list[BatchExportItemResult] = []
        reserved: set[Path] = set()
        for item_id in selected_item_ids:
            item = items_by_id[item_id]
            if item.status is not BatchItemStatus.COMPLETED or not item.result_ref:
                results.append(
                    BatchExportItemResult(
                        item_id,
                        item.source,
                        None,
                        "只有处理成功的图片可以导出",
                    )
                )
                continue
            try:
                document = self._result_store.load(item.result_ref)
                output = _resize_document(document, selected_options)
                if selected_options.watermark is not None:
                    output = apply_watermark_template(
                        output, selected_options.watermark
                    )
                target = _unique_target(
                    export_directory,
                    f"{item.source.stem}-translated",
                    suffix,
                    reserved,
                )
                self._export_image.execute(
                    output,
                    target,
                    ExportOptions(
                        quality=selected_options.quality,
                        preserve_alpha=selected_options.preserve_alpha,
                    ),
                )
                reserved.add(target)
                results.append(BatchExportItemResult(item_id, item.source, target))
            except Exception as error:
                results.append(
                    BatchExportItemResult(
                        item_id,
                        item.source,
                        None,
                        str(error) or type(error).__name__,
                    )
                )
        return BatchExportResult(tuple(results))


def _resize_document(
    document: ImageDocument,
    options: BatchExportOptions,
) -> ImageDocument:
    width, height = document.asset.width, document.asset.height
    if options.resize_mode is BatchResizeMode.ORIGINAL:
        return document
    if options.resize_mode is BatchResizeMode.PERCENT:
        scale = options.resize_value / 100
    else:
        scale = min(1.0, options.resize_value / max(width, height))
    target = (max(1, round(width * scale)), max(1, round(height * scale)))
    if target == (width, height):
        return document
    image = Image.frombytes(document.mode, (width, height), document.pixels)
    resized = image.resize(target, Image.Resampling.LANCZOS)
    return ImageDocument(
        dataclass_replace(
            document.asset,
            width=target[0],
            height=target[1],
            has_alpha=document.mode == "RGBA",
        ),
        document.mode,
        resized.tobytes(),
    )


def _unique_target(
    directory: Path,
    stem: str,
    suffix: str,
    reserved: set[Path],
) -> Path:
    candidate = directory / f"{stem}{suffix}"
    index = 2
    while candidate.exists() or candidate in reserved:
        candidate = directory / f"{stem}-{index}{suffix}"
        index += 1
    return candidate
