import pytest

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


def _region(
    region_id: str,
    text: str,
    language: str,
    y: float,
    confidence: float = 0.95,
) -> TextRegion:
    return TextRegion(
        region_id,
        order_quad(((0, y), (200, y), (200, y + 30), (0, y + 30))),
        text,
        confidence,
        language,
        "fixture-model",
    )


class _RecordingAdapter:
    adapter_id = "recording-fixture"

    def __init__(self) -> None:
        self.calls: list[tuple[tuple[str, ...], str | None, str]] = []

    def translate(self, texts, source_language, target_language):
        self.calls.append((texts, source_language, target_language))
        return tuple(
            TranslationAdapterItem(translated_text=f"translated:{text}")
            for text in texts
        )


def test_automatic_confidence_threshold_defaults_to_point_seven_five() -> None:
    use_case = TranslateRegions(MockTranslationAdapter(), ProtectionEngine())
    assert use_case.automatic_confidence_threshold == 0.75


@pytest.mark.parametrize("threshold", (-0.0001, 1.0001))
def test_automatic_confidence_threshold_rejects_invalid_values(
    threshold: float,
) -> None:
    with pytest.raises(ValueError, match="confidence threshold"):
        TranslateRegions(
            MockTranslationAdapter(),
            ProtectionEngine(),
            automatic_confidence_threshold=threshold,
        )


def test_confidence_gate_filters_adapter_input_and_preserves_region_order() -> None:
    adapter = _RecordingAdapter()
    result = TranslateRegions(adapter, ProtectionEngine()).execute(
        OcrResult(
            (
                _region("low", "LOW", "en", 0, 0.7499),
                _region("boundary", "BOUNDARY", "en", 40, 0.75),
                _region("high", "HIGH", "en", 80, 0.90),
            ),
            "en",
            "fixture-model",
            1,
        ),
        TranslationSelection(TranslationMode.ALL, "zh-Hans"),
    )

    assert [unit.region_id for unit in result.units] == ["low", "boundary", "high"]
    review, boundary, high = result.units
    assert review.status is TranslationStatus.REVIEW_REQUIRED
    assert review.translated_text == review.source_text == "LOW"
    assert review.error_code is None
    assert review.error_message is None
    assert not review.should_erase_source
    assert boundary.status is TranslationStatus.TRANSLATED
    assert high.status is TranslationStatus.TRANSLATED
    assert adapter.calls == [
        (("BOUNDARY", "HIGH"), None, "zh-Hans"),
    ]


def test_all_low_confidence_regions_skip_adapter_and_manual_override_translates() -> None:
    adapter = _RecordingAdapter()
    use_case = TranslateRegions(adapter, ProtectionEngine())
    ocr = OcrResult(
        (
            _region("first", "FIRST", "en", 0, 0.20),
            _region("second", "SECOND", "en", 40, 0.74),
        ),
        "en",
        "fixture-model",
        1,
    )
    selection = TranslationSelection(TranslationMode.ALL, "zh-Hans")

    automatic = use_case.execute(ocr, selection)
    assert [unit.status for unit in automatic.units] == [
        TranslationStatus.REVIEW_REQUIRED,
        TranslationStatus.REVIEW_REQUIRED,
    ]
    assert adapter.calls == []

    manual = use_case.execute(ocr, selection, allow_low_confidence=True)
    assert all(
        unit.status is TranslationStatus.TRANSLATED for unit in manual.units
    )
    assert adapter.calls == [
        (("FIRST", "SECOND"), None, "zh-Hans"),
    ]


def test_language_and_fully_protected_precedence_over_confidence_gate() -> None:
    adapter = _RecordingAdapter()
    result = TranslateRegions(adapter, ProtectionEngine()).execute(
        OcrResult(
            (
                _region("wrong-language", "PROMOTION", "fr", 0, 0.20),
                _region("protected", "SKU-AB12 2026", "en", 40, 0.20),
                _region("review", "SALE", "en", 80, 0.20),
            ),
            "en",
            "fixture-model",
            1,
        ),
        TranslationSelection(
            TranslationMode.SPECIFIC_LANGUAGE,
            "zh-Hans",
            source_language="en",
        ),
    )

    assert [unit.status for unit in result.units] == [
        TranslationStatus.SKIPPED_LANGUAGE,
        TranslationStatus.SKIPPED_PROTECTED,
        TranslationStatus.REVIEW_REQUIRED,
    ]
    assert adapter.calls == []



def test_low_confidence_region_does_not_trigger_remote_language_detection() -> None:
    class _DetectingAdapter(_RecordingAdapter):
        reports_source_language = True

    adapter = _DetectingAdapter()
    result = TranslateRegions(adapter, ProtectionEngine()).execute(
        OcrResult(
            (_region("review", "LOW", "en", 0, 0.74),),
            "en",
            "fixture-model",
            1,
        ),
        TranslationSelection(TranslationMode.ALL, "zh-Hans"),
    )

    assert result.units[0].status is TranslationStatus.REVIEW_REQUIRED
    assert adapter.calls == []


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
                    translated_text="Plug*⟦0⟧",
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
