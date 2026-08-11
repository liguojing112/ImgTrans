from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from difflib import SequenceMatcher
from math import atan2, cos, degrees, hypot, radians, sin

import cv2
import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetricsF,
    QGlyphRun,
    QImage,
    QPainter,
    QTextLayout,
    QTextOption,
)

from src.domain.image import ImageDocument
from src.domain.layout import (
    TextAlignment,
    ArcTextPath,
    CircularTextPath,
    PathPoint,
    TextBox,
    TextLayer,
    TextLayout,
    TextPath,
    TextStyle,
    VerticalAlignment,
    ensure_bottom_inward_circular_path,
    fit_font_size,
    transform_arc_path,
)
from src.domain.ocr import OcrResult, TextRegion
from src.domain.translation import TranslationResult, TranslationStatus, TranslationUnit
from src.platform.fonts import resolve_system_font, resolve_system_font_details


_RTL_LANGUAGES = {"ar", "fa", "ur"}
_AUTO_FONT_STRETCHES = (100, 87, 75, 67)


class QtBasicTextLayoutAdapter:
    def __init__(self, font_family: str | None = None) -> None:
        self._font_family = font_family

    def layout(
        self,
        source: ImageDocument,
        ocr_result: OcrResult,
        translation_result: TranslationResult,
    ) -> TextLayout:
        regions = {region.region_id: region for region in ocr_result.regions}
        circular_center = (
            (
                ocr_result.preview_strips[0].center.x,
                ocr_result.preview_strips[0].center.y,
            )
            if ocr_result.preview_strips
            else None
        )
        layers: list[TextLayer] = []
        for group in _translated_groups(translation_result, regions):
            units = tuple(item[0] for item in group)
            grouped_regions = tuple(item[1] for item in group)
            unit = units[0]
            region = grouped_regions[0]
            text = " ".join(item.translated_text for item in units)
            box = (
                _paragraph_text_box(grouped_regions)
                if len(grouped_regions) > 1
                else _text_box_for_translation(region, text, circular_center)
            )
            path = (
                None
                if len(grouped_regions) > 1
                else _text_path_for_region(
                    source,
                    region,
                    box,
                    circular_center,
                )
            )
            if path is not None:
                expanded_box = _expand_arc_box_for_translation(
                    source,
                    box,
                    region.text,
                    text,
                )
                if expanded_box != box:
                    path = transform_arc_path(path, box, expanded_box)
                    box = expanded_box
            alignment = (
                TextAlignment.RIGHT
                if unit.target_language in _RTL_LANGUAGES
                else TextAlignment.LEFT
                if len(grouped_regions) > 1
                else TextAlignment.CENTER
            )
            resolution = (
                None
                if self._font_family is not None
                else resolve_system_font_details(unit.target_language)
            )
            font_family = self._font_family or resolution.family
            label_background = _vertical_colored_label_background(source, region)
            layer = self.reflow(
                TextLayer(
                    region.region_id,
                    text,
                    box,
                    TextStyle(
                        font_family,
                        6,
                        _estimate_foreground_color(source, region),
                        alignment,
                        wrap=not region.enhanced_only,
                        font_degraded=resolution.degraded if resolution else False,
                        font_fallback_reason=resolution.reason if resolution else None,
                        font_weight=_estimate_font_weight(source, region),
                        background_rgb=label_background,
                        background_opacity=1.0 if label_background is not None else 0.0,
                    ),
                    path=path,
                ),
                text,
            )
            if region.enhanced_only:
                layer = _fit_enhanced_tangent_layer(layer)
            layers.append(layer)
        repeated_curves = _normalize_repeated_curved_layers(
            ocr_result,
            tuple(layers),
            self.reflow,
        )
        repeated_panels = _normalize_repeated_panel_rows(source, repeated_curves)
        repeated_vertical = _normalize_repeated_vertical_labels(repeated_panels)
        aligned_panels = _align_panel_title_and_body(repeated_vertical)
        normalized = _normalize_visual_group_sizes(source, aligned_panels)
        return TextLayout(
            _fit_short_latin_spacing(
                _fit_dense_short_word_overflow(
                    ocr_result,
                    translation_result,
                    normalized,
                )
            )
        )

    def create_layer(self, region_id: str, text: str, box: TextBox) -> TextLayer:
        resolution = (
            None if self._font_family is not None else resolve_system_font_details("zh-Hans")
        )
        return self.reflow(
            TextLayer(
                region_id,
                text,
                box,
                TextStyle(
                    self._font_family or resolution.family,
                    6,
                    (24, 32, 51),
                    font_degraded=resolution.degraded if resolution else False,
                    font_fallback_reason=resolution.reason if resolution else None,
                ),
            ),
            text,
        )

    def reflow(self, layer: TextLayer, text: str) -> TextLayer:
        def fits(size: float, stretch: int) -> bool:
            return _text_fits(layer, text, size, stretch)

        if layer.style.auto_fit:
            if layer.path is not None:
                single_line_candidates = tuple(
                    (
                        *fit_font_size(
                            6,
                            max(6, min(160, layer.box.height * 0.9)),
                            lambda size, stretch=stretch: _arc_single_line_fits(
                                layer,
                                text,
                                size,
                                stretch,
                            ),
                        ),
                        stretch,
                    )
                    for stretch in _AUTO_FONT_STRETCHES
                )
                single_size, single_overflow, single_stretch = max(
                    single_line_candidates,
                    key=lambda candidate: (candidate[0], candidate[2]),
                )
                if (
                    not single_overflow
                    and single_size
                    >= max(
                        6,
                        layer.box.height
                        * (
                            0.28
                            if abs(layer.box.rotation_degrees) >= 12
                            else 0.2
                        ),
                    )
                ):
                    return replace(
                        layer,
                        text=text,
                        style=replace(
                            layer.style,
                            font_size=single_size,
                            font_stretch=single_stretch,
                        ),
                        overflow=False,
                    )
            candidates = tuple(
                (
                    *fit_font_size(
                        6,
                        max(6, min(160, layer.box.height * 0.9)),
                        lambda size, stretch=stretch: fits(size, stretch),
                    ),
                    stretch,
                )
                for stretch in _AUTO_FONT_STRETCHES
            )
            base_size, base_overflow, _ = candidates[0]
            size, overflow, stretch = max(
                candidates,
                key=lambda candidate: (candidate[0], candidate[2]),
            )
            if size < base_size + max(1.0, base_size * 0.12):
                size, overflow, stretch = base_size, base_overflow, 100
        else:
            size = layer.style.font_size
            stretch = layer.style.font_stretch
            overflow = not fits(size, stretch)
        return replace(
            layer,
            text=text,
            style=replace(
                layer.style,
                font_size=size,
                font_stretch=stretch,
            ),
            overflow=overflow,
        )


class QtTextRenderer:
    def render(self, document: ImageDocument, layout: TextLayout) -> ImageDocument:
        image = _qimage(document).convertToFormat(QImage.Format.Format_RGBA8888)
        painter = QPainter(image)
        painter.setRenderHints(
            QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing
        )
        for layer in layout.layers:
            if not layer.visible:
                continue
            font, horizontal_scale = _render_font_and_horizontal_scale(layer)
            if layer.path is not None:
                painter.save()
                painter.setOpacity(layer.style.text_opacity)
                _render_arc_layer(
                    painter,
                    layer,
                    font,
                    horizontal_scale=horizontal_scale,
                )
                painter.restore()
                continue
            painter.save()
            painter.translate(layer.box.center_x, layer.box.center_y)
            painter.rotate(layer.box.rotation_degrees)
            painter.scale(
                (-1 if layer.mirror_x else 1) * horizontal_scale,
                -1 if layer.mirror_y else 1,
            )
            painter.setFont(font)
            target = QRectF(
                -layer.box.width / (2 * horizontal_scale),
                -layer.box.height / 2,
                layer.box.width / horizontal_scale,
                layer.box.height,
            )
            painter.setClipRect(target)
            if (
                layer.style.background_rgb is not None
                and layer.style.background_opacity > 0
            ):
                background = QColor(*layer.style.background_rgb)
                background.setAlphaF(layer.style.background_opacity)
                painter.fillRect(target, background)
            painter.setOpacity(layer.style.text_opacity)
            flags = _text_flags(layer.style, layer.text)
            if layer.style.shadow_opacity > 0:
                painter.save()
                painter.translate(
                    layer.style.shadow_offset_x / horizontal_scale,
                    layer.style.shadow_offset_y,
                )
                shadow = QColor(*layer.style.shadow_rgb)
                shadow.setAlphaF(layer.style.shadow_opacity)
                painter.setPen(shadow)
                painter.drawText(target, flags, layer.text)
                painter.restore()
            if layer.style.stroke_width > 0:
                painter.setPen(QColor(*layer.style.stroke_rgb))
                radius = max(1, round(layer.style.stroke_width))
                for offset_x in range(-radius, radius + 1):
                    for offset_y in range(-radius, radius + 1):
                        if offset_x or offset_y:
                            painter.drawText(
                                target.translated(
                                    offset_x / horizontal_scale,
                                    offset_y,
                                ),
                                flags,
                                layer.text,
                            )
            painter.setPen(QColor(*layer.style.fill_rgb))
            if (
                layer.style.line_height != 1
                and layer.style.stroke_width == 0
                and layer.style.shadow_opacity == 0
            ):
                _draw_text_with_line_height(
                    painter,
                    target,
                    layer.text,
                    font,
                    layer.style,
                )
            else:
                painter.drawText(target, flags, layer.text)
            painter.restore()
        painter.end()
        rgba = _rgba_bytes(image, document.asset.width, document.asset.height)
        pixels = rgba if document.mode == "RGBA" else rgba[:, :, :3].copy()
        return ImageDocument(document.asset, document.mode, pixels.tobytes())


def _qimage(document: ImageDocument) -> QImage:
    image_format = (
        QImage.Format.Format_RGBA8888
        if document.mode == "RGBA"
        else QImage.Format.Format_RGB888
    )
    channels = 4 if document.mode == "RGBA" else 3
    return QImage(
        document.pixels,
        document.asset.width,
        document.asset.height,
        document.asset.width * channels,
        image_format,
    ).copy()


def _font_for_style(style: TextStyle, *, native_stretch: bool = False) -> QFont:
    font = QFont(style.font_family)
    font.setPixelSize(max(1, round(style.font_size)))
    font.setStretch(style.font_stretch if native_stretch else 100)
    font.setWeight(QFont.Weight(style.font_weight))
    font.setLetterSpacing(
        QFont.SpacingType.AbsoluteSpacing,
        style.letter_spacing,
    )
    return font


def _draw_text_with_line_height(
    painter: QPainter,
    target: QRectF,
    text: str,
    font: QFont,
    style: TextStyle,
) -> None:
    layout = QTextLayout(text, font)
    option = QTextOption()
    option.setWrapMode(
        QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere
        if style.wrap
        else QTextOption.WrapMode.NoWrap
    )
    option.setAlignment(
        {
            TextAlignment.LEFT: Qt.AlignmentFlag.AlignLeft,
            TextAlignment.CENTER: Qt.AlignmentFlag.AlignHCenter,
            TextAlignment.RIGHT: Qt.AlignmentFlag.AlignRight,
        }[style.alignment]
    )
    layout.setTextOption(option)
    lines = []
    layout.beginLayout()
    while True:
        line = layout.createLine()
        if not line.isValid():
            break
        line.setLineWidth(target.width())
        lines.append(line)
    layout.endLayout()
    if not lines:
        return
    metrics = QFontMetricsF(font)
    step = metrics.height() * style.line_height
    total_height = metrics.height() + step * (len(lines) - 1)
    if style.vertical_alignment is VerticalAlignment.TOP:
        top = target.top()
    elif style.vertical_alignment is VerticalAlignment.BOTTOM:
        top = target.bottom() - total_height
    else:
        top = target.center().y() - total_height / 2
    for index, line in enumerate(lines):
        line.setPosition(QPointF(target.left(), top + index * step))
    layout.draw(painter, QPointF(0, 0))


def _font_horizontal_scale(style: TextStyle) -> float:
    return style.font_stretch / 100


def _fit_dense_short_word_overflow(
    ocr_result: OcrResult,
    translation_result: TranslationResult,
    layers: tuple[TextLayer, ...],
) -> tuple[TextLayer, ...]:
    if len(ocr_result.regions) < 40:
        return layers
    short_cjk_regions = sum(
        len(region.text.strip()) in {2, 3, 4}
        and _contains_cjk(region.text)
        for region in ocr_result.regions
    )
    if short_cjk_regions < max(30, len(ocr_result.regions) // 2):
        return layers

    units = {unit.region_id: unit for unit in translation_result.units}
    fitted = list(layers)
    for index, layer in enumerate(fitted):
        unit = units.get(layer.region_id)
        if (
            not layer.overflow
            or unit is None
            or unit.status is not TranslationStatus.TRANSLATED
            or len(unit.source_text.strip()) != 2
            or not all(_contains_cjk(character) for character in unit.source_text.strip())
            or not _is_single_latin_word(layer.text)
        ):
            continue
        candidates = tuple(
            (
                *fit_font_size(
                    4,
                    max(4, layer.style.font_size),
                    lambda size, stretch=stretch: _text_fits(
                        layer,
                        layer.text,
                        size,
                        stretch,
                    ),
                ),
                stretch,
            )
            for stretch in (*_AUTO_FONT_STRETCHES, 50)
        )
        size, overflow, stretch = max(
            candidates,
            key=lambda candidate: (candidate[0], candidate[2]),
        )
        if overflow:
            continue
        fitted[index] = replace(
            layer,
            style=replace(
                layer.style,
                font_size=size,
                font_stretch=stretch,
            ),
            overflow=False,
        )
    return tuple(fitted)


def _fit_short_latin_spacing(
    layers: tuple[TextLayer, ...],
) -> tuple[TextLayer, ...]:
    """电商短英文译文单行留白较大时适度加大字距，缩小与原文的视觉占比差距。

    只在「纯拉丁、非路径、未溢出、单行且仍有明显留白」时生效，且重新校验加
    字距后仍能完整放进文字框，避免把原本排版好的文本撑到换行或溢出。
    """
    if not layers:
        return layers
    fitted = list(layers)
    for index, layer in enumerate(fitted):
        text = layer.text
        if (
            not text.strip()
            or layer.path is not None
            or layer.overflow
            or not layer.visible
            or layer.style.letter_spacing != 0.0
            or not _contains_latin(text)
            or _contains_cjk(text)
        ):
            continue
        metrics = QFontMetricsF(_font_for_text(layer.style, text))
        horizontal_scale = layer.style.font_stretch / 100
        text_width = metrics.horizontalAdvance(text) * horizontal_scale
        if text_width <= 0 or text_width >= layer.box.width * 0.85:
            continue
        spare = layer.box.width - text_width
        spacing = min(spare * 0.5, layer.style.font_size * 0.35)
        if spacing <= 0.1:
            continue
        candidate = replace(
            layer,
            style=replace(layer.style, letter_spacing=spacing),
        )
        if not _text_fits(
            candidate,
            text,
            candidate.style.font_size,
            candidate.style.font_stretch,
        ):
            continue
        fitted[index] = candidate
    return tuple(fitted)


def _is_single_latin_word(text: str) -> bool:
    value = text.strip()
    return (
        bool(value)
        and not any(character.isspace() for character in value)
        and _contains_latin(value)
        and not _contains_cjk(value)
        and all(character.isalpha() or character in {"-", "'"} for character in value)
    )


def _font_for_layer(layer: TextLayer) -> QFont:
    return _font_for_text(layer.style, layer.text)


def _render_font_and_horizontal_scale(layer: TextLayer) -> tuple[QFont, float]:
    native_stretch = layer.path is not None or _is_visibly_rotated(layer.box.rotation_degrees)
    font = _font_for_style(layer.style, native_stretch=native_stretch)
    return font, 1.0 if native_stretch else _font_horizontal_scale(layer.style)


def _is_visibly_rotated(rotation_degrees: float) -> bool:
    normalized = abs(((rotation_degrees + 90) % 180) - 90)
    return normalized >= 10


def _font_for_text(
    style: TextStyle,
    text: str,
    *,
    font_size: float | None = None,
    font_stretch: int | None = None,
) -> QFont:
    measured_style = replace(
        style,
        font_size=style.font_size if font_size is None else font_size,
        font_stretch=style.font_stretch if font_stretch is None else font_stretch,
    )
    return _font_for_style(measured_style)


def _rgba_bytes(image: QImage, width: int, height: int) -> np.ndarray:
    row_bytes = image.bytesPerLine()
    buffer = np.frombuffer(image.constBits(), dtype=np.uint8).reshape(height, row_bytes)
    return buffer[:, : width * 4].reshape(height, width, 4).copy()


def _text_box(region: TextRegion) -> TextBox:
    p0, p1, _, p3 = region.polygon
    width = hypot(p1.x - p0.x, p1.y - p0.y)
    height = hypot(p3.x - p0.x, p3.y - p0.y)
    return TextBox(
        sum(point.x for point in region.polygon) / 4,
        sum(point.y for point in region.polygon) / 4,
        max(1, width),
        max(1, height),
        degrees(atan2(p1.y - p0.y, p1.x - p0.x)),
    )


def _text_box_for_translation(
    region: TextRegion,
    translated_text: str,
    circular_center: tuple[float, float] | None = None,
) -> TextBox:
    enhanced_box = _enhanced_tangent_text_box(region, circular_center)
    if enhanced_box is not None:
        return enhanced_box
    box = _text_box(region)
    if region.enhanced_only and box.height > box.width:
        return TextBox(
            box.center_x,
            box.center_y,
            box.height,
            box.width,
            box.rotation_degrees + 90,
        )
    if (
        box.height >= box.width * 1.8
        and _contains_latin(translated_text)
        and not _contains_cjk(translated_text)
    ):
        return TextBox(
            box.center_x,
            box.center_y,
            box.height,
            box.width,
            box.rotation_degrees + 90,
        )
    return box


def _enhanced_tangent_text_box(
    region: TextRegion,
    circular_center: tuple[float, float] | None = None,
) -> TextBox | None:
    if circular_center is None and (
        not region.enhanced_only or not region.observations
    ):
        return None
    points = np.asarray(
        tuple((point.x, point.y) for point in region.polygon),
        dtype=float,
    )
    center = np.mean(points, axis=0)
    if circular_center is not None:
        rotation = degrees(
            atan2(
                float(center[1]) - circular_center[1],
                float(center[0]) - circular_center[0],
            )
        ) + 90
    else:
        agreeing = tuple(
            observation
            for observation in region.observations
            if observation.confidence >= 0.8
            and _text_similarity(observation.text, region.text) >= 0.82
        )
        evidence = agreeing or region.observations
        reference = max(
            evidence,
            key=lambda observation: (
                observation.confidence,
                len(observation.text),
                observation.view_id,
            ),
        )
        aligned_angles = tuple(
            _align_axis_angle(observation.angle_degrees, reference.angle_degrees)
            for observation in evidence
        )
        weights = tuple(max(0.01, observation.confidence) for observation in evidence)
        rotation = sum(
            angle * weight
            for angle, weight in zip(aligned_angles, weights, strict=True)
        ) / sum(weights)
    angle = radians(rotation)
    tangent = np.asarray((cos(angle), sin(angle)), dtype=float)
    normal = np.asarray((-sin(angle), cos(angle)), dtype=float)
    relative = points - center
    tangent_values = relative @ tangent
    normal_values = relative @ normal
    width = float(tangent_values.max() - tangent_values.min())
    height = float(normal_values.max() - normal_values.min())
    if width <= 0 or height <= 0:
        return None
    return TextBox(
        float(center[0]),
        float(center[1]),
        max(1.0, width),
        max(1.0, height),
        _normalized_degrees(rotation),
    )


def _align_axis_angle(value: float, reference: float) -> float:
    aligned = value
    while aligned - reference > 90:
        aligned -= 180
    while aligned - reference < -90:
        aligned += 180
    return aligned


def _normalized_degrees(value: float) -> float:
    return (value + 180) % 360 - 180


def _text_similarity(first: str, second: str) -> float:
    first_value = "".join(
        character.casefold() for character in first if character.isalnum()
    )
    second_value = "".join(
        character.casefold() for character in second if character.isalnum()
    )
    if not first_value or not second_value:
        return 0.0
    return SequenceMatcher(None, first_value, second_value).ratio()


def _fit_enhanced_tangent_layer(layer: TextLayer) -> TextLayer:
    fitted_layer = (
        replace(
            layer,
            box=replace(
                layer.box,
                height=layer.box.height + min(2.0, layer.box.height * 0.25),
            ),
        )
        if _contains_cjk(layer.text) and layer.box.height <= 12
        else layer
    )
    candidates = tuple(
        (
            *fit_font_size(
                6,
                max(6, min(160, fitted_layer.box.height * 0.98)),
                lambda size, stretch=stretch: _text_fits(
                    fitted_layer,
                    fitted_layer.text,
                    size,
                    stretch,
                ),
            ),
            stretch,
        )
        for stretch in (200, 175, 150, 125, 100, 87, 75, 67, 50)
    )
    size, overflow, stretch = max(
        candidates,
        key=lambda candidate: (
            not candidate[1],
            candidate[0],
            candidate[2],
        ),
    )
    return replace(
        fitted_layer,
        style=replace(
            fitted_layer.style,
            font_size=size,
            font_stretch=stretch,
            wrap=False,
        ),
        overflow=overflow,
    )


def _text_path_for_region(
    document: ImageDocument,
    region: TextRegion,
    box: TextBox,
    circular_center: tuple[float, float] | None,
) -> TextPath | None:
    circular_path = circular_text_path_for_region(region, box, circular_center)
    if circular_path is not None:
        return circular_path
    return _estimate_arc_text_path(document, region, box)


def circular_text_path_for_region(
    region: TextRegion,
    box: TextBox,
    circular_center: tuple[float, float] | None,
) -> CircularTextPath | None:
    if (
        circular_center is None
        or not region.enhanced_only
        or not region.observations
        or not any(
            observation.source.startswith("polar")
            for observation in region.observations
        )
    ):
        return None
    center_x, center_y = circular_center
    points = np.asarray(
        tuple((point.x, point.y) for point in region.polygon),
        dtype=float,
    )
    region_center = np.mean(points, axis=0)
    radial = region_center - np.asarray((center_x, center_y), dtype=float)
    radius = float(np.linalg.norm(radial))
    if radius <= max(2.0, box.height):
        return None

    midpoint_angle = atan2(float(radial[1]), float(radial[0]))
    point_angles = np.arctan2(points[:, 1] - center_y, points[:, 0] - center_x)
    relative_angles = np.asarray(
        [
            (float(angle) - midpoint_angle + np.pi) % (2 * np.pi) - np.pi
            for angle in point_angles
        ],
        dtype=float,
    )
    minimum_angle = float(relative_angles.min())
    maximum_angle = float(relative_angles.max())
    angular_span = maximum_angle - minimum_angle
    if angular_span <= radians(0.5) or angular_span >= radians(75):
        return None

    return ensure_bottom_inward_circular_path(
        CircularTextPath(
            PathPoint(float(center_x), float(center_y)),
            radius,
            degrees(midpoint_angle + minimum_angle),
            degrees(midpoint_angle + maximum_angle),
        )
    )


def _estimate_arc_text_path(
    document: ImageDocument,
    region: TextRegion,
    box: TextBox,
) -> ArcTextPath | None:
    if not _contains_cjk(region.text) or len(region.text) < 5:
        return None
    width = max(2, round(box.width))
    height = max(2, round(box.height))
    if width / height < 2 or height < 20:
        return None

    channels = 4 if document.mode == "RGBA" else 3
    image = np.frombuffer(document.pixels, dtype=np.uint8).reshape(
        document.asset.height,
        document.asset.width,
        channels,
    )[:, :, :3]
    source_points = np.float32(
        [(point.x, point.y) for point in region.polygon]
    )
    target_points = np.float32(
        ((0, 0), (width - 1, 0), (width - 1, height - 1), (0, height - 1))
    )
    crop = cv2.warpPerspective(
        image,
        cv2.getPerspectiveTransform(source_points, target_points),
        (width, height),
    )
    gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
    _, foreground = cv2.threshold(
        gray,
        0,
        255,
        cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU,
    )
    component_count, _, stats, centroids = cv2.connectedComponentsWithStats(
        foreground
    )
    points = []
    minimum_area = max(4, round(width * height * 0.001))
    for index in range(1, component_count):
        x, y, component_width, component_height, area = stats[index]
        if (
            area < minimum_area
            or component_height < height * 0.12
            or component_height > height * 0.9
            or component_width > width * 0.45
        ):
            continue
        points.append((float(centroids[index][0]), float(y + component_height)))
    if len(points) < 5:
        return None

    xs = np.asarray([point[0] for point in points], dtype=float)
    ys = np.asarray([point[1] for point in points], dtype=float)
    quadratic = np.polyfit(xs, ys, 2)
    linear = np.polyfit(xs, ys, 1)
    quadratic_error = float(
        np.sqrt(np.mean((np.polyval(quadratic, xs) - ys) ** 2))
    )
    linear_error = float(np.sqrt(np.mean((np.polyval(linear, xs) - ys) ** 2)))
    midpoint = float(np.polyval(quadratic, width / 2))
    endpoint_average = float(
        (np.polyval(quadratic, 0) + np.polyval(quadratic, width)) / 2
    )
    bend_pixels = midpoint - endpoint_average
    strong_curve = (
        abs(bend_pixels) >= height * 0.18
        and quadratic_error <= linear_error * 0.8
    )
    rotated_curve = (
        abs(box.rotation_degrees) >= 12
        and abs(bend_pixels) >= max(2.0, height * 0.04)
    )
    if not strong_curve and not rotated_curve:
        return None

    baseline = np.float32(
        [
            (0, np.clip(np.polyval(quadratic, 0), 0, height - 1)),
            (
                (width - 1) / 2,
                np.clip(
                    np.polyval(quadratic, (width - 1) / 2),
                    0,
                    height - 1,
                ),
            ),
            (
                width - 1,
                np.clip(np.polyval(quadratic, width - 1), 0, height - 1),
            ),
        ]
    ).reshape(1, 3, 2)
    mapped = cv2.perspectiveTransform(
        baseline,
        cv2.getPerspectiveTransform(target_points, source_points),
    )[0]
    start = PathPoint(float(mapped[0][0]), float(mapped[0][1]))
    midpoint_path = PathPoint(float(mapped[1][0]), float(mapped[1][1]))
    end = PathPoint(float(mapped[2][0]), float(mapped[2][1]))
    control = PathPoint(
        2 * midpoint_path.x - (start.x + end.x) / 2,
        2 * midpoint_path.y - (start.y + end.y) / 2,
    )
    return ArcTextPath(start, control, end)


def _expand_arc_box_for_translation(
    document: ImageDocument,
    box: TextBox,
    source_text: str,
    translated_text: str,
) -> TextBox:
    if (
        len(translated_text) <= len(source_text) * 1.8
        or abs(box.rotation_degrees) < 12
    ):
        return box
    maximum_width = min(
        box.width * 1.3,
        document.asset.width * 0.25,
    )
    if maximum_width <= box.width + 1:
        return box
    return replace(box, width=maximum_width)


def _translated_groups(
    translation_result: TranslationResult,
    regions: dict[str, TextRegion],
) -> tuple[tuple[tuple[TranslationUnit, TextRegion], ...], ...]:
    entries = tuple(
        (unit, region)
        for unit in translation_result.units
        if unit.should_erase_source
        for region in (regions.get(unit.region_id),)
        if region is not None
    )
    groups: list[list[tuple[TranslationUnit, TextRegion]]] = []
    for entry in entries:
        if groups and _same_paragraph_line(groups[-1][-1], entry):
            groups[-1].append(entry)
        else:
            groups.append([entry])
    return tuple(tuple(group) for group in groups)


def _same_paragraph_line(
    first: tuple[TranslationUnit, TextRegion],
    second: tuple[TranslationUnit, TextRegion],
) -> bool:
    first_unit, first_region = first
    second_unit, second_region = second
    if (
        first_unit.target_language != second_unit.target_language
        or len(first_region.text) < 10
        or len(second_region.text) < 10
        or not _contains_cjk(first_region.text)
        or not _contains_cjk(second_region.text)
    ):
        return False
    first_box = _text_box(first_region)
    second_box = _text_box(second_region)
    if (
        abs(first_box.rotation_degrees) > 3
        or abs(second_box.rotation_degrees) > 3
        or max(first_box.height, second_box.height)
        > min(first_box.height, second_box.height) * 1.35
    ):
        return False
    first_left = first_box.center_x - first_box.width / 2
    second_left = second_box.center_x - second_box.width / 2
    first_bottom = first_box.center_y + first_box.height / 2
    second_top = second_box.center_y - second_box.height / 2
    gap = second_top - first_bottom
    overlap = min(
        first_box.center_x + first_box.width / 2,
        second_box.center_x + second_box.width / 2,
    ) - max(first_left, second_left)
    return (
        abs(first_left - second_left) <= max(first_box.height, second_box.height) * 0.25
        and -min(first_box.height, second_box.height) * 0.2
        <= gap
        <= max(first_box.height, second_box.height) * 0.35
        and overlap >= min(first_box.width, second_box.width) * 0.65
    )


def _paragraph_text_box(regions: tuple[TextRegion, ...]) -> TextBox:
    xs = tuple(point.x for region in regions for point in region.polygon)
    ys = tuple(point.y for region in regions for point in region.polygon)
    return TextBox(
        (min(xs) + max(xs)) / 2,
        (min(ys) + max(ys)) / 2,
        max(1.0, max(xs) - min(xs)),
        max(1.0, max(ys) - min(ys)),
    )


def _contains_cjk(text: str) -> bool:
    return any(
        "\u3400" <= character <= "\u9fff"
        or "\uf900" <= character <= "\ufaff"
        for character in text
    )


def _contains_latin(text: str) -> bool:
    return any(
        "A" <= character <= "Z" or "a" <= character <= "z"
        for character in text
    )


def _normalize_visual_group_sizes(
    document: ImageDocument,
    layers: tuple[TextLayer, ...],
) -> tuple[TextLayer, ...]:
    if len(layers) < 2:
        return layers
    parents = list(range(len(layers)))

    def find(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(first: int, second: int) -> None:
        first_root = find(first)
        second_root = find(second)
        if first_root != second_root:
            parents[second_root] = first_root

    signatures = tuple(_background_signature(document, layer.box) for layer in layers)
    for first in range(len(layers)):
        for second in range(first + 1, len(layers)):
            if _same_visual_group(
                layers[first],
                signatures[first],
                layers[second],
                signatures[second],
            ):
                union(first, second)
    groups: dict[int, list[int]] = {}
    for index in range(len(layers)):
        groups.setdefault(find(index), []).append(index)
    normalized = list(layers)
    for indexes in groups.values():
        if len(indexes) < 2:
            continue
        group_boxes = {index: layers[index].box for index in indexes}
        vertical_stack = (
            max(layers[index].box.center_x for index in indexes)
            - min(layers[index].box.center_x for index in indexes)
            <= float(
                np.median([layers[index].box.height for index in indexes])
            )
            * 0.65
        )
        if len(indexes) >= 3 and vertical_stack:
            common_width = min(
                document.asset.width,
                max(layers[index].box.width for index in indexes) * 1.25,
            )
            common_center_x = float(
                np.median([layers[index].box.center_x for index in indexes])
            )
            common_center_x = min(
                max(common_center_x, common_width / 2),
                document.asset.width - common_width / 2,
            )
            group_boxes = {
                index: replace(
                    layers[index].box,
                    center_x=common_center_x,
                    width=common_width,
                )
                for index in indexes
            }
        common_stretch = min(
            layers[index].style.font_stretch for index in indexes
        )
        weights = sorted(layers[index].style.font_weight for index in indexes)
        common_weight = weights[(len(weights) - 1) // 2]
        group_layers = {
            index: replace(
                layers[index],
                box=group_boxes[index],
                style=replace(layers[index].style, font_weight=common_weight),
            )
            for index in indexes
        }
        common_size = min(
            fit_font_size(
                6,
                max(6, min(160, layers[index].box.height * 0.9)),
                lambda size, index=index: _text_fits(
                    group_layers[index],
                    layers[index].text,
                    size,
                    common_stretch,
                ),
            )[0]
            for index in indexes
        )
        for index in indexes:
            candidate = replace(
                group_layers[index],
                style=replace(
                    group_layers[index].style,
                    font_size=common_size,
                    font_stretch=common_stretch,
                ),
            )
            normalized[index] = replace(
                candidate,
                overflow=not _text_fits(
                    candidate,
                    candidate.text,
                    candidate.style.font_size,
                    candidate.style.font_stretch,
                ),
            )
    return tuple(normalized)


def _normalize_repeated_panel_rows(
    document: ImageDocument,
    layers: tuple[TextLayer, ...],
) -> tuple[TextLayer, ...]:
    if len(layers) < 3:
        return layers
    signatures = tuple(_background_signature(document, layer.box) for layer in layers)
    parents = list(range(len(layers)))

    def find(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(first: int, second: int) -> None:
        first_root = find(first)
        second_root = find(second)
        if first_root != second_root:
            parents[second_root] = first_root

    for first in range(len(layers)):
        first_layer = layers[first]
        if first_layer.path is not None or abs(first_layer.box.rotation_degrees) > 3:
            continue
        for second in range(first + 1, len(layers)):
            second_layer = layers[second]
            if (
                second_layer.path is not None
                or abs(second_layer.box.rotation_degrees) > 3
            ):
                continue
            height_ratio = max(
                first_layer.box.height,
                second_layer.box.height,
            ) / min(first_layer.box.height, second_layer.box.height)
            if (
                height_ratio > 1.15
                or abs(first_layer.box.center_y - second_layer.box.center_y)
                > max(first_layer.box.height, second_layer.box.height) * 0.3
                or np.linalg.norm(
                    np.asarray(first_layer.style.fill_rgb, dtype=float)
                    - np.asarray(second_layer.style.fill_rgb, dtype=float)
                )
                > 25
                or np.linalg.norm(signatures[first][0] - signatures[second][0]) > 35
                or abs(signatures[first][2] - signatures[second][2]) > 35
            ):
                continue
            union(first, second)

    groups: dict[int, list[int]] = {}
    for index in range(len(layers)):
        groups.setdefault(find(index), []).append(index)
    normalized = list(layers)
    for indexes in groups.values():
        if len(indexes) < 3:
            continue
        indexes.sort(key=lambda index: layers[index].box.center_x)
        widths = [layers[index].box.width for index in indexes]
        heights = [layers[index].box.height for index in indexes]
        maximum_gap = max(float(np.median(widths)) * 1.75, float(np.median(heights)) * 6)
        if any(
            layers[right].box.center_x
            - layers[right].box.width / 2
            - (
                layers[left].box.center_x
                + layers[left].box.width / 2
            )
            > maximum_gap
            for left, right in zip(indexes, indexes[1:])
        ):
            continue

        cell_edges = [0.0]
        cell_edges.extend(
            (
                layers[left].box.center_x + layers[right].box.center_x
            )
            / 2
            for left, right in zip(indexes, indexes[1:])
        )
        cell_edges.append(float(document.asset.width))
        center_spacings = [
            layers[right].box.center_x - layers[left].box.center_x
            for left, right in zip(indexes, indexes[1:])
        ]
        compact_caption_row = (
            len(indexes) == 3
            and bool(center_spacings)
            and all(signatures[index][1] <= 35 for index in indexes)
            and float(np.median(widths))
            <= float(np.median(center_spacings)) * 0.75
        )
        caption_width = (
            float(np.median(center_spacings)) * 0.9
            if compact_caption_row
            else 0.0
        )
        group_layers: dict[int, TextLayer] = {}
        for position, index in enumerate(indexes):
            expanded_box = _matching_background_run_box(
                document,
                layers[index].box,
                signatures[index][0],
                cell_edges[position],
                cell_edges[position + 1],
            )
            if compact_caption_row:
                expanded_box = replace(
                    expanded_box,
                    center_x=layers[index].box.center_x,
                    width=max(
                        expanded_box.width,
                        min(caption_width, layers[index].box.width * 1.8),
                    ),
                    height=layers[index].box.height * 1.3,
                )
            group_layers[index] = replace(
                layers[index],
                box=expanded_box,
                style=replace(
                    layers[index].style,
                    alignment=(
                        TextAlignment.CENTER
                        if compact_caption_row
                        else TextAlignment.LEFT
                    ),
                ),
            )

        common_stretch = min(
            group_layers[index].style.font_stretch for index in indexes
        )
        common_rotation = float(
            np.median(
                [group_layers[index].box.rotation_degrees for index in indexes]
            )
        )
        if abs(common_rotation) <= 1.5:
            common_rotation = 0.0
        weights = sorted(
            group_layers[index].style.font_weight for index in indexes
        )
        common_weight = weights[(len(weights) - 1) // 2]
        group_layers = {
            index: replace(
                group_layers[index],
                box=replace(
                    group_layers[index].box,
                    rotation_degrees=common_rotation,
                ),
                style=replace(
                    group_layers[index].style,
                    font_weight=common_weight,
                ),
            )
            for index in indexes
        }
        common_size = min(
            fit_font_size(
                6,
                max(6, min(160, group_layers[index].box.height * 0.9)),
                lambda size, index=index: _text_fits(
                    group_layers[index],
                    group_layers[index].text,
                    size,
                    common_stretch,
                ),
            )[0]
            for index in indexes
        )
        for index in indexes:
            candidate = replace(
                group_layers[index],
                style=replace(
                    group_layers[index].style,
                    font_size=common_size,
                    font_stretch=common_stretch,
                ),
            )
            normalized[index] = replace(
                candidate,
                overflow=not _text_fits(
                    candidate,
                    candidate.text,
                    common_size,
                    common_stretch,
                ),
            )
    return tuple(normalized)


def _normalize_repeated_curved_layers(
    ocr_result: OcrResult,
    layers: tuple[TextLayer, ...],
    reflow: Callable[[TextLayer, str], TextLayer],
) -> tuple[TextLayer, ...]:
    if len(layers) < 2:
        return layers
    regions = {region.region_id: region for region in ocr_result.regions}
    parents = list(range(len(layers)))

    def find(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(first: int, second: int) -> None:
        first_root = find(first)
        second_root = find(second)
        if first_root != second_root:
            parents[second_root] = first_root

    for first in range(len(layers)):
        first_layer = layers[first]
        first_region = regions.get(first_layer.region_id)
        if first_layer.path is None or first_region is None:
            continue
        for second in range(first + 1, len(layers)):
            second_layer = layers[second]
            second_region = regions.get(second_layer.region_id)
            if second_layer.path is None or second_region is None:
                continue
            if _are_repeated_curved_regions(
                first_region,
                first_layer,
                second_region,
                second_layer,
            ):
                union(first, second)

    groups: dict[int, list[int]] = {}
    for index in range(len(layers)):
        groups.setdefault(find(index), []).append(index)
    normalized = list(layers)
    for indexes in groups.values():
        if len(indexes) < 2:
            continue
        canonical_index = max(
            indexes,
            key=lambda index: regions[layers[index].region_id].confidence,
        )
        canonical = layers[canonical_index]
        if canonical.path is None:
            continue
        for index in indexes:
            if index == canonical_index:
                continue
            layer = layers[index]
            candidate = replace(
                layer,
                text=canonical.text,
                path=transform_arc_path(
                    canonical.path,
                    canonical.box,
                    layer.box,
                ),
            )
            normalized[index] = reflow(candidate, canonical.text)
    return tuple(normalized)


def _are_repeated_curved_regions(
    first_region: TextRegion,
    first_layer: TextLayer,
    second_region: TextRegion,
    second_layer: TextLayer,
) -> bool:
    first_text = first_region.text.replace(" ", "")
    second_text = second_region.text.replace(" ", "")
    if (
        min(len(first_text), len(second_text)) < 6
        or not _contains_cjk(first_text)
        or not _contains_cjk(second_text)
        or abs(len(first_text) - len(second_text)) > 2
        or _normalized_edit_distance(first_text, second_text) > 0.3
        or abs(
            first_layer.box.rotation_degrees
            - second_layer.box.rotation_degrees
        )
        > 5
    ):
        return False
    width_ratio = max(first_layer.box.width, second_layer.box.width) / min(
        first_layer.box.width,
        second_layer.box.width,
    )
    height_ratio = max(first_layer.box.height, second_layer.box.height) / min(
        first_layer.box.height,
        second_layer.box.height,
    )
    return width_ratio <= 1.3 and height_ratio <= 1.3


def _normalized_edit_distance(first: str, second: str) -> float:
    if first == second:
        return 0.0
    if not first or not second:
        return 1.0
    previous = list(range(len(second) + 1))
    for first_index, first_character in enumerate(first, start=1):
        current = [first_index]
        for second_index, second_character in enumerate(second, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[second_index] + 1,
                    previous[second_index - 1]
                    + (first_character != second_character),
                )
            )
        previous = current
    return previous[-1] / max(len(first), len(second))


def _normalize_repeated_vertical_labels(
    layers: tuple[TextLayer, ...],
) -> tuple[TextLayer, ...]:
    normalized = list(layers)
    used: set[int] = set()
    for first in range(len(layers)):
        if first in used:
            continue
        first_layer = layers[first]
        if (
            first_layer.path is not None
            or abs(abs(first_layer.box.rotation_degrees) - 90) > 8
        ):
            continue
        indexes = [first]
        for second in range(first + 1, len(layers)):
            second_layer = layers[second]
            if (
                second_layer.path is not None
                or second_layer.text != first_layer.text
                or abs(abs(second_layer.box.rotation_degrees) - 90) > 8
            ):
                continue
            width_ratio = max(
                first_layer.box.width,
                second_layer.box.width,
            ) / min(first_layer.box.width, second_layer.box.width)
            height_ratio = max(
                first_layer.box.height,
                second_layer.box.height,
            ) / min(first_layer.box.height, second_layer.box.height)
            if width_ratio <= 1.25 and height_ratio <= 1.25:
                indexes.append(second)
        if len(indexes) < 2:
            continue
        used.update(indexes)
        common_stretch = min(
            layers[index].style.font_stretch for index in indexes
        )
        common_weight = max(
            layers[index].style.font_weight for index in indexes
        )
        candidates = {
            index: replace(
                layers[index],
                box=replace(
                    layers[index].box,
                    rotation_degrees=90,
                ),
                style=replace(
                    layers[index].style,
                    alignment=TextAlignment.CENTER,
                    font_stretch=common_stretch,
                    font_weight=common_weight,
                ),
            )
            for index in indexes
        }
        common_size = min(
            fit_font_size(
                6,
                max(6, min(160, candidates[index].box.height * 0.9)),
                lambda size, index=index: _text_fits(
                    candidates[index],
                    candidates[index].text,
                    size,
                    common_stretch,
                ),
            )[0]
            for index in indexes
        )
        for index in indexes:
            candidate = replace(
                candidates[index],
                style=replace(
                    candidates[index].style,
                    font_size=common_size,
                ),
            )
            normalized[index] = replace(
                candidate,
                overflow=not _text_fits(
                    candidate,
                    candidate.text,
                    common_size,
                    common_stretch,
                ),
            )
    return tuple(normalized)


def _align_panel_title_and_body(
    layers: tuple[TextLayer, ...],
) -> tuple[TextLayer, ...]:
    normalized = list(layers)
    used_body: set[int] = set()
    for title_index, title in enumerate(layers):
        if (
            title.path is not None
            or title.style.alignment is not TextAlignment.LEFT
            or abs(title.box.rotation_degrees) > 3
        ):
            continue
        candidates = []
        for body_index, body in enumerate(layers):
            if (
                body_index == title_index
                or body_index in used_body
                or body.path is not None
                or body.style.alignment is not TextAlignment.LEFT
                or abs(body.box.rotation_degrees) > 3
                or body.box.center_y <= title.box.center_y
                or body.style.font_size >= title.style.font_size * 0.85
            ):
                continue
            vertical_distance = body.box.center_y - title.box.center_y
            if vertical_distance > max(title.box.height, body.box.height) * 1.6:
                continue
            title_left = title.box.center_x - title.box.width / 2
            title_right = title.box.center_x + title.box.width / 2
            body_left = body.box.center_x - body.box.width / 2
            body_right = body.box.center_x + body.box.width / 2
            overlap = min(title_right, body_right) - max(title_left, body_left)
            if overlap < min(title.box.width, body.box.width) * 0.5:
                continue
            candidates.append(
                (
                    abs(title.box.center_x - body.box.center_x),
                    vertical_distance,
                    body_index,
                )
            )
        if not candidates:
            continue
        _, _, body_index = min(candidates)
        used_body.add(body_index)
        body = layers[body_index]
        common_left = min(
            title.box.center_x - title.box.width / 2,
            body.box.center_x - body.box.width / 2,
        )
        normalized[title_index] = replace(
            title,
            box=replace(
                title.box,
                center_x=common_left + title.box.width / 2,
            ),
        )
        normalized[body_index] = replace(
            body,
            box=replace(
                body.box,
                center_x=common_left + body.box.width / 2,
            ),
        )
    return tuple(normalized)


def _matching_background_run_box(
    document: ImageDocument,
    box: TextBox,
    background: np.ndarray,
    cell_left: float,
    cell_right: float,
) -> TextBox:
    channels = 4 if document.mode == "RGBA" else 3
    pixels = np.frombuffer(document.pixels, dtype=np.uint8).reshape(
        document.asset.height,
        document.asset.width,
        channels,
    )[:, :, :3]
    y0 = max(0, round(box.center_y - box.height * 0.8))
    y1 = min(document.asset.height, round(box.center_y + box.height * 0.8) + 1)
    left = max(0, round(cell_left))
    right = min(document.asset.width, round(cell_right))
    if y1 <= y0 or right - left < box.width:
        return box
    column_colors = np.median(pixels[y0:y1, left:right], axis=0).astype(float)
    color_distance_limit = 26 if float(np.ptp(background)) > 35 else 42
    matching = (
        np.linalg.norm(column_colors - background.astype(float), axis=1)
        <= color_distance_limit
    ).astype(np.uint8)
    kernel_width = (
        3
        if float(np.ptp(background)) > 35
        else max(3, min(9, round(box.height * 0.25)))
    )
    matching = cv2.morphologyEx(
        matching.reshape(1, -1),
        cv2.MORPH_CLOSE,
        np.ones((1, kernel_width), dtype=np.uint8),
    ).reshape(-1)
    center = max(0, min(len(matching) - 1, round(box.center_x) - left))
    if not matching[center]:
        candidates = np.flatnonzero(matching)
        if not len(candidates):
            return box
        center = int(candidates[np.argmin(abs(candidates - center))])
    run_left = center
    run_right = center
    while run_left > 0 and matching[run_left - 1]:
        run_left -= 1
    while run_right + 1 < len(matching) and matching[run_right + 1]:
        run_right += 1
    padding = max(2, round(box.height * 0.08))
    x0 = left + run_left + padding
    x1 = left + run_right + 1 - padding
    if x1 - x0 < box.width * 0.95:
        return box
    return replace(
        box,
        center_x=(x0 + x1) / 2,
        width=max(1.0, x1 - x0),
    )


def _same_visual_group(
    first: TextLayer,
    first_background: tuple[np.ndarray, float, float],
    second: TextLayer,
    second_background: tuple[np.ndarray, float, float],
) -> bool:
    if first.path is not None or second.path is not None:
        return False
    if first.style.font_family != second.style.font_family:
        return False
    first_height = first.box.height
    second_height = second.box.height
    if (
        abs(first.box.rotation_degrees) > 3
        or abs(second.box.rotation_degrees) > 3
        or abs(first.box.rotation_degrees - second.box.rotation_degrees) > 3
    ):
        return False
    height_ratio = max(first_height, second_height) / min(
        first_height,
        second_height,
    )
    upper, lower = sorted((first.box, second.box), key=lambda box: box.center_y)
    vertical_gap = (
        lower.center_y - lower.height / 2
        - (upper.center_y + upper.height / 2)
    )
    vertical_stack = (
        height_ratio <= 1.08
        and abs(first.box.center_x - second.box.center_x)
        <= max(first_height, second_height) * 0.65
        and -min(first_height, second_height) * 0.35
        <= vertical_gap
        <= max(first_height, second_height) * 1.25
    )
    left, right = sorted((first.box, second.box), key=lambda box: box.center_x)
    horizontal_gap = (
        right.center_x - right.width / 2
        - (left.center_x + left.width / 2)
    )
    horizontal_row = (
        height_ratio <= 1.15
        and abs(first.box.center_y - second.box.center_y)
        <= max(first_height, second_height) * 0.3
        and -min(first.box.width, second.box.width) * 0.15
        <= horizontal_gap
        <= max(first.box.width, second.box.width) * 0.75
    )
    if not vertical_stack and not horizontal_row:
        return False
    if np.linalg.norm(
        np.asarray(first.style.fill_rgb, dtype=float)
        - np.asarray(second.style.fill_rgb, dtype=float)
    ) > 25:
        return False
    first_median, first_chroma, first_texture = first_background
    second_median, second_chroma, second_texture = second_background
    background_distance = float(np.linalg.norm(first_median - second_median))
    return (
        abs(first_texture - second_texture) <= 35
        and (
            background_distance <= 35
            or (
                first_chroma <= 25
                and second_chroma <= 25
                and background_distance <= 60
            )
        )
    )


def _background_signature(
    document: ImageDocument,
    box: TextBox,
) -> tuple[np.ndarray, float, float]:
    channels = 4 if document.mode == "RGBA" else 3
    pixels = np.frombuffer(document.pixels, dtype=np.uint8).reshape(
        document.asset.height,
        document.asset.width,
        channels,
    )[:, :, :3]
    padding_x = max(4, round(box.width * 0.25))
    padding_y = max(3, round(box.height * 0.25))
    x0 = max(0, int(box.center_x - box.width / 2) - padding_x)
    x1 = min(
        document.asset.width,
        int(box.center_x + box.width / 2) + padding_x + 1,
    )
    y0 = max(0, int(box.center_y - box.height / 2) - padding_y)
    y1 = min(
        document.asset.height,
        int(box.center_y + box.height / 2) + padding_y + 1,
    )
    samples = pixels[y0:y1, x0:x1].reshape(-1, 3).astype(float)
    median = np.median(samples, axis=0)
    chroma = float(max(median) - min(median))
    texture = float(np.mean(np.std(samples, axis=0)))
    return median, chroma, texture


def _text_fits(
    layer: TextLayer,
    text: str,
    size: float,
    stretch: int,
) -> bool:
    font = _font_for_text(
        layer.style,
        text,
        font_size=size,
        font_stretch=stretch,
    )
    metrics = QFontMetricsF(font)
    horizontal_scale = stretch / 100
    if layer.path is not None:
        lines = _arc_text_lines(
            text,
            font,
            layer.path,
            horizontal_scale,
        )
        return (
            all(
                metrics.horizontalAdvance(line) * horizontal_scale
                <= layer.path.approximate_length() + 0.5
                for line in lines
            )
            and metrics.height() * len(lines) <= layer.box.height + 0.5
        )
    bounds = metrics.boundingRect(
        QRectF(
            0,
            0,
            layer.box.width / horizontal_scale,
            layer.box.height,
        ),
        _text_flags(layer.style, text),
        text,
    )
    return (
        bounds.width() * horizontal_scale <= layer.box.width + 0.5
        and bounds.height() <= layer.box.height + 0.5
    )


def _arc_single_line_fits(
    layer: TextLayer,
    text: str,
    size: float,
    stretch: int,
) -> bool:
    if layer.path is None:
        return False
    font = _font_for_text(
        layer.style,
        text,
        font_size=size,
        font_stretch=stretch,
    )
    metrics = QFontMetricsF(font)
    horizontal_scale = stretch / 100
    return (
        metrics.horizontalAdvance(text) * horizontal_scale
        <= layer.path.approximate_length() + 0.5
        and metrics.height() <= layer.box.height + 0.5
    )


def _text_flags(style: TextStyle, text: str) -> int:
    horizontal = {
        TextAlignment.LEFT: Qt.AlignmentFlag.AlignLeft,
        TextAlignment.CENTER: Qt.AlignmentFlag.AlignHCenter,
        TextAlignment.RIGHT: Qt.AlignmentFlag.AlignRight,
    }[style.alignment]
    vertical = {
        VerticalAlignment.TOP: Qt.AlignmentFlag.AlignTop,
        VerticalAlignment.CENTER: Qt.AlignmentFlag.AlignVCenter,
        VerticalAlignment.BOTTOM: Qt.AlignmentFlag.AlignBottom,
    }[style.vertical_alignment]
    flags = horizontal | vertical
    if style.wrap:
        flags |= Qt.TextFlag.TextWordWrap
        if _requires_character_wrap(text):
            flags |= Qt.TextFlag.TextWrapAnywhere
    else:
        flags |= Qt.TextFlag.TextSingleLine
    return int(flags)


def _requires_character_wrap(text: str) -> bool:
    return not any(character.isspace() for character in text) and any(
        "\u3400" <= character <= "\u9fff"
        or "\uf900" <= character <= "\ufaff"
        or "\u3040" <= character <= "\u30ff"
        or "\uac00" <= character <= "\ud7af"
        for character in text
    )


def _render_arc_layer(
    painter: QPainter,
    layer: TextLayer,
    font: QFont,
    *,
    horizontal_scale: float | None = None,
) -> None:
    path = layer.path
    if path is None or not layer.text:
        return
    if horizontal_scale is None:
        horizontal_scale = _font_horizontal_scale(layer.style)
    lines = _arc_text_lines(layer.text, font, path, horizontal_scale)
    line_height = QFontMetricsF(font).height()
    normal_offsets = (
        (0.0,)
        if len(lines) == 1
        else tuple(
            (index - (len(lines) - 1)) * line_height
            for index in range(len(lines))
        )
    )
    for text, normal_offset in zip(lines, normal_offsets, strict=True):
        _render_arc_text_line(
            painter,
            layer,
            path,
            font,
            text,
            normal_offset,
            horizontal_scale,
        )


def _render_arc_text_line(
    painter: QPainter,
    layer: TextLayer,
    path: TextPath,
    font: QFont,
    text: str,
    normal_offset: float,
    horizontal_scale: float,
) -> None:
    glyphs = tuple(
        (glyph, advance * horizontal_scale)
        for glyph, advance in _shaped_glyphs(text, font)
    )
    if not glyphs:
        return
    total_width = sum(advance for _, advance in glyphs)
    path_length = path.approximate_length()
    tracking = _arc_tracking(path, glyphs, path_length, total_width)
    tracked_width = total_width + tracking * max(0, len(glyphs) - 1)
    if layer.style.alignment is TextAlignment.LEFT:
        offset = 0.0
    elif layer.style.alignment is TextAlignment.RIGHT:
        offset = max(0.0, path_length - tracked_width)
    else:
        offset = max(0.0, (path_length - tracked_width) / 2)
    samples = _arc_samples(path)
    if layer.style.shadow_opacity > 0:
        shadow = QColor(*layer.style.shadow_rgb)
        shadow.setAlphaF(layer.style.shadow_opacity)
        painter.setPen(shadow)
        _draw_arc_glyphs(
            painter,
            path,
            glyphs,
            samples,
            offset,
            normal_offset,
            layer.style.shadow_offset_x,
            layer.style.shadow_offset_y,
            tracking,
            horizontal_scale,
            layer.mirror_x,
            layer.mirror_y,
        )
    if layer.style.stroke_width > 0:
        painter.setPen(QColor(*layer.style.stroke_rgb))
        radius = max(1, round(layer.style.stroke_width))
        for offset_x in range(-radius, radius + 1):
            for offset_y in range(-radius, radius + 1):
                if offset_x or offset_y:
                    _draw_arc_glyphs(
                        painter,
                        path,
                        glyphs,
                        samples,
                        offset,
                        normal_offset,
                        offset_x,
                        offset_y,
                        tracking,
                        horizontal_scale,
                        layer.mirror_x,
                        layer.mirror_y,
                    )
    painter.setPen(QColor(*layer.style.fill_rgb))
    _draw_arc_glyphs(
        painter,
        path,
        glyphs,
        samples,
        offset,
        normal_offset,
        0,
        0,
        tracking,
        horizontal_scale,
        layer.mirror_x,
        layer.mirror_y,
    )


def _arc_tracking(
    path: TextPath,
    glyphs: tuple[tuple[QGlyphRun, float], ...],
    path_length: float,
    text_width: float,
) -> float:
    if not isinstance(path, CircularTextPath) or len(glyphs) < 2:
        return 0.0
    spare = path_length - text_width
    if spare <= 0:
        return 0.0
    average_advance = text_width / len(glyphs)
    return min(spare / (len(glyphs) - 1), average_advance * 0.75)


def _arc_text_lines(
    text: str,
    font: QFont,
    path: TextPath,
    horizontal_scale: float = 1,
) -> tuple[str, ...]:
    metrics = QFontMetricsF(font)
    path_length = path.approximate_length()
    if metrics.horizontalAdvance(text) * horizontal_scale <= path_length + 0.5:
        return (text,)
    words = text.split()
    if len(words) < 2:
        return (text,)
    candidates = tuple(
        (" ".join(words[:index]), " ".join(words[index:]))
        for index in range(1, len(words))
    )
    first, second = min(
        candidates,
        key=lambda lines: (
            max(metrics.horizontalAdvance(line) for line in lines),
            abs(metrics.horizontalAdvance(lines[0]) - metrics.horizontalAdvance(lines[1])),
        ),
    )
    if (
        max(metrics.horizontalAdvance(first), metrics.horizontalAdvance(second))
        * horizontal_scale
        > path_length + 0.5
    ):
        return (text,)
    return first, second


def _shaped_glyphs(text: str, font: QFont) -> tuple[tuple[QGlyphRun, float], ...]:
    layout = QTextLayout(text, font)
    layout.beginLayout()
    line = layout.createLine()
    line.setLineWidth(1_000_000)
    layout.endLayout()
    values = []
    for run in line.glyphRuns():
        raw_font = run.rawFont()
        glyph_indexes = run.glyphIndexes()
        positions = run.positions()
        advances = raw_font.advancesForGlyphIndexes(glyph_indexes)
        for glyph_index, position, advance in zip(
            glyph_indexes, positions, advances, strict=True
        ):
            glyph = QGlyphRun()
            glyph.setRawFont(raw_font)
            glyph.setGlyphIndexes((glyph_index,))
            glyph.setPositions((QPointF(0, 0),))
            width = max(0.01, hypot(advance.x(), advance.y()))
            values.append((position.x(), glyph, width))
    values.sort(key=lambda value: value[0])
    return tuple((glyph, width) for _, glyph, width in values)


def _arc_samples(path: TextPath, segments: int = 192) -> tuple[tuple[float, float], ...]:
    result = [(0.0, 0.0)]
    previous = path.start
    distance = 0.0
    for index in range(1, segments + 1):
        position = index / segments
        point = path.point_at(position)
        distance += hypot(point.x - previous.x, point.y - previous.y)
        result.append((distance, position))
        previous = point
    return tuple(result)


def _draw_arc_glyphs(
    painter: QPainter,
    path: TextPath,
    glyphs: tuple[tuple[QGlyphRun, float], ...],
    samples: tuple[tuple[float, float], ...],
    offset: float,
    normal_offset: float,
    draw_offset_x: float,
    draw_offset_y: float,
    tracking: float = 0,
    horizontal_scale: float = 1,
    mirror_x: bool = False,
    mirror_y: bool = False,
) -> None:
    cursor = offset
    total_length = samples[-1][0]
    for glyph, advance in glyphs:
        distance = min(total_length, cursor + advance / 2)
        if path.reverse:
            distance = total_length - distance
        position = _position_at_distance(samples, distance)
        point = path.point_at(position)
        tangent = path.tangent_at(position)
        angle = degrees(atan2(tangent.y, tangent.x))
        if isinstance(path, CircularTextPath):
            angle = _bottom_inward_text_angle(path, position, angle)
        tangent_length = max(0.01, hypot(tangent.x, tangent.y))
        normal_x = -tangent.y / tangent_length
        normal_y = tangent.x / tangent_length
        painter.save()
        painter.translate(
            point.x + normal_x * normal_offset,
            point.y + normal_y * normal_offset,
        )
        painter.rotate(angle)
        painter.scale(
            (-1 if mirror_x else 1) * horizontal_scale,
            -1 if mirror_y else 1,
        )
        painter.drawGlyphRun(
            QPointF(
                (-advance / 2 + draw_offset_x) / horizontal_scale,
                draw_offset_y,
            ),
            glyph,
        )
        painter.restore()
        cursor += advance + tracking


def _bottom_inward_text_angle(
    path: CircularTextPath,
    position: float,
    angle: float,
) -> float:
    point = path.point_at(position)
    inward_x = path.center.x - point.x
    inward_y = path.center.y - point.y
    angle_radians = radians(angle)
    glyph_bottom_x = -sin(angle_radians)
    glyph_bottom_y = cos(angle_radians)
    if glyph_bottom_x * inward_x + glyph_bottom_y * inward_y < 0:
        angle += 180
    return (angle + 180) % 360 - 180


def _position_at_distance(
    samples: tuple[tuple[float, float], ...], distance: float
) -> float:
    for index in range(1, len(samples)):
        previous_distance, previous_position = samples[index - 1]
        current_distance, current_position = samples[index]
        if distance <= current_distance:
            span = current_distance - previous_distance
            ratio = 0 if span <= 0 else (distance - previous_distance) / span
            return previous_position + (current_position - previous_position) * ratio
    return 1.0


def _estimate_foreground_color(
    document: ImageDocument,
    region: TextRegion,
) -> tuple[int, int, int]:
    channels = 4 if document.mode == "RGBA" else 3
    pixels = np.frombuffer(document.pixels, dtype=np.uint8).reshape(
        document.asset.height, document.asset.width, channels
    )[:, :, :3]
    if region.observations:
        mapped_foreground = _mapped_polygon_foreground_color(pixels, region)
        if mapped_foreground is not None:
            return mapped_foreground
    colored_label_foreground = _vertical_colored_label_foreground(
        pixels,
        region,
    )
    if colored_label_foreground is not None:
        return colored_label_foreground
    xs = [point.x for point in region.polygon]
    ys = [point.y for point in region.polygon]
    x0 = max(0, min(document.asset.width - 1, int(min(xs))))
    x1 = max(x0 + 1, min(document.asset.width, int(max(xs)) + 1))
    y0 = max(0, min(document.asset.height - 1, int(min(ys))))
    y1 = max(y0 + 1, min(document.asset.height, int(max(ys)) + 1))
    patch = pixels[y0:y1, x0:x1]
    samples = patch.reshape(-1, 3)
    if not len(samples):
        return (24, 32, 51)
    luminance = samples @ np.array((0.2126, 0.7152, 0.0722))
    low = float(np.percentile(luminance, 7.5))
    high = float(np.percentile(luminance, 92.5))
    dark = np.median(samples[luminance <= low], axis=0)
    bright = np.median(samples[luminance >= high], axis=0)
    edge = max(1, min(patch.shape[:2]) // 8)
    border = np.concatenate(
        (
            patch[:edge].reshape(-1, 3),
            patch[-edge:].reshape(-1, 3),
            patch[:, :edge].reshape(-1, 3),
            patch[:, -edge:].reshape(-1, 3),
        )
    )
    background = np.median(border, axis=0)
    dark_distance = float(np.linalg.norm(dark - background))
    bright_distance = float(np.linalg.norm(bright - background))
    color = dark if dark_distance >= bright_distance else bright
    if max(dark_distance, bright_distance) < 32:
        black = np.zeros(3)
        white = np.full(3, 255)
        color = (
            black
            if _contrast_ratio(black, background) >= _contrast_ratio(white, background)
            else white
        )
    return tuple(int(value) for value in color)  # type: ignore[return-value]


def _mapped_polygon_foreground_color(
    pixels: np.ndarray,
    region: TextRegion,
) -> tuple[int, int, int] | None:
    height, width = pixels.shape[:2]
    polygon = np.asarray(
        tuple((round(point.x), round(point.y)) for point in region.polygon),
        dtype=np.int32,
    )
    polygon[:, 0] = np.clip(polygon[:, 0], 0, width - 1)
    polygon[:, 1] = np.clip(polygon[:, 1], 0, height - 1)
    geometry = np.zeros((height, width), dtype=np.uint8)
    cv2.fillPoly(geometry, (polygon,), 1)
    inside = geometry > 0
    if np.count_nonzero(inside) < 4:
        return None
    dilation = cv2.dilate(geometry, np.ones((5, 5), dtype=np.uint8))
    outside = (dilation > 0) & ~inside
    inside_pixels = pixels[inside].astype(np.float32)
    background_pixels = pixels[outside].astype(np.float32)
    background = np.median(
        background_pixels if len(background_pixels) else inside_pixels,
        axis=0,
    )
    distances = np.linalg.norm(inside_pixels - background, axis=1)
    if not len(distances):
        return None
    threshold = max(32.0, float(np.percentile(distances, 88)))
    foreground_pixels = inside_pixels[distances >= threshold]
    if not len(foreground_pixels):
        return None
    foreground = np.median(foreground_pixels, axis=0)
    if float(np.linalg.norm(foreground - background)) < 32:
        return None
    return tuple(int(round(value)) for value in foreground)  # type: ignore[return-value]


def _vertical_colored_label_foreground(
    pixels: np.ndarray,
    region: TextRegion,
) -> tuple[int, int, int] | None:
    palette = _vertical_colored_label_palette(pixels, region)
    return None if palette is None else palette[0]


def _vertical_colored_label_background(
    document: ImageDocument,
    region: TextRegion,
) -> tuple[int, int, int] | None:
    channels = 4 if document.mode == "RGBA" else 3
    pixels = np.frombuffer(document.pixels, dtype=np.uint8).reshape(
        document.asset.height,
        document.asset.width,
        channels,
    )[:, :, :3]
    palette = _vertical_colored_label_palette(pixels, region)
    return None if palette is None else palette[1]


def _vertical_colored_label_palette(
    pixels: np.ndarray,
    region: TextRegion,
) -> tuple[tuple[int, int, int], tuple[int, int, int]] | None:
    xs = np.asarray([point.x for point in region.polygon], dtype=float)
    ys = np.asarray([point.y for point in region.polygon], dtype=float)
    if np.ptp(ys) < np.ptp(xs) * 1.8:
        return None
    height, width = pixels.shape[:2]
    polygon = np.asarray(
        [(round(point.x), round(point.y)) for point in region.polygon],
        dtype=np.int32,
    )
    polygon[:, 0] = np.clip(polygon[:, 0], 0, width - 1)
    polygon[:, 1] = np.clip(polygon[:, 1], 0, height - 1)
    geometry = np.zeros((height, width), dtype=np.uint8)
    cv2.fillPoly(geometry, (polygon,), 1)
    polygon_area = int(np.count_nonzero(geometry))
    if not polygon_area:
        return None
    chroma = pixels.max(axis=2).astype(np.int16) - pixels.min(axis=2).astype(
        np.int16
    )
    colored = (geometry > 0) & (chroma > 45)
    colored_area = int(np.count_nonzero(colored))
    # A label background fills most of the OCR polygon.  Saturated glyphs on
    # a neutral background can also form one connected component, but their
    # coverage is much lower and must not be painted back as a solid block.
    if colored_area / polygon_area < 0.55:
        return None
    component_count, labels, stats, _ = cv2.connectedComponentsWithStats(
        colored.astype(np.uint8),
        8,
    )
    if component_count <= 1:
        return None
    largest_id = int(np.argmax(stats[1:, cv2.CC_STAT_AREA])) + 1
    background_mask = labels == largest_id
    if np.count_nonzero(background_mask) / colored_area < 0.75:
        return None
    coordinates = np.column_stack(np.where(background_mask))[:, ::-1].astype(
        np.int32
    )
    support = np.zeros((height, width), dtype=np.uint8)
    cv2.fillConvexPoly(
        support,
        cv2.convexHull(coordinates),
        1,
    )
    support_mask = (geometry > 0) & (support > 0)
    background = np.median(
        pixels[background_mask].astype(np.float32),
        axis=0,
    )
    luminance = pixels @ np.asarray(
        (0.2126, 0.7152, 0.0722),
        dtype=np.float32,
    )
    neutral = chroma < 35
    candidates = (
        support_mask & neutral & (luminance >= 180),
        support_mask & neutral & (luminance <= 120),
    )
    ranked: list[tuple[float, np.ndarray]] = []
    for candidate in candidates:
        ratio = float(np.count_nonzero(candidate)) / polygon_area
        if not 0.01 <= ratio <= 0.35:
            continue
        foreground = np.median(
            pixels[candidate].astype(np.float32),
            axis=0,
        )
        contrast = float(np.linalg.norm(foreground - background))
        if contrast >= 65:
            ranked.append((contrast, foreground))
    if not ranked:
        return None
    foreground = max(ranked, key=lambda item: item[0])[1]
    return (
        tuple(int(round(value)) for value in foreground),
        tuple(int(round(value)) for value in background),
    )  # type: ignore[return-value]


def _estimate_font_weight(
    document: ImageDocument,
    region: TextRegion,
) -> int:
    channels = 4 if document.mode == "RGBA" else 3
    pixels = np.frombuffer(document.pixels, dtype=np.uint8).reshape(
        document.asset.height,
        document.asset.width,
        channels,
    )[:, :, :3]
    xs = [point.x for point in region.polygon]
    ys = [point.y for point in region.polygon]
    x0 = max(0, min(document.asset.width - 1, int(min(xs))))
    x1 = max(x0 + 1, min(document.asset.width, int(max(xs)) + 1))
    y0 = max(0, min(document.asset.height - 1, int(min(ys))))
    y1 = max(y0 + 1, min(document.asset.height, int(max(ys)) + 1))
    patch = pixels[y0:y1, x0:x1]
    height, width = patch.shape[:2]
    if height < 18 or width < 12:
        return 400
    edge = max(1, min(height, width) // 8)
    border = np.concatenate(
        (
            patch[:edge].reshape(-1, 3),
            patch[-edge:].reshape(-1, 3),
            patch[:, :edge].reshape(-1, 3),
            patch[:, -edge:].reshape(-1, 3),
        )
    ).astype(np.float32)
    background = np.median(border, axis=0)
    foreground = np.asarray(
        _estimate_foreground_color(document, region),
        dtype=np.float32,
    )
    contrast = float(np.linalg.norm(foreground - background))
    if contrast < 70:
        return 400
    values = patch.astype(np.float32)
    foreground_distance = np.linalg.norm(values - foreground, axis=2)
    background_distance = np.linalg.norm(values - background, axis=2)
    ink = (
        (foreground_distance + 8 < background_distance)
        & (background_distance > max(24, contrast * 0.18))
    ).astype(np.uint8)
    polygon = np.asarray(
        [
            [
                round(point.x - x0),
                round(point.y - y0),
            ]
            for point in region.polygon
        ],
        dtype=np.int32,
    )
    polygon[:, 0] = np.clip(polygon[:, 0], 0, width - 1)
    polygon[:, 1] = np.clip(polygon[:, 1], 0, height - 1)
    polygon_mask = np.zeros((height, width), dtype=np.uint8)
    cv2.fillPoly(polygon_mask, (polygon,), 1)
    ink &= polygon_mask
    ink_pixels = int(np.count_nonzero(ink))
    polygon_pixels = int(np.count_nonzero(polygon_mask))
    if not ink_pixels or not polygon_pixels:
        return 400
    ink_ratio = ink_pixels / polygon_pixels
    if not 0.03 <= ink_ratio <= 0.5:
        return 400
    component_count, _, stats, _ = cv2.connectedComponentsWithStats(ink, 8)
    component_areas = stats[1:, cv2.CC_STAT_AREA]
    visible_characters = sum(not character.isspace() for character in region.text)
    if (
        component_count <= 1
        or (visible_characters >= 2 and component_count <= 2)
        or (
            visible_characters >= 3
            and len(component_areas)
            and int(component_areas.max()) > ink_pixels * 0.85
        )
    ):
        return 400
    distance = cv2.distanceTransform(ink, cv2.DIST_L2, 3)
    thickness_samples = distance[distance > 0]
    if not len(thickness_samples):
        return 400
    common_radius = float(np.percentile(thickness_samples, 90))
    maximum_radius = float(thickness_samples.max())
    relative_thickness = common_radius * 2 / height
    if (
        common_radius >= 1.75
        and maximum_radius >= 4.0
        and (
            (height >= 24 and relative_thickness >= 0.18)
            or (height >= 48 and ink_ratio >= 0.33 and common_radius >= 2.5)
        )
    ):
        return 700
    if (
        common_radius >= 1.45
        and maximum_radius >= 2.35
        and relative_thickness >= 0.09
    ):
        return 600
    return 400


def _contrast_ratio(first: np.ndarray, second: np.ndarray) -> float:
    def luminance(color: np.ndarray) -> float:
        values = color.astype(np.float64) / 255.0
        linear = np.where(
            values <= 0.04045,
            values / 12.92,
            ((values + 0.055) / 1.055) ** 2.4,
        )
        return float(linear @ np.array((0.2126, 0.7152, 0.0722)))

    lighter, darker = sorted((luminance(first), luminance(second)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)
