from __future__ import annotations

from dataclasses import dataclass, replace
from difflib import SequenceMatcher
from math import atan2, degrees, hypot
from time import perf_counter

from src.application.ports import TranslationAdapter
from src.domain.language import SUPPORTED_LANGUAGE_CODES
from src.domain.ocr import OcrMode, OcrResult, TextRegion
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
        automatic_confidence_threshold: float | None = None,
        preserve_numbers: bool = True,
        merge_paragraphs: bool = True,
    ) -> TranslationResult:
        threshold = (
            self._automatic_confidence_threshold
            if automatic_confidence_threshold is None
            else automatic_confidence_threshold
        )
        if not 0 <= threshold <= 1:
            raise ValueError(
                "Automatic translation confidence threshold must be between zero and one"
            )
        started = perf_counter()
        units: list[TranslationUnit | None] = [None] * len(ocr_result.regions)
        prepared: list[tuple[int, TextRegion, ProtectedText]] = []
        prepared_info: dict[int, tuple[TextRegion, ProtectedText]] = {}
        repeated_review_candidates: list[
            tuple[int, TextRegion, ProtectedText]
        ] = []
        reports_source_language = bool(
            getattr(self._adapter, "reports_source_language", False)
        )
        complex_layout_review = (
            not allow_low_confidence
            and ocr_result.mode is not OcrMode.HIGH_RECALL
            and _requires_rotated_layout_review(ocr_result)
        )
        corroborated_regions = _corroborated_low_confidence_regions(
            ocr_result,
            threshold,
        )
        for index, region in enumerate(ocr_result.regions):
            if (
                selection.source_language is not None
                and region.language_code != selection.source_language
            ):
                units[index] = self._skipped_unit(
                    region, selection.target_language, TranslationStatus.SKIPPED_LANGUAGE
                )
                continue
            corroborated_text = corroborated_regions.get(region.region_id)
            if corroborated_text is not None:
                region = replace(region, text=corroborated_text)
            protected = self._protection.protect(
                region.text,
                brand_terms,
                preserve_numbers,
            )
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
                if _can_recover_repeated_high_recall_region(
                    ocr_result,
                    region,
                    protected,
                ):
                    repeated_review_candidates.append(
                        (index, region, protected)
                    )
                    continue
                if not _is_unanimous_long_high_recall_region(
                    ocr_result,
                    region,
                    protected,
                ):
                    units[index] = _review_required_unit(
                        region,
                        selection.target_language,
                        protected,
                    )
                    continue
            if (
                complex_layout_review
                and region.confidence < max(
                    0.9,
                    threshold,
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
                and region.confidence < threshold
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
            prepared_info[index] = (region, protected)
        prepared, paragraph_members = (
            self._combine_paragraph_groups(
                ocr_result,
                prepared,
                prepared_info,
                selection,
                brand_terms,
                preserve_numbers,
                units,
            )
            if merge_paragraphs
            else (prepared, {})
        )
        if prepared:
            source_language = selection.source_language
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
                members = paragraph_members.get(index) or ((index, None),)
                detected_source = (
                    adapter_item.source_language or region.language_code
                )
                if adapter_item.error_code is not None:
                    for member_index, group_id in members:
                        member_region, member_protected = prepared_info[member_index]
                        units[member_index] = TranslationUnit(
                            member_region.region_id,
                            member_region.text,
                            detected_source,
                            selection.target_language,
                            member_region.text,
                            TranslationStatus.FAILED,
                            member_protected.spans,
                            adapter_item.error_code,
                            adapter_item.error_message,
                            group_id,
                        )
                    continue
                if (
                    selection.source_language is None
                    and detected_source == selection.target_language
                ):
                    for member_index, group_id in members:
                        member_region = prepared_info[member_index][0]
                        units[member_index] = self._skipped_unit(
                            member_region,
                            selection.target_language,
                            TranslationStatus.SKIPPED_LANGUAGE,
                            detected_source,
                            group_id,
                        )
                    continue
                try:
                    restored = protected.restore(adapter_item.translated_text or "")
                except ProtectionError as error:
                    retried = self._retry_without_number_protection(
                        region,
                        selection,
                        brand_terms,
                        protected,
                    )
                    if retried is not None:
                        for member_index, group_id in members:
                            member_region, member_protected = prepared_info[
                                member_index
                            ]
                            units[member_index] = TranslationUnit(
                                member_region.region_id,
                                member_region.text,
                                retried.source_language,
                                selection.target_language,
                                retried.translated_text,
                                TranslationStatus.TRANSLATED,
                                member_protected.spans,
                                paragraph_group_id=group_id,
                            )
                        continue
                    for member_index, group_id in members:
                        member_region, member_protected = prepared_info[member_index]
                        units[member_index] = TranslationUnit(
                            member_region.region_id,
                            member_region.text,
                            detected_source,
                            selection.target_language,
                            member_region.text,
                            TranslationStatus.FAILED,
                            member_protected.spans,
                            "placeholder_damaged",
                            str(error),
                            group_id,
                        )
                    continue
                if (
                    ocr_result.mode is OcrMode.HIGH_RECALL
                    and region.enhanced_only
                    and not _translation_matches_target_script(
                        region.text,
                        restored,
                        selection.target_language,
                    )
                ):
                    repeated_review_candidates.append(
                        (index, region, protected)
                    )
                    continue
                for member_index, group_id in members:
                    member_region, member_protected = prepared_info[member_index]
                    units[member_index] = TranslationUnit(
                        member_region.region_id,
                        member_region.text,
                        detected_source,
                        selection.target_language,
                        restored,
                        TranslationStatus.TRANSLATED,
                        member_protected.spans,
                        paragraph_group_id=group_id,
                    )
        _recover_repeated_high_recall_regions(
            ocr_result,
            selection,
            repeated_review_candidates,
            units,
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

    def _retry_without_number_protection(
        self,
        region: TextRegion,
        selection: TranslationSelection,
        brand_terms: tuple[str, ...],
        protected: ProtectedText,
    ) -> TranslationUnit | None:
        """占位符在翻译中被破坏时，去掉数字保护重试一次。

        商品参数文本（如「堵头*2」「50-75管通用」）里的数字/符号被保护成
        ⟦N⟧ 占位符，翻译服务（LLM/Azure）不理解该符号，返回时常把它还原
        成原文数字或直接丢弃，导致 restore 报 placeholder_damaged。若失败
        文本恰好含数字保护，用不保护数字的方式直译一次，通常能正常翻译，
        避免这类词直接标成「翻译失败」。
        """
        if not any(span.kind is ProtectionKind.NUMBER for span in protected.spans):
            return None
        plain = self._protection.protect(
            region.text,
            brand_terms,
            preserve_numbers=False,
        )
        if plain.fully_protected:
            return None
        try:
            items = self._adapter.translate(
                (plain.masked,),
                selection.source_language or region.language_code,
                selection.target_language,
            )
        except Exception:
            return None
        if not items or items[0].error_code is not None:
            return None
        try:
            restored = plain.restore(items[0].translated_text or "")
        except ProtectionError:
            return None
        if not restored.strip():
            return None
        return TranslationUnit(
            region.region_id,
            region.text,
            region.language_code,
            selection.target_language,
            restored,
            TranslationStatus.TRANSLATED,
            plain.spans,
        )

    @staticmethod
    def _skipped_unit(
        region: TextRegion,
        target_language: str,
        status: TranslationStatus,
        source_language: str | None = None,
        paragraph_group_id: str | None = None,
    ) -> TranslationUnit:
        return TranslationUnit(
            region.region_id,
            region.text,
            source_language or region.language_code,
            target_language,
            region.text,
            status,
            paragraph_group_id=paragraph_group_id,
        )

    def _combine_paragraph_groups(
        self,
        ocr_result: OcrResult,
        prepared: list[tuple[int, TextRegion, ProtectedText]],
        prepared_info: dict[int, tuple[TextRegion, ProtectedText]],
        selection: TranslationSelection,
        brand_terms: tuple[str, ...],
        preserve_numbers: bool,
        units: list[TranslationUnit | None],
    ) -> tuple[
        list[tuple[int, TextRegion, ProtectedText]],
        dict[int, tuple[tuple[int, str], ...]],
    ]:
        """把同一自然段的相邻文本行合并为一个整段翻译条目。

        逐行独立翻译会把句子从中间切断（如「…我」「们支持…」），译文质量差
        且各行译文长度伸缩导致排版碎片化。合并后整段一次翻译，布局阶段再按
        段落并集框重排为连续文本块。

        返回新的 prepared 列表（合并条目占据首行位置）以及
        「首行索引 → ((成员行索引, 段落ID), …)」映射。
        """
        if ocr_result.mode is not OcrMode.STANDARD or len(prepared) < 2:
            return prepared, {}
        groups: list[tuple[int, ...]] = []
        current: list[int] = []
        for index, _, _ in prepared:
            if current and _lines_form_paragraph(
                ocr_result.regions[current[-1]],
                ocr_result.regions[index],
            ):
                current.append(index)
            else:
                if len(current) >= 2:
                    groups.append(tuple(current))
                current = [index]
        if len(current) >= 2:
            groups.append(tuple(current))
        if not groups:
            return prepared, {}

        member_indexes: set[int] = set()
        head_to_group: dict[int, tuple[int, ...]] = {}
        for group in groups:
            head_to_group[group[0]] = group
            member_indexes.update(group[1:])

        rebuilt: list[tuple[int, TextRegion, ProtectedText]] = []
        combined: dict[int, tuple[tuple[int, str], ...]] = {}
        for index, region, protected in prepared:
            group = head_to_group.get(index)
            if group is None:
                if index in member_indexes:
                    continue
                rebuilt.append((index, region, protected))
                continue
            group_id = f"paragraph-{index}"
            members: list[tuple[int, str]] = []
            texts: list[str] = []
            for member_index in group:
                members.append((member_index, group_id))
                texts.append(prepared_info[member_index][0].text)
            combined_text = join_paragraph_text(tuple(texts))
            combined_protected = self._protection.protect(
                combined_text,
                brand_terms,
                preserve_numbers,
            )
            if combined_protected.fully_protected:
                for member_index, _group_id in members:
                    member_region, member_protected = prepared_info[member_index]
                    units[member_index] = TranslationUnit(
                        member_region.region_id,
                        member_region.text,
                        member_region.language_code,
                        selection.target_language,
                        member_region.text,
                        TranslationStatus.SKIPPED_PROTECTED,
                        member_protected.spans,
                        paragraph_group_id=group_id,
                    )
                continue
            head_language = prepared_info[index][0].language_code
            terminology_text = self._terminology_catalog.lookup(
                selection.source_language or head_language,
                selection.target_language,
                combined_text,
            )
            if terminology_text is not None:
                for member_index, _group_id in members:
                    member_region, member_protected = prepared_info[member_index]
                    units[member_index] = TranslationUnit(
                        member_region.region_id,
                        member_region.text,
                        selection.source_language or head_language,
                        selection.target_language,
                        terminology_text,
                        TranslationStatus.TRANSLATED,
                        member_protected.spans,
                        paragraph_group_id=group_id,
                    )
                continue
            synthetic = replace(prepared_info[index][0], text=combined_text)
            combined[index] = tuple(members)
            rebuilt.append((index, synthetic, combined_protected))
        return rebuilt, combined


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


def _translation_matches_target_script(
    source_text: str,
    translated_text: str,
    target_language: str,
) -> bool:
    if target_language not in {"zh-Hans", "zh-Hant"}:
        return True
    if not _contains_latin(source_text):
        return True
    return any(
        "\u3400" <= character <= "\u9fff"
        or "\uf900" <= character <= "\ufaff"
        for character in translated_text
    )


def _contains_latin(text: str) -> bool:
    return any(
        "A" <= character <= "Z" or "a" <= character <= "z"
        for character in text
    )


def _review_required_unit(
    region: TextRegion,
    target_language: str,
    protected: ProtectedText,
) -> TranslationUnit:
    return TranslationUnit(
        region.region_id,
        region.text,
        region.language_code,
        target_language,
        region.text,
        TranslationStatus.REVIEW_REQUIRED,
        protected.spans,
    )


def _can_recover_repeated_high_recall_region(
    ocr_result: OcrResult,
    region: TextRegion,
    protected: ProtectedText,
) -> bool:
    if (
        ocr_result.mode is not OcrMode.HIGH_RECALL
        or not region.enhanced_only
        or region.confidence < 0.82
        or protected.spans
        or not _normalized_latin_token(region.text)
    ):
        return False
    supported = tuple(
        observation
        for observation in region.observations
        if observation.confidence >= 0.8
    )
    if len({observation.view_id for observation in supported}) < 2:
        return False
    centers = tuple(
        (
            sum(point.x for point in observation.polygon) / 4,
            sum(point.y for point in observation.polygon) / 4,
        )
        for observation in supported
    )
    stable_mapping = all(
        hypot(first[0] - second[0], first[1] - second[1]) <= 4
        for first in centers
        for second in centers
    )
    return stable_mapping and _has_repeated_high_recall_reference(
        ocr_result,
        region,
    )


def _has_repeated_high_recall_reference(
    ocr_result: OcrResult,
    region: TextRegion,
) -> bool:
    token = _normalized_latin_token(region.text)
    if token is None:
        return False
    for reference in ocr_result.regions:
        if (
            reference.region_id == region.region_id
            or not reference.auto_process_eligible
        ):
            continue
        reference_token = _normalized_latin_token(reference.text)
        if reference_token is None:
            continue
        edits = _edit_distance(token, reference_token)
        maximum_edits = (
            1 if max(len(token), len(reference_token)) <= 5 else 2
        )
        if (
            edits <= maximum_edits
            and SequenceMatcher(None, token, reference_token).ratio() >= 0.70
        ):
            return True
    return False


def _is_unanimous_long_high_recall_region(
    ocr_result: OcrResult,
    region: TextRegion,
    protected: ProtectedText,
) -> bool:
    token = _normalized_latin_token(region.text)
    if (
        ocr_result.mode is not OcrMode.HIGH_RECALL
        or not region.enhanced_only
        or region.confidence < 0.82
        or protected.spans
        or token is None
        or len(token) < 8
    ):
        return False
    supported = tuple(
        observation
        for observation in region.observations
        if observation.confidence >= 0.80
    )
    if len({observation.view_id for observation in supported}) < 3:
        return False
    if {
        _normalized_latin_token(observation.text)
        for observation in supported
    } != {token}:
        return False
    centers = tuple(
        (
            sum(point.x for point in observation.polygon) / 4,
            sum(point.y for point in observation.polygon) / 4,
        )
        for observation in supported
    )
    if any(
        hypot(first[0] - second[0], first[1] - second[1]) > 0.5
        for first in centers
        for second in centers
    ):
        return False
    angles = tuple(
        degrees(
            atan2(
                observation.polygon[1].y - observation.polygon[0].y,
                observation.polygon[1].x - observation.polygon[0].x,
            )
        )
        for observation in supported
    )
    return all(
        min(abs(first - second) % 180, 180 - abs(first - second) % 180)
        <= 0.5
        for first in angles
        for second in angles
    )


def _recover_repeated_high_recall_regions(
    ocr_result: OcrResult,
    selection: TranslationSelection,
    candidates: list[tuple[int, TextRegion, ProtectedText]],
    units: list[TranslationUnit | None],
) -> None:
    if not candidates:
        return
    regions = {region.region_id: region for region in ocr_result.regions}
    references = []
    for unit in units:
        if (
            unit is None
            or unit.status is not TranslationStatus.TRANSLATED
            or not _translation_matches_target_script(
                unit.source_text,
                unit.translated_text,
                selection.target_language,
            )
        ):
            continue
        region = regions.get(unit.region_id)
        token = _normalized_latin_token(unit.source_text)
        if (
            region is None
            or not region.auto_process_eligible
            or token is None
        ):
            continue
        references.append((token, region.confidence, unit))
    groups: dict[str, list[tuple[float, TranslationUnit]]] = {}
    for token, confidence, unit in references:
        groups.setdefault(token, []).append((confidence, unit))
    for index, region, protected in candidates:
        token = _normalized_latin_token(region.text)
        match = (
            _select_repeated_translation(region.text, token, groups)
            if token is not None
            else None
        )
        if match is None:
            units[index] = _review_required_unit(
                region,
                selection.target_language,
                protected,
            )
            continue
        translated_text, source_language = match
        units[index] = TranslationUnit(
            region.region_id,
            region.text,
            source_language,
            selection.target_language,
            translated_text,
            TranslationStatus.TRANSLATED,
            protected.spans,
        )


def _select_repeated_translation(
    source_text: str,
    token: str,
    groups: dict[str, list[tuple[float, TranslationUnit]]],
) -> tuple[str, str] | None:
    neighbours = []
    for reference_token, values in groups.items():
        edits = _edit_distance(token, reference_token)
        similarity = SequenceMatcher(None, token, reference_token).ratio()
        maximum_edits = 1 if max(len(token), len(reference_token)) <= 5 else 2
        minimum_similarity = 0.70 if len(values) >= 2 else 0.72
        if edits <= maximum_edits and similarity >= minimum_similarity:
            neighbours.append(
                (
                    reference_token,
                    values,
                    len(values),
                    edits,
                    similarity,
                )
            )
    if not neighbours:
        return None
    exact = next(
        (neighbour for neighbour in neighbours if neighbour[0] == token),
        None,
    )
    if exact is not None:
        stronger = tuple(
            neighbour
            for neighbour in neighbours
            if neighbour[0] != token
            and neighbour[2] >= exact[2] + 2
        )
        selected = (
            max(stronger, key=lambda value: (value[2], -value[3], value[4]))
            if stronger
            else exact
        )
    else:
        neighbours.sort(
            key=lambda value: (-value[2], value[3], -value[4], value[0])
        )
        selected = neighbours[0]
        if (
            len(neighbours) > 1
            and neighbours[1][2] == selected[2]
            and neighbours[1][3] == selected[3]
        ):
            return None
    values = selected[1]
    exact_spelling = tuple(
        value for value in values if value[1].source_text == source_text
    )
    eligible_values = exact_spelling or tuple(values)
    translation_counts: dict[str, int] = {}
    for _, unit in eligible_values:
        translation_counts[unit.translated_text] = (
            translation_counts.get(unit.translated_text, 0) + 1
        )
    confidence, unit = max(
        eligible_values,
        key=lambda value: (
            translation_counts[value[1].translated_text],
            value[0],
        ),
    )
    return unit.translated_text, unit.source_language


def _normalized_latin_token(text: str) -> str | None:
    value = "".join(
        character.casefold()
        for character in text
        if character.isalpha()
    )
    if len(value) < 4 or not all("a" <= character <= "z" for character in value):
        return None
    return value


def _edit_distance(first: str, second: str) -> int:
    previous = tuple(range(len(second) + 1))
    for first_index, first_character in enumerate(first, start=1):
        current = [first_index]
        for second_index, second_character in enumerate(second, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[second_index] + 1,
                    previous[second_index - 1]
                    + (first_character != second_character),
                )
            )
        previous = tuple(current)
    return previous[-1]


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


@dataclass(frozen=True, slots=True)
class _RegionBox:
    left: float
    right: float
    top: float
    bottom: float
    angle: float

    @property
    def width(self) -> float:
        return max(self.right - self.left, 0.01)

    @property
    def height(self) -> float:
        return max(self.bottom - self.top, 0.01)


def _region_box(region: TextRegion) -> _RegionBox:
    xs = tuple(point.x for point in region.polygon)
    ys = tuple(point.y for point in region.polygon)
    first, second = region.polygon[0], region.polygon[1]
    angle = degrees(atan2(second.y - first.y, second.x - first.x))
    while angle > 90:
        angle -= 180
    while angle < -90:
        angle += 180
    return _RegionBox(min(xs), max(xs), min(ys), max(ys), angle)


def _contains_cjk_text(text: str) -> bool:
    return any(_is_cjk_char(character) for character in text)


def _is_cjk_char(character: str) -> bool:
    return (
        "\u3400" <= character <= "\u9fff"
        or "\uf900" <= character <= "\ufaff"
    ) if character else False


def join_paragraph_text(texts: tuple[str, ...]) -> str:
    """拼接段落各行原文；相邻行之间仅在两侧都不是 CJK 时补空格。"""
    parts: list[str] = []
    for position, text in enumerate(texts):
        if (
            position
            and not _is_cjk_char(texts[position - 1][-1:])
            and not _is_cjk_char(text[:1])
        ):
            parts.append(" ")
        parts.append(text)
    return "".join(parts)


def _lines_form_paragraph(first: TextRegion, second: TextRegion) -> bool:
    """判断上下相邻两行是否属于同一自然段（字号相近、左缘对齐、行距合理、水平重叠）。"""
    if (
        not _contains_cjk_text(first.text)
        or not _contains_cjk_text(second.text)
        or len(first.text.strip()) < 6
        or len(second.text.strip()) < 6
    ):
        return False
    first_box = _region_box(first)
    second_box = _region_box(second)
    max_height = max(first_box.height, second_box.height)
    min_height = min(first_box.height, second_box.height)
    if (
        abs(first_box.angle) > 3
        or abs(second_box.angle) > 3
        or max_height > min_height * 1.35
    ):
        return False
    gap = second_box.top - first_box.bottom
    overlap = (
        min(first_box.right, second_box.right)
        - max(first_box.left, second_box.left)
    )
    return (
        gap >= -0.25 * min_height
        and gap <= 0.8 * max_height
        and abs(first_box.left - second_box.left) <= 0.35 * max_height
        and overlap >= 0.5 * min(first_box.width, second_box.width)
    )
