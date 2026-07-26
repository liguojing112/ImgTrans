import os
from pathlib import Path
from typing import Any

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QPointF

from src.application.bootstrap import StartupSnapshot
from src.application.image_io import ExportImage, ImportImage
from src.application.ocr import RecognizeText
from src.domain.image import ImageDocument, ImageLimits
from src.domain.ocr import (
    HighRecallOcrOptions,
    OcrMode,
    OcrResult,
    TextRegion,
    order_quad,
)
from src.domain.product import ProductInfo
from src.infrastructure.pillow_image_codec import PillowImageCodec
from src.ui.main_window import MainWindow


class ImmediateTaskRunner:
    def submit(self, operation: Any, on_success: Any, on_error: Any) -> None:
        try:
            on_success(operation())
        except Exception as error:
            on_error(error)


class FixtureOcrAdapter:
    language_codes = ("zh-Hans", "en")

    def __init__(self) -> None:
        self.high_recall_options: HighRecallOcrOptions | None = None

    def recognize(self, document: ImageDocument, language_code: str) -> OcrResult:
        region = TextRegion(
            "region-0001",
            order_quad(((12, 14), (100, 14), (100, 42), (12, 42))),
            "PRODUCT",
            0.96,
            language_code,
            "fixture-model",
        )
        return OcrResult((region,), language_code, "fixture-model", 18.5)

    def recognize_high_recall(
        self,
        document: ImageDocument,
        language_code: str,
        options: HighRecallOcrOptions,
    ) -> OcrResult:
        self.high_recall_options = options
        standard = self.recognize(document, language_code).regions[0]
        enhanced = TextRegion(
            "region-0002",
            order_quad(((108, 44), (148, 44), (148, 68), (108, 68))),
            "ROTATED",
            0.93,
            language_code,
            "fixture-model",
            enhanced_only=True,
            auto_process_eligible=False,
        )
        return OcrResult(
            (standard, enhanced),
            language_code,
            "fixture-model",
            50,
            OcrMode.HIGH_RECALL,
        )


def test_window_runs_ocr_and_shows_regions_and_text(tmp_path: Path) -> None:
    application = QApplication.instance() or QApplication(["imgtrans-ocr-test"])
    source = tmp_path / "product.png"
    Image.new("RGB", (160, 100), "white").save(source)
    codec = PillowImageCodec()
    window = MainWindow(
        StartupSnapshot(
            ProductInfo("图片翻译", "0.1.0", "M1"),
            tmp_path / "data",
            tmp_path / "cache",
        ),
        import_image=ImportImage(codec, ImageLimits()),
        export_image=ExportImage(codec),
        task_runner=ImmediateTaskRunner(),
        recognize_text=RecognizeText(FixtureOcrAdapter()),
    )
    window.show()
    window.request_import(source)
    window.request_ocr("en")
    application.processEvents()
    assert window.image_canvas.region_count == 1
    assert window.ocr_panel.results.topLevelItemCount() == 1
    assert window.ocr_panel.results.topLevelItem(0).text(0) == "PRODUCT"
    assert window.ocr_panel.results.topLevelItem(0).text(1) == "96.0%"
    assert window.statusBar().currentMessage() == "OCR 完成：识别到 1 个文字区域"
    assert window.ocr_button.isEnabled()
    window.close()


def test_window_passes_high_recall_geometry_and_confirms_edited_candidate(
    tmp_path: Path,
) -> None:
    application = QApplication.instance() or QApplication(["imgtrans-high-recall-ui-test"])
    source = tmp_path / "ring.png"
    Image.new("RGB", (200, 160), "white").save(source)
    codec = PillowImageCodec()
    adapter = FixtureOcrAdapter()
    window = MainWindow(
        StartupSnapshot(
            ProductInfo("图片翻译", "0.1.0", "M1"),
            tmp_path / "data",
            tmp_path / "cache",
        ),
        import_image=ImportImage(codec, ImageLimits()),
        export_image=ExportImage(codec),
        task_runner=ImmediateTaskRunner(),
        recognize_text=RecognizeText(adapter),
    )
    window.request_import(source)
    window._ocr_center_selected(QPointF(100, 80))
    window.ocr_panel.inner_radius.setValue(30)
    window.ocr_panel.outer_radius.setValue(70)
    window.ocr_panel.mode_combo.setCurrentIndex(
        window.ocr_panel.mode_combo.findData(OcrMode.HIGH_RECALL.value)
    )
    window.request_ocr("en")
    application.processEvents()

    assert adapter.high_recall_options is not None
    assert adapter.high_recall_options.center is not None
    assert adapter.high_recall_options.center.x == 100
    assert adapter.high_recall_options.ring_bands[0].outer_radius == 70
    item = window.ocr_panel.results.topLevelItem(1)
    item.setText(0, "ROTATED EDITED")
    item.setSelected(True)
    window.ocr_panel._confirm_selected_region()
    confirmed = window._ocr_result.regions[1]
    assert confirmed.text == "ROTATED EDITED"
    assert confirmed.auto_process_eligible
    window.close()
