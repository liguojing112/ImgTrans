from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from bidi.algorithm import (
    apply_mirroring,
    calc_level_runs,
    explicit_embed_and_overrides,
    get_base_level,
    get_embedding_levels,
    get_empty_storage,
    reorder_resolved_levels,
    resolve_implicit_levels,
    resolve_neutral_types,
    resolve_weak_types,
)
import regex
import uharfbuzz as hb

from prototypes.complex_script_layout.contracts import (
    GlyphCluster,
    LayoutLine,
    LayoutRequest,
    LayoutResult,
)
from prototypes.complex_script_layout.line_breaker import greedy_line_spans


@dataclass(frozen=True)
class _VisualRun:
    chars: tuple[str, ...]
    source_indices: tuple[int, ...]
    direction: str


@dataclass(frozen=True)
class _FontRun:
    chars: tuple[str, ...]
    source_indices: tuple[int, ...]
    direction: str
    font_path: Path


class _Font:
    def __init__(self, path: Path, pixel_size: float) -> None:
        self.path = path
        data = path.read_bytes()
        self.face = hb.Face(data)
        self.font = hb.Font(self.face)
        hb.ot_font_set_funcs(self.font)
        scale = round(pixel_size * 64)
        self.font.scale = (scale, scale)

    def supports(self, text: str) -> bool:
        return all(char.isspace() or self.font.get_nominal_glyph(ord(char)) is not None for char in text)


class HarfBuzzLayoutBackend:
    name = "harfbuzz-python-bidi"

    def __init__(self) -> None:
        self._fonts: dict[tuple[Path, float], _Font] = {}

    def layout(self, request: LayoutRequest) -> LayoutResult:
        if not request.font_path.is_file():
            raise FileNotFoundError(request.font_path)
        fallback = request.font_path.with_name("NotoSans-Regular.ttf")
        if not fallback.is_file():
            fallback = request.font_path

        def measure(value: str) -> float:
            clusters, _direction, width, _bounds = self._shape_text(
                value,
                0,
                request,
                request.font_path,
                fallback,
                0,
                0,
            )
            return width if clusters else 0.0

        spans = greedy_line_spans(request.text, request.width, measure, request.language_code)
        primary = self._font(request.font_path, request.font_size)
        extents = primary.font.get_font_extents("ltr")
        ascent = (extents.ascender if extents else request.font_size * 64) / 64
        descent = abs((extents.descender if extents else -request.font_size * 16) / 64)
        line_height = max(request.font_size * 1.2, ascent + descent)
        lines: list[LayoutLine] = []
        all_bounds: list[tuple[float, float, float, float]] = []

        for line_index, span in enumerate(spans):
            line_text = span.extract(request.text)
            baseline = line_index * line_height + ascent
            clusters, direction, width, bounds = self._shape_text(
                line_text,
                span.start,
                request,
                request.font_path,
                fallback,
                0,
                baseline,
            )
            x_offset = _alignment_offset(request.alignment, request.width, width)
            shifted = tuple(_shift_cluster(cluster, x_offset, 0) for cluster in clusters)
            shifted_bounds = _shift_bounds(bounds, x_offset, 0)
            if shifted:
                all_bounds.append(shifted_bounds)
            lines.append(
                LayoutLine(
                    text_start=span.start,
                    text_end=span.end,
                    direction=direction,
                    position=(x_offset, line_index * line_height),
                    size=(width, line_height),
                    clusters=shifted,
                )
            )
        ink_bounds = _union_bounds(all_bounds)
        warnings = () if len(lines) * line_height <= request.height else ("layout_exceeds_height",)
        return LayoutResult(self.name, request, tuple(lines), ink_bounds, warnings)

    def render(self, request: LayoutRequest, layer_path: Path, debug_path: Path) -> LayoutResult:
        import os

        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtCore import QRectF, Qt
        from PySide6.QtGui import QColor, QImage, QPainter, QPen, QRawFont
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance() or QApplication([])
        _ = app
        result = self.layout(request)
        raw_fonts: dict[str, QRawFont] = {}
        for line in result.lines:
            for cluster in line.clusters:
                if cluster.font_file not in raw_fonts:
                    raw_fonts[cluster.font_file] = QRawFont(
                        str(request.font_path.with_name(cluster.font_file)), request.font_size
                    )

        def paint(image: QImage, debug: bool) -> None:
            painter = QPainter(image)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
            painter.setPen(QColor("#111111"))
            painter.setBrush(QColor("#111111"))
            for line in result.lines:
                for index, cluster in enumerate(line.clusters):
                    raw_font = raw_fonts[cluster.font_file]
                    for glyph, (x, y) in zip(cluster.glyph_ids, cluster.positions):
                        painter.drawPath(raw_font.pathForGlyph(glyph).translated(x, y))
                    if debug:
                        painter.setBrush(Qt.BrushStyle.NoBrush)
                        painter.setPen(QPen(QColor(30, 90, 220, 180), 1))
                        bx, by, width, height = cluster.bounds
                        painter.drawRect(QRectF(bx, by, width, height))
                        painter.drawText(bx, max(10.0, by - 2), str(index))
                        painter.setPen(QColor("#111111"))
                        painter.setBrush(QColor("#111111"))
            painter.end()

        layer_path.parent.mkdir(parents=True, exist_ok=True)
        layer = QImage(request.width, request.height, QImage.Format.Format_ARGB32_Premultiplied)
        layer.fill(Qt.GlobalColor.transparent)
        paint(layer, False)
        if not layer.save(str(layer_path)):
            raise RuntimeError(f"Could not save {layer_path}")
        debug_image = QImage(
            request.width, request.height, QImage.Format.Format_ARGB32_Premultiplied
        )
        debug_image.fill(QColor("white"))
        paint(debug_image, True)
        if not debug_image.save(str(debug_path)):
            raise RuntimeError(f"Could not save {debug_path}")
        return result

    def _shape_text(
        self,
        text: str,
        source_offset: int,
        request: LayoutRequest,
        primary_path: Path,
        fallback_path: Path,
        origin_x: float,
        baseline: float,
    ) -> tuple[tuple[GlyphCluster, ...], str, float, tuple[float, float, float, float]]:
        if not text:
            direction = _base_direction(text, request.direction)
            return (), direction, 0.0, (origin_x, baseline, 0.0, 0.0)
        visual_runs, direction = _bidi_visual_runs(text, request.direction, source_offset)
        font_runs: list[_FontRun] = []
        for visual_run in visual_runs:
            split_runs = self._split_fonts(visual_run, primary_path, fallback_path, request.font_size)
            font_runs.extend(reversed(split_runs) if visual_run.direction == "rtl" else split_runs)

        cursor = origin_x
        clusters: list[GlyphCluster] = []
        bounds: list[tuple[float, float, float, float]] = []
        for run in font_runs:
            shaped, advance = self._shape_font_run(run, request.language_code, request.font_size, cursor, baseline)
            clusters.extend(shaped)
            bounds.extend(cluster.bounds for cluster in shaped if cluster.bounds[2] or cluster.bounds[3])
            cursor += advance
        return tuple(clusters), direction, cursor - origin_x, _union_bounds(bounds)

    def _split_fonts(
        self,
        run: _VisualRun,
        primary_path: Path,
        fallback_path: Path,
        pixel_size: float,
    ) -> tuple[_FontRun, ...]:
        logical_text = "".join(run.chars)
        primary = self._font(primary_path, pixel_size)
        pieces: list[tuple[Path, tuple[str, ...], tuple[int, ...]]] = []
        for match in regex.finditer(r"\X", logical_text):
            chars = tuple(logical_text[match.start() : match.end()])
            indices = run.source_indices[match.start() : match.end()]
            chosen = primary_path if primary.supports("".join(chars)) else fallback_path
            if pieces and pieces[-1][0] == chosen:
                old_path, old_chars, old_indices = pieces[-1]
                pieces[-1] = (old_path, old_chars + chars, old_indices + indices)
            else:
                pieces.append((chosen, chars, indices))
        return tuple(
            _FontRun(chars, indices, run.direction, path)
            for path, chars, indices in pieces
        )

    def _shape_font_run(
        self,
        run: _FontRun,
        language_code: str,
        pixel_size: float,
        origin_x: float,
        baseline: float,
    ) -> tuple[tuple[GlyphCluster, ...], float]:
        resource = self._font(run.font_path, pixel_size)
        buffer = hb.Buffer()
        buffer.add_codepoints([ord(char) for char in run.chars])
        buffer.guess_segment_properties()
        buffer.direction = run.direction
        buffer.language = language_code
        buffer.cluster_level = hb.BufferClusterLevel.MONOTONE_GRAPHEMES
        hb.shape(resource.font, buffer)
        infos = buffer.glyph_infos
        positions = buffer.glyph_positions
        cluster_starts = sorted({info.cluster for info in infos})
        cluster_ends = {
            start: cluster_starts[index + 1] if index + 1 < len(cluster_starts) else len(run.chars)
            for index, start in enumerate(cluster_starts)
        }
        cursor = origin_x
        grouped: list[list[tuple[object, object, float, float]]] = []
        for info, position in zip(infos, positions):
            glyph_x = cursor + position.x_offset / 64
            glyph_y = baseline - position.y_offset / 64
            if not grouped or grouped[-1][0][0].cluster != info.cluster:
                grouped.append([])
            grouped[-1].append((info, position, glyph_x, glyph_y))
            cursor += position.x_advance / 64

        clusters: list[GlyphCluster] = []
        for group in grouped:
            hb_cluster = group[0][0].cluster
            char_end = cluster_ends[hb_cluster]
            source_indices = run.source_indices[hb_cluster:char_end]
            source_start = min(source_indices)
            source_end = max(source_indices) + 1
            glyph_bounds: list[tuple[float, float, float, float]] = []
            for info, _position, glyph_x, glyph_y in group:
                extents = resource.font.get_glyph_extents(info.codepoint)
                if extents:
                    glyph_bounds.append(
                        (
                            glyph_x + extents.x_bearing / 64,
                            glyph_y - extents.y_bearing / 64,
                            extents.width / 64,
                            abs(extents.height / 64),
                        )
                    )
            clusters.append(
                GlyphCluster(
                    text_start=source_start,
                    text_end=source_end,
                    text="".join(run.chars[hb_cluster:char_end]),
                    font_file=run.font_path.name,
                    glyph_ids=tuple(item[0].codepoint for item in group),
                    positions=tuple((item[2], item[3]) for item in group),
                    bounds=_union_bounds(glyph_bounds),
                )
            )
        return tuple(clusters), cursor - origin_x

    def _font(self, path: Path, pixel_size: float) -> _Font:
        key = (path.resolve(), pixel_size)
        if key not in self._fonts:
            self._fonts[key] = _Font(path, pixel_size)
        return self._fonts[key]


def _base_direction(text: str, requested: str) -> str:
    if requested in {"ltr", "rtl"}:
        return requested
    return "rtl" if get_base_level(text) else "ltr"


def _bidi_visual_runs(
    text: str,
    requested_direction: str,
    source_offset: int = 0,
) -> tuple[tuple[_VisualRun, ...], str]:
    direction = _base_direction(text, requested_direction)
    storage = get_empty_storage()
    storage["base_level"] = 1 if direction == "rtl" else 0
    storage["base_dir"] = "R" if direction == "rtl" else "L"
    get_embedding_levels(text, storage)
    for index, char in enumerate(storage["chars"]):
        char["index"] = source_offset + index
    explicit_embed_and_overrides(storage)
    calc_level_runs(storage)
    resolve_weak_types(storage)
    resolve_neutral_types(storage, False)
    resolve_implicit_levels(storage, False)
    reorder_resolved_levels(storage, False)
    apply_mirroring(storage, False)

    groups: list[list[dict[str, object]]] = []
    for char in storage["chars"]:
        parity = int(char["level"]) % 2
        step = -1 if parity else 1
        if (
            not groups
            or int(groups[-1][-1]["level"]) % 2 != parity
            or int(char["index"]) - int(groups[-1][-1]["index"]) != step
        ):
            groups.append([])
        groups[-1].append(char)

    visual_runs: list[_VisualRun] = []
    for group in groups:
        rtl = int(group[0]["level"]) % 2 == 1
        logical = list(reversed(group)) if rtl else group
        visual_runs.append(
            _VisualRun(
                chars=tuple(str(char["ch"]) for char in logical),
                source_indices=tuple(int(char["index"]) for char in logical),
                direction="rtl" if rtl else "ltr",
            )
        )
    return tuple(visual_runs), direction


def _alignment_offset(alignment: str, width: float, content_width: float) -> float:
    if alignment == "right":
        return max(0.0, width - content_width)
    if alignment == "center":
        return max(0.0, (width - content_width) / 2)
    return 0.0


def _shift_bounds(
    bounds: tuple[float, float, float, float], dx: float, dy: float
) -> tuple[float, float, float, float]:
    return (bounds[0] + dx, bounds[1] + dy, bounds[2], bounds[3])


def _shift_cluster(cluster: GlyphCluster, dx: float, dy: float) -> GlyphCluster:
    return GlyphCluster(
        text_start=cluster.text_start,
        text_end=cluster.text_end,
        text=cluster.text,
        font_file=cluster.font_file,
        glyph_ids=cluster.glyph_ids,
        positions=tuple((x + dx, y + dy) for x, y in cluster.positions),
        bounds=_shift_bounds(cluster.bounds, dx, dy),
    )


def _union_bounds(
    values: Iterable[tuple[float, float, float, float]],
) -> tuple[float, float, float, float]:
    bounds = tuple(value for value in values if value[2] or value[3])
    if not bounds:
        return (0.0, 0.0, 0.0, 0.0)
    left = min(value[0] for value in bounds)
    top = min(value[1] for value in bounds)
    right = max(value[0] + value[2] for value in bounds)
    bottom = max(value[1] + value[3] for value in bounds)
    return (left, top, right - left, bottom - top)
