from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class OcrProfile:
    profile_id: str
    recognition_language: str
    model_type: str
    ocr_version: str


COMMON = OcrProfile("ppocrv6-common-small", "ch", "small", "PP-OCRv6")
CYRILLIC = OcrProfile("ppocrv5-cyrillic-mobile", "cyrillic", "mobile", "PP-OCRv5")
KOREAN = OcrProfile("ppocrv5-korean-mobile", "korean", "mobile", "PP-OCRv5")
THAI = OcrProfile("ppocrv5-thai-mobile", "th", "mobile", "PP-OCRv5")
ARABIC = OcrProfile("ppocrv5-arabic-mobile", "arabic", "mobile", "PP-OCRv5")
DEVANAGARI = OcrProfile("ppocrv5-devanagari-mobile", "devanagari", "mobile", "PP-OCRv5")


LANGUAGE_PROFILES: dict[str, OcrProfile | None] = {
    "zh-Hans": COMMON,
    "zh-Hant": COMMON,
    "ru": CYRILLIC,
    "ja": COMMON,
    "ko": KOREAN,
    "en": COMMON,
    "th": THAI,
    "ar": ARABIC,
    "vi": COMMON,
    "it": COMMON,
    "de": COMMON,
    "id": COMMON,
    "pt-PT": COMMON,
    "fil": COMMON,
    "pt-BR": COMMON,
    "pl": COMMON,
    "ms": COMMON,
    "hi": DEVANAGARI,
    "es": COMMON,
    "fr": COMMON,
    "bn": None,
    "ur": ARABIC,
    "tr": COMMON,
    "fa": ARABIC,
    "sw": COMMON,
}
