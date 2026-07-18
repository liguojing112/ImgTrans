from __future__ import annotations

from time import perf_counter

from src.application.ports import TranslationAdapter
from src.domain.language import SUPPORTED_LANGUAGE_CODES
from src.domain.ocr import OcrResult, TextRegion
from src.domain.protection import ProtectedText, ProtectionEngine, ProtectionError
from src.domain.translation import (
    TranslationAdapterItem,
    TranslationError,
    TranslationResult,
    TranslationSelection,
    TranslationStatus,
    TranslationUnit,
)


class TranslateRegions:
    def __init__(self, adapter: TranslationAdapter, protection: ProtectionEngine) -> None:
        self._adapter = adapter
        self._protection = protection

    @property
    def language_codes(self) -> tuple[str, ...]:
        return SUPPORTED_LANGUAGE_CODES

    @property
    def adapter_id(self) -> str:
        return self._adapter.adapter_id

    def execute(
        self,
        ocr_result: OcrResult,
        selection: TranslationSelection,
        brand_terms: tuple[str, ...] = (),
    ) -> TranslationResult:
        started = perf_counter()
        units: list[TranslationUnit | None] = [None] * len(ocr_result.regions)
        prepared: list[tuple[int, TextRegion, ProtectedText]] = []
        reports_source_language = bool(
            getattr(self._adapter, "reports_source_language", False)
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
