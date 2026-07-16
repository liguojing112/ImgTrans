import os
from dataclasses import replace
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from src.application.composition import CreateCompositionEditor
from src.domain.image import ImageAsset, ImageDocument, ImageFileFormat
from src.domain.inpainting import EraseMask
from src.domain.layout import (
    ArtisticPreset,
    TextBox,
    TextLayer,
    TextLayout,
    TextStyle,
    default_arc_path,
)
from src.infrastructure.text_renderer import QtBasicTextLayoutAdapter, QtTextRenderer
from src.platform.fonts import resolve_system_font


def test_all_m2_edit_commands_undo_back_to_exact_initial_pixels() -> None:
    QApplication.instance() or QApplication(["m2-edit-integration"])
    asset = ImageAsset(Path("m2.png"), 220, 120, 1, ImageFileFormat.PNG, False, False)
    background = ImageDocument(asset, "RGB", bytes([245]) * 220 * 120 * 3)
    original = TextLayer(
        "original",
        "SALE",
        TextBox(110, 55, 140, 42),
        TextStyle(resolve_system_font("en"), 24, (20, 30, 40)),
    )
    renderer = QtTextRenderer()
    layout = TextLayout((original,))
    initial = renderer.render(background, layout)
    editor = CreateCompositionEditor(QtBasicTextLayoutAdapter(), renderer).execute(
        background, initial, layout
    )

    editor.replace_text("original", "SUMMER SALE")
    editor.replace_box("original", TextBox(120, 60, 150, 48, 8))
    current = editor.layout.layer_by_id("original")
    editor.replace_style(
        "original",
        replace(
            current.style,
            fill_rgb=(180, 25, 35),
            stroke_width=2,
            shadow_opacity=0.5,
            effect_preset=ArtisticPreset.POSTER,
        ),
        8,
    )
    editor.replace_path(
        "original", default_arc_path(editor.layout.layer_by_id("original").box)
    )
    added = editor.add_layer("新增译文")
    added_id = added.affected_region_id
    editor.delete_layer(added_id)

    mask = bytearray(220 * 120)
    for y in range(82, 98):
        mask[y * 220 + 150 : y * 220 + 190] = bytes([255]) * 40
    repaired_pixels = bytearray(background.pixels)
    for index, value in enumerate(mask):
        if value:
            repaired_pixels[index * 3 : index * 3 + 3] = bytes((180, 180, 180))
    repaired = ImageDocument(asset, "RGB", bytes(repaired_pixels))
    manual_layer = TextLayer(
        "manual-final",
        "手动译文",
        TextBox(170, 90, 40, 16),
        TextStyle(resolve_system_font("zh-Hans"), 12, (0, 0, 0)),
    )
    editor.apply_manual_region(repaired, manual_layer, EraseMask(220, 120, bytes(mask)))

    result = None
    for _ in range(7):
        result = editor.undo()
    assert editor.layout == layout
    assert editor.background_document.pixels == background.pixels
    assert result is not None
    assert result.document.pixels == initial.pixels
    assert not editor.can_undo
