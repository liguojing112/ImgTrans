from prototypes.complex_script_layout.line_breaker import (
    grapheme_spans,
    greedy_line_spans,
    span_boundaries_are_graphemes,
)


def test_combining_sequences_are_single_graphemes() -> None:
    assert len(grapheme_spans("น้ำ")) == 1
    assert len(grapheme_spans("क्ष")) == 1
    assert len(grapheme_spans("ক্ষ")) == 1


def test_greedy_wrap_never_splits_grapheme() -> None:
    text = "น้ำกำลังเดินทางภาษาไทย"
    spans = greedy_line_spans(text, 4, lambda value: len(value), "th")
    assert len(spans) > 1
    assert span_boundaries_are_graphemes(text, spans)


def test_manual_newline_creates_separate_spans() -> None:
    spans = greedy_line_spans("บรรทัดแรก\nบรรทัดสอง", 100, lambda value: len(value), "th")
    assert len(spans) == 2
