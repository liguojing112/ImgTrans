from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
import unicodedata

from src.domain.language import SUPPORTED_LANGUAGE_CODES


def normalize_terminology_text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).split())


@dataclass(frozen=True, slots=True)
class TerminologyEntry:
    source_language: str
    target_language: str
    source_text: str
    target_text: str
    enabled: bool = True

    def __post_init__(self) -> None:
        if self.source_language not in SUPPORTED_LANGUAGE_CODES:
            raise ValueError("Unsupported terminology source language")
        if self.target_language not in SUPPORTED_LANGUAGE_CODES:
            raise ValueError("Unsupported terminology target language")
        source_text = normalize_terminology_text(self.source_text)
        target_text = normalize_terminology_text(self.target_text)
        if not source_text or not target_text:
            raise ValueError("Terminology source and target text cannot be empty")
        object.__setattr__(self, "source_text", source_text)
        object.__setattr__(self, "target_text", target_text)


def normalize_terminology_entries(
    entries: tuple[TerminologyEntry, ...] | list[TerminologyEntry],
) -> tuple[TerminologyEntry, ...]:
    unique: dict[tuple[str, str, str], TerminologyEntry] = {}
    for value in entries:
        entry = TerminologyEntry(
            value.source_language,
            value.target_language,
            value.source_text,
            value.target_text,
            value.enabled,
        )
        key = (
            entry.source_language,
            entry.target_language,
            entry.source_text,
        )
        unique.pop(key, None)
        unique[key] = entry
    return tuple(unique.values())


class TerminologyCatalog:
    def __init__(self, entries: tuple[TerminologyEntry, ...] = ()) -> None:
        self._lock = RLock()
        self._entries = normalize_terminology_entries(entries)

    def replace(self, entries: tuple[TerminologyEntry, ...]) -> None:
        normalized = normalize_terminology_entries(entries)
        with self._lock:
            self._entries = normalized

    def snapshot(self) -> tuple[TerminologyEntry, ...]:
        with self._lock:
            return self._entries

    def lookup(
        self,
        source_language: str,
        target_language: str,
        source_text: str,
    ) -> str | None:
        normalized_source = normalize_terminology_text(source_text)
        with self._lock:
            entries = self._entries
        for entry in entries:
            if (
                entry.enabled
                and entry.source_language == source_language
                and entry.target_language == target_language
                and entry.source_text == normalized_source
            ):
                return entry.target_text
        return None
