from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from src.domain.language import SUPPORTED_LANGUAGE_CODES
from src.domain.protection import ProtectedSpan


class TranslationError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class TranslationMode(str, Enum):
    ALL = "all"
    SPECIFIC_LANGUAGE = "specific_language"


class TranslationStatus(str, Enum):
    TRANSLATED = "translated"
    SKIPPED_LANGUAGE = "skipped_language"
    SKIPPED_PROTECTED = "skipped_protected"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class TranslationAdapterItem:
    translated_text: str | None = None
    source_language: str | None = None
    error_code: str | None = None
    error_message: str | None = None

    def __post_init__(self) -> None:
        succeeded = self.translated_text is not None
        failed = self.error_code is not None
        if succeeded == failed:
            raise ValueError("Adapter item must contain either text or an error")
        if succeeded and not self.translated_text:
            raise ValueError("Translated text cannot be empty")
        if self.source_language is not None and not self.source_language:
            raise ValueError("Detected source language cannot be empty")
        if failed and not self.error_message:
            raise ValueError("Failed adapter item requires an error message")


@dataclass(frozen=True, slots=True)
class TranslationSelection:
    mode: TranslationMode
    target_language: str
    source_language: str | None = None

    def __post_init__(self) -> None:
        if self.target_language not in SUPPORTED_LANGUAGE_CODES:
            raise ValueError("Unsupported target language")
        if self.mode is TranslationMode.SPECIFIC_LANGUAGE:
            if self.source_language not in SUPPORTED_LANGUAGE_CODES:
                raise ValueError("Specific-language mode requires a supported source language")
        elif self.source_language is not None:
            raise ValueError("All-language mode cannot include a source-language filter")


@dataclass(frozen=True, slots=True)
class TranslationUnit:
    region_id: str
    source_text: str
    source_language: str
    target_language: str
    translated_text: str
    status: TranslationStatus
    protected_spans: tuple[ProtectedSpan, ...] = ()
    error_code: str | None = None
    error_message: str | None = None

    def __post_init__(self) -> None:
        failed = self.status is TranslationStatus.FAILED
        if failed and (not self.error_code or not self.error_message):
            raise ValueError("Failed translation unit requires an error")
        if not failed and (self.error_code is not None or self.error_message is not None):
            raise ValueError("Successful or skipped translation cannot contain an error")

    @property
    def should_erase_source(self) -> bool:
        return self.status is TranslationStatus.TRANSLATED


@dataclass(frozen=True, slots=True)
class TranslationResult:
    units: tuple[TranslationUnit, ...]
    selection: TranslationSelection
    provider: str
    elapsed_ms: float

    def __post_init__(self) -> None:
        if self.elapsed_ms < 0:
            raise ValueError("Translation elapsed time cannot be negative")
