import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtWidgets import QApplication

from src.domain.image import ImageAsset, ImageDocument, ImageFileFormat
from src.domain.layout import fit_font_size
from src.domain.ocr import OcrResult, TextRegion, order_quad
from src.domain.translation import (
    TranslationMode,
    TranslationResult,
    TranslationSelection,
    TranslationStatus,
    TranslationUnit,
)
from src.infrastructure.text_renderer import QtBasicTextLayoutAdapter, QtTextRenderer


def _document() -> ImageDocument:
    pixels = np.full((80, 180, 3), 245, dtype=np.uint8)
    pixels[20:52, 20:150] = (20, 30, 40)
    asset = ImageAsset(Path("layout.png"), 180, 80, 1, ImageFileFormat.PNG, False, False)
    return ImageDocument(asset, "RGB", pixels.tobytes())


def _translation(region_id: str, text: str = "夏季促销") -> TranslationResult:
    return TranslationResult(
        (
            TranslationUnit(
                region_id,
                "SUMMER SALE",
                "en",
                "zh-Hans",
                text,
                TranslationStatus.TRANSLATED,
            ),
        ),
        TranslationSelection(TranslationMode.ALL, "zh-Hans"),
        "fixture",
        1,
    )


def test_binary_font_fit_returns_largest_fitting_value_and_overflow() -> None:
    size, overflow = fit_font_size(6, 30, lambda value: value <= 18)
    assert 17.9 <= size <= 18
    assert not overflow
    assert fit_font_size(6, 30, lambda value: False) == (6, True)


def test_qt_layout_preserves_region_geometry_and_estimates_foreground() -> None:
    QApplication.instance() or QApplication(["layout-test"])
    document = _document()
    region = TextRegion(
        "r1",
        order_quad(((20, 20), (150, 20), (150, 52), (20, 52))),
        "SUMMER SALE",
        0.99,
        "en",
        "fixture",
    )
    layout = QtBasicTextLayoutAdapter().layout(
        document,
        OcrResult((region,), "en", "fixture", 1),
        _translation("r1"),
    )
    assert len(layout.layers) == 1
    layer = layout.layers[0]
    assert layer.box.center_x == 85
    assert layer.box.center_y == 36
    assert layer.box.width == 130
    assert layer.style.font_size >= 6
    assert max(layer.style.fill_rgb) < 80
    repaired = ImageDocument(
        document.asset,
        document.mode,
        np.full((80, 180, 3), 245, dtype=np.uint8).tobytes(),
    )
    rendered = QtTextRenderer().render(repaired, layout)
    assert rendered.mode == "RGB"
    assert rendered.pixels != repaired.pixels


def test_long_translation_is_marked_as_overflow_in_tiny_box() -> None:
    QApplication.instance() or QApplication(["layout-overflow-test"])
    document = _document()
    region = TextRegion(
        "tiny",
        order_quad(((10, 10), (24, 10), (24, 15), (10, 15))),
        "X",
        0.99,
        "en",
        "fixture",
    )
    layout = QtBasicTextLayoutAdapter().layout(
        document,
        OcrResult((region,), "en", "fixture", 1),
        _translation("tiny", "这是一段无法放入极小文字框的长译文"),
    )
    assert layout.layers[0].overflow
