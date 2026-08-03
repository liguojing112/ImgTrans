from pathlib import Path

from PIL import Image
import pytest

from src.application.batch_export import (
    BatchExportOptions,
    BatchResizeMode,
    BatchWatermarkOptions,
    ExportBatchSelection,
)
from src.application.image_io import ExportImage
from src.domain.batch import BatchItemSnapshot, BatchItemStatus, BatchSnapshot, BatchStatus
from src.domain.image import ImageAsset, ImageDocument, ImageFileFormat
from src.domain.layout import TextStyle
from src.infrastructure.pillow_image_codec import PillowImageCodec


class _MemoryResultStore:
    def __init__(self, documents: dict[str, ImageDocument]) -> None:
        self.documents = documents

    def load(self, result_ref: str) -> ImageDocument:
        return self.documents[result_ref]

    def save(self, batch_id: str, item_id: str, document: ImageDocument) -> str:
        raise NotImplementedError

    def clear(self, batch_id: str) -> None:
        pass


def _document(source: Path, color: tuple[int, int, int]) -> ImageDocument:
    asset = ImageAsset(source, 12, 8, 1, ImageFileFormat.PNG, False, False)
    return ImageDocument(asset, "RGB", bytes(color) * 12 * 8)


def _large_document(source: Path, color: tuple[int, int, int]) -> ImageDocument:
    asset = ImageAsset(source, 120, 80, 1, ImageFileFormat.PNG, False, False)
    return ImageDocument(asset, "RGB", bytes(color) * 120 * 80)


def test_selection_exports_only_requested_successes_and_avoids_name_collisions(
    tmp_path: Path,
) -> None:
    first_source = tmp_path / "one" / "product.png"
    second_source = tmp_path / "two" / "product.webp"
    store = _MemoryResultStore(
        {
            "r1": _document(first_source, (10, 20, 30)),
            "r2": _document(second_source, (40, 50, 60)),
        }
    )
    snapshot = BatchSnapshot(
        "batch-test",
        BatchStatus.COMPLETED,
        (
            BatchItemSnapshot("i1", first_source, BatchItemStatus.COMPLETED, result_ref="r1"),
            BatchItemSnapshot("i2", second_source, BatchItemStatus.COMPLETED, result_ref="r2"),
            BatchItemSnapshot("i3", Path("bad.png"), BatchItemStatus.FAILED, error="bad"),
        ),
        2,
    )
    result = ExportBatchSelection(store, ExportImage(PillowImageCodec())).execute(
        snapshot,
        ("i1", "i2"),
        tmp_path,
        ".png",
    )
    assert result.succeeded_count == 2
    assert result.failed_count == 0
    assert [item.target.name for item in result.items] == [
        "product-translated.png",
        "product-translated-2.png",
    ]
    for item in result.items:
        with Image.open(item.target) as image:
            assert image.size == (12, 8)


def test_selection_reports_non_success_item_without_stopping_other_exports(
    tmp_path: Path,
) -> None:
    source = tmp_path / "ok.png"
    store = _MemoryResultStore({"ok": _document(source, (1, 2, 3))})
    snapshot = BatchSnapshot(
        "batch-test",
        BatchStatus.COMPLETED,
        (
            BatchItemSnapshot("ok", source, BatchItemStatus.COMPLETED, result_ref="ok"),
            BatchItemSnapshot("bad", Path("bad.png"), BatchItemStatus.FAILED, error="bad"),
        ),
        2,
    )
    result = ExportBatchSelection(store, ExportImage(PillowImageCodec())).execute(
        snapshot,
        ("bad", "ok"),
        tmp_path,
        ".webp",
    )
    assert result.succeeded_count == 1
    assert result.failed_count == 1
    assert result.items[0].target is None
    assert result.items[1].target.is_file()


def test_batch_export_resizes_then_applies_text_watermark(tmp_path: Path) -> None:
    source = tmp_path / "watermarked.png"
    document = _large_document(source, (10, 20, 30))
    store = _MemoryResultStore({"result": document})
    snapshot = BatchSnapshot(
        "batch-test",
        BatchStatus.COMPLETED,
        (
            BatchItemSnapshot(
                "item",
                source,
                BatchItemStatus.COMPLETED,
                result_ref="result",
            ),
        ),
        1,
    )
    options = BatchExportOptions(
        quality=80,
        resize_mode=BatchResizeMode.PERCENT,
        resize_value=50,
        watermark=BatchWatermarkOptions(
            "text",
            opacity=0.8,
            position="bottom_right",
            text="DEMO",
            style=TextStyle("Arial", 16, (255, 255, 255)),
        ),
    )
    result = ExportBatchSelection(
        store, ExportImage(PillowImageCodec())
    ).execute(snapshot, ("item",), tmp_path, ".png", options)
    assert result.succeeded_count == 1
    with Image.open(result.items[0].target) as image:
        assert image.size == (60, 40)
        colors = image.convert("RGB").getcolors(maxcolors=60 * 40)
        assert colors is not None and len(colors) > 1


def test_batch_max_edge_never_upscales_source(tmp_path: Path) -> None:
    source = tmp_path / "small.png"
    document = _document(source, (40, 50, 60))
    store = _MemoryResultStore({"result": document})
    snapshot = BatchSnapshot(
        "batch-test",
        BatchStatus.COMPLETED,
        (
            BatchItemSnapshot(
                "item",
                source,
                BatchItemStatus.COMPLETED,
                result_ref="result",
            ),
        ),
        1,
    )
    options = BatchExportOptions(
        resize_mode=BatchResizeMode.MAX_EDGE,
        resize_value=64,
    )
    result = ExportBatchSelection(
        store, ExportImage(PillowImageCodec())
    ).execute(snapshot, ("item",), tmp_path, ".png", options)
    with Image.open(result.items[0].target) as image:
        assert image.size == (12, 8)


def test_batch_export_can_isolate_results_in_named_subdirectory(
    tmp_path: Path,
) -> None:
    source = tmp_path / "product.png"
    store = _MemoryResultStore({"result": _document(source, (40, 50, 60))})
    snapshot = BatchSnapshot(
        "batch-test",
        BatchStatus.COMPLETED,
        (
            BatchItemSnapshot(
                "item",
                source,
                BatchItemStatus.COMPLETED,
                result_ref="result",
            ),
        ),
        1,
    )
    result = ExportBatchSelection(
        store, ExportImage(PillowImageCodec())
    ).execute(
        snapshot,
        ("item",),
        tmp_path,
        ".png",
        BatchExportOptions(subdirectory_name="translated-run"),
    )
    assert result.succeeded_count == 1
    assert result.items[0].target.parent == tmp_path / "translated-run"
    assert result.items[0].target.is_file()


@pytest.mark.parametrize(
    "name",
    ("", ".", "..", "../outside", "bad/name", "bad:name", "trailing."),
)
def test_batch_export_rejects_unsafe_subdirectory_names(name: str) -> None:
    with pytest.raises(ValueError, match="subdirectory"):
        BatchExportOptions(subdirectory_name=name)
