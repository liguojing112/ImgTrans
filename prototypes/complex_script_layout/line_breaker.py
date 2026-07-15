from __future__ import annotations

from dataclasses import dataclass
from typing import Callable
import unicodedata

import regex


@dataclass(frozen=True)
class TextSpan:
    start: int
    end: int

    def extract(self, text: str) -> str:
        return text[self.start : self.end]


def grapheme_spans(text: str) -> tuple[TextSpan, ...]:
    return tuple(TextSpan(match.start(), match.end()) for match in regex.finditer(r"\X", text))


def is_break_opportunity(cluster: str, language_code: str) -> bool:
    if not cluster:
        return False
    if cluster.isspace() or cluster == "\n":
        return True
    if language_code == "th":
        return True
    category = unicodedata.category(cluster[-1])
    return category.startswith("P") or cluster[-1] in {"-", "/", "\u200b"}


def greedy_line_spans(
    text: str,
    max_width: float,
    measure: Callable[[str], float],
    language_code: str,
) -> tuple[TextSpan, ...]:
    if not text:
        return ()
    lines: list[TextSpan] = []
    paragraph_start = 0
    for paragraph in text.splitlines(keepends=True):
        content = paragraph[:-1] if paragraph.endswith(("\n", "\r")) else paragraph
        if content.endswith("\r"):
            content = content[:-1]
        spans = grapheme_spans(content)
        cursor = 0
        while cursor < len(spans):
            accepted = cursor
            last_break: int | None = None
            probe = cursor
            while probe < len(spans):
                candidate = content[spans[cursor].start : spans[probe].end]
                if probe > cursor and measure(candidate) > max_width:
                    break
                accepted = probe
                if is_break_opportunity(spans[probe].extract(content), language_code):
                    last_break = probe
                probe += 1
            if accepted < cursor:
                accepted = cursor
            if probe < len(spans) and last_break is not None and last_break >= cursor:
                accepted = last_break
            start = paragraph_start + spans[cursor].start
            end = paragraph_start + spans[accepted].end
            lines.append(TextSpan(start, end))
            cursor = accepted + 1
            while cursor < len(spans) and spans[cursor].extract(content).isspace():
                cursor += 1
        if not spans:
            lines.append(TextSpan(paragraph_start, paragraph_start))
        paragraph_start += len(paragraph)
    if paragraph_start < len(text):
        lines.extend(
            TextSpan(paragraph_start + span.start, paragraph_start + span.end)
            for span in grapheme_spans(text[paragraph_start:])
        )
    return tuple(lines)


def span_boundaries_are_graphemes(text: str, spans: tuple[TextSpan, ...]) -> bool:
    boundaries = {0, len(text)}
    for span in grapheme_spans(text):
        boundaries.add(span.start)
        boundaries.add(span.end)
    return all(span.start in boundaries and span.end in boundaries for span in spans)

