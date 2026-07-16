from src.application.translation import TranslateRegions
from src.domain.ocr import OcrResult, TextRegion, order_quad
from src.domain.protection import ProtectionEngine
from src.domain.translation import (
    TranslationAdapterItem,
    TranslationMode,
    TranslationSelection,
    TranslationStatus,
)
from src.infrastructure.mock_translator import MockTranslationAdapter


def _ocr(text: str) -> OcrResult:
    region = TextRegion(
        "r1",
        order_quad(((0, 0), (300, 0), (300, 40), (0, 40))),
        text,
        1,
        "en",
        "fixture",
    )
    return OcrResult((region,), "en", "fixture", 0)


def test_mock_translator_is_deterministic_and_preserves_placeholders() -> None:
    use_case = TranslateRegions(MockTranslationAdapter(), ProtectionEngine())
    selection = TranslationSelection(TranslationMode.ALL, "zh-Hans")
    first = use_case.execute(_ocr("PRODUCT X100 25%"), selection)
    second = use_case.execute(_ocr("PRODUCT X100 25%"), selection)
    assert first.units[0].translated_text == "商品 X100 25%"
    assert second.units[0].translated_text == first.units[0].translated_text
    assert first.provider == "mock-local"


class DamagingAdapter:
    adapter_id = "damaging"

    def translate(self, texts: tuple[str, ...], source_language: str | None, target_language: str):
        del texts, source_language, target_language
        return (TranslationAdapterItem(translated_text="占位符丢失"),)


def test_damaged_protection_placeholder_fails_without_corrupting_text() -> None:
    use_case = TranslateRegions(DamagingAdapter(), ProtectionEngine())
    result = use_case.execute(
        _ocr("PRODUCT X100"),
        TranslationSelection(TranslationMode.ALL, "zh-Hans"),
    )
    assert result.units[0].status is TranslationStatus.FAILED
    assert result.units[0].translated_text == "PRODUCT X100"
    assert result.units[0].error_code == "placeholder_damaged"
    assert not result.units[0].should_erase_source
