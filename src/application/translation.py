from __future__ import annotations

from dataclasses import replace
from difflib import SequenceMatcher
from math import atan2, degrees
from time import perf_counter

from src.application.ports import TranslationAdapter
from src.domain.language import SUPPORTED_LANGUAGE_CODES
from src.domain.ocr import OcrResult, TextRegion
from src.domain.protection import (
    ProtectedText,
    ProtectionEngine,
    ProtectionError,
    ProtectionKind,
)
from src.domain.terminology import TerminologyCatalog
from src.domain.translation import (
    TranslationAdapterItem,
    TranslationError,
    TranslationResult,
    TranslationSelection,
    TranslationStatus,
    TranslationUnit,
)


class TranslateRegions:
    def __init__(
        self,
        adapter: TranslationAdapter,
        protection: ProtectionEngine,
        automatic_confidence_threshold: float = 0.75,
        terminology_catalog: TerminologyCatalog | None = None,
    ) -> None:
        if not 0 <= automatic_confidence_threshold <= 1:
            raise ValueError(
                "Automatic translation confidence threshold must be between zero and one"
            )
        self._adapter = adapter
        self._protection = protection
        self._automatic_confidence_threshold = automatic_confidence_threshold
        self._terminology_catalog = terminology_catalog or TerminologyCatalog()

    @property
    def language_codes(self) -> tuple[str, ...]:
        return SUPPORTED_LANGUAGE_CODES

    @property
    def adapter_id(self) -> str:
        return self._adapter.adapter_id

    @property
    def automatic_confidence_threshold(self) -> float:
        return self._automatic_confidence_threshold

    @property
    def terminology_catalog(self) -> TerminologyCatalog:
        return self._terminology_catalog

    def execute(
        self,
        ocr_result: OcrResult,
        selection: TranslationSelection,
        brand_terms: tuple[str, ...] = (),
        allow_low_confidence: bool = False,
    ) -> TranslationResult:
        started = perf_counter()
        units: list[TranslationUnit | None] = [None] * len(ocr_result.regions)
        prepared: list[tuple[int, TextRegion, ProtectedText]] = []
        reports_source_language = bool(
            getattr(self._adapter, "reports_source_language", False)
        )
        complex_layout_review = (
            not allow_low_confidence
            and _requires_rotated_layout_review(ocr_result)
        )
        corroborated_regions = _corroborated_low_confidence_regions(
            ocr_result,
            self._automatic_confidence_threshold,
        )
        for index, region in enumerate(ocr_result.regions):
            if (
                selection.source_language is not None
                and not reports_source_language
                and region.language_code != selection.source_language
            ):
                units[index] = self._skipped_unit(
                    region, selection.target_language, TranslationStatus.SKIPPED_LANGUAGE
                )
                continue
            corroborated_text = corroborated_regions.get(region.region_id)
            if corroborated_text is not None:
                region = replace(region, text=corroborated_text)
            protected = self._protection.protect(region.text, brand_terms)
            if protected.fully_protected:
                units[index] = TranslationUnit(
                    region.region_id,
                    region.text,
                    region.language_code,
                    selection.target_language,
                    region.text,
                    TranslationStatus.SKIPPED_PROTECTED,
                    protected.spans,
                )
                continue
            if (
                not allow_low_confidence
                and region.enhanced_only
                and not region.auto_process_eligible
            ):
                units[index] = TranslationUnit(
                    region.region_id,
                    region.text,
                    region.language_code,
                    selection.target_language,
                    region.text,
                    TranslationStatus.REVIEW_REQUIRED,
                    protected.spans,
                )
                continue
            if (
                complex_layout_review
                and region.confidence < max(
                    0.9,
                    self._automatic_confidence_threshold,
                )
            ):
                units[index] = TranslationUnit(
                    region.region_id,
                    region.text,
                    region.language_code,
                    selection.target_language,
                    region.text,
                    TranslationStatus.REVIEW_REQUIRED,
                    protected.spans,
                )
                continue
            if (
                not allow_low_confidence
                and region.confidence < self._automatic_confidence_threshold
                and region.region_id not in corroborated_regions
            ):
                units[index] = TranslationUnit(
                    region.region_id,
                    region.text,
                    region.language_code,
                    selection.target_language,
                    region.text,
                    TranslationStatus.REVIEW_REQUIRED,
                    protected.spans,
                )
                continue
            has_brand_protection = any(
                span.kind is ProtectionKind.BRAND for span in protected.spans
            )
            terminology_text = (
                None
                if has_brand_protection
                else self._terminology_catalog.lookup(
                    selection.source_language or region.language_code,
                    selection.target_language,
                    region.text,
                )
            )
            if terminology_text is not None:
                units[index] = TranslationUnit(
                    region.region_id,
                    region.text,
                    selection.source_language or region.language_code,
                    selection.target_language,
                    terminology_text,
                    TranslationStatus.TRANSLATED,
                    protected.spans,
                )
                continue
            prepared.append((index, region, protected))
        if prepared:
            source_language = (
                None if reports_source_language else selection.source_language
            )
            try:
                translated = self._adapter.translate(
                    tuple(item[2].masked for item in prepared),
                    source_language,
                    selection.target_language,
                )
            except TranslationError:
                raise
            except Exception as error:
                raise TranslationError("adapter_failed", f"翻译服务失败：{error}") from error
            if len(translated) != len(prepared):
                raise TranslationError("invalid_adapter_result", "翻译结果数量与请求数量不一致")
            if any(not isinstance(item, TranslationAdapterItem) for item in translated):
                raise TranslationError(
                    "invalid_adapter_result",
                    "翻译适配器返回了无效逐项结果",
                )
            if reports_source_language:
                translated = self._retry_script_mismatches(
                    prepared,
                    translated,
                    selection.target_language,
                )
            for (index, region, protected), adapter_item in zip(
                prepared, translated, strict=True
            ):
                detected_source = (
                    adapter_item.source_language or region.language_code
                )
                if adapter_item.error_code is not None:
                    units[index] = TranslationUnit(
                        region.region_id,
                        region.text,
                        detected_source,
                        selection.target_language,
                        region.text,
                        TranslationStatus.FAILED,
                        protected.spans,
                        adapter_item.error_code,
                        adapter_item.error_message,
                    )
                    continue
                if (
                    selection.source_language is not None
                    and detected_source != selection.source_language
                ) or (
                    selection.source_language is None
                    and detected_source == selection.target_language
                ):
                    units[index] = self._skipped_unit(
                        region,
                        selection.target_language,
                        TranslationStatus.SKIPPED_LANGUAGE,
                        detected_source,
                    )
                    continue
                try:
                    restored = protected.restore(adapter_item.translated_text or "")
                except ProtectionError as error:
                    units[index] = TranslationUnit(
                        region.region_id,
                        region.text,
                        detected_source,
                        selection.target_language,
                        region.text,
                        TranslationStatus.FAILED,
                        protected.spans,
                        "placeholder_damaged",
                        str(error),
                    )
                    continue
                units[index] = TranslationUnit(
                    region.region_id,
                    region.text,
                    detected_source,
                    selection.target_language,
                    restored,
                    TranslationStatus.TRANSLATED,
                    protected.spans,
                )
        completed = tuple(unit for unit in units if unit is not None)
        return TranslationResult(
            completed,
            selection,
            self._adapter.adapter_id,
            (perf_counter() - started) * 1000,
        )

    def _retry_script_mismatches(
        self,
        prepared: list[tuple[int, TextRegion, ProtectedText]],
        translated: tuple[TranslationAdapterItem, ...],
        target_language: str,
    ) -> tuple[TranslationAdapterItem, ...]:
        groups: dict[str, list[int]] = {}
        for position, ((_, region, _), item) in enumerate(
            zip(prepared, translated, strict=True)
        ):
            obvious_source = _obvious_script_language(
                region.text,
                region.language_code,
            )
            if (
                item.error_code is None
                and item.source_language == target_language
                and obvious_source is not None
                and obvious_source != target_language
            ):
                groups.setdefault(obvious_source, []).append(position)
        if not groups:
            return translated
        values = list(translated)
        for source_language, positions in groups.items():
            retried = self._adapter.translate(
                tuple(prepared[position][2].masked for position in positions),
                source_language,
                target_language,
            )
            if len(retried) != len(positions) or any(
                not isinstance(item, TranslationAdapterItem) for item in retried
            ):
                raise TranslationError(
                    "invalid_adapter_result",
                    "翻译适配器返回了无效重试结果",
                )
            for position, item in zip(positions, retried, strict=True):
                values[position] = item
        return tuple(values)

    @staticmethod
    def _skipped_unit(
        region: TextRegion,
        target_language: str,
        status: TranslationStatus,
        source_language: str | None = None,
    ) -> TranslationUnit:
        return TranslationUnit(
            region.region_id,
            region.text,
            source_language or region.language_code,
            target_language,
            region.text,
            status,
        )


def _obvious_script_language(text: str, fallback: str) -> str | None:
    if any("\uac00" <= character <= "\ud7af" for character in text):
        return "ko"
    if any("\u0e00" <= character <= "\u0e7f" for character in text):
        return "th"
    if any("\u0900" <= character <= "\u097f" for character in text):
        return "hi"
    if any("\u0980" <= character <= "\u09ff" for character in text):
        return "bn"
    if any("\u0400" <= character <= "\u052f" for character in text):
        return "ru"
    if any("\u0600" <= character <= "\u06ff" for character in text):
        return fallback if fallback in {"ar", "fa", "ur"} else "ar"
    if any(
        "\u3400" <= character <= "\u9fff"
        or "\uf900" <= character <= "\ufaff"
        for character in text
    ):
        return fallback if fallback in {"zh-Hans", "zh-Hant", "ja"} else "zh-Hans"
    return None


def _requires_rotated_layout_review(ocr_result: OcrResult) -> bool:
    regions = ocr_result.regions
    if len(regions) < 12:
        return False
    rotated = 0
    for region in regions:
        first, second = region.polygon[:2]
        angle = degrees(atan2(second.y - first.y, second.x - first.x))
        while angle > 90:
            angle -= 180
        while angle < -90:
            angle += 180
        if abs(angle) >= 12:
            rotated += 1
    return rotated / len(regions) >= 0.7


def _corroborated_low_confidence_regions(
    ocr_result: OcrResult,
    threshold: float,
) -> dict[str, str]:
    reliable = tuple(
        region
        for region in ocr_result.regions
        if region.confidence >= threshold and len(region.text.strip()) >= 6
    )
    corroborated: dict[str, str] = {}
    for candidate in ocr_result.regions:
        if (
            candidate.confidence >= threshold
            or candidate.confidence < max(0.7, threshold - 0.05)
            or len(candidate.text.strip()) < 6
        ):
            continue
        candidate_width, candidate_height, candidate_angle = _region_geometry(candidate)
        for reference in reliable:
            if (
                candidate.language_code != reference.language_code
                or SequenceMatcher(
                    None,
                    candidate.text.strip(),
                    reference.text.strip(),
                ).ratio()
                < 0.72
            ):
                continue
            reference_width, reference_height, reference_angle = _region_geometry(
                reference
            )
            if (
                abs(candidate_angle - reference_angle) <= 5
                and max(candidate_width, reference_width)
                / min(candidate_width, reference_width)
                <= 1.3
                and max(candidate_height, reference_height)
                / min(candidate_height, reference_height)
                <= 1.3
            ):
                corroborated[candidate.region_id] = candidate.text
                break
    if len(ocr_result.regions) < 40:
        return corroborated

    repeated_reliable: dict[str, list[TextRegion]] = {}
    for region in ocr_result.regions:
        text = region.text.strip()
        if (
            region.confidence >= threshold
            and len(text) >= 2
            and _obvious_script_language(text, region.language_code)
            in {"zh-Hans", "zh-Hant", "ja"}
        ):
            repeated_reliable.setdefault(text, []).append(region)
    canonical_groups = {
        text: tuple(regions)
        for text, regions in repeated_reliable.items()
        if len(regions) >= 5
    }
    for candidate in ocr_result.regions:
        candidate_text = candidate.text.strip()
        if (
            candidate.confidence >= max(0.9, threshold)
            or candidate.region_id in corroborated
            or candidate.confidence < max(0.5, threshold - 0.25)
            or len(candidate_text) < 2
        ):
            continue
        matches = []
        for canonical_text, references in canonical_groups.items():
            if (
                candidate.language_code != references[0].language_code
                or len(candidate_text) != len(canonical_text)
            ):
                continue
            similarity = SequenceMatcher(
                None,
                candidate_text,
                canonical_text,
            ).ratio()
            minimum_similarity = (
                1.0
                if candidate.confidence < max(0.62, threshold - 0.13)
                else 0.5
            )
            if similarity < minimum_similarity or not any(
                _regions_have_similar_orientation(candidate, reference)
                for reference in references
            ):
                continue
            matches.append((similarity, len(references), canonical_text))
        if not matches:
            continue
        matches.sort(reverse=True)
        best = matches[0]
        if len(matches) > 1 and matches[1][0] == best[0]:
            continue
        corroborated[candidate.region_id] = best[2]
    return corroborated


def _regions_have_similar_orientation(
    first: TextRegion,
    second: TextRegion,
) -> bool:
    _, _, first_angle = _region_geometry(first)
    _, _, second_angle = _region_geometry(second)
    return abs(first_angle - second_angle) <= 8


def _region_geometry(region: TextRegion) -> tuple[float, float, float]:
    first, second, _, fourth = region.polygon
    width = max(
        0.01,
        ((second.x - first.x) ** 2 + (second.y - first.y) ** 2) ** 0.5,
    )
    height = max(
        0.01,
        ((fourth.x - first.x) ** 2 + (fourth.y - first.y) ** 2) ** 0.5,
    )
    angle = degrees(atan2(second.y - first.y, second.x - first.x))
    while angle > 90:
        angle -= 180
    while angle < -90:
        angle += 180
    return width, height, angle
