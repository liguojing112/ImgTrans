import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

from src.domain.image import ImageAsset, ImageDocument, ImageFileFormat
from src.domain.layout import TextAlignment, TextStyle, fit_font_size
from src.domain.ocr import OcrResult, TextRegion, order_quad
from src.domain.translation import (
    TranslationMode,
    TranslationResult,
    TranslationSelection,
    TranslationStatus,
    TranslationUnit,
)
from src.infrastructure.text_renderer import (
    QtBasicTextLayoutAdapter,
    QtTextRenderer,
    _estimate_foreground_color,
    _text_flags,
)


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
    assert min(layer.style.fill_rgb) > 240
    repaired = ImageDocument(
        document.asset,
        document.mode,
        np.full((80, 180, 3), 245, dtype=np.uint8).tobytes(),
    )
    rendered = QtTextRenderer().render(repaired, layout)
    assert rendered.mode == "RGB"
    assert rendered.pixels != repaired.pixels


def test_foreground_estimation_preserves_white_text_over_photo_badge() -> None:
    pixels = np.full((48, 160, 3), (154, 154, 156), dtype=np.uint8)
    pixels[:, 38:49] = (72, 74, 78)
    pixels[:, 112:120] = (82, 84, 88)
    pixels[12:17, 58:104] = (247, 247, 248)
    pixels[23:28, 51:111] = (245, 246, 247)
    pixels[34:39, 60:101] = (248, 248, 249)
    asset = ImageAsset(
        Path("badge.png"),
        160,
        48,
        1,
        ImageFileFormat.PNG,
        False,
        False,
    )
    document = ImageDocument(asset, "RGB", pixels.tobytes())
    region = TextRegion(
        "badge",
        order_quad(((0, 0), (159, 0), (159, 47), (0, 47))),
        "优质售后",
        1.0,
        "zh-Hans",
        "fixture",
    )

    assert min(_estimate_foreground_color(document, region)) >= 240


def test_foreground_estimation_keeps_dark_text_on_yellow_background() -> None:
    pixels = np.full((40, 140, 3), (245, 205, 25), dtype=np.uint8)
    pixels[10:15, 35:105] = (20, 22, 18)
    pixels[23:28, 42:98] = (24, 25, 20)
    asset = ImageAsset(
        Path("packaging.png"),
        140,
        40,
        1,
        ImageFileFormat.PNG,
        False,
        False,
    )
    document = ImageDocument(asset, "RGB", pixels.tobytes())
    region = TextRegion(
        "packaging",
        order_quad(((0, 0), (139, 0), (139, 39), (0, 39))),
        "洗脸巾",
        1.0,
        "zh-Hans",
        "fixture",
    )

    assert max(_estimate_foreground_color(document, region)) <= 30


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


def test_long_latin_translation_uses_limited_condensing_for_readability() -> None:
    QApplication.instance() or QApplication(["layout-condensed-test"])
    pixels = np.full((80, 500, 3), (30, 70, 150), dtype=np.uint8)
    asset = ImageAsset(
        Path("paragraph.png"),
        500,
        80,
        1,
        ImageFileFormat.PNG,
        False,
        False,
    )
    document = ImageDocument(asset, "RGB", pixels.tobytes())
    region = TextRegion(
        "paragraph",
        order_quad(((30, 20), (447, 20), (447, 44), (30, 44))),
        "构建全新的家居装饰供应链",
        1.0,
        "zh-Hans",
        "fixture",
    )
    translated = (
        "Building a brand-new home decoration supply chain, committed to "
        "bringing the boundaries of decoration into the home."
    )
    result = TranslationResult(
        (
            TranslationUnit(
                "paragraph",
                region.text,
                "zh-Hans",
                "en",
                translated,
                TranslationStatus.TRANSLATED,
            ),
        ),
        TranslationSelection(TranslationMode.ALL, "en"),
        "fixture",
        1,
    )

    layer = QtBasicTextLayoutAdapter().layout(
        document,
        OcrResult((region,), "zh-Hans", "fixture", 1),
        result,
    ).layers[0]

    assert 67 <= layer.style.font_stretch < 100
    assert layer.style.font_size > 6


def test_adjacent_long_cjk_lines_share_one_editable_paragraph_layer() -> None:
    QApplication.instance() or QApplication(["layout-paragraph-test"])
    pixels = np.full((100, 500, 3), (30, 70, 150), dtype=np.uint8)
    asset = ImageAsset(
        Path("paragraph-lines.png"),
        500,
        100,
        1,
        ImageFileFormat.PNG,
        False,
        False,
    )
    document = ImageDocument(asset, "RGB", pixels.tobytes())
    regions = (
        TextRegion(
            "line-1",
            order_quad(((30, 20), (447, 20), (447, 44), (30, 44))),
            "构建全新的家居装饰供应链，致力于让装饰边界到家",
            1.0,
            "zh-Hans",
            "fixture",
        ),
        TextRegion(
            "line-2",
            order_quad(((30, 44), (306, 44), (306, 66), (30, 66))),
            "中国家居装饰五金一站式品牌概念",
            1.0,
            "zh-Hans",
            "fixture",
        ),
    )
    translations = (
        TranslationUnit(
            "line-1",
            regions[0].text,
            "zh-Hans",
            "en",
            "Building a new home decoration supply chain.",
            TranslationStatus.TRANSLATED,
        ),
        TranslationUnit(
            "line-2",
            regions[1].text,
            "zh-Hans",
            "en",
            "A one-stop brand concept for home decoration hardware.",
            TranslationStatus.TRANSLATED,
        ),
    )
    result = TranslationResult(
        translations,
        TranslationSelection(TranslationMode.ALL, "en"),
        "fixture",
        1,
    )

    layout = QtBasicTextLayoutAdapter().layout(
        document,
        OcrResult(regions, "zh-Hans", "fixture", 1),
        result,
    )

    assert len(layout.layers) == 1
    assert layout.layers[0].region_id == "line-1"
    assert layout.layers[0].text == (
        "Building a new home decoration supply chain. "
        "A one-stop brand concept for home decoration hardware."
    )
    assert layout.layers[0].style.alignment is TextAlignment.LEFT
    assert layout.layers[0].box.height == 46


def test_latin_text_wraps_only_at_word_boundaries() -> None:
    style = TextStyle("Arial", 12, (0, 0, 0))
    flags = _text_flags(style, "Water purifiers")
    assert flags & Qt.TextFlag.TextWordWrap
    assert not flags & Qt.TextFlag.TextWrapAnywhere


def test_unspaced_cjk_text_can_wrap_between_characters() -> None:
    style = TextStyle("Arial", 12, (0, 0, 0))
    flags = _text_flags(style, "复杂中文排版")
    assert flags & Qt.TextFlag.TextWordWrap
    assert flags & Qt.TextFlag.TextWrapAnywhere
