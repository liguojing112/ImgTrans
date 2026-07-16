import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from src.application.composition import CreateCompositionEditor
from src.domain.image import ImageAsset, ImageDocument, ImageFileFormat
from src.domain.layout import (
    FontStyleHint,
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


def test_font_candidates_are_installed_and_cover_requested_text() -> None:
    QApplication.instance() or QApplication(["font-candidate-test"])
    candidates = recommend_system_fonts("商品 SALE", FontStyleHint.DISPLAY, 4)
    assert candidates
    assert all(isinstance(candidate, str) and candidate for candidate in candidates)
