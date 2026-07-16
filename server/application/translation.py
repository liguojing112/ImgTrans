from __future__ import annotations

from typing import Protocol

from server.domain.translation import (
    TranslationProviderError,
    TranslationProviderItem,
    TranslationTextRequest,
    TranslationTextResult,
)


class TranslationProvider(Protocol):
    @property
    def provider_id(self) -> str: ...

    def translate(
        self,
        texts: tuple[str, ...],
        source_language: str | None,
        target_language: str,
        correlation_id: str,
    ) -> tuple[TranslationProviderItem, ...]: ...


class TranslateText:
    def __init__(
        self,
        provider: TranslationProvider,
        *,
        max_items: int = 100,
        max_item_characters: int = 5000,
        max_total_characters: int = 20_000,
    ) -> None:
        self._provider = provider
        self._max_items = max_items
        self._max_item_characters = max_item_characters
        self._max_total_characters = max_total_characters

    def execute(self, request: TranslationTextRequest) -> TranslationTextResult:
        self._validate(request)
        try:
            translated = self._provider.translate(
                tuple(item.text for item in request.items),
                request.source_language,
                request.target_language,
                request.correlation_id,
            )
        except TranslationProviderError as error:
            translated = tuple(
                TranslationProviderItem(
                    error_code=error.code,
                    error_message=str(error),
                )
                for _ in request.items
            )
        if len(translated) != len(request.items):
            translated = tuple(
                TranslationProviderItem(
                    error_code="invalid_provider_response",
                    error_message="Translation provider returned an invalid response",
                )
                for _ in request.items
            )
        return TranslationTextResult(self._provider.provider_id, translated)

    def _validate(self, request: TranslationTextRequest) -> None:
        if not request.items or len(request.items) > self._max_items:
            raise ValueError("Translation item count is invalid")
        if any(
            not item.text or len(item.text) > self._max_item_characters
            for item in request.items
        ):
            raise ValueError("Translation item text is invalid")
        if sum(len(item.text) for item in request.items) > self._max_total_characters:
            raise ValueError("Translation request contains too many characters")
