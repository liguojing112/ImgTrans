from src.application.translation import TranslateRegions
from src.domain.ocr import OcrResult, TextRegion, order_quad
from src.domain.protection import ProtectionEngine, ProtectionKind
from src.domain.translation import (
    TranslationAdapterItem,
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


def test_all_language_mode_preserves_regions_already_in_target_language() -> None:
    ocr = OcrResult(
        (_region("r1", "SUMMER SALE", "en", 0), _region("r2", "商品", "zh-Hans", 40)),
        "en",
        "fixture-model",
        1,
    )
    selection = TranslationSelection(TranslationMode.ALL, "zh-Hans")
    result = TranslateRegions(MockTranslationAdapter(), ProtectionEngine()).execute(ocr, selection)
    assert len(result.units) == 2
    assert result.units[0].status is TranslationStatus.TRANSLATED
    assert result.units[1].status is TranslationStatus.SKIPPED_LANGUAGE
    assert not result.units[1].should_erase_source


def test_short_cjk_text_retries_when_auto_detection_claims_target_language() -> None:
    class _DetectingAdapter:
        adapter_id = "detecting-fixture"
        reports_source_language = True

        def __init__(self) -> None:
            self.calls = []

        def translate(self, texts, source_language, target_language):
            self.calls.append((texts, source_language, target_language))
            if source_language is None:
                return (
                    TranslationAdapterItem(
                        translated_text=texts[0],
                        source_language="en",
                    ),
                )
            return (
                TranslationAdapterItem(
                    translated_text='Plug*<x id="0"/>',
                    source_language="zh-Hans",
                ),
            )

    adapter = _DetectingAdapter()
    ocr = OcrResult(
        (_region("r1", "堵头*2", "zh-Hans", 0),),
        "zh-Hans",
        "fixture-model",
        1,
    )
    result = TranslateRegions(adapter, ProtectionEngine()).execute(
        ocr,
        TranslationSelection(TranslationMode.ALL, "en"),
    )

    assert result.units[0].status is TranslationStatus.TRANSLATED
    assert result.units[0].translated_text == "Plug*2"
    assert [call[1] for call in adapter.calls] == [None, "zh-Hans"]
