from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from src.application.image_io import ExportImage
from src.application.ports import BatchResultStore
from src.domain.batch import BatchItemStatus, BatchSnapshot
from src.domain.image import ImageFileFormat


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
    ) -> BatchExportResult:
        if not selected_item_ids:
            raise ValueError("请至少选择一张成功图片")
        if not target_directory.is_dir():
            raise ValueError("批量导出目录不存在")
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
            target = _unique_target(
                target_directory,
                f"{item.source.stem}-translated",
                suffix,
                reserved,
            )
            try:
                document = self._result_store.load(item.result_ref)
                self._export_image.execute(document, target)
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
