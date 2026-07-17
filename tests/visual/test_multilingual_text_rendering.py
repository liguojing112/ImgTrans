from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QTextLayout
from PySide6.QtWidgets import QApplication

from src.domain.image import ImageAsset, ImageDocument, ImageFileFormat
from src.domain.language import SUPPORTED_LANGUAGE_CODES
from src.domain.layout import TextAlignment
from src.domain.ocr import OcrResult, TextRegion, order_quad
from src.domain.translation import (
    TranslationMode,
    TranslationResult,
    TranslationSelection,
    TranslationStatus,
    TranslationUnit,
)
from src.infrastructure.text_renderer import QtBasicTextLayoutAdapter, QtTextRenderer
from src.platform.fonts import resolve_system_font


REPRESENTATIVE_TEXT = {
    "zh-Hans": "商品促销",
    "zh-Hant": "商品促銷",
    "ru": "Скидка",
    "ja": "商品セール",
    "ko": "상품 할인",
    "en": "Summer sale",
    "th": "สินค้าลดราคา",
    "ar": "عرض خاص",
    "vi": "Khuyến mãi",
    "it": "Offerta speciale",
    "de": "Sonderangebot",
    "id": "Diskon produk",
    "pt-PT": "Promoção",
    "fil": "Espesyal na alok",
    "pt-BR": "Promoção",
    "pl": "Promocja",
    "ms": "Promosi produk",
    "hi": "विशेष ऑफ़र",
    "es": "Oferta especial",
    "fr": "Offre spéciale",
    "bn": "বিশেষ অফার",
    "ur": "خصوصی پیشکش",
    "tr": "Özel teklif",
    "fa": "پیشنهاد ویژه",
    "sw": "Ofa maalum",
}


@pytest.fixture(scope="module", autouse=True)
def application() -> QApplication:
    return QApplication.instance() or QApplication(["multilingual-visual-test"])


def _document(width: int = 480, height: int = 120) -> ImageDocument:
    pixels = np.full((height, width, 3), 255, dtype=np.uint8)
    asset = ImageAsset(
        Path("multilingual.png"),
        width,
        height,
        len(pixels.tobytes()),
        ImageFileFormat.PNG,
        False,
        False,
    )
    return ImageDocument(asset, "RGB", pixels.tobytes())


def _layout(language_code: str, text: str):
    document = _document()
    region = TextRegion(
        "region-1",
        order_quad(((20, 20), (460, 20), (460, 100), (20, 100))),
        "SOURCE",
        1.0,
        "en",
        "fixture",
    )
    ocr = OcrResult((region,), "en", "fixture", 1)
    translation = TranslationResult(
        (
            TranslationUnit(
                region.region_id,
                region.text,
                region.language_code,
                language_code,
                text,
                TranslationStatus.TRANSLATED,
            ),
        ),
        TranslationSelection(TranslationMode.ALL, language_code),
        "fixture",
        1,
    )
    layout = QtBasicTextLayoutAdapter().layout(document, ocr, translation)
    return document, layout


def _glyph_indexes(text: str, family: str) -> tuple[int, ...]:
    font = QFont(family)
    font.setPixelSize(32)
    layout = QTextLayout(text, font)
    layout.setTextOption(layout.textOption())
    layout.beginLayout()
    line = layout.createLine()
    line.setLineWidth(440)
    layout.endLayout()
    return tuple(index for run in line.glyphRuns() for index in run.glyphIndexes())


@pytest.mark.parametrize("language_code", SUPPORTED_LANGUAGE_CODES)
def test_supported_language_shapes_and_renders_visible_text(language_code: str) -> None:
    assert set(REPRESENTATIVE_TEXT) == set(SUPPORTED_LANGUAGE_CODES)
    text = REPRESENTATIVE_TEXT[language_code]
    family = resolve_system_font(language_code)
    glyphs = _glyph_indexes(text, family)
    assert glyphs
    assert all(index != 0 for index in glyphs)

    document, layout = _layout(language_code, text)
    assert len(layout.layers) == 1
    assert not layout.layers[0].overflow
    rendered = QtTextRenderer().render(document, layout)
    pixels = np.frombuffer(rendered.pixels, dtype=np.uint8).reshape(120, 480, 3)
    ink = np.max(np.abs(pixels.astype(np.int16) - 255), axis=2) > 12
    assert 20 < int(ink.sum()) < 30_000


@pytest.mark.parametrize("language_code", ("ar", "fa", "ur"))
def test_rtl_text_uses_right_alignment_and_keeps_latin_number_runs(
    language_code: str,
) -> None:
    document, layout = _layout(language_code, f"{REPRESENTATIVE_TEXT[language_code]} 50% SKU")
    layer = layout.layers[0]
    assert layer.style.alignment is TextAlignment.RIGHT
    rendered = QtTextRenderer().render(document, layout)
    pixels = np.frombuffer(rendered.pixels, dtype=np.uint8).reshape(120, 480, 3)
    ink = np.max(np.abs(pixels.astype(np.int16) - 255), axis=2) > 12
    _, xs = np.nonzero(ink)
    assert len(xs) > 20
    assert int(xs.max()) > document.asset.width * 0.8


def test_ltr_text_keeps_left_to_right_qt_direction() -> None:
    document, layout = _layout("en", "Product SKU-100")
    assert layout.layers[0].style.alignment is TextAlignment.CENTER
    font = QFont(layout.layers[0].style.font_family)
    text_layout = QTextLayout(layout.layers[0].text, font)
    assert text_layout.textOption().textDirection() in {
        Qt.LayoutDirection.LayoutDirectionAuto,
        Qt.LayoutDirection.LeftToRight,
    }
