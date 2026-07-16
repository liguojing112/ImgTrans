import os
from pathlib import Path
from typing import Any

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PySide6.QtWidgets import QApplication

from src.application.bootstrap import StartupSnapshot
from src.application.image_io import ExportImage, ImportImage
from src.application.ocr import RecognizeText
from src.application.translation import TranslateRegions
from src.domain.image import ImageDocument, ImageLimits
from src.domain.ocr import OcrResult, TextRegion, order_quad
from src.domain.product import ProductInfo
from src.domain.protection import ProtectionEngine
from src.infrastructure.mock_translator import MockTranslationAdapter
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
            order_quad(((12, 14), (180, 14), (180, 48), (12, 48))),
            "ACME X100 25% OFF",
            0.98,
            language_code,
            "fixture-model",
        )
        return OcrResult((region,), language_code, "fixture-model", 8)


def test_window_runs_mock_translation_and_shows_protected_terms(tmp_path: Path) -> None:
    application = QApplication.instance() or QApplication(["imgtrans-translation-test"])
    source = tmp_path / "product.png"
    Image.new("RGB", (220, 100), "white").save(source)
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
        translate_regions=TranslateRegions(MockTranslationAdapter(), ProtectionEngine()),
    )
    window.show()
    window.request_import(source)
    window.request_ocr("en")
    window.translation_panel.brand_terms.setText("ACME")
    window.request_translation()
    application.processEvents()
    assert window.translation_panel.results.topLevelItemCount() == 1
    item = window.translation_panel.results.topLevelItem(0)
    assert item.text(1) == "ACME X100 25% 优惠"
    assert item.text(2) == "已翻译"
    assert "品牌:ACME" in item.text(3)
    assert "型号:X100" in item.text(3)
    assert "品牌 ACME" in window.translation_panel.protection_summary.text()
    assert "型号 X100" in window.translation_panel.protection_summary.text()
    assert window.side_tabs.currentWidget() is window.translation_panel
    assert window.statusBar().currentMessage() == "模拟翻译完成：1 个区域生成译文"
    window.close()
