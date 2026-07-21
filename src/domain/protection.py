from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum
import re


class ProtectionError(ValueError):
    pass


_PLACEHOLDER_TAG = re.compile(
    r'<x\s+id\s*=\s*"(?P<id>\d+)"\s*/\s*>'
)
_X_TAG_FRAGMENT = re.compile(
    r"<\s*/?\s*x(?=\s|/|>|$)",
    re.IGNORECASE,
)


class ProtectionKind(str, Enum):
    BRAND = "brand"
    MODEL = "model"
    SKU = "sku"
    URL = "url"
    NUMBER = "number"


def normalize_brand_terms(values: str | Iterable[str]) -> tuple[str, ...]:
    source = (values,) if isinstance(values, str) else values
    normalized: list[str] = []
    seen: set[str] = set()
    for value in source:
        for candidate in value.replace("，", ",").split(","):
            term = candidate.strip()
            key = term.casefold()
            if term and key not in seen:
                seen.add(key)
                normalized.append(term)
    return tuple(normalized)


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
        expected: dict[int, ProtectedSpan] = {}
        for span in self.spans:
            match = _PLACEHOLDER_TAG.fullmatch(span.placeholder)
            if match is None:
                raise ProtectionError("翻译结果未完整保留保护词占位符")
            placeholder_id = int(match.group("id"))
            if placeholder_id in expected:
                raise ProtectionError("翻译结果未完整保留保护词占位符")
            expected[placeholder_id] = span

        matches = tuple(_PLACEHOLDER_TAG.finditer(translated))
        actual_ids = Counter(int(match.group("id")) for match in matches)
        if actual_ids != Counter(expected.keys()):
            raise ProtectionError("翻译结果未完整保留保护词占位符")
        without_placeholders = _PLACEHOLDER_TAG.sub("", translated)
        if _X_TAG_FRAGMENT.search(without_placeholders):
            raise ProtectionError("翻译结果未完整保留保护词占位符")
        return _PLACEHOLDER_TAG.sub(
            lambda match: expected[int(match.group("id"))].text,
            translated,
        )


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
        for term in sorted(normalize_brand_terms(brand_terms), key=len, reverse=True):
            escaped = re.escape(term)
            pattern = (
                re.compile(rf"(?<![A-Za-z0-9_]){escaped}(?![A-Za-z0-9_])", re.IGNORECASE)
                if term.isascii()
                else re.compile(escaped, re.IGNORECASE)
            )
            candidates.extend(self._matches(pattern, text, ProtectionKind.BRAND))
            if self._is_complete_brand_fragment(text, term):
                candidates.append(_Candidate(0, len(text), ProtectionKind.BRAND))
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

    @staticmethod
    def _is_complete_brand_fragment(text: str, term: str) -> bool:
        text_key = "".join(character.casefold() for character in text if character.isalnum())
        term_key = "".join(character.casefold() for character in term if character.isalnum())
        if not text_key or text_key == term_key or len(text_key) >= len(term_key):
            return False
        minimum = 3 if text_key.isascii() else 2
        return len(text_key) >= minimum and text_key in term_key
