import pytest
from dataclasses import replace
from math import cos, radians, sin

from src.application.translation import TranslateRegions
from src.domain.ocr import (
    OcrMode,
    OcrObservation,
    OcrResult,
    TextRegion,
    order_quad,
)
from src.domain.protection import ProtectionEngine, ProtectionKind
from src.domain.terminology import TerminologyCatalog, TerminologyEntry
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


def _enhanced_region(
    region_id: str,
    text: str,
    y: float,
    confidence: float,
    *,
    auto_process_eligible: bool,
) -> TextRegion:
    region = _region(region_id, text, "en", y, confidence)
    observations = tuple(
        OcrObservation(
            "polar",
            0,
            scale,
            confidence,
            region.polygon,
            text,
            f"view-{region_id}-{scale}",
        )
        for scale in (2, 3)
    )
    return replace(
        region,
        enhanced_only=True,
        auto_process_eligible=auto_process_eligible,
        observations=observations,
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


class _ChineseRecordingAdapter(_RecordingAdapter):
    def __init__(self, translations: dict[str, str]) -> None:
        super().__init__()
        self._translations = translations

    def translate(self, texts, source_language, target_language):
        self.calls.append((texts, source_language, target_language))
        return tuple(
            TranslationAdapterItem(
                translated_text=self._translations.get(text, text)
            )
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


def test_unconfirmed_enhanced_region_never_calls_adapter_until_manual_confirmation() -> None:
    adapter = _RecordingAdapter()
    use_case = TranslateRegions(adapter, ProtectionEngine())
    enhanced = replace(
        _region("enhanced", "ROTATED", "en", 0, 0.99),
        enhanced_only=True,
        auto_process_eligible=False,
    )
    ocr = OcrResult((enhanced,), "en", "fixture-model", 1)
    selection = TranslationSelection(TranslationMode.ALL, "zh-Hans")

    automatic = use_case.execute(ocr, selection)
    assert automatic.units[0].status is TranslationStatus.REVIEW_REQUIRED
    assert not automatic.units[0].should_erase_source
    assert adapter.calls == []

    confirmed = use_case.execute(
        OcrResult(
            (replace(enhanced, auto_process_eligible=True),),
            "en",
            "fixture-model",
            1,
        ),
        selection,
    )
    assert confirmed.units[0].status is TranslationStatus.TRANSLATED
    assert adapter.calls == [(("ROTATED",), None, "zh-Hans")]


def test_standard_candidate_in_high_recall_mode_uses_normal_confidence_gate() -> None:
    adapter = _RecordingAdapter()
    use_case = TranslateRegions(adapter, ProtectionEngine())
    candidate = replace(
        _region("standard", "ROTATED", "en", 0, 0.99),
        auto_process_eligible=False,
    )
    ocr = OcrResult(
        (candidate,),
        "en",
        "fixture-model",
        1,
        OcrMode.HIGH_RECALL,
    )

    result = use_case.execute(
        ocr,
        TranslationSelection(TranslationMode.ALL, "zh-Hans"),
    )

    assert result.units[0].status is TranslationStatus.TRANSLATED
    assert result.units[0].should_erase_source
    assert adapter.calls == [(("ROTATED",), None, "zh-Hans")]


def test_high_recall_enhanced_candidate_preserves_source_when_chinese_is_missing() -> None:
    adapter = _RecordingAdapter()
    candidate = replace(
        _region("enhanced", "NETWORKING", "en", 0, 0.96),
        enhanced_only=True,
        auto_process_eligible=True,
    )

    result = TranslateRegions(adapter, ProtectionEngine()).execute(
        OcrResult(
            (candidate,),
            "en",
            "fixture-model",
            1,
            OcrMode.HIGH_RECALL,
        ),
        TranslationSelection(TranslationMode.ALL, "zh-Hans"),
    )

    unit = result.units[0]
    assert unit.status is TranslationStatus.REVIEW_REQUIRED
    assert unit.translated_text == unit.source_text
    assert not unit.should_erase_source
    assert adapter.calls == [(("NETWORKING",), None, "zh-Hans")]


def test_high_recall_repeated_candidate_uses_existing_translation_without_extra_call() -> None:
    adapter = _ChineseRecordingAdapter({"Sales": "销售"})
    result = TranslateRegions(adapter, ProtectionEngine()).execute(
        OcrResult(
            (
                _enhanced_region(
                    "reference",
                    "Sales",
                    0,
                    0.93,
                    auto_process_eligible=True,
                ),
                _enhanced_region(
                    "recovered",
                    "Sates",
                    40,
                    0.84,
                    auto_process_eligible=False,
                ),
            ),
            "en",
            "fixture-model",
            1,
            OcrMode.HIGH_RECALL,
        ),
        TranslationSelection(
            TranslationMode.SPECIFIC_LANGUAGE,
            "zh-Hans",
            source_language="en",
        ),
    )

    assert [unit.region_id for unit in result.units] == [
        "reference",
        "recovered",
    ]
    assert [unit.status for unit in result.units] == [
        TranslationStatus.TRANSLATED,
        TranslationStatus.TRANSLATED,
    ]
    assert result.units[1].translated_text == "销售"
    assert adapter.calls == [(("Sales",), "en", "zh-Hans")]


def test_high_recall_target_script_failure_can_reuse_repeated_translation() -> None:
    adapter = _ChineseRecordingAdapter(
        {
            "Import": "进口",
            "imgort": "imgort",
        }
    )
    result = TranslateRegions(adapter, ProtectionEngine()).execute(
        OcrResult(
            (
                _enhanced_region(
                    "reference",
                    "Import",
                    0,
                    0.93,
                    auto_process_eligible=True,
                ),
                _enhanced_region(
                    "recovered",
                    "imgort",
                    40,
                    0.88,
                    auto_process_eligible=True,
                ),
            ),
            "en",
            "fixture-model",
            1,
            OcrMode.HIGH_RECALL,
        ),
        TranslationSelection(
            TranslationMode.SPECIFIC_LANGUAGE,
            "zh-Hans",
            source_language="en",
        ),
    )

    assert [unit.status for unit in result.units] == [
        TranslationStatus.TRANSLATED,
        TranslationStatus.TRANSLATED,
    ]
    assert result.units[1].translated_text == "进口"
    assert adapter.calls == [
        (("Import", "imgort"), "en", "zh-Hans"),
    ]


def test_high_recall_unmatched_candidate_remains_review_required() -> None:
    adapter = _ChineseRecordingAdapter({"Sales": "销售"})
    result = TranslateRegions(adapter, ProtectionEngine()).execute(
        OcrResult(
            (
                _enhanced_region(
                    "reference",
                    "Sales",
                    0,
                    0.93,
                    auto_process_eligible=True,
                ),
                _enhanced_region(
                    "unmatched",
                    "Prei",
                    40,
                    0.88,
                    auto_process_eligible=False,
                ),
            ),
            "en",
            "fixture-model",
            1,
            OcrMode.HIGH_RECALL,
        ),
        TranslationSelection(
            TranslationMode.SPECIFIC_LANGUAGE,
            "zh-Hans",
            source_language="en",
        ),
    )

    assert result.units[1].status is TranslationStatus.REVIEW_REQUIRED
    assert result.units[1].translated_text == "Prei"
    assert not result.units[1].should_erase_source
    assert adapter.calls == [(("Sales",), "en", "zh-Hans")]


def test_high_recall_candidate_prefers_closest_repeated_spelling() -> None:
    adapter = _ChineseRecordingAdapter(
        {
            "Export": "出口",
            "Eport": "体育",
        }
    )
    result = TranslateRegions(adapter, ProtectionEngine()).execute(
        OcrResult(
            (
                _enhanced_region(
                    "export-reference",
                    "Export",
                    0,
                    0.93,
                    auto_process_eligible=True,
                ),
                _enhanced_region(
                    "eport-reference",
                    "Eport",
                    40,
                    0.94,
                    auto_process_eligible=True,
                ),
                _enhanced_region(
                    "ambiguous",
                    "Expert",
                    80,
                    0.88,
                    auto_process_eligible=False,
                ),
            ),
            "en",
            "fixture-model",
            1,
            OcrMode.HIGH_RECALL,
        ),
        TranslationSelection(
            TranslationMode.SPECIFIC_LANGUAGE,
            "zh-Hans",
            source_language="en",
        ),
    )

    assert result.units[2].status is TranslationStatus.TRANSLATED
    assert result.units[2].translated_text == "出口"
    assert adapter.calls == [
        (("Export", "Eport"), "en", "zh-Hans"),
    ]


def test_high_recall_repeated_majority_recovers_noisy_spelling() -> None:
    adapter = _ChineseRecordingAdapter({"Success": "成功"})
    result = TranslateRegions(adapter, ProtectionEngine()).execute(
        OcrResult(
            (
                _enhanced_region(
                    "reference-1",
                    "Success",
                    0,
                    0.93,
                    auto_process_eligible=True,
                ),
                _enhanced_region(
                    "reference-2",
                    "Success",
                    40,
                    0.94,
                    auto_process_eligible=True,
                ),
                _enhanced_region(
                    "recovered",
                    "saccezs",
                    80,
                    0.95,
                    auto_process_eligible=True,
                ),
            ),
            "en",
            "fixture-model",
            1,
            OcrMode.HIGH_RECALL,
        ),
        TranslationSelection(
            TranslationMode.SPECIFIC_LANGUAGE,
            "zh-Hans",
            source_language="en",
        ),
    )

    assert result.units[2].status is TranslationStatus.TRANSLATED
    assert result.units[2].translated_text == "成功"
    assert adapter.calls == [
        (("Success", "Success", "saccezs"), "en", "zh-Hans"),
    ]


def test_high_recall_unanimous_long_candidate_can_translate() -> None:
    adapter = _ChineseRecordingAdapter({"Opportunnty": "机会"})
    candidate = _enhanced_region(
        "stable",
        "Opportunnty",
        0,
        0.8204,
        auto_process_eligible=False,
    )
    candidate = replace(
        candidate,
        observations=candidate.observations
        + (
            replace(
                candidate.observations[0],
                scale=4,
                view_id="view-stable-4",
            ),
        ),
    )

    result = TranslateRegions(adapter, ProtectionEngine()).execute(
        OcrResult(
            (candidate,),
            "en",
            "fixture-model",
            1,
            OcrMode.HIGH_RECALL,
        ),
        TranslationSelection(
            TranslationMode.SPECIFIC_LANGUAGE,
            "zh-Hans",
            source_language="en",
        ),
    )

    assert result.units[0].status is TranslationStatus.TRANSLATED
    assert result.units[0].translated_text == "机会"
    assert adapter.calls == [(("Opportunnty",), "en", "zh-Hans")]


def test_high_recall_short_or_disagreed_candidate_stays_review_required() -> None:
    adapter = _ChineseRecordingAdapter({"kgort": "未知"})
    candidate = _enhanced_region(
        "short",
        "kgort",
        0,
        0.88,
        auto_process_eligible=False,
    )
    candidate = replace(
        candidate,
        observations=candidate.observations
        + (
            replace(
                candidate.observations[0],
                scale=4,
                view_id="view-short-4",
            ),
        ),
    )

    result = TranslateRegions(adapter, ProtectionEngine()).execute(
        OcrResult(
            (candidate,),
            "en",
            "fixture-model",
            1,
            OcrMode.HIGH_RECALL,
        ),
        TranslationSelection(
            TranslationMode.SPECIFIC_LANGUAGE,
            "zh-Hans",
            source_language="en",
        ),
    )

    assert result.units[0].status is TranslationStatus.REVIEW_REQUIRED
    assert adapter.calls == []


def test_repeated_high_confidence_region_corroborates_borderline_curved_label() -> None:
    adapter = _RecordingAdapter()

    def repeated_region(
        region_id: str,
        text: str,
        confidence: float,
        y: float,
        width: float,
        height: float,
    ) -> TextRegion:
        angle = radians(-24)
        horizontal = (cos(angle) * width, sin(angle) * width)
        vertical = (-sin(angle) * height, cos(angle) * height)
        return TextRegion(
            region_id,
            order_quad(
                (
                    (40, y),
                    (40 + horizontal[0], y + horizontal[1]),
                    (
                        40 + horizontal[0] + vertical[0],
                        y + horizontal[1] + vertical[1],
                    ),
                    (40 + vertical[0], y + vertical[1]),
                )
            ),
            text,
            confidence,
            "zh-Hans",
            "fixture-model",
        )

    result = TranslateRegions(adapter, ProtectionEngine()).execute(
        OcrResult(
            (
                repeated_region(
                    "reliable",
                    "干湿两用柔软亲肤",
                    0.82,
                    80,
                    120,
                    50,
                ),
                repeated_region(
                    "corroborated",
                    "干温雨用柔软亲肤",
                    0.711,
                    180,
                    108,
                    47,
                ),
                repeated_region(
                    "unmatched",
                    "完全不同低置信文字",
                    0.72,
                    280,
                    110,
                    48,
                ),
            ),
            "zh-Hans",
            "fixture-model",
            1,
        ),
        TranslationSelection(TranslationMode.ALL, "en"),
    )

    assert [unit.status for unit in result.units] == [
        TranslationStatus.TRANSLATED,
        TranslationStatus.TRANSLATED,
        TranslationStatus.REVIEW_REQUIRED,
    ]
    assert adapter.calls == [
        (("干湿两用柔软亲肤", "干温雨用柔软亲肤"), None, "en"),
    ]


def test_dense_horizontal_artwork_uses_per_region_confidence_gate() -> None:
    adapter = _RecordingAdapter()
    use_case = TranslateRegions(adapter, ProtectionEngine())
    ocr = OcrResult(
        tuple(
            _region(f"dense-{index}", f"WORD {index}", "en", index * 4)
            for index in range(60)
        ),
        "en",
        "fixture-model",
        1,
    )
    selection = TranslationSelection(TranslationMode.ALL, "zh-Hans")

    assert all(
        unit.status is TranslationStatus.TRANSLATED
        for unit in use_case.execute(ocr, selection).units
    )
    assert len(adapter.calls) == 1
    assert len(adapter.calls[0][0]) == 60


def test_dense_artwork_corroborates_repeated_short_cjk_text() -> None:
    adapter = _RecordingAdapter()
    canonical = "\u54c1\u8d28"
    regions = [
        _region(f"reliable-{index}", canonical, "zh-Hans", index * 40)
        for index in range(5)
    ]
    regions.extend(
        (
            _region("exact-low", canonical, "zh-Hans", 220, 0.55),
            TextRegion(
                "fuzzy-low",
                order_quad(((0, 260), (420, 260), (420, 330), (0, 330))),
                "\u54c1\u79e9",
                0.70,
                "zh-Hans",
                "fixture-model",
            ),
            _region("fuzzy-high", "\u54c1\u79e7", "zh-Hans", 280, 0.86),
            _region("unmatched-low", "\u69bb\u79e7", "zh-Hans", 300, 0.70),
        )
    )
    regions.extend(
        _region(f"filler-{index}", f"TEXT {index}", "zh-Hans", 340 + index * 40)
        for index in range(32)
    )

    result = TranslateRegions(adapter, ProtectionEngine()).execute(
        OcrResult(tuple(regions), "zh-Hans", "fixture-model", 1),
        TranslationSelection(TranslationMode.ALL, "en"),
    )
    units = {unit.region_id: unit for unit in result.units}

    assert units["exact-low"].status is TranslationStatus.TRANSLATED
    assert units["exact-low"].source_text == canonical
    assert units["fuzzy-low"].status is TranslationStatus.TRANSLATED
    assert units["fuzzy-low"].source_text == canonical
    assert units["fuzzy-high"].status is TranslationStatus.TRANSLATED
    assert units["fuzzy-high"].source_text == canonical
    assert units["unmatched-low"].status is TranslationStatus.REVIEW_REQUIRED
    assert adapter.calls[0][0].count(canonical) == 8


def test_rotated_word_cloud_translates_only_high_confidence_regions() -> None:
    adapter = _RecordingAdapter()

    def rotated_region(index: int) -> TextRegion:
        angle = radians(30)
        center_x = 120 + index * 3
        center_y = 80 + index * 4
        horizontal = (cos(angle) * 40, sin(angle) * 40)
        vertical = (-sin(angle) * 10, cos(angle) * 10)
        return TextRegion(
            f"rotated-{index}",
            order_quad(
                (
                    (
                        center_x - horizontal[0] - vertical[0],
                        center_y - horizontal[1] - vertical[1],
                    ),
                    (
                        center_x + horizontal[0] - vertical[0],
                        center_y + horizontal[1] - vertical[1],
                    ),
                    (
                        center_x + horizontal[0] + vertical[0],
                        center_y + horizontal[1] + vertical[1],
                    ),
                    (
                        center_x - horizontal[0] + vertical[0],
                        center_y - horizontal[1] + vertical[1],
                    ),
                )
            ),
            f"WORD {index}",
            0.85 if index == 0 else 0.99,
            "en",
            "fixture-model",
        )

    result = TranslateRegions(adapter, ProtectionEngine()).execute(
        OcrResult(
            tuple(rotated_region(index) for index in range(12)),
            "en",
            "fixture-model",
            1,
        ),
        TranslationSelection(TranslationMode.ALL, "zh-Hans"),
    )

    assert result.units[0].status is TranslationStatus.REVIEW_REQUIRED
    assert all(
        unit.status is TranslationStatus.TRANSLATED for unit in result.units[1:]
    )
    assert len(adapter.calls) == 1
    assert len(adapter.calls[0][0]) == 11


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


def test_brand_terms_skip_fully_protected_regions_and_restore_partial_spans() -> None:
    adapter = _RecordingAdapter()
    result = TranslateRegions(adapter, ProtectionEngine()).execute(
        OcrResult(
            (
                _region("full", "Alpha", "en", 0),
                _region("partial", "Alpha SALE", "en", 40),
            ),
            "en",
            "fixture-model",
            1,
        ),
        TranslationSelection(TranslationMode.ALL, "zh-Hans"),
        ("Alpha",),
    )

    assert result.units[0].status is TranslationStatus.SKIPPED_PROTECTED
    assert result.units[0].translated_text == "Alpha"
    assert result.units[1].status is TranslationStatus.TRANSLATED
    assert result.units[1].translated_text == "translated:Alpha SALE"
    assert adapter.calls == [
        (('<x id="0"/> SALE',), None, "zh-Hans"),
    ]


def test_exact_terminology_overrides_complete_region_without_adapter_call() -> None:
    adapter = _RecordingAdapter()
    catalog = TerminologyCatalog(
        (
            TerminologyEntry(
                "zh-Hans",
                "en",
                "50-75管通用",
                "Fits 50–75 mm Pipes",
            ),
        )
    )
    result = TranslateRegions(
        adapter,
        ProtectionEngine(),
        terminology_catalog=catalog,
    ).execute(
        OcrResult(
            (
                _region("term", "50-75管通用", "zh-Hans", 0),
                _region("ordinary", "普通文字", "zh-Hans", 40),
            ),
            "zh-Hans",
            "fixture-model",
            1,
        ),
        TranslationSelection(TranslationMode.ALL, "en"),
    )

    assert result.units[0].status is TranslationStatus.TRANSLATED
    assert result.units[0].translated_text == "Fits 50–75 mm Pipes"
    assert adapter.calls == [(('普通文字',), None, "en")]


def test_terminology_requires_complete_match_and_enabled_entry() -> None:
    adapter = _RecordingAdapter()
    catalog = TerminologyCatalog(
        (
            TerminologyEntry("en", "zh-Hans", "Clamp", "卡箍"),
            TerminologyEntry(
                "en", "zh-Hans", "Disabled", "禁用", enabled=False
            ),
        )
    )
    result = TranslateRegions(
        adapter,
        ProtectionEngine(),
        terminology_catalog=catalog,
    ).execute(
        OcrResult(
            (
                _region("substring", "Clamp set", "en", 0),
                _region("disabled", "Disabled", "en", 40),
            ),
            "en",
            "fixture-model",
            1,
        ),
        TranslationSelection(TranslationMode.ALL, "zh-Hans"),
    )

    assert [unit.translated_text for unit in result.units] == [
        "translated:Clamp set",
        "translated:Disabled",
    ]
    assert adapter.calls == [(('Clamp set', 'Disabled'), None, "zh-Hans")]


def test_brand_protection_precedes_exact_terminology() -> None:
    adapter = _RecordingAdapter()
    catalog = TerminologyCatalog(
        (
            TerminologyEntry("en", "zh-Hans", "Alpha", "错误覆盖"),
            TerminologyEntry("en", "zh-Hans", "Alpha SALE", "错误覆盖"),
        )
    )
    result = TranslateRegions(
        adapter,
        ProtectionEngine(),
        terminology_catalog=catalog,
    ).execute(
        OcrResult(
            (
                _region("full", "Alpha", "en", 0),
                _region("partial", "Alpha SALE", "en", 40),
            ),
            "en",
            "fixture-model",
            1,
        ),
        TranslationSelection(TranslationMode.ALL, "zh-Hans"),
        ("Alpha",),
    )

    assert result.units[0].status is TranslationStatus.SKIPPED_PROTECTED
    assert result.units[1].translated_text == "translated:Alpha SALE"
    assert adapter.calls == [(('<x id="0"/> SALE',), None, "zh-Hans")]


def test_review_precedes_terminology_and_manual_override_can_use_term() -> None:
    adapter = _RecordingAdapter()
    catalog = TerminologyCatalog(
        (TerminologyEntry("en", "zh-Hans", "Clamp", "卡箍"),)
    )
    use_case = TranslateRegions(
        adapter,
        ProtectionEngine(),
        terminology_catalog=catalog,
    )
    ocr = OcrResult(
        (_region("low", "Clamp", "en", 0, 0.74),),
        "en",
        "fixture-model",
        1,
    )
    selection = TranslationSelection(TranslationMode.ALL, "zh-Hans")

    automatic = use_case.execute(ocr, selection)
    manual = use_case.execute(ocr, selection, allow_low_confidence=True)

    assert automatic.units[0].status is TranslationStatus.REVIEW_REQUIRED
    assert manual.units[0].status is TranslationStatus.TRANSLATED
    assert manual.units[0].translated_text == "卡箍"
    assert adapter.calls == []


def test_local_language_skip_precedes_exact_terminology() -> None:
    adapter = _RecordingAdapter()
    catalog = TerminologyCatalog(
        (TerminologyEntry("fr", "zh-Hans", "Clamp", "错误覆盖"),)
    )
    result = TranslateRegions(
        adapter,
        ProtectionEngine(),
        terminology_catalog=catalog,
    ).execute(
        OcrResult(
            (_region("wrong-language", "Clamp", "fr", 0),),
            "fr",
            "fixture-model",
            1,
        ),
        TranslationSelection(
            TranslationMode.SPECIFIC_LANGUAGE,
            "zh-Hans",
            source_language="en",
        ),
    )

    assert result.units[0].status is TranslationStatus.SKIPPED_LANGUAGE
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


def test_specific_source_language_is_authoritative_for_detecting_adapter() -> None:
    class _DetectingAdapter(_RecordingAdapter):
        reports_source_language = True

        def translate(self, texts, source_language, target_language):
            self.calls.append((texts, source_language, target_language))
            return tuple(
                TranslationAdapterItem(
                    translated_text=f"translated:{text}",
                    source_language=source_language,
                )
                for text in texts
            )

    adapter = _DetectingAdapter()
    result = TranslateRegions(adapter, ProtectionEngine()).execute(
        OcrResult(
            (
                _region("english", "SALES", "en", 0),
                _region("other-language", "VENTES", "fr", 40),
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
        TranslationStatus.TRANSLATED,
        TranslationStatus.SKIPPED_LANGUAGE,
    ]
    assert adapter.calls == [(("SALES",), "en", "zh-Hans")]


def test_all_language_mode_still_requests_remote_auto_detection() -> None:
    class _DetectingAdapter(_RecordingAdapter):
        reports_source_language = True

    adapter = _DetectingAdapter()
    TranslateRegions(adapter, ProtectionEngine()).execute(
        OcrResult(
            (_region("english", "SALES", "en", 0),),
            "en",
            "fixture-model",
            1,
        ),
        TranslationSelection(TranslationMode.ALL, "zh-Hans"),
    )

    assert adapter.calls == [(("SALES",), None, "zh-Hans")]


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
