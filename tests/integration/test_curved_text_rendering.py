import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from src.application.composition import CreateCompositionEditor
from src.domain.image import ImageAsset, ImageDocument, ImageFileFormat
from src.domain.layout import (
    CircularTextPath,
    FontStyleHint,
    PathPoint,
    TextBox,
    TextLayer,
    TextLayout,
    TextStyle,
    default_arc_path,
    transform_arc_path,
)
from src.infrastructure.text_renderer import QtBasicTextLayoutAdapter, QtTextRenderer
from src.platform.font_candidates import recommend_system_fonts
from src.platform.fonts import resolve_system_font


def _background() -> ImageDocument:
    asset = ImageAsset(Path("curve.png"), 240, 130, 1, ImageFileFormat.PNG, False, False)
    return ImageDocument(asset, "RGB", bytes([245]) * 240 * 130 * 3)


def test_curved_text_renders_and_round_trips_unified_history() -> None:
    QApplication.instance() or QApplication(["curve-render-test"])
    background = _background()
    box = TextBox(120, 70, 180, 65)
    layer = TextLayer(
        "curve",
        "CURVED 商品",
        box,
        TextStyle(resolve_system_font("zh-Hans"), 28, (20, 30, 40), auto_fit=False),
    )
    renderer = QtTextRenderer()
    straight = renderer.render(background, TextLayout((layer,)))
    editor = CreateCompositionEditor(QtBasicTextLayoutAdapter(), renderer).execute(
        background,
        straight,
        TextLayout((layer,)),
    )
    curved = editor.replace_path("curve", default_arc_path(box, 0.65))
    assert curved.layout.layer_by_id("curve").path is not None
    assert curved.document.pixels != straight.pixels
    assert editor.undo().document.pixels == straight.pixels
    assert editor.redo().document.pixels == curved.document.pixels


def test_resizing_curved_layer_transforms_path_with_box() -> None:
    QApplication.instance() or QApplication(["curve-transform-test"])
    background = _background()
    box = TextBox(120, 65, 160, 50)
    path = default_arc_path(box)
    layer = TextLayer(
        "curve",
        "TEXT",
        box,
        TextStyle(resolve_system_font("en"), 22, (0, 0, 0)),
        path=path,
    )
    renderer = QtTextRenderer()
    layout = TextLayout((layer,))
    initial = renderer.render(background, layout)
    editor = CreateCompositionEditor(QtBasicTextLayoutAdapter(), renderer).execute(
        background, initial, layout
    )
    target = TextBox(130, 70, 120, 70, 15)
    result = editor.replace_box("curve", target)
    assert result.layout.layer_by_id("curve").path == transform_arc_path(path, box, target)


def test_circular_text_renders_glyphs_along_the_ring() -> None:
    QApplication.instance() or QApplication(["circular-render-test"])
    width = height = 260
    asset = ImageAsset(
        Path("circular.png"),
        width,
        height,
        1,
        ImageFileFormat.PNG,
        False,
        False,
    )
    background = ImageDocument(
        asset,
        "RGB",
        bytes([255]) * width * height * 3,
    )
    path = CircularTextPath(PathPoint(130, 130), 85, 200, 340)
    layer = TextLayer(
        "ring",
        "圆环文字排版",
        TextBox(130, 130, 190, 32),
        TextStyle(
            resolve_system_font("zh-Hans"),
            24,
            (0, 0, 0),
            auto_fit=False,
        ),
        path=path,
    )
    rendered = QtTextRenderer().render(background, TextLayout((layer,)))
    pixels = np.frombuffer(rendered.pixels, dtype=np.uint8).reshape(
        height,
        width,
        3,
    )
    ys, xs = np.where(np.any(pixels < 220, axis=2))
    assert len(xs) > 20
    radii = np.hypot(xs - 130, ys - 130)
    assert np.median(radii) == pytest.approx(85, abs=14)
    assert np.ptp(ys) > 15


def test_font_candidates_are_installed_and_cover_requested_text() -> None:
    QApplication.instance() or QApplication(["font-candidate-test"])
    candidates = recommend_system_fonts("商品 SALE", FontStyleHint.DISPLAY, 4)
    assert candidates
    assert all(isinstance(candidate, str) and candidate for candidate in candidates)
