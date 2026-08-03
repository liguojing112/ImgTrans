import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from src.application.composition import CreateCompositionEditor, transform_image_document
from src.domain.composition import ImageTransform
from src.domain.image import ImageAsset, ImageDocument, ImageFileFormat
from src.domain.layout import (
    default_arc_path,
    TextAlignment,
    TextBox,
    TextLayer,
    TextLayout,
    TextStyle,
    VerticalAlignment,
)
from src.domain.inpainting import EraseMask
from src.infrastructure.text_renderer import QtBasicTextLayoutAdapter, QtTextRenderer
from src.platform.fonts import resolve_system_font


def _background() -> ImageDocument:
    asset = ImageAsset(Path("edit.png"), 180, 80, 1, ImageFileFormat.PNG, False, False)
    return ImageDocument(asset, "RGB", np.full((80, 180, 3), 245, np.uint8).tobytes())


def _pattern_background(mode: str = "RGB") -> ImageDocument:
    channels = 4 if mode == "RGBA" else 3
    pixels = np.arange(60 * 90 * channels, dtype=np.uint8).reshape(
        60, 90, channels
    )
    asset = ImageAsset(
        Path("pattern.png"),
        90,
        60,
        1,
        ImageFileFormat.PNG,
        mode == "RGBA",
        False,
    )
    return ImageDocument(asset, mode, pixels.tobytes())


def test_edit_reflows_renders_and_round_trips_history() -> None:
    QApplication.instance() or QApplication(["edit-composition-test"])
    background = _background()
    layer = TextLayer(
        "r1",
        "促销",
        TextBox(90, 40, 120, 30),
        TextStyle(
            resolve_system_font("zh-Hans"),
            20,
            (20, 30, 40),
            font_weight=700,
        ),
    )
    renderer = QtTextRenderer()
    initial_layout = TextLayout((layer,))
    initial = renderer.render(background, initial_layout)
    editor = CreateCompositionEditor(
        QtBasicTextLayoutAdapter(), renderer
    ).execute(background, initial, initial_layout)
    edited = editor.replace_text("r1", "夏季新品促销")
    assert edited.layout.layer_by_id("r1").text == "夏季新品促销"
    assert edited.layout.layer_by_id("r1").style.font_weight == 700
    assert edited.can_undo and not edited.can_redo
    assert edited.document.pixels != initial.pixels
    undone = editor.undo()
    assert undone.layout.layer_by_id("r1").text == "促销"
    assert undone.document.pixels == initial.pixels
    assert undone.can_redo
    redone = editor.redo()
    assert redone.layout.layer_by_id("r1").text == "夏季新品促销"
    assert redone.layout.layer_by_id("r1").style.font_weight == 700
    assert redone.document.pixels == edited.document.pixels


def test_initial_translation_can_be_undone_to_exact_original_and_redone() -> None:
    QApplication.instance() or QApplication(["initial-translation-history-test"])
    original = _background()
    repaired_pixels = np.frombuffer(original.pixels, np.uint8).copy()
    repaired_pixels[30:90] = 180
    repaired = ImageDocument(original.asset, original.mode, repaired_pixels.tobytes())
    layer = TextLayer(
        "translated",
        "Translated",
        TextBox(90, 40, 100, 28),
        TextStyle(resolve_system_font("en"), 18, (10, 20, 30)),
    )
    layout = TextLayout((layer,))
    renderer = QtTextRenderer()
    translated = renderer.render(repaired, layout)
    editor = CreateCompositionEditor(
        QtBasicTextLayoutAdapter(),
        renderer,
    ).execute(
        repaired,
        translated,
        layout,
        original,
        record_initial_translation=True,
    )

    assert editor.can_undo
    undone = editor.undo()
    assert undone.document.pixels == original.pixels
    assert undone.layout.layers == ()
    assert undone.can_redo

    redone = editor.redo()
    assert redone.document.pixels == translated.pixels
    assert redone.layout == layout
    assert redone.can_undo


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


def test_restore_original_region_is_undoable_and_exact() -> None:
    QApplication.instance() or QApplication(["restore-region-test"])
    background = _background()
    source_pixels = np.frombuffer(background.pixels, np.uint8).reshape(80, 180, 3).copy()
    source_pixels[20:50, 40:100] = (12, 34, 56)
    source = ImageDocument(background.asset, "RGB", source_pixels.tobytes())
    layer = TextLayer(
        "r1",
        "translated",
        TextBox(70, 35, 60, 30),
        TextStyle(resolve_system_font("en"), 16, (0, 0, 0)),
    )
    layout = TextLayout((layer,))
    renderer = QtTextRenderer()
    editor = CreateCompositionEditor(QtBasicTextLayoutAdapter(), renderer).execute(
        background,
        renderer.render(background, layout),
        layout,
    )
    mask_array = np.zeros((80, 180), np.uint8)
    mask_array[20:50, 40:100] = 255
    restored = editor.restore_original_region(
        "r1",
        source,
        EraseMask(180, 80, mask_array.tobytes()),
    )
    pixels = np.frombuffer(restored.document.pixels, np.uint8).reshape(80, 180, 3)
    assert np.array_equal(pixels[20:50, 40:100], source_pixels[20:50, 40:100])
    assert all(item.region_id != "r1" for item in restored.layout.layers)
    undone = editor.undo()
    assert undone.layout.layer_by_id("r1").text == "translated"


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


def test_crop_transforms_text_path_and_undo_restores_full_canvas() -> None:
    QApplication.instance() or QApplication(["crop-composition-test"])
    background = _background()
    box = TextBox(90, 40, 80, 24)
    layer = TextLayer(
        "arc",
        "ARC",
        box,
        TextStyle(resolve_system_font("en"), 16, (0, 0, 0)),
        path=default_arc_path(box),
    )
    renderer = QtTextRenderer()
    editor = CreateCompositionEditor(
        QtBasicTextLayoutAdapter(), renderer
    ).execute(background, renderer.render(background, TextLayout((layer,))), TextLayout((layer,)))

    cropped = editor.crop(TextBox(100, 40, 100, 60))

    assert (cropped.document.asset.width, cropped.document.asset.height) == (100, 60)
    moved = cropped.layout.layer_by_id("arc")
    assert moved.box.center_x == pytest.approx(40)
    assert moved.box.center_y == pytest.approx(30)
    assert moved.path is not None
    assert moved.path.start.x == pytest.approx(layer.path.start.x - 50)
    restored = editor.undo()
    assert restored.document.asset.width == 180
    assert restored.layout.layer_by_id("arc") == layer


@pytest.mark.parametrize("mode,channels", [("RGB", 3), ("RGBA", 4)])
def test_background_repair_only_commits_masked_pixels(mode: str, channels: int) -> None:
    QApplication.instance() or QApplication(["repair-patch-test"])
    width, height = 12, 8
    pixels = np.arange(width * height * channels, dtype=np.uint8).reshape(
        height, width, channels
    )
    asset = ImageAsset(
        Path("repair.png"),
        width,
        height,
        1,
        ImageFileFormat.PNG,
        mode == "RGBA",
        False,
    )
    original = ImageDocument(asset, mode, pixels.tobytes())
    changed = pixels.copy()
    changed[:, :, :] = 250
    repaired = ImageDocument(asset, mode, changed.tobytes())
    mask_pixels = bytearray(width * height)
    for y in range(2, 5):
        for x in range(4, 8):
            mask_pixels[y * width + x] = 255
    mask = EraseMask(width, height, bytes(mask_pixels))
    editor = CreateCompositionEditor(
        QtBasicTextLayoutAdapter(), QtTextRenderer()
    ).execute(original, original, TextLayout(()))

    result = editor.apply_background_repair(repaired, mask)
    output = np.frombuffer(result.document.pixels, dtype=np.uint8).reshape(
        height, width, channels
    )
    selected = np.zeros((height, width), dtype=bool)
    selected[2:5, 4:8] = True
    assert np.array_equal(output[selected], changed[selected])
    assert np.array_equal(output[~selected], pixels[~selected])
    assert editor.undo().document.pixels == original.pixels


def test_watermark_add_duplicate_crop_and_undo_share_history() -> None:
    QApplication.instance() or QApplication(["watermark-composition-test"])
    background = _background()
    editor = CreateCompositionEditor(
        QtBasicTextLayoutAdapter(), QtTextRenderer()
    ).execute(background, background, TextLayout(()))
    style = TextStyle(resolve_system_font("en"), 20, (255, 255, 255))

    added = editor.add_text_watermark("DEMO", style, opacity=0.4)
    assert len(added.watermarks) == 1
    assert added.document.pixels != background.pixels
    watermark_id = added.watermarks[0].watermark_id
    duplicated = editor.duplicate_watermark(watermark_id)
    assert len(duplicated.watermarks) == 2
    cropped = editor.crop(TextBox(90, 40, 120, 70))
    assert cropped.viewport is not None
    assert cropped.document.asset.width == 120
    editor.undo()
    editor.undo()
    restored = editor.undo()
    assert not restored.watermarks
    assert restored.document.pixels == background.pixels


@pytest.mark.parametrize(
    ("operation", "expected_size", "expected_center", "expected_rotation"),
    (
        (ImageTransform.ROTATE_90_CW, (60, 90), (40, 30), 105),
        (ImageTransform.ROTATE_90_CCW, (60, 90), (20, 60), -75),
        (ImageTransform.ROTATE_180, (90, 60), (60, 40), -165),
        (ImageTransform.FLIP_HORIZONTAL, (90, 60), (60, 20), 165),
        (ImageTransform.FLIP_VERTICAL, (90, 60), (30, 40), -15),
    ),
)
def test_canvas_transform_updates_text_reference_and_undo(
    operation: ImageTransform,
    expected_size: tuple[int, int],
    expected_center: tuple[float, float],
    expected_rotation: float,
) -> None:
    QApplication.instance() or QApplication(["canvas-transform-test"])
    background = _pattern_background()
    box = TextBox(30, 20, 28, 14, 15)
    layer = TextLayer(
        "arc",
        "ARC",
        box,
        TextStyle(resolve_system_font("en"), 12, (0, 0, 0)),
        path=default_arc_path(box),
    )
    renderer = QtTextRenderer()
    editor = CreateCompositionEditor(
        QtBasicTextLayoutAdapter(), renderer
    ).execute(
        background,
        renderer.render(background, TextLayout((layer,))),
        TextLayout((layer,)),
        background,
    )

    transformed = editor.transform_canvas(operation)

    assert (
        transformed.document.asset.width,
        transformed.document.asset.height,
    ) == expected_size
    changed = transformed.layout.layer_by_id("arc")
    assert (changed.box.center_x, changed.box.center_y) == pytest.approx(
        expected_center
    )
    assert (changed.box.width, changed.box.height) == pytest.approx((28, 14))
    assert changed.box.rotation_degrees == pytest.approx(expected_rotation)
    assert changed.path is not None
    expected_reference = transform_image_document(background, operation)
    assert transformed.reference_document.pixels == expected_reference.pixels
    restored = editor.undo()
    assert restored.layout.layer_by_id("arc") == layer
    assert restored.reference_document.pixels == background.pixels
    assert (restored.document.asset.width, restored.document.asset.height) == (90, 60)


@pytest.mark.parametrize("mode", ("RGB", "RGBA"))
def test_orthogonal_image_transform_is_pixel_exact(mode: str) -> None:
    document = _pattern_background(mode)
    rotated = transform_image_document(document, ImageTransform.ROTATE_90_CW)
    restored = transform_image_document(rotated, ImageTransform.ROTATE_90_CCW)
    assert restored.mode == mode
    assert restored.pixels == document.pixels


@pytest.mark.parametrize(
    ("operation", "mirror_x", "mirror_y"),
    (
        (ImageTransform.FLIP_HORIZONTAL, True, False),
        (ImageTransform.FLIP_VERTICAL, False, True),
    ),
)
def test_canvas_flip_marks_text_for_glyph_mirroring(
    operation: ImageTransform,
    mirror_x: bool,
    mirror_y: bool,
) -> None:
    QApplication.instance() or QApplication(["canvas-flip-text-test"])
    background = _pattern_background()
    layer = TextLayer(
        "flip",
        "FLIP",
        TextBox(30, 20, 28, 14, 15),
        TextStyle(resolve_system_font("en"), 12, (0, 0, 0)),
    )
    renderer = QtTextRenderer()
    editor = CreateCompositionEditor(
        QtBasicTextLayoutAdapter(), renderer
    ).execute(
        background,
        renderer.render(background, TextLayout((layer,))),
        TextLayout((layer,)),
        background,
    )

    changed = editor.transform_canvas(operation).layout.layer_by_id("flip")

    assert changed.mirror_x is mirror_x
    assert changed.mirror_y is mirror_y


def test_invisible_text_layer_is_not_rendered_but_remains_in_layout() -> None:
    QApplication.instance() or QApplication(["hidden-layer-test"])
    background = _background()
    layer = TextLayer(
        "hidden",
        "HIDDEN",
        TextBox(90, 40, 100, 30),
        TextStyle(resolve_system_font("en"), 20, (0, 0, 0)),
        visible=False,
    )
    editor = CreateCompositionEditor(
        QtBasicTextLayoutAdapter(), QtTextRenderer()
    ).execute(background, background, TextLayout((layer,)))
    result = editor.replace_layer(layer)
    assert result.layout.layer_by_id("hidden").visible is False
    assert result.document.pixels == background.pixels
