import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from src.application.composition import CreateCompositionEditor
from src.domain.image import ImageAsset, ImageDocument, ImageFileFormat
from src.domain.layout import (
    TextAlignment,
    TextBox,
    TextLayer,
    TextLayout,
    TextStyle,
    VerticalAlignment,
)
from src.infrastructure.text_renderer import QtBasicTextLayoutAdapter, QtTextRenderer
from src.platform.fonts import resolve_system_font


def _background() -> ImageDocument:
    asset = ImageAsset(Path("edit.png"), 180, 80, 1, ImageFileFormat.PNG, False, False)
    return ImageDocument(asset, "RGB", np.full((80, 180, 3), 245, np.uint8).tobytes())


def test_edit_reflows_renders_and_round_trips_history() -> None:
    QApplication.instance() or QApplication(["edit-composition-test"])
    background = _background()
    layer = TextLayer(
        "r1",
        "促销",
        TextBox(90, 40, 120, 30),
        TextStyle(resolve_system_font("zh-Hans"), 20, (20, 30, 40)),
    )
    renderer = QtTextRenderer()
    initial_layout = TextLayout((layer,))
    initial = renderer.render(background, initial_layout)
    editor = CreateCompositionEditor(
        QtBasicTextLayoutAdapter(), renderer
    ).execute(background, initial, initial_layout)
    edited = editor.replace_text("r1", "夏季新品促销")
    assert edited.layout.layer_by_id("r1").text == "夏季新品促销"
    assert edited.can_undo and not edited.can_redo
    assert edited.document.pixels != initial.pixels
    undone = editor.undo()
    assert undone.layout.layer_by_id("r1").text == "促销"
    assert undone.document.pixels == initial.pixels
    assert undone.can_redo
    redone = editor.redo()
    assert redone.layout.layer_by_id("r1").text == "夏季新品促销"
    assert redone.document.pixels == edited.document.pixels


def test_long_edit_exposes_overflow_without_losing_text() -> None:
    QApplication.instance() or QApplication(["edit-overflow-test"])
    background = _background()
    layer = TextLayer(
        "tiny",
        "A",
        TextBox(20, 15, 12, 5),
        TextStyle(resolve_system_font("zh-Hans"), 6, (0, 0, 0)),
    )
    renderer = QtTextRenderer()
    layout = TextLayout((layer,))
    editor = CreateCompositionEditor(QtBasicTextLayoutAdapter(), renderer).execute(
        background,
        renderer.render(background, layout),
        layout,
    )
    result = editor.replace_text("tiny", "这是一段无法放入框内的完整长译文")
    edited = result.layout.layer_by_id("tiny")
    assert edited.overflow
    assert edited.text.endswith("完整长译文")


class _FailingRenderer:
    def render(self, document: ImageDocument, layout: TextLayout) -> ImageDocument:
        raise RuntimeError("render failed")


def test_failed_render_does_not_commit_edit_history() -> None:
    QApplication.instance() or QApplication(["edit-rollback-test"])
    background = _background()
    layer = TextLayer(
        "r1",
        "原文",
        TextBox(90, 40, 120, 30),
        TextStyle(resolve_system_font("zh-Hans"), 20, (20, 30, 40)),
    )
    editor = CreateCompositionEditor(
        QtBasicTextLayoutAdapter(), _FailingRenderer()
    ).execute(background, background, TextLayout((layer,)))
    with pytest.raises(RuntimeError, match="render failed"):
        editor.replace_text("r1", "修改")
    assert editor.layout.layer_by_id("r1").text == "原文"
    assert not editor.can_undo


def test_geometry_edit_reflows_and_uses_same_undo_history() -> None:
    QApplication.instance() or QApplication(["geometry-edit-test"])
    background = _background()
    original = TextLayer(
        "r1",
        "一段需要重新适配的译文",
        TextBox(90, 40, 120, 30),
        TextStyle(resolve_system_font("zh-Hans"), 18, (20, 30, 40)),
    )
    renderer = QtTextRenderer()
    layout = TextLayout((original,))
    editor = CreateCompositionEditor(QtBasicTextLayoutAdapter(), renderer).execute(
        background,
        renderer.render(background, layout),
        layout,
    )
    smaller = TextBox(105, 45, 55, 18, 17)
    edited = editor.replace_box("r1", smaller)
    layer = edited.layout.layer_by_id("r1")
    assert layer.box == smaller
    assert layer.style.font_size <= original.style.font_size
    assert edited.can_undo
    undone = editor.undo()
    assert undone.layout.layer_by_id("r1") == original
    redone = editor.redo()
    assert redone.layout.layer_by_id("r1").box == smaller


def test_style_stroke_shadow_and_manual_size_render_and_undo() -> None:
    QApplication.instance() or QApplication(["style-edit-test"])
    background = _background()
    original = TextLayer(
        "r1",
        "STYLE",
        TextBox(90, 40, 120, 34),
        TextStyle(resolve_system_font("en"), 20, (20, 30, 40)),
    )
    renderer = QtTextRenderer()
    layout = TextLayout((original,))
    initial = renderer.render(background, layout)
    editor = CreateCompositionEditor(QtBasicTextLayoutAdapter(), renderer).execute(
        background, initial, layout
    )
    style = TextStyle(
        original.style.font_family,
        14,
        (180, 20, 30),
        TextAlignment.RIGHT,
        VerticalAlignment.BOTTOM,
        False,
        False,
        (255, 255, 255),
        2,
        (0, 0, 0),
        0.7,
        4,
        3,
    )
    result = editor.replace_style("r1", style, 25)
    changed = result.layout.layer_by_id("r1")
    assert changed.style == style
    assert changed.style.font_size == 14
    assert changed.box.rotation_degrees == 25
    assert result.document.pixels != initial.pixels
    undone = editor.undo()
    assert undone.layout.layer_by_id("r1") == original
    assert undone.document.pixels == initial.pixels


def test_add_delete_layers_are_rendered_and_undoable() -> None:
    QApplication.instance() or QApplication(["layer-management-test"])
    background = _background()
    renderer = QtTextRenderer()
    editor = CreateCompositionEditor(QtBasicTextLayoutAdapter(), renderer).execute(
        background, background, TextLayout(())
    )
    added = editor.add_layer()
    assert len(added.layout.layers) == 1
    assert added.affected_region_id.startswith("manual-")
    region_id = added.affected_region_id
    assert added.layout.layer_by_id(region_id).text == "新译文"
    deleted = editor.delete_layer(region_id)
    assert not deleted.layout.layers
    restored = editor.undo()
    assert restored.layout.layer_by_id(region_id).text == "新译文"
    editor.undo()
    assert not editor.layout.layers
    editor.redo()
    assert editor.layout.layer_by_id(region_id).text == "新译文"


def test_styled_render_preserves_rgba_outside_text_box() -> None:
    QApplication.instance() or QApplication(["style-alpha-test"])
    pixels = np.zeros((60, 120, 4), dtype=np.uint8)
    pixels[:, :, :3] = (40, 80, 120)
    pixels[:, :, 3] = np.arange(120, dtype=np.uint8)[None, :]
    asset = ImageAsset(Path("alpha-style.png"), 120, 60, 1, ImageFileFormat.PNG, True, False)
    background = ImageDocument(asset, "RGBA", pixels.tobytes())
    style = TextStyle(
        resolve_system_font("en"),
        24,
        (255, 255, 255),
        stroke_rgb=(0, 0, 0),
        stroke_width=2,
        shadow_opacity=0.6,
        shadow_offset_x=3,
        shadow_offset_y=2,
    )
    layout = TextLayout((TextLayer("alpha", "TEXT", TextBox(60, 30, 70, 30), style),))
    output = QtTextRenderer().render(background, layout)
    rendered = np.frombuffer(output.pixels, dtype=np.uint8).reshape(60, 120, 4)
    outside = np.ones((60, 120), dtype=bool)
    outside[10:50, 15:105] = False
    assert np.array_equal(rendered[outside], pixels[outside])
    assert np.any(rendered[~outside] != pixels[~outside])
