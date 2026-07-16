import os
from pathlib import Path
from typing import Any

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PySide6.QtWidgets import QApplication

from src.application.bootstrap import StartupSnapshot
from src.application.image_io import ExportImage, ImportImage
from src.application.ocr import RecognizeText
from src.domain.image import ImageDocument, ImageLimits
from src.domain.ocr import OcrResult, TextRegion, order_quad
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
