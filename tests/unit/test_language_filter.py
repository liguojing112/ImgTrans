from src.application.translation import TranslateRegions
from src.domain.ocr import OcrResult, TextRegion, order_quad
from src.domain.protection import ProtectionEngine, ProtectionKind
from src.domain.translation import (
    TranslationMode,
    TranslationSelection,
    TranslationStatus,
)
from src.infrastructure.mock_translator import MockTranslationAdapter


def _region(region_id: str, text: str, language: str, y: float) -> TextRegion:
    return TextRegion(
        region_id,
        order_quad(((0, y), (200, y), (200, y + 30), (0, y + 30))),
        text,
        0.95,
        language,
        "fixture-model",
    )


def test_specific_language_filter_and_protection_statuses() -> None:
    ocr = OcrResult(
        (
            _region("r1", "ACME X100 25% OFF", "en", 0),
            _region("r2", "PROMOTION", "fr", 40),
            _region("r3", "SKU-AB12 2026", "en", 80),
        ),
        "en",
        "fixture-model",
        10,
    )
    selection = TranslationSelection(
        TranslationMode.SPECIFIC_LANGUAGE, "zh-Hans", source_language="en"
    )
    result = TranslateRegions(MockTranslationAdapter(), ProtectionEngine()).execute(
        ocr, selection, ("ACME",)
    )
    translated, wrong_language, fully_protected = result.units
    assert translated.status is TranslationStatus.TRANSLATED
    assert translated.translated_text == "ACME X100 25% 优惠"
    assert translated.should_erase_source
    assert {span.kind for span in translated.protected_spans} == {
        ProtectionKind.BRAND,
        ProtectionKind.MODEL,
        ProtectionKind.NUMBER,
    }
    assert wrong_language.status is TranslationStatus.SKIPPED_LANGUAGE
    assert wrong_language.translated_text == wrong_language.source_text
    assert not wrong_language.should_erase_source
    assert fully_protected.status is TranslationStatus.SKIPPED_PROTECTED
    assert not fully_protected.should_erase_source


def test_all_language_mode_translates_every_non_protected_region() -> None:
    ocr = OcrResult(
        (_region("r1", "SUMMER SALE", "en", 0), _region("r2", "商品", "zh-Hans", 40)),
        "en",
        "fixture-model",
        1,
    )
    selection = TranslationSelection(TranslationMode.ALL, "zh-Hans")
    result = TranslateRegions(MockTranslationAdapter(), ProtectionEngine()).execute(ocr, selection)
    assert len(result.units) == 2
    assert all(unit.status is TranslationStatus.TRANSLATED for unit in result.units)
