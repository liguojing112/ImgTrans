import os
from dataclasses import replace
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import cv2
import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QFontMetricsF

from src.domain.image import ImageAsset, ImageDocument, ImageFileFormat
from src.domain.layout import (
    CircularTextPath,
    PathPoint,
    TextAlignment,
    TextBox,
    TextLayer,
    TextStyle,
    default_arc_path,
    ensure_bottom_inward_circular_path,
    fit_font_size,
    transform_arc_path,
)
from src.domain.ocr import (
    OcrObservation,
    OcrPreviewStrip,
    OcrResult,
    Point,
    RingBand,
    TextRegion,
    order_quad,
)
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
    _align_panel_title_and_body,
    _arc_text_lines,
    _estimate_foreground_color,
    _estimate_font_weight,
    _estimate_arc_text_path,
    _fit_dense_short_word_overflow,
    _fit_enhanced_tangent_layer,
    _fit_short_latin_spacing,
    _font_for_layer,
    _font_for_style,
    _font_for_text,
    _matching_background_run_box,
    _normalize_repeated_curved_layers,
    _normalize_repeated_panel_rows,
    _normalize_repeated_vertical_labels,
    _normalize_visual_group_sizes,
    _render_font_and_horizontal_scale,
    _text_fits,
    _text_flags,
    _text_box_for_translation,
    _bottom_inward_text_angle,
    _vertical_colored_label_background,
    _vertical_colored_label_foreground,
)
from src.platform.fonts import resolve_system_font


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


def test_circular_text_path_uses_exact_radius_and_tangent() -> None:
    path = CircularTextPath(PathPoint(100, 100), 50, -90, 0)
    assert path.start.x == pytest.approx(100)
    assert path.start.y == pytest.approx(50)
    assert path.end.x == pytest.approx(150)
    assert path.end.y == pytest.approx(100)
    midpoint = path.point_at(0.5)
    assert midpoint.x == pytest.approx(135.355, abs=0.01)
    assert midpoint.y == pytest.approx(64.645, abs=0.01)
    tangent = path.tangent_at(0)
    assert tangent.x > 0
    assert tangent.y == pytest.approx(0, abs=0.01)
    assert path.approximate_length() == pytest.approx(np.pi * 25)


def test_circular_text_path_places_the_character_bottom_toward_center() -> None:
    path = CircularTextPath(PathPoint(100, 100), 50, 90, 150)
    inward = ensure_bottom_inward_circular_path(path)
    assert inward.center == path.center
    assert inward.radius == path.radius
    assert {inward.start, inward.end} == {path.start, path.end}
    assert inward.start_angle_degrees == 90
    assert inward.end_angle_degrees == 150

    reversed_path = CircularTextPath(PathPoint(100, 100), 50, -60, -120)
    corrected = ensure_bottom_inward_circular_path(reversed_path)
    assert corrected.start_angle_degrees == -120
    assert corrected.end_angle_degrees == -60


def test_circular_glyph_bottom_faces_the_center_at_every_position() -> None:
    path = CircularTextPath(PathPoint(100, 100), 50, 30, 150)
    for position in (0.0, 0.25, 0.5, 0.75, 1.0):
        tangent = path.tangent_at(position)
        raw_angle = np.degrees(np.arctan2(tangent.y, tangent.x))
        angle = _bottom_inward_text_angle(path, position, raw_angle)
        point = path.point_at(position)
        inward = np.asarray(
            (path.center.x - point.x, path.center.y - point.y),
            dtype=float,
        )
        glyph_bottom = np.asarray(
            (-np.sin(np.radians(angle)), np.cos(np.radians(angle))),
            dtype=float,
        )
        assert float(inward @ glyph_bottom) > 0


def test_high_recall_ring_region_creates_true_circular_path() -> None:
    QApplication.instance() or QApplication(["layout-circular-path-test"])
    width = height = 240
    asset = ImageAsset(
        Path("ring-layout.png"),
        width,
        height,
        1,
        ImageFileFormat.PNG,
        False,
        False,
    )
    document = ImageDocument(
        asset,
        "RGB",
        np.full((height, width, 3), 245, dtype=np.uint8).tobytes(),
    )
    polygon = order_quad(((90, 24), (150, 24), (150, 36), (90, 36)))
    observation = OcrObservation(
        "polar",
        0,
        3,
        0.95,
        polygon,
        "Business",
        "polar:0:scale:3",
    )
    region = TextRegion(
        "ring",
        polygon,
        "Business",
        0.95,
        "en",
        "circular",
        observations=(observation,),
        enhanced_only=True,
        auto_process_eligible=True,
    )
    ocr_result = OcrResult(
        (region,),
        "en",
        "circular",
        1,
        preview_strips=(
            OcrPreviewStrip(
                "ring",
                1,
                1,
                b"\xff\xff\xff",
                Point(120, 120),
                RingBand(70, 110),
            ),
        ),
    )
    layer = QtBasicTextLayoutAdapter("Arial").layout(
        document,
        ocr_result,
        _translation("ring", "商业"),
    ).layers[0]
    assert isinstance(layer.path, CircularTextPath)
    assert layer.path.center == PathPoint(120, 120)
    assert layer.path.radius == pytest.approx(90)
    midpoint = layer.path.point_at(0.5)
    assert midpoint.x == pytest.approx(120, abs=0.5)
    assert midpoint.y == pytest.approx(30, abs=0.5)


def test_text_style_defaults_to_regular_and_rejects_unsupported_weights() -> None:
    assert TextStyle("Arial", 12, (0, 0, 0)).font_weight == 400
    with pytest.raises(ValueError, match="Font weight"):
        TextStyle("Arial", 12, (0, 0, 0), font_weight=500)


def test_curved_source_glyphs_create_arc_path_but_straight_glyphs_do_not() -> None:
    width, height = 220, 100
    curved_pixels = np.full((height, width, 3), 245, dtype=np.uint8)
    straight_pixels = curved_pixels.copy()
    x_positions = (25, 55, 85, 115, 145, 175)
    curved_tops = (24, 34, 43, 43, 34, 24)
    for x, top in zip(x_positions, curved_tops, strict=True):
        curved_pixels[top : top + 24, x : x + 16] = 15
        straight_pixels[34:58, x : x + 16] = 15
    asset = ImageAsset(
        Path("arc-source.png"),
        width,
        height,
        1,
        ImageFileFormat.PNG,
        False,
        False,
    )
    region = TextRegion(
        "curve",
        order_quad(((10, 10), (210, 10), (210, 90), (10, 90))),
        "\u52a0\u539a\u73cd\u73e0\u7eb9",
        0.99,
        "zh-Hans",
        "fixture",
    )
    box = TextBox(110, 50, 200, 80)

    curved_path = _estimate_arc_text_path(
        ImageDocument(asset, "RGB", curved_pixels.tobytes()),
        region,
        box,
    )
    straight_path = _estimate_arc_text_path(
        ImageDocument(asset, "RGB", straight_pixels.tobytes()),
        region,
        box,
    )

    assert curved_path is not None
    assert curved_path.point_at(0.5).y > curved_path.start.y
    assert straight_path is None


def test_long_arc_translation_uses_two_curved_lines_before_shrinking() -> None:
    QApplication.instance() or QApplication(["layout-arc-wrap-test"])
    font_family = resolve_system_font("en")
    box = TextBox(100, 40, 158, 52, -24)
    layer = TextLayer(
        "curved-label",
        "Soft and moisturizing for both dry and warm use",
        box,
        TextStyle(font_family, 6, (20, 20, 20), font_stretch=67),
        path=default_arc_path(box, 0.3),
    )

    reflowed = QtBasicTextLayoutAdapter(font_family).reflow(layer, layer.text)
    lines = _arc_text_lines(
        reflowed.text,
        _font_for_layer(reflowed),
        reflowed.path,
        reflowed.style.font_stretch / 100,
    )

    assert len(lines) == 2
    assert reflowed.style.font_size > 8
    assert not reflowed.overflow


def test_spacious_arc_translation_stays_on_one_curve() -> None:
    QApplication.instance() or QApplication(["layout-arc-single-line-test"])
    font_family = resolve_system_font("en")
    box = TextBox(130, 55, 211, 89)
    layer = TextLayer(
        "wide-curved-label",
        "Thickened pearl pattern",
        box,
        TextStyle(font_family, 6, (20, 20, 20)),
        path=default_arc_path(box, -0.45),
    )

    reflowed = QtBasicTextLayoutAdapter(font_family).reflow(layer, layer.text)

    assert _arc_text_lines(
        reflowed.text,
        _font_for_layer(reflowed),
        reflowed.path,
        reflowed.style.font_stretch / 100,
    ) == (layer.text,)
    assert reflowed.style.font_size >= box.height * 0.2
    assert not reflowed.overflow


def test_repeated_curved_labels_use_high_confidence_text_and_curve() -> None:
    first_box = TextBox(100, 80, 140, 48, -22)
    second_box = TextBox(300, 220, 130, 44, -20)
    unrelated_box = TextBox(500, 160, 135, 46, 18)
    regions = (
        TextRegion(
            "first",
            order_quad(((32, 84), (162, 32), (180, 76), (50, 128))),
            "柔软亲肤适合使用",
            0.92,
            "zh-Hans",
            "test",
        ),
        TextRegion(
            "second",
            order_quad(((235, 220), (357, 176), (372, 218), (250, 262))),
            "柔软近肤适合使甪",
            0.74,
            "zh-Hans",
            "test",
        ),
        TextRegion(
            "unrelated",
            order_quad(((435, 118), (563, 160), (548, 204), (420, 162))),
            "品质可靠值得信赖",
            0.88,
            "zh-Hans",
            "test",
        ),
    )
    first_path = default_arc_path(first_box, 0.25)
    second_original_path = default_arc_path(second_box, -0.45)
    unrelated_path = default_arc_path(unrelated_box, -0.3)
    first = TextLayer(
        "first",
        "Soft and skin-friendly",
        first_box,
        TextStyle("Arial", 15, (20, 20, 20)),
        path=first_path,
    )
    second = TextLayer(
        "second",
        "Soft and suitable",
        second_box,
        TextStyle("Arial", 13, (20, 20, 20)),
        path=second_original_path,
    )
    unrelated = TextLayer(
        "unrelated",
        "Reliable quality",
        unrelated_box,
        TextStyle("Arial", 14, (20, 20, 20)),
        path=unrelated_path,
    )

    normalized = _normalize_repeated_curved_layers(
        OcrResult(regions, "zh-Hans", "test", 1),
        (first, second, unrelated),
        lambda layer, text: replace(layer, text=text),
    )

    assert normalized[0] == first
    assert normalized[1].text == first.text
    assert normalized[1].path == transform_arc_path(
        first_path,
        first.box,
        second.box,
    )
    assert normalized[1].path != second_original_path
    assert normalized[2] == unrelated


def test_vertical_source_box_rotates_latin_translation_without_moving_center() -> None:
    region = TextRegion(
        "vertical",
        order_quad(((20, 10), (40, 10), (40, 90), (20, 90))),
        "\u5168\u65b0\u5546\u54c1",
        0.99,
        "zh-Hans",
        "fixture",
    )

    box = _text_box_for_translation(region, "Brand new products")

    assert (box.center_x, box.center_y) == (30, 50)
    assert (box.width, box.height) == (80, 20)
    assert box.rotation_degrees == 90


def test_enhanced_tangent_box_uses_long_edge_for_non_latin_translation() -> None:
    region = TextRegion(
        "circular",
        order_quad(((96, 40), (104, 40), (104, 100), (96, 100))),
        "Import",
        0.93,
        "en",
        "fixture",
        enhanced_only=True,
        auto_process_eligible=True,
    )

    box = _text_box_for_translation(region, "进口")

    assert (box.center_x, box.center_y) == (100, 70)
    assert (box.width, box.height) == (60, 8)
    assert box.rotation_degrees == 90


def test_enhanced_tangent_box_uses_observation_angle_and_projected_extents() -> None:
    center = np.asarray((100.0, 90.0))
    angle = np.deg2rad(32)
    tangent = np.asarray((np.cos(angle), np.sin(angle)))
    normal = np.asarray((-np.sin(angle), np.cos(angle)))
    points = tuple(
        center + tangent * tangent_offset + normal * normal_offset
        for tangent_offset, normal_offset in (
            (-30, -5),
            (30, -5),
            (30, 5),
            (-30, 5),
        )
    )
    polygon = order_quad(points)
    observation = OcrObservation(
        "polar",
        32,
        3,
        0.96,
        polygon,
        "Business",
        "polar:2:scale:3",
    )
    region = TextRegion(
        "circular",
        polygon,
        "Business",
        0.96,
        "en",
        "fixture",
        observations=(observation,),
        enhanced_only=True,
        auto_process_eligible=True,
    )

    box = _text_box_for_translation(region, "商业")

    assert box.center_x == pytest.approx(100)
    assert box.center_y == pytest.approx(90)
    assert box.width == pytest.approx(60)
    assert box.height == pytest.approx(10)
    assert box.rotation_degrees == pytest.approx(32)


def test_enhanced_short_chinese_uses_available_radial_height_without_moving() -> None:
    layer = TextLayer(
        "ring",
        "全球",
        TextBox(120, 90, 42, 8, 37),
        TextStyle("Arial", 6, (40, 40, 40), wrap=False),
    )

    fitted = _fit_enhanced_tangent_layer(layer)

    assert fitted.box.center_x == layer.box.center_x
    assert fitted.box.center_y == layer.box.center_y
    assert fitted.box.rotation_degrees == layer.box.rotation_degrees
    assert fitted.box.height > layer.box.height
    assert fitted.style.font_size > layer.style.font_size
    assert not fitted.overflow


def test_enhanced_tangent_translation_is_single_line_and_uses_available_width() -> None:
    polygon = order_quad(((20, 40), (100, 40), (100, 54), (20, 54)))
    observation = OcrObservation(
        "polar",
        0,
        3,
        0.97,
        polygon,
        "International",
        "polar:1:scale:3",
    )
    region = TextRegion(
        "circular",
        polygon,
        "International",
        0.97,
        "en",
        "fixture",
        observations=(observation,),
        enhanced_only=True,
        auto_process_eligible=True,
    )
    translation = TranslationResult(
        (
            TranslationUnit(
                "circular",
                "International",
                "en",
                "zh-Hans",
                "国际",
                TranslationStatus.TRANSLATED,
            ),
        ),
        TranslationSelection(TranslationMode.ALL, "zh-Hans"),
        "fixture",
        1,
    )

    layer = QtBasicTextLayoutAdapter("Arial").layout(
        _document(),
        OcrResult((region,), "en", "fixture", 1),
        translation,
    ).layers[0]

    assert not layer.style.wrap
    assert layer.style.font_stretch > 100
    assert layer.style.font_size >= 6
    assert not layer.overflow


def test_colored_vertical_labels_keep_light_and_dark_source_foregrounds() -> None:
    pixels = np.full((110, 180, 3), (242, 242, 242), dtype=np.uint8)
    pixels[15:95, 20:46] = (126, 61, 151)
    pixels[15:95, 120:146] = (174, 220, 48)
    for top in (24, 40, 56, 72):
        pixels[top : top + 8, 28:38] = (248, 248, 248)
        pixels[top : top + 8, 128:138] = (20, 21, 17)
    purple = TextRegion(
        "purple",
        order_quad(((20, 15), (46, 15), (46, 95), (20, 95))),
        "全新商品",
        0.99,
        "zh-Hans",
        "fixture",
    )
    green = TextRegion(
        "green",
        order_quad(((120, 15), (146, 15), (146, 95), (120, 95))),
        "全新商品",
        0.99,
        "zh-Hans",
        "fixture",
    )

    assert min(_vertical_colored_label_foreground(pixels, purple)) >= 240
    assert max(_vertical_colored_label_foreground(pixels, green)) <= 25
    document = ImageDocument(
        ImageAsset(
            Path("vertical-labels.png"),
            180,
            110,
            1,
            ImageFileFormat.PNG,
            False,
            False,
        ),
        "RGB",
        pixels.tobytes(),
    )
    assert _vertical_colored_label_background(document, purple) == (126, 61, 151)
    assert _vertical_colored_label_background(document, green) == (174, 220, 48)


def test_vertical_colored_glyphs_on_white_are_not_treated_as_label_background() -> None:
    pixels = np.full((90, 50, 3), (250, 250, 250), dtype=np.uint8)
    pixels[12:78, 18:26] = (98, 222, 250)
    pixels[18:24, 14:32] = (98, 222, 250)
    pixels[42:48, 14:32] = (98, 222, 250)
    pixels[68:74, 14:32] = (98, 222, 250)
    region = TextRegion(
        "cyan-word",
        order_quad(((12, 8), (32, 8), (32, 82), (12, 82))),
        "Eport",
        0.99,
        "en",
        "fixture",
    )
    document = ImageDocument(
        ImageAsset(
            Path("cyan-word.png"),
            50,
            90,
            1,
            ImageFileFormat.PNG,
            False,
            False,
        ),
        "RGB",
        pixels.tobytes(),
    )

    assert _vertical_colored_label_background(document, region) is None


def test_repeated_vertical_labels_share_geometry_and_style_without_moving() -> None:
    layers = (
        TextLayer(
            "purple",
            "Brand new products",
            TextBox(75.5, 195.75, 66.03, 23.02, 87.5),
            TextStyle(
                "Segoe UI",
                11.49,
                (248, 248, 248),
                font_stretch=67,
                font_weight=400,
            ),
        ),
        TextLayer(
            "green",
            "Brand new products",
            TextBox(285.25, 206.25, 64.03, 20.03, 92.86),
            TextStyle(
                "Segoe UI",
                11.5,
                (20, 21, 17),
                font_stretch=75,
                font_weight=700,
            ),
        ),
    )

    normalized = _normalize_repeated_vertical_labels(layers)

    assert [(layer.box.center_x, layer.box.center_y) for layer in normalized] == [
        (75.5, 195.75),
        (285.25, 206.25),
    ]
    assert {layer.box.rotation_degrees for layer in normalized} == {90}
    assert len({round(layer.style.font_size, 3) for layer in normalized}) == 1
    assert {layer.style.font_stretch for layer in normalized} == {67}
    assert {layer.style.font_weight for layer in normalized} == {700}
    assert {layer.style.alignment for layer in normalized} == {
        TextAlignment.CENTER
    }
    assert [layer.style.fill_rgb for layer in normalized] == [
        (248, 248, 248),
        (20, 21, 17),
    ]
    assert not any(layer.overflow for layer in normalized)


def test_qfont_uses_text_style_weight() -> None:
    QApplication.instance() or QApplication(["layout-qfont-weight-test"])
    assert int(_font_for_style(TextStyle("Arial", 12, (0, 0, 0))).weight()) == 400
    assert int(
        _font_for_style(
            TextStyle("Arial", 12, (0, 0, 0), font_weight=600)
        ).weight()
    ) == 600
    assert int(
        _font_for_style(
            TextStyle("Arial", 12, (0, 0, 0), font_weight=700)
        ).weight()
    ) == 700
    layer_font = _font_for_layer(
        TextLayer(
            "weighted",
            "Long weighted heading",
            TextBox(100, 20, 180, 30),
            TextStyle("Arial", 20, (0, 0, 0), font_weight=700),
        )
    )
    assert int(layer_font.weight()) == 700
    assert layer_font.stretch() <= 100


def test_rotated_and_curved_text_use_native_font_stretch_for_rendering() -> None:
    QApplication.instance() or QApplication(["layout-native-stretch-render-test"])
    style = TextStyle("Segoe UI", 24, (0, 0, 0), font_stretch=67)
    box = TextBox(80, 40, 120, 28)

    horizontal_font, horizontal_scale = _render_font_and_horizontal_scale(
        TextLayer("horizontal", "Readable", box, style)
    )
    rotated_font, rotated_scale = _render_font_and_horizontal_scale(
        TextLayer("rotated", "Readable", replace(box, rotation_degrees=90), style)
    )
    curved_font, curved_scale = _render_font_and_horizontal_scale(
        TextLayer(
            "curved",
            "Readable",
            box,
            style,
            path=default_arc_path(box, 0.35),
        )
    )

    assert horizontal_font.stretch() == 100
    assert horizontal_scale == pytest.approx(0.67)
    assert rotated_font.stretch() == 67
    assert rotated_scale == 1
    assert curved_font.stretch() == 67
    assert curved_scale == 1


def test_weight_aware_reflow_and_renderer_share_effective_font() -> None:
    QApplication.instance() or QApplication(["layout-weight-aware-fit-test"])
    font_family = resolve_system_font("en")
    adapter = QtBasicTextLayoutAdapter(font_family)
    box = TextBox(20, 22.5, 40, 45)
    regular = adapter.reflow(
        TextLayer(
            "regular",
            "Label * 2",
            box,
            TextStyle(font_family, 6, (0, 0, 0), font_weight=400),
        ),
        "Label * 2",
    )
    bold = adapter.reflow(
        TextLayer(
            "bold",
            "Label * 2",
            box,
            TextStyle(font_family, 6, (0, 0, 0), font_weight=700),
        ),
        "Label * 2",
    )

    assert (
        bold.style.font_size * bold.style.font_stretch / 100
        < regular.style.font_size * regular.style.font_stretch / 100
    )
    assert bold.style.font_weight == 700
    measured = _font_for_text(
        bold.style,
        bold.text,
        font_size=bold.style.font_size,
        font_stretch=bold.style.font_stretch,
    )
    rendered = _font_for_layer(bold)
    assert (
        measured.family(),
        measured.pixelSize(),
        int(measured.weight()),
        measured.stretch(),
    ) == (
        rendered.family(),
        rendered.pixelSize(),
        int(rendered.weight()),
        rendered.stretch(),
    )


def test_bold_wrap_and_overflow_use_rendered_font_metrics() -> None:
    QApplication.instance() or QApplication(["layout-bold-overflow-test"])
    adapter = QtBasicTextLayoutAdapter("Segoe UI")
    style = TextStyle(
        "Segoe UI",
        20,
        (0, 0, 0),
        font_weight=700,
        auto_fit=False,
    )
    overflowing = adapter.reflow(
        TextLayer("bold", "Label * 2", TextBox(34.5, 14.5, 69, 29), style),
        "Label * 2",
    )
    assert overflowing.overflow

    fitting = adapter.reflow(
        TextLayer(
            "bold",
            "Label * 2",
            TextBox(34.5, 14.5, 69, 29),
            replace(style, font_size=13),
        ),
        "Label * 2",
    )
    assert not fitting.overflow
    font = _font_for_layer(fitting)
    bounds = QFontMetricsF(font).boundingRect(
        QRectF(0, 0, fitting.box.width, fitting.box.height),
        _text_flags(fitting.style, fitting.text),
        fitting.text,
    )
    assert bounds.width() <= fitting.box.width + 0.5
    assert bounds.height() <= fitting.box.height + 0.5


def test_weight_aware_reflow_marks_overflow_at_minimum_size() -> None:
    QApplication.instance() or QApplication(["layout-bold-minimum-test"])
    layer = TextLayer(
        "tiny",
        "A label that cannot fit",
        TextBox(5, 2.5, 10, 5),
        TextStyle("Segoe UI", 6, (0, 0, 0), font_weight=700),
    )

    result = QtBasicTextLayoutAdapter("Segoe UI").reflow(layer, layer.text)

    assert result.style.font_size == 6
    assert result.overflow


@pytest.mark.parametrize(
    ("stroke_thickness", "expected_weight"),
    ((1, 400), (2, 600), (5, 700)),
)
def test_font_weight_estimation_distinguishes_synthetic_strokes(
    stroke_thickness: int,
    expected_weight: int,
) -> None:
    pixels = np.full((60, 240, 3), 255, dtype=np.uint8)
    cv2.putText(
        pixels,
        "SAMPLE",
        (8, 45),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.4,
        (0, 0, 0),
        stroke_thickness,
        cv2.LINE_AA,
    )
    asset = ImageAsset(
        Path("synthetic-weight.png"),
        240,
        60,
        1,
        ImageFileFormat.PNG,
        False,
        False,
    )
    document = ImageDocument(asset, "RGB", pixels.tobytes())
    region = TextRegion(
        "weight",
        order_quad(((5, 10), (210, 10), (210, 50), (5, 50))),
        "SAMPLE",
        1,
        "en",
        "fixture",
    )

    assert _estimate_font_weight(document, region) == expected_weight


def test_font_weight_estimation_falls_back_for_unreliable_region() -> None:
    pixels = np.full((60, 240, 3), 127, dtype=np.uint8)
    asset = ImageAsset(
        Path("unreliable-weight.png"),
        240,
        60,
        1,
        ImageFileFormat.PNG,
        False,
        False,
    )
    document = ImageDocument(asset, "RGB", pixels.tobytes())
    region = TextRegion(
        "weight",
        order_quad(((5, 5), (210, 5), (210, 55), (5, 55))),
        "SAMPLE",
        1,
        "en",
        "fixture",
    )

    assert _estimate_font_weight(document, region) == 400


def test_reflow_and_visual_group_normalization_preserve_and_unify_weight() -> None:
    QApplication.instance() or QApplication(["layout-weight-group-test"])
    adapter = QtBasicTextLayoutAdapter("Arial")
    layer = TextLayer(
        "single",
        "TEXT",
        TextBox(90, 30, 100, 24),
        TextStyle("Arial", 12, (255, 255, 255), font_weight=700),
    )
    assert adapter.reflow(layer, "UPDATED").style.font_weight == 700

    document = ImageDocument(
        ImageAsset(
            Path("weight-group.png"),
            180,
            120,
            1,
            ImageFileFormat.PNG,
            False,
            False,
        ),
        "RGB",
        np.full((120, 180, 3), (40, 60, 80), dtype=np.uint8).tobytes(),
    )
    grouped = tuple(
        TextLayer(
            f"group-{index}",
            "TEXT",
            TextBox(90, 22 + index * 30, 100, 24),
            TextStyle(
                "Arial",
                12,
                (255, 255, 255),
                font_weight=weight,
            ),
        )
        for index, weight in enumerate((400, 600, 700))
    )

    normalized = _normalize_visual_group_sizes(document, grouped)
    assert {item.style.font_weight for item in normalized} == {600}
    assert not any(item.overflow for item in normalized)
    assert all(
        _text_fits(
            item,
            item.text,
            item.style.font_size,
            item.style.font_stretch,
        )
        for item in normalized
    )


def test_visual_group_keeps_distinct_text_hierarchy() -> None:
    QApplication.instance() or QApplication(["layout-weight-hierarchy-test"])
    document = ImageDocument(
        ImageAsset(
            Path("weight-hierarchy.png"),
            240,
            100,
            1,
            ImageFileFormat.PNG,
            False,
            False,
        ),
        "RGB",
        np.full((100, 240, 3), (245, 245, 245), dtype=np.uint8).tobytes(),
    )
    layers = (
        TextLayer(
            "heading",
            "Heading",
            TextBox(120, 25, 190, 40),
            TextStyle("Arial", 20, (30, 30, 30), font_weight=700),
        ),
        TextLayer(
            "body",
            "Body copy",
            TextBox(120, 62, 190, 32),
            TextStyle("Arial", 14, (30, 30, 30), font_weight=400),
        ),
    )

    normalized = _normalize_visual_group_sizes(document, layers)

    assert normalized == layers


def test_repeated_background_panels_keep_heading_and_body_hierarchy_consistent() -> None:
    QApplication.instance() or QApplication(["layout-repeated-panel-test"])
    pixels = np.full((130, 1000, 3), (235, 225, 205), dtype=np.uint8)
    for left in (5, 255, 505, 755):
        pixels[10:120, left : left + 240] = (250, 241, 210)
        pixels[25:105, left + 15 : left + 75] = (246, 201, 72)
    document = ImageDocument(
        ImageAsset(
            Path("repeated-panels.png"),
            1000,
            130,
            1,
            ImageFileFormat.PNG,
            False,
            False,
        ),
        "RGB",
        pixels.tobytes(),
    )
    # 标题取短文案、正文取长文案，与真实电商面板结构一致。
    # 说明：行内字号统一取「组内各成员拟合字号的最小值」，标题组与正文组各自独立计算，
    # 组间没有层级约束。若标题文案反而比正文长（原 fixture 即如此：最长标题 33 字挤在
    # 110px 框，最长正文 30 字却有 115px），标题字号会被压到与正文持平甚至更小
    # （实测 13.4812 vs 13.4953，余量 -0.014），断言结果取决于平台字体度量。
    # 现结构下余量 +15.28，可跨平台稳定断言。
    titles = (
        "Thicker",
        "Dry & wet",
        "Pearl weave",
        "Gentle",
    )
    bodies = (
        "Thicker and more durable",
        "Wash face and remove makeup",
        "Soft touch, double cleanliness",
        "No lint or shedding",
    )
    layers = tuple(
        layer
        for index, left in enumerate((5, 255, 505, 755))
        for layer in (
            TextLayer(
                f"title-{index}",
                titles[index],
                TextBox(
                    left + 155,
                    43,
                    110,
                    32,
                    (0.2, -1.1, 0.3, -0.2)[index],
                ),
                TextStyle("Arial", 12 + index, (24, 20, 12)),
            ),
            TextLayer(
                f"body-{index}",
                bodies[index],
                TextBox(
                    left + 155,
                    82,
                    115,
                    24,
                    (-0.3, 0.8, -0.1, 0.4)[index],
                ),
                TextStyle("Arial", 8 + index, (28, 24, 16)),
            ),
        )
    )

    normalized = _normalize_repeated_panel_rows(document, layers)
    normalized_titles = tuple(
        layer for layer in normalized if layer.region_id.startswith("title-")
    )
    normalized_bodies = tuple(
        layer for layer in normalized if layer.region_id.startswith("body-")
    )

    assert len({round(layer.style.font_size, 3) for layer in normalized_titles}) == 1
    assert len({round(layer.style.font_size, 3) for layer in normalized_bodies}) == 1
    assert normalized_titles[0].style.font_size > normalized_bodies[0].style.font_size
    assert all(layer.style.alignment is TextAlignment.LEFT for layer in normalized)
    assert all(layer.box.rotation_degrees == 0 for layer in normalized)
    assert all(layer.box.width > 110 for layer in normalized_titles)
    assert not any(layer.overflow for layer in normalized)


def test_three_icon_captions_share_larger_centered_readable_boxes() -> None:
    QApplication.instance() or QApplication(["layout-icon-caption-test"])
    document = ImageDocument(
        ImageAsset(
            Path("icon-captions.png"),
            520,
            100,
            1,
            ImageFileFormat.PNG,
            False,
            False,
        ),
        "RGB",
        np.full((100, 520, 3), (246, 244, 239), dtype=np.uint8).tobytes(),
    )
    layers = tuple(
        TextLayer(
            f"caption-{index}",
            text,
            TextBox(center_x, 50, width, height),
            TextStyle("Segoe UI", 10.5, (20, 18, 15)),
        )
        for index, (text, center_x, width, height) in enumerate(
            (
                ("Suitable for both dry and wet use", 100, 90, 29),
                ("Mother and infant are usable", 265, 89, 28),
                ("Does not easily shed cotton", 418, 92, 31),
            )
        )
    )

    normalized = _normalize_repeated_panel_rows(document, layers)

    assert all(layer.box.width >= 135 for layer in normalized)
    assert all(layer.box.height >= 36 for layer in normalized)
    assert {layer.style.alignment for layer in normalized} == {
        TextAlignment.CENTER
    }
    assert len({round(layer.style.font_size, 3) for layer in normalized}) == 1
    assert normalized[0].style.font_size > 10.5
    assert not any(layer.overflow for layer in normalized)


def test_panel_title_and_body_share_left_edge_without_changing_size() -> None:
    title = TextLayer(
        "title",
        "Gentle and non-irritating",
        TextBox(1153, 1142.5, 164, 39),
        TextStyle(
            "Segoe UI",
            23.48,
            (14, 7, 0),
            TextAlignment.LEFT,
            font_stretch=67,
        ),
    )
    body = TextLayer(
        "body",
        "No lint or shedding hair",
        TextBox(1134, 1177.25, 202, 32),
        TextStyle(
            "Segoe UI",
            14.49,
            (36, 28, 1),
            TextAlignment.LEFT,
            font_stretch=67,
        ),
    )

    normalized = _align_panel_title_and_body((title, body))

    left_edges = {
        round(layer.box.center_x - layer.box.width / 2, 3)
        for layer in normalized
    }
    assert len(left_edges) == 1
    assert [layer.box.width for layer in normalized] == [164, 202]
    assert [layer.style.font_size for layer in normalized] == [23.48, 14.49]


def test_colored_panel_run_stops_at_different_background_separator() -> None:
    pixels = np.full((90, 340, 3), (252, 238, 190), dtype=np.uint8)
    pixels[:, 198:216] = (254, 240, 162)
    document = ImageDocument(
        ImageAsset(
            Path("panel-separator.png"),
            340,
            90,
            1,
            ImageFileFormat.PNG,
            False,
            False,
        ),
        "RGB",
        pixels.tobytes(),
    )
    box = TextBox(145, 45, 105, 30)

    expanded = _matching_background_run_box(
        document,
        box,
        np.asarray((252, 238, 190), dtype=float),
        0,
        340,
    )

    assert expanded.center_x + expanded.width / 2 <= 198


def test_similar_horizontal_labels_share_font_style_without_moving_boxes() -> None:
    QApplication.instance() or QApplication(["layout-horizontal-group-test"])
    pixels = np.full((120, 360, 3), (65, 70, 75), dtype=np.uint8)
    pixels[20:90, 5:135] = (165, 45, 30)
    pixels[20:90, 145:350] = (160, 42, 28)
    document = ImageDocument(
        ImageAsset(
            Path("horizontal-labels.png"),
            360,
            120,
            1,
            ImageFileFormat.PNG,
            False,
            False,
        ),
        "RGB",
        pixels.tobytes(),
    )
    layers = (
        TextLayer(
            "first",
            "Dishwasher",
            TextBox(70, 55, 102, 43, -1.5),
            TextStyle(
                "Arial",
                30,
                (235, 220, 215),
                font_stretch=67,
                font_weight=600,
            ),
        ),
        TextLayer(
            "second",
            "Pre-filter",
            TextBox(245, 56, 158, 39),
            TextStyle(
                "Arial",
                29,
                (232, 218, 212),
                font_stretch=100,
                font_weight=700,
            ),
        ),
    )

    normalized = _normalize_visual_group_sizes(document, layers)

    assert [layer.box for layer in normalized] == [layer.box for layer in layers]
    assert len({round(layer.style.font_size, 3) for layer in normalized}) == 1
    assert {layer.style.font_stretch for layer in normalized} == {67}
    assert {layer.style.font_weight for layer in normalized} == {600}
    assert not any(layer.overflow for layer in normalized)


def test_horizontal_group_does_not_collapse_three_label_boxes() -> None:
    QApplication.instance() or QApplication(["layout-horizontal-box-test"])
    pixels = np.full((100, 360, 3), (245, 245, 245), dtype=np.uint8)
    document = ImageDocument(
        ImageAsset(
            Path("horizontal-boxes.png"),
            360,
            100,
            1,
            ImageFileFormat.PNG,
            False,
            False,
        ),
        "RGB",
        pixels.tobytes(),
    )
    layers = tuple(
        TextLayer(
            f"label-{index}",
            text,
            TextBox(center_x, 50, width, 30),
            TextStyle("Arial", 18, (45, 45, 45)),
        )
        for index, (text, center_x, width) in enumerate(
            (
                ("Plug * 2", 65, 70),
                ("Plug * 2", 165, 70),
                ("Clamp", 260, 55),
            )
        )
    )

    normalized = _normalize_visual_group_sizes(document, layers)

    assert [layer.box for layer in normalized] == [layer.box for layer in layers]
    assert len({round(layer.style.font_size, 3) for layer in normalized}) == 1


def _glyph_band(pixels: np.ndarray, top: int, height: int) -> None:
    """在浅底上画一条深色"文字"墨迹带，替代真实字形渲染。"""
    pixels[top : top + height, 60:200] = (30, 30, 30)


def test_noisy_ocr_boxes_with_equal_glyph_height_share_one_font_size() -> None:
    """回归：OCR 框一松一紧、但原图字形同大时，译文必须同字号。

    历史缺陷：视觉同组判定只看 OCR 框高比（≤1.08），框抖动直接让归并失败，
    同图里视觉同大的文字各自按框高拟合，译成一块大一块小。"""
    QApplication.instance() or QApplication(["layout-ink-height-group-test"])
    pixels = np.full((200, 260, 3), (250, 250, 250), dtype=np.uint8)
    _glyph_band(pixels, 61, 18)
    _glyph_band(pixels, 131, 18)
    document = ImageDocument(
        ImageAsset(
            Path("noisy-boxes.png"),
            260,
            200,
            1,
            ImageFileFormat.PNG,
            False,
            False,
        ),
        "RGB",
        pixels.tobytes(),
    )
    layers = (
        TextLayer(
            "tight",
            "Team",
            TextBox(130, 70, 150, 24),
            TextStyle("Arial", 20, (30, 30, 30)),
        ),
        TextLayer(
            "loose",
            "Team",
            TextBox(130, 140, 150, 38),
            TextStyle("Arial", 34, (30, 30, 30), font_stretch=87),
        ),
    )

    normalized = _normalize_visual_group_sizes(document, layers)

    assert len({round(layer.style.font_size, 3) for layer in normalized}) == 1
    assert {layer.style.font_stretch for layer in normalized} == {87}
    assert not any(layer.overflow for layer in normalized)


def test_visual_group_keeps_hierarchy_from_glyph_height_not_box_height() -> None:
    """框高相近但字形一大一小（标题/正文）不得并成同一字号。"""
    QApplication.instance() or QApplication(["layout-ink-height-hierarchy-test"])
    pixels = np.full((200, 260, 3), (250, 250, 250), dtype=np.uint8)
    _glyph_band(pixels, 48, 26)
    _glyph_band(pixels, 118, 13)
    document = ImageDocument(
        ImageAsset(
            Path("hierarchy-boxes.png"),
            260,
            200,
            1,
            ImageFileFormat.PNG,
            False,
            False,
        ),
        "RGB",
        pixels.tobytes(),
    )
    layers = (
        TextLayer(
            "heading",
            "Team",
            TextBox(130, 61, 150, 30),
            TextStyle("Arial", 26, (30, 30, 30)),
        ),
        TextLayer(
            "body",
            "Team",
            TextBox(130, 124, 150, 30),
            TextStyle("Arial", 13, (30, 30, 30)),
        ),
    )

    normalized = _normalize_visual_group_sizes(document, layers)

    assert normalized == layers


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


def test_short_latin_text_gets_letter_spacing_to_fill_wide_box() -> None:
    QApplication.instance() or QApplication(["layout-latin-spacing-test"])
    layer = TextLayer(
        "short",
        "Soft",
        TextBox(60, 20, 120, 30),
        TextStyle("Arial", 22.5, (20, 20, 20), wrap=False),
    )

    fitted = _fit_short_latin_spacing((layer,))

    assert fitted[0].style.letter_spacing > 0
    assert not fitted[0].overflow
    assert _text_fits(
        fitted[0],
        fitted[0].text,
        fitted[0].style.font_size,
        fitted[0].style.font_stretch,
    )


def test_latin_text_that_fills_box_gets_no_letter_spacing() -> None:
    QApplication.instance() or QApplication(["layout-latin-spacing-none-test"])
    layer = TextLayer(
        "fill",
        "Additive-free",
        TextBox(60, 20, 130, 30),
        TextStyle("Arial", 22.5, (20, 20, 20), wrap=False),
    )

    fitted = _fit_short_latin_spacing((layer,))

    assert fitted[0].style.letter_spacing == 0.0


def test_cjk_text_gets_no_letter_spacing() -> None:
    QApplication.instance() or QApplication(["layout-latin-spacing-cjk-test"])
    layer = TextLayer(
        "cjk",
        "商品促销",
        TextBox(60, 20, 120, 30),
        TextStyle("Arial", 22.5, (20, 20, 20), wrap=False),
    )

    fitted = _fit_short_latin_spacing((layer,))

    assert fitted[0].style.letter_spacing == 0.0


def test_dense_short_word_overflow_uses_compact_readable_font() -> None:
    QApplication.instance() or QApplication(["layout-dense-word-cloud-test"])
    regions = tuple(
        TextRegion(
            f"region-{index:04d}",
            order_quad(((0, 0), (18, 0), (18, 9), (0, 9))),
            "新品",
            0.9,
            "zh-Hans",
            "fixture",
        )
        for index in range(1, 41)
    )
    ocr_result = OcrResult(regions, "zh-Hans", "fixture", 1)
    translation_result = TranslationResult(
        (
            TranslationUnit(
                "region-0001",
                "新品",
                "zh-Hans",
                "en",
                "Featured",
                TranslationStatus.TRANSLATED,
            ),
            TranslationUnit(
                "region-0002",
                "新品",
                "zh-Hans",
                "en",
                "New arrival",
                TranslationStatus.TRANSLATED,
            ),
        ),
        TranslationSelection(TranslationMode.ALL, "en"),
        "fixture",
        1,
    )
    layers = (
        TextLayer(
            "region-0001",
            "Featured",
            TextBox(20, 20, 18, 9),
            TextStyle("Arial", 6, (0, 0, 0)),
            overflow=True,
        ),
        TextLayer(
            "region-0002",
            "New arrival",
            TextBox(50, 20, 18, 9),
            TextStyle("Arial", 6, (0, 0, 0)),
            overflow=True,
        ),
    )

    fitted = _fit_dense_short_word_overflow(
        ocr_result,
        translation_result,
        layers,
    )

    assert not fitted[0].overflow
    assert 4 <= fitted[0].style.font_size <= 6
    assert fitted[0].style.font_stretch >= 50
    assert fitted[1] == layers[1]


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
    # 框高取 48（可容纳多行）：自动排版只在「压缩带来的字号收益 >= max(1pt, 基准的 12%)」
    # 时才启用压缩。若框高仅 24，收益恰好卡在阈值边缘（实测 10.49 → 11.50，阈值 11.75），
    # 结论会随平台默认字体的度量差异翻转，无法稳定表达本用例意图。
    # 48 高时压缩收益明确（14.46 → 20.50@67，阈值 16.20），可跨平台稳定断言。
    region = TextRegion(
        "paragraph",
        order_quad(((30, 20), (447, 20), (447, 68), (30, 68))),
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


def test_similar_stacked_backgrounds_share_one_font_size() -> None:
    QApplication.instance() or QApplication(["layout-visual-group-test"])
    pixels = np.full((390, 260, 3), (25, 45, 80), dtype=np.uint8)
    regions = []
    source_texts = ("厂家直销", "优质售后", "专业团队", "良心企业", "全国销售")
    translated_texts = (
        "Factory direct sales",
        "High-quality after-sales service",
        "Professional team",
        "A conscientious enterprise",
        "Nationwide sales",
    )
    for index, (source_text, background) in enumerate(
        zip(source_texts, (132, 138, 128, 142, 155), strict=True)
    ):
        top = 20 + index * 65
        pixels[top - 8 : top + 43, 40:221] = background
        regions.append(
            TextRegion(
                f"label-{index}",
                order_quad(((70, top), (190, top), (190, top + 35), (70, top + 35))),
                source_text,
                1.0,
                "zh-Hans",
                "fixture",
            )
        )
    asset = ImageAsset(
        Path("stacked-labels.png"),
        260,
        390,
        1,
        ImageFileFormat.PNG,
        False,
        False,
    )
    document = ImageDocument(asset, "RGB", pixels.tobytes())
    units = tuple(
        TranslationUnit(
            region.region_id,
            region.text,
            "zh-Hans",
            "en",
            translated_text,
            TranslationStatus.TRANSLATED,
        )
        for region, translated_text in zip(regions, translated_texts, strict=True)
    )
    result = TranslationResult(
        units,
        TranslationSelection(TranslationMode.ALL, "en"),
        "fixture",
        1,
    )

    layout = QtBasicTextLayoutAdapter().layout(
        document,
        OcrResult(tuple(regions), "zh-Hans", "fixture", 1),
        result,
    )

    assert len(layout.layers) == 5
    assert len({round(layer.style.font_size, 3) for layer in layout.layers}) == 1
    assert len({layer.style.font_stretch for layer in layout.layers}) == 1
    assert len({round(layer.box.center_x, 3) for layer in layout.layers}) == 1
    assert {round(layer.box.width, 3) for layer in layout.layers} == {150}


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


def test_paragraph_group_units_render_one_continuous_block() -> None:
    QApplication.instance() or QApplication(["layout-paragraph-group-test"])
    pixels = np.full((90, 480, 3), (30, 70, 150), dtype=np.uint8)
    asset = ImageAsset(
        Path("paragraph-group.png"),
        480,
        90,
        1,
        ImageFileFormat.PNG,
        False,
        False,
    )
    document = ImageDocument(asset, "RGB", pixels.tobytes())
    regions = (
        TextRegion(
            "line-1",
            order_quad(((30, 10), (447, 10), (447, 34), (30, 34))),
            "根据新广告法规定所有页面不得出现绝对化用词",
            1.0,
            "zh-Hans",
            "fixture",
        ),
        TextRegion(
            "line-2",
            order_quad(((30, 54), (447, 54), (447, 78), (30, 78))),
            "我们支持新广告法为了不影响正常消费者正常购物",
            1.0,
            "zh-Hans",
            "fixture",
        ),
    )
    paragraph_text = (
        "According to the new advertising law, no absolute wording is "
        "allowed on any page."
    )
    translations = tuple(
        TranslationUnit(
            region.region_id,
            region.text,
            "zh-Hans",
            "en",
            paragraph_text,
            TranslationStatus.TRANSLATED,
            paragraph_group_id="paragraph-0",
        )
        for region in regions
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

    # 行间距 20 远超几何启发式阈值，但显式段落组 ID 仍合并为一个连续块，
    # 且文本取整段译文一次（而非逐行 join 重复两次）。
    assert len(layout.layers) == 1
    layer = layout.layers[0]
    assert layer.region_id == "line-1"
    assert layer.text == paragraph_text
    assert layer.style.alignment is TextAlignment.LEFT
    assert layer.box.width == 417
    assert layer.box.height == 68


def test_widely_spaced_lines_without_group_id_stay_separate_layers() -> None:
    QApplication.instance() or QApplication([
        "layout-paragraph-group-control-test"
    ])
    pixels = np.full((90, 480, 3), (30, 70, 150), dtype=np.uint8)
    asset = ImageAsset(
        Path("paragraph-group-control.png"),
        480,
        90,
        1,
        ImageFileFormat.PNG,
        False,
        False,
    )
    document = ImageDocument(asset, "RGB", pixels.tobytes())
    regions = (
        TextRegion(
            "line-1",
            order_quad(((30, 10), (447, 10), (447, 34), (30, 34))),
            "根据新广告法规定所有页面不得出现绝对化用词",
            1.0,
            "zh-Hans",
            "fixture",
        ),
        TextRegion(
            "line-2",
            order_quad(((30, 54), (447, 54), (447, 78), (30, 78))),
            "我们支持新广告法为了不影响正常消费者正常购物",
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
            "First line translation stays on its own layer.",
            TranslationStatus.TRANSLATED,
        ),
        TranslationUnit(
            "line-2",
            regions[1].text,
            "zh-Hans",
            "en",
            "Second line translation stays on its own layer.",
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

    assert [layer.region_id for layer in layout.layers] == ["line-1", "line-2"]
