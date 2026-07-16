import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from src.application.batch_export import ExportBatchSelection
from src.application.bootstrap import StartupSnapshot
from src.application.image_io import ExportImage
from src.application.ocr import RecognizeText
from src.application.translation import TranslateRegions
from src.domain.batch import BatchItemSnapshot, BatchItemStatus, BatchSnapshot, BatchStatus
from src.domain.image import ImageAsset, ImageDocument, ImageFileFormat
from src.domain.ocr import OcrResult
from src.domain.product import ProductInfo
from src.domain.protection import ProtectionEngine
from src.infrastructure.mock_translator import MockTranslationAdapter
from src.infrastructure.pillow_image_codec import PillowImageCodec
from src.ui.batch_panel import BatchPanel
from src.ui.main_window import MainWindow


class _ImmediateTaskRunner:
    def submit(self, operation, on_success, on_error) -> None:
        try:
            on_success(operation())
        except Exception as error:
            on_error(error)


class _UnusedOcr:
    language_codes = ("en",)

    def recognize(self, document, language_code):
        return OcrResult((), language_code, "unused", 0)


class _MemoryStore:
    def __init__(self, document: ImageDocument) -> None:
        self.document = document
        self.cleared: list[str] = []

    def save(self, batch_id, item_id, document):
        self.document = document
        return "result"

    def load(self, result_ref):
        assert result_ref == "result"
        return self.document

    def clear(self, batch_id):
        self.cleared.append(batch_id)


class _CompletedBatch:
    def __init__(self) -> None:
        self.cancelled = False

    def execute(self, sources, ocr_language, selection, brand_terms=(), on_update=None):
        del ocr_language, selection, brand_terms
        snapshot = BatchSnapshot(
            "batch-ui",
            BatchStatus.COMPLETED,
            tuple(
                BatchItemSnapshot(
                    f"item-{index}",
                    source,
                    BatchItemStatus.COMPLETED,
                    result_ref="result",
                )
                for index, source in enumerate(sources)
            ),
            2,
        )
        if on_update is not None:
            on_update(snapshot)
        return snapshot

    def cancel(self):
        self.cancelled = True


def _document(tmp_path: Path) -> ImageDocument:
    asset = ImageAsset(tmp_path / "result.png", 40, 24, 1, ImageFileFormat.PNG, False, False)
    return ImageDocument(asset, "RGB", bytes((20, 80, 160)) * 40 * 24)


def test_batch_panel_preserves_selection_and_exposes_failed_status() -> None:
    QApplication.instance() or QApplication(["batch-panel-ui"])
    panel = BatchPanel()
    panel.add_sources((Path("one.png"), Path("two.png")))
    snapshot = BatchSnapshot(
        "batch-ui",
        BatchStatus.COMPLETED,
        (
            BatchItemSnapshot("one", Path("one.png"), BatchItemStatus.COMPLETED, result_ref="r1"),
            BatchItemSnapshot("two", Path("two.png"), BatchItemStatus.FAILED, error="broken"),
        ),
        2,
    )
    panel.set_snapshot(snapshot)
    panel.set_available(True, False)
    assert panel.selected_result_ids == ("one",)
    assert panel.items.topLevelItem(1).text(1) == "失败"
    assert panel.items.topLevelItem(1).text(3) == "broken"
    panel.items.topLevelItem(0).setCheckState(0, Qt.CheckState.Unchecked)
    panel.set_snapshot(snapshot)
    assert panel.selected_result_ids == ()


def test_main_window_runs_previews_and_selectively_exports_batch(tmp_path: Path) -> None:
    application = QApplication.instance() or QApplication(["batch-main-ui"])
    document = _document(tmp_path)
    store = _MemoryStore(document)
    scheduler = _CompletedBatch()
    recognize = RecognizeText(_UnusedOcr())
    translate = TranslateRegions(MockTranslationAdapter(), ProtectionEngine())
    exporter = ExportImage(PillowImageCodec())
    window = MainWindow(
        StartupSnapshot(
            ProductInfo("图片翻译", "0.1.0", "M2"),
            tmp_path / "data",
            tmp_path / "cache",
        ),
        export_image=exporter,
        task_runner=_ImmediateTaskRunner(),
        recognize_text=recognize,
        translate_regions=translate,
        run_batch=scheduler,
        batch_result_store=store,
        export_batch_selection=ExportBatchSelection(store, exporter),
    )
    window.show()
    sources = (tmp_path / "one.png", tmp_path / "two.png")
    window.batch_panel.add_sources(sources)
    window._set_busy(False, "ready")
    window.request_batch()
    application.processEvents()
    assert window._batch_snapshot.completed_count == 2
    assert window.batch_panel.selected_result_ids == ("item-0", "item-1")
    window.request_batch_preview("item-0")
    assert window.current_document is document
    assert window.image_canvas.pixmap() is not None
    window.batch_panel.items.topLevelItem(1).setCheckState(0, Qt.CheckState.Unchecked)
    window.request_batch_export(tmp_path)
    assert (tmp_path / "one-translated.png").is_file()
    assert not (tmp_path / "two-translated.png").exists()
    window.close()
