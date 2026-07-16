from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re


class ProtectionError(ValueError):
    pass


class ProtectionKind(str, Enum):
    BRAND = "brand"
    MODEL = "model"
    SKU = "sku"
    URL = "url"
    NUMBER = "number"


@dataclass(frozen=True, slots=True)
class ProtectedSpan:
    start: int
    end: int
    text: str
    kind: ProtectionKind
    placeholder: str


@dataclass(frozen=True, slots=True)
class ProtectedText:
    original: str
    masked: str
    spans: tuple[ProtectedSpan, ...]

    @property
    def fully_protected(self) -> bool:
        remainder = re.sub(r'<x id="\d+"/>', "", self.masked)
        return not any(character.isalnum() for character in remainder)

    def restore(self, translated: str) -> str:
        restored = translated
        for span in self.spans:
            if restored.count(span.placeholder) != 1:
                raise ProtectionError("翻译结果未完整保留保护词占位符")
            restored = restored.replace(span.placeholder, span.text)
        return restored


@dataclass(frozen=True, slots=True)
class _Candidate:
    start: int
    end: int
    kind: ProtectionKind


class ProtectionEngine:
    _URL = re.compile(
        r"https?://[^\s]+|www\.[^\s]+|\b(?:[A-Za-z0-9-]+\.)+(?:com|net|org|cn|io|co|shop)\b(?:/[^\s]*)?",
        re.IGNORECASE,
    )
    _SKU = re.compile(r"\bSKU(?:[:#\s-]*)(?=[A-Z0-9._/-]*\d)[A-Z0-9][A-Z0-9._/-]*\b", re.IGNORECASE)
    _MODEL = re.compile(
        r"\b(?=[A-Za-z0-9._/-]*[A-Za-z])(?=[A-Za-z0-9._/-]*\d)[A-Za-z0-9]+(?:[._/-][A-Za-z0-9]+)*\b"
    )
    _NUMBER = re.compile(r"(?<![\w])\d+(?:[.,]\d+)*(?:%|[xX]\d+)?(?![\w])")

    def protect(self, text: str, brand_terms: tuple[str, ...] = ()) -> ProtectedText:
        candidates: list[_Candidate] = []
        candidates.extend(self._matches(self._URL, text, ProtectionKind.URL))
        candidates.extend(self._matches(self._SKU, text, ProtectionKind.SKU))
        candidates.extend(self._matches(self._MODEL, text, ProtectionKind.MODEL))
        candidates.extend(self._matches(self._NUMBER, text, ProtectionKind.NUMBER))
        for term in sorted({term.strip() for term in brand_terms if term.strip()}, key=len, reverse=True):
            escaped = re.escape(term)
            pattern = (
                re.compile(rf"(?<![A-Za-z0-9_]){escaped}(?![A-Za-z0-9_])", re.IGNORECASE)
                if term.isascii()
                else re.compile(escaped, re.IGNORECASE)
            )
            candidates.extend(self._matches(pattern, text, ProtectionKind.BRAND))
        selected: list[_Candidate] = []
        for candidate in sorted(candidates, key=lambda item: (item.start, -(item.end - item.start))):
            if any(candidate.start < item.end and candidate.end > item.start for item in selected):
                continue
            selected.append(candidate)
        selected.sort(key=lambda item: item.start)
        pieces = []
        spans = []
        cursor = 0
        for index, candidate in enumerate(selected):
            placeholder = f'<x id="{index}"/>'
            pieces.append(text[cursor : candidate.start])
            pieces.append(placeholder)
            spans.append(
                ProtectedSpan(
                    candidate.start,
                    candidate.end,
                    text[candidate.start : candidate.end],
                    candidate.kind,
                    placeholder,
                )
            )
            cursor = candidate.end
        pieces.append(text[cursor:])
        return ProtectedText(text, "".join(pieces), tuple(spans))

    @staticmethod
    def _matches(pattern: re.Pattern[str], text: str, kind: ProtectionKind) -> list[_Candidate]:
        return [_Candidate(match.start(), match.end(), kind) for match in pattern.finditer(text)]
