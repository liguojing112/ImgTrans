from __future__ import annotations

from PySide6.QtGui import QFont, QFontDatabase, QRawFont

from src.domain.layout import FontStyleHint
from src.platform.fonts import resolve_system_font


_TOKENS = {
    FontStyleHint.SANS: ("sans", "arial", "helvetica", "segoe", "gothic", "雅黑"),
    FontStyleHint.SERIF: ("serif", "times", "song", "simsun", "mincho", "宋"),
    FontStyleHint.DISPLAY: ("black", "heavy", "impact", "display", "poster", "bold"),
    FontStyleHint.HANDWRITTEN: ("script", "hand", "cursive", "kai", "comic", "楷"),
}


def recommend_system_fonts(
    text: str,
    style_hint: FontStyleHint,
    limit: int = 8,
) -> tuple[str, ...]:
    if limit <= 0:
        raise ValueError("Font candidate limit must be positive")
    sample = tuple(dict.fromkeys(value for value in text if not value.isspace()))[:64]
    families = QFontDatabase.families()
    supported = [family for family in families if _supports(family, sample)]
    tokens = _TOKENS[style_hint]
    supported.sort(
        key=lambda family: (
            -sum(token in family.casefold() for token in tokens),
            family.casefold(),
        )
    )
    if supported:
        return tuple(supported[:limit])
    fallback = resolve_system_font(_infer_language(text))
    return (fallback,)


def _supports(family: str, sample: tuple[str, ...]) -> bool:
    raw = QRawFont.fromFont(QFont(family, 12))
    return raw.isValid() and all(raw.supportsCharacter(ord(value)) for value in sample)


def _infer_language(text: str) -> str:
    for value in text:
        code = ord(value)
        if 0x0600 <= code <= 0x06FF:
            return "ar"
        if 0x0900 <= code <= 0x097F:
            return "hi"
        if 0x0E00 <= code <= 0x0E7F:
            return "th"
        if 0x3040 <= code <= 0x30FF:
            return "ja"
        if 0xAC00 <= code <= 0xD7AF:
            return "ko"
        if 0x4E00 <= code <= 0x9FFF:
            return "zh-Hans"
    return "en"
