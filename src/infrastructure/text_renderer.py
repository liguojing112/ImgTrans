from __future__ import annotations

from dataclasses import replace
from math import atan2, degrees, hypot

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
)

from src.domain.image import ImageDocument
from src.domain.layout import (
    TextAlignment,
    ArcTextPath,
    TextBox,
    TextLayer,
    TextLayout,
    TextStyle,
    VerticalAlignment,
    fit_font_size,
)
from src.domain.ocr import OcrResult, TextRegion
from src.domain.translation import TranslationResult, TranslationUnit
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
                else _text_box(region)
            )
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
            layers.append(
                self.reflow(
                    TextLayer(
                        region.region_id,
                        text,
                        box,
                        TextStyle(
                            font_family,
                            6,
                            _estimate_foreground_color(source, region),
                            alignment,
                            font_degraded=resolution.degraded if resolution else False,
                            font_fallback_reason=resolution.reason if resolution else None,
                        ),
                    ),
                    text,
                )
            )
        return TextLayout(tuple(layers))

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
        flags = _text_flags(layer.style, text)

        def fits(size: float, stretch: int) -> bool:
            font = QFont(layer.style.font_family)
            font.setPixelSize(max(1, round(size)))
            font.setStretch(stretch)
            metrics = QFontMetricsF(font)
            if layer.path is not None:
                return (
                    metrics.horizontalAdvance(text) <= layer.path.approximate_length() + 0.5
                    and metrics.height() <= layer.box.height + 0.5
                )
            bounds = QFontMetricsF(font).boundingRect(
                QRectF(0, 0, layer.box.width, layer.box.height),
                flags,
                text,
            )
            return (
                bounds.width() <= layer.box.width + 0.5
                and bounds.height() <= layer.box.height + 0.5
            )

        if layer.style.auto_fit:
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
            font = QFont(layer.style.font_family)
            font.setPixelSize(max(1, round(layer.style.font_size)))
            font.setStretch(layer.style.font_stretch)
            if layer.path is not None:
                _render_arc_layer(painter, layer, font)
                continue
            painter.save()
            painter.translate(layer.box.center_x, layer.box.center_y)
            painter.rotate(layer.box.rotation_degrees)
            painter.setFont(font)
            target = QRectF(
                -layer.box.width / 2,
                -layer.box.height / 2,
                layer.box.width,
                layer.box.height,
            )
            flags = _text_flags(layer.style, layer.text)
            if layer.style.shadow_opacity > 0:
                painter.save()
                painter.translate(
                    layer.style.shadow_offset_x,
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
                                target.translated(offset_x, offset_y),
                                flags,
                                layer.text,
                            )
            painter.setPen(QColor(*layer.style.fill_rgb))
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


def _render_arc_layer(painter: QPainter, layer: TextLayer, font: QFont) -> None:
    path = layer.path
    if path is None or not layer.text:
        return
    glyphs = _shaped_glyphs(layer.text, font)
    if not glyphs:
        return
    total_width = sum(advance for _, advance in glyphs)
    path_length = path.approximate_length()
    if layer.style.alignment is TextAlignment.LEFT:
        offset = 0.0
    elif layer.style.alignment is TextAlignment.RIGHT:
        offset = max(0.0, path_length - total_width)
    else:
        offset = max(0.0, (path_length - total_width) / 2)
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
            layer.style.shadow_offset_x,
            layer.style.shadow_offset_y,
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
                        offset_x,
                        offset_y,
                    )
    painter.setPen(QColor(*layer.style.fill_rgb))
    _draw_arc_glyphs(painter, path, glyphs, samples, offset, 0, 0)


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


def _arc_samples(path: ArcTextPath, segments: int = 192) -> tuple[tuple[float, float], ...]:
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
    path: ArcTextPath,
    glyphs: tuple[tuple[QGlyphRun, float], ...],
    samples: tuple[tuple[float, float], ...],
    offset: float,
    draw_offset_x: float,
    draw_offset_y: float,
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
        painter.save()
        painter.translate(point.x, point.y)
        painter.rotate(angle)
        painter.drawGlyphRun(
            QPointF(-advance / 2 + draw_offset_x, draw_offset_y),
            glyph,
        )
        painter.restore()
        cursor += advance


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
