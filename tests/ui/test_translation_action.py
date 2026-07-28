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
from src.domain.language import SUPPORTED_LANGUAGE_CODES
from src.domain.image import ImageDocument, ImageLimits
from src.domain.ocr import OcrResult, TextRegion, order_quad
from src.domain.product import ProductInfo
from src.domain.protection import ProtectionEngine
from src.domain.terminology import TerminologyCatalog, TerminologyEntry
from src.domain.translation import (
    TranslationMode,
    TranslationResult,
    TranslationSelection,
    TranslationStatus,
    TranslationUnit,
)
from src.infrastructure.mock_translator import MockTranslationAdapter
from src.infrastructure.pillow_image_codec import PillowImageCodec
from src.ui.main_window import MainWindow
from src.ui.translation_panel import TranslationPanel


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


class MemoryBrandTermsPreferences:
    def __init__(self, values=()) -> None:
        self.values = tuple(values)
        self.saved: list[tuple[str, ...]] = []

    def load(self) -> tuple[str, ...]:
        return self.values

    def save(self, brand_terms: tuple[str, ...]) -> None:
        self.values = brand_terms
        self.saved.append(brand_terms)


class MemoryTerminologyPreferences:
    def __init__(self, values=()) -> None:
        self.values = tuple(values)
        self.saved: list[tuple[TerminologyEntry, ...]] = []

    def load(self) -> tuple[TerminologyEntry, ...]:
        return self.values

    def save(self, entries: tuple[TerminologyEntry, ...]) -> None:
        self.values = entries
        self.saved.append(entries)


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


def test_panel_shows_review_required_without_counting_it_as_failure() -> None:
    QApplication.instance() or QApplication(["imgtrans-review-status-test"])
    panel = TranslationPanel(("en", "zh-Hans"), provider_id="server-proxy")
    result = TranslationResult(
        (
            TranslationUnit(
                "review",
                "LOW",
                "en",
                "zh-Hans",
                "LOW",
                TranslationStatus.REVIEW_REQUIRED,
            ),
            TranslationUnit(
                "translated",
                "HIGH",
                "en",
                "zh-Hans",
                "translated",
                TranslationStatus.TRANSLATED,
            ),
            TranslationUnit(
                "failed",
                "BAD",
                "en",
                "zh-Hans",
                "BAD",
                TranslationStatus.FAILED,
                error_code="fixture_failed",
                error_message="fixture failure",
            ),
        ),
        TranslationSelection(TranslationMode.ALL, "zh-Hans"),
        "server-proxy",
        12.3,
    )

    panel.set_result(result)

    assert panel.results.topLevelItemCount() == 3
    review = panel.results.topLevelItem(0)
    assert review.text(0) == "LOW"
    assert review.text(1) == "LOW"
    assert review.text(2) == "\u5f85\u590d\u6838\uff1a\u81ea\u52a8\u5904\u7406\u53ef\u9760\u6027\u4e0d\u8db3"
    assert review.toolTip(2) == "\u8be5\u533a\u57df\u672a\u81ea\u52a8\u7ffb\u8bd1\uff0c\u539f\u56fe\u4fdd\u6301\u4e0d\u53d8"
    assert panel.results.topLevelItem(2).text(2) == "\u5931\u8d25\uff1a\u4fdd\u7559\u539f\u6587"
    assert (
        "\u670d\u52a1\u7aef\u7ffb\u8bd1\u5b8c\u6210\uff1a1 \u4e2a\u5df2\u7ffb\u8bd1 \u00b7 1 \u4e2a\u5f85\u590d\u6838 \u00b7 \u5171 3 \u4e2a\u533a\u57df"
        in panel.status_label.text()
    )
    panel.close()


def test_panel_defaults_target_language_to_english_when_available() -> None:
    QApplication.instance() or QApplication(["imgtrans-default-target-test"])
    panel = TranslationPanel(("zh-Hans", "en"), provider_id="server-proxy")

    assert panel.selection.target_language == "en"

    panel.close()


def test_panel_exposes_customer_language_baseline_and_auto_source_detection() -> None:
    QApplication.instance() or QApplication(["imgtrans-language-baseline-test"])
    panel = TranslationPanel(
        SUPPORTED_LANGUAGE_CODES,
        provider_id="server-proxy",
    )

    assert panel.source_combo.currentData() is None
    assert panel.source_combo.currentText() == "自动识别源语言"
    assert tuple(
        panel.source_combo.itemData(index)
        for index in range(1, panel.source_combo.count())
    ) == SUPPORTED_LANGUAGE_CODES
    assert tuple(
        panel.target_combo.itemData(index)
        for index in range(panel.target_combo.count())
    ) == SUPPORTED_LANGUAGE_CODES

    panel.mode_combo.setCurrentIndex(
        panel.mode_combo.findData(TranslationMode.SPECIFIC_LANGUAGE)
    )
    assert panel.source_combo.isEnabled()
    assert panel.selection.mode is TranslationMode.SPECIFIC_LANGUAGE
    assert panel.selection.source_language == "zh-Hans"

    panel.source_combo.setCurrentIndex(panel.source_combo.findData("bn"))
    assert panel.selection.source_language == "bn"

    panel.mode_combo.setCurrentIndex(panel.mode_combo.findData(TranslationMode.ALL))
    assert panel.source_combo.currentData() is None
    assert panel.selection.mode is TranslationMode.ALL
    assert panel.selection.source_language is None
    panel.close()


def test_window_loads_persists_and_immediately_applies_brand_terms(tmp_path: Path) -> None:
    QApplication.instance() or QApplication(["imgtrans-brand-preferences-test"])
    preferences = MemoryBrandTermsPreferences(("Alpha", "Beta"))
    window = MainWindow(
        StartupSnapshot(
            ProductInfo("Image Translator", "0.1.0", "M1"),
            tmp_path / "data",
            tmp_path / "cache",
        ),
        translate_regions=TranslateRegions(
            MockTranslationAdapter(), ProtectionEngine()
        ),
        brand_terms_preferences=preferences,
    )

    assert window.translation_panel.configured_brand_terms == ("Alpha", "Beta")
    window.translation_panel.brand_terms.setText(
        " Gamma， Alpha, gamma "
    )
    assert window.translation_panel.configured_brand_terms == ("Gamma", "Alpha")
    window.translation_panel.brand_terms.editingFinished.emit()
    assert preferences.saved[-1] == ("Gamma", "Alpha")
    assert window.translation_panel.brand_terms.text() == "Gamma, Alpha"
    window.close()


def test_window_edits_current_language_pair_and_updates_catalog_immediately(
    tmp_path: Path,
) -> None:
    QApplication.instance() or QApplication(["imgtrans-terminology-preferences-test"])
    catalog = TerminologyCatalog()
    preferences = MemoryTerminologyPreferences(
        (
            TerminologyEntry("en", "zh-Hans", "Clamp", "卡箍"),
            TerminologyEntry("zh-Hans", "en", "卡箍", "Clamp"),
        )
    )
    translate = TranslateRegions(
        MockTranslationAdapter(),
        ProtectionEngine(),
        terminology_catalog=catalog,
    )
    window = MainWindow(
        StartupSnapshot(
            ProductInfo("Image Translator", "0.1.0", "M1"),
            tmp_path / "data",
            tmp_path / "cache",
        ),
        recognize_text=RecognizeText(FixtureOcrAdapter()),
        translate_regions=translate,
        terminology_preferences=preferences,
        terminology_catalog=catalog,
    )
    window.ocr_panel.language_combo.setCurrentIndex(
        window.ocr_panel.language_combo.findData("en")
    )
    window.translation_panel.target_combo.setCurrentIndex(
        window.translation_panel.target_combo.findData("zh-Hans")
    )

    assert "Clamp => 卡箍" in window.translation_panel.terminology_editor.toPlainText()
    window.translation_panel.terminology_editor.setPlainText(
        " Ａ  B => first\nA B => second"
    )

    assert catalog.lookup("en", "zh-Hans", "A B") == "second"
    assert preferences.saved[-1][-1] == TerminologyEntry(
        "en", "zh-Hans", "A B", "second"
    )
    assert catalog.lookup("zh-Hans", "en", "卡箍") == "Clamp"
    window.close()
