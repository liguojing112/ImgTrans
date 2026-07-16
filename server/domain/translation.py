from __future__ import annotations

from dataclasses import dataclass


SUPPORTED_LANGUAGE_CODES = (
    "zh-Hans",
    "zh-Hant",
    "ru",
    "ja",
    "ko",
    "en",
    "th",
    "ar",
    "vi",
    "it",
    "de",
    "id",
    "pt-PT",
    "fil",
    "pt-BR",
    "pl",
    "ms",
    "hi",
    "es",
    "fr",
    "bn",
    "ur",
    "tr",
    "fa",
    "sw",
)

MICROSOFT_LANGUAGE_CODES = {
    code: code for code in SUPPORTED_LANGUAGE_CODES
} | {
    "pt-BR": "pt",
    "pt-PT": "pt-pt",
}


class TranslationProviderError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        retry_after_seconds: float | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.retry_after_seconds = retry_after_seconds


@dataclass(frozen=True, slots=True)
class TranslationProviderItem:
    translated_text: str | None = None
    error_code: str | None = None
    error_message: str | None = None

    def __post_init__(self) -> None:
        if (self.translated_text is None) == (self.error_code is None):
            raise ValueError("Provider item must contain text or an error")
        if self.translated_text is not None and not self.translated_text:
            raise ValueError("Provider translation cannot be empty")
        if self.error_code is not None and not self.error_message:
            raise ValueError("Provider error requires a public message")


@dataclass(frozen=True, slots=True)
class TranslationTextItem:
    item_id: str
    text: str


@dataclass(frozen=True, slots=True)
class TranslationTextRequest:
    items: tuple[TranslationTextItem, ...]
    source_language: str | None
    target_language: str
    correlation_id: str


@dataclass(frozen=True, slots=True)
class TranslationTextResult:
    provider: str
    items: tuple[TranslationProviderItem, ...]
