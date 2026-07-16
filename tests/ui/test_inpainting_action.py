import os
from pathlib import Path
from typing import Any

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PySide6.QtWidgets import QApplication

from src.application.bootstrap import StartupSnapshot
from src.application.image_io import ExportImage, ImportImage
from src.application.inpainting import BuildEraseMask, RepairTranslatedRegions
from src.application.ocr import RecognizeText
from src.application.translation import TranslateRegions
from src.domain.image import ImageDocument, ImageLimits
from src.domain.inpainting import InpaintingRequest, InpaintingResult
from src.domain.ocr import OcrResult, TextRegion, order_quad
from src.domain.product import ProductInfo
from src.domain.protection import ProtectionEngine
from src.infrastructure.mock_translator import MockTranslationAdapter
from src.infrastructure.opencv_inpaint_adapter import OpenCvInpaintAdapter
from src.infrastructure.pillow_image_codec import PillowImageCodec
from src.infrastructure.pillow_mask_rasterizer import PillowMaskRasterizer
from src.ui.main_window import MainWindow


class ImmediateTaskRunner:
    def submit(self, operation: Any, on_success: Any, on_error: Any) -> None:
        try:
            on_success(operation())
        except Exception as error:
            on_error(error)


class FixtureOcrAdapter:
    language_codes = ("en",)

    def recognize(self, document: ImageDocument, language_code: str) -> OcrResult:
        region = TextRegion(
            "region-1",
            order_quad(((20, 20), (100, 20), (100, 50), (20, 50))),
            "SALE",
            0.99,
            "en",
            "fixture",
        )
        return OcrResult((region,), "en", "fixture", 1)


def test_window_repairs_toggles_and_restores_original(tmp_path: Path) -> None:
    application = QApplication.instance() or QApplication(["imgtrans-repair-test"])
    source = tmp_path / "source.png"
    image = Image.new("RGB", (140, 80), "navy")
    for x in range(20, 101):
        for y in range(20, 51):
            image.putpixel((x, y), (255, 255, 255))
    image.save(source)
    codec = PillowImageCodec()
    window = MainWindow(
        StartupSnapshot(ProductInfo("图片翻译", "0.1.0", "M1"), tmp_path / "data", tmp_path / "cache"),
        import_image=ImportImage(codec, ImageLimits()),
        export_image=ExportImage(codec),
        task_runner=ImmediateTaskRunner(),
        recognize_text=RecognizeText(FixtureOcrAdapter()),
        translate_regions=TranslateRegions(MockTranslationAdapter(), ProtectionEngine()),
        repair_regions=RepairTranslatedRegions(
            BuildEraseMask(PillowMaskRasterizer(), expansion=0),
            OpenCvInpaintAdapter(),
        ),
    )
    window.show()
    window.request_import(source)
    original_pixels = window.current_document.pixels
    window.request_ocr("en")
    window.request_translation()
    assert window.repair_button.isEnabled()
    window.request_repair()
    application.processEvents()
    assert window.current_document.pixels != original_pixels
    assert window.side_tabs.currentWidget() is window.inpainting_panel
    assert "opencv-telea" in window.inpainting_panel.status_label.text()
    assert window.inpainting_panel.toggle_button.isEnabled()
    window.toggle_original_preview()
    assert window.inpainting_panel.toggle_button.text() == "查看修复图"
    window.restore_original()
    assert window.current_document.pixels == original_pixels
    assert not window.inpainting_panel.toggle_button.isEnabled()
    window.close()
