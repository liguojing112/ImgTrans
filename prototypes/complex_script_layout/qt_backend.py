from __future__ import annotations

from bisect import bisect_right
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QImage,
    QPainter,
    QPen,
    QTextLayout,
    QTextOption,
)
from PySide6.QtWidgets import QApplication

from prototypes.complex_script_layout.contracts import (
    GlyphCluster,
    LayoutLine,
    LayoutRequest,
    LayoutResult,
)
from prototypes.complex_script_layout.line_breaker import grapheme_spans


_APP: QApplication | None = None


class QtLayoutBackend:
    name = "qt-qtextlayout"

    def __init__(self) -> None:
        global _APP
        _APP = QApplication.instance() or QApplication([])
        self._app = _APP
        self._registered_dirs: set[Path] = set()
        self._family_to_file: dict[str, str] = {}

    def layout(self, request: LayoutRequest) -> LayoutResult:
        _layout, result = self._create_layout(request)
        return result

    def render(self, request: LayoutRequest, layer_path: Path, debug_path: Path) -> LayoutResult:
        layout, result = self._create_layout(request)
        layer_path.parent.mkdir(parents=True, exist_ok=True)
        image = QImage(request.width, request.height, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        painter.setPen(QColor("#111111"))
        layout.draw(painter, QPointF(0, 0))
        painter.end()
        if not image.save(str(layer_path)):
            raise RuntimeError(f"Could not save {layer_path}")

        debug = QImage(request.width, request.height, QImage.Format.Format_ARGB32_Premultiplied)
        debug.fill(QColor("white"))
        painter = QPainter(debug)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        painter.setPen(QColor("#111111"))
        layout.draw(painter, QPointF(0, 0))
        painter.setPen(QPen(QColor(220, 30, 45, 180), 1))
        for line in result.lines:
            for index, cluster in enumerate(line.clusters):
                x, y, width, height = cluster.bounds
                painter.drawRect(QRectF(x, y, width, height))
                painter.drawText(QPointF(x, max(10.0, y - 2)), str(index))
        painter.end()
        if not debug.save(str(debug_path)):
            raise RuntimeError(f"Could not save {debug_path}")
        return result

    def _create_layout(self, request: LayoutRequest) -> tuple[QTextLayout, LayoutResult]:
        self._register_fonts(request.font_path.parent)
        primary_family = self._family_for_file(request.font_path.name)
        fallback_family = self._family_for_file("NotoSans-Regular.ttf")
        font = QFont()
        font.setFamilies([family for family in (primary_family, fallback_family) if family])
        font.setPixelSize(round(request.font_size))

        option = QTextOption()
        option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        if request.direction == "rtl":
            option.setTextDirection(Qt.LayoutDirection.RightToLeft)
        elif request.direction == "ltr":
            option.setTextDirection(Qt.LayoutDirection.LeftToRight)
        alignment = {
            "left": Qt.AlignmentFlag.AlignLeft,
            "center": Qt.AlignmentFlag.AlignHCenter,
            "right": Qt.AlignmentFlag.AlignRight,
        }[request.alignment]
        option.setAlignment(alignment)

        layout_text = request.text.replace("\n", "\u2028")
        layout = QTextLayout(layout_text, font)
        layout.setTextOption(option)
        layout.beginLayout()
        y = 0.0
        qlines = []
        while True:
            line = layout.createLine()
            if not line.isValid():
                break
            line.setLineWidth(request.width)
            line.setPosition(QPointF(0, y))
            y += line.height()
            qlines.append(line)
        layout.endLayout()

        cp_boundaries, utf16_boundaries = _utf16_boundaries(request.text)
        lines: list[LayoutLine] = []
        all_bounds: list[tuple[float, float, float, float]] = []
        retrieval = QTextLayout.GlyphRunRetrievalFlag.RetrieveAll
        for line in qlines:
            line_start_utf16 = line.textStart()
            line_end_utf16 = line_start_utf16 + line.textLength()
            line_start = _utf16_to_codepoint(line_start_utf16, cp_boundaries, utf16_boundaries)
            line_end = _utf16_to_codepoint(line_end_utf16, cp_boundaries, utf16_boundaries)
            clusters: list[GlyphCluster] = []
            line_text = request.text[line_start:line_end]
            for span in grapheme_spans(line_text):
                start = line_start + span.start
                end = line_start + span.end
                start_utf16 = utf16_boundaries[start]
                length_utf16 = utf16_boundaries[end] - start_utf16
                for run in line.glyphRuns(start_utf16, length_utf16, retrieval):
                    glyphs = tuple(int(glyph) for glyph in run.glyphIndexes())
                    positions = tuple((point.x(), point.y()) for point in run.positions())
                    raw_font = run.rawFont()
                    font_file = self._family_to_file.get(
                        raw_font.familyName(), request.font_path.name
                    )
                    rects = []
                    for glyph, position in zip(run.glyphIndexes(), run.positions()):
                        rect = raw_font.boundingRect(glyph).translated(position)
                        rects.append((rect.x(), rect.y(), rect.width(), rect.height()))
                    cluster_bounds = _union_bounds(rects)
                    if (
                        clusters
                        and clusters[-1].glyph_ids == glyphs
                        and clusters[-1].positions == positions
                        and clusters[-1].font_file == font_file
                    ):
                        previous = clusters.pop()
                        cluster = GlyphCluster(
                            text_start=previous.text_start,
                            text_end=end,
                            text=request.text[previous.text_start:end],
                            font_file=font_file,
                            glyph_ids=glyphs,
                            positions=positions,
                            bounds=cluster_bounds,
                        )
                    else:
                        cluster = GlyphCluster(
                            text_start=start,
                            text_end=end,
                            text=request.text[start:end],
                            font_file=font_file,
                            glyph_ids=glyphs,
                            positions=positions,
                            bounds=cluster_bounds,
                        )
                    clusters.append(cluster)
                    all_bounds.append(cluster_bounds)
            direction = _line_direction(request, request.text[line_start:line_end])
            lines.append(
                LayoutLine(
                    text_start=line_start,
                    text_end=line_end,
                    direction=direction,
                    position=(line.position().x(), line.position().y()),
                    size=(line.naturalTextWidth(), line.height()),
                    clusters=tuple(clusters),
                )
            )
        warnings = () if y <= request.height else ("layout_exceeds_height",)
        result = LayoutResult(
            backend=self.name,
            request=request,
            lines=tuple(lines),
            ink_bounds=_union_bounds(all_bounds),
            warnings=warnings,
        )
        return layout, result

    def _register_fonts(self, directory: Path) -> None:
        directory = directory.resolve()
        if directory in self._registered_dirs:
            return
        for path in directory.glob("*.ttf"):
            font_id = QFontDatabase.addApplicationFont(str(path))
            if font_id < 0:
                raise RuntimeError(f"Qt could not register {path}")
            for family in QFontDatabase.applicationFontFamilies(font_id):
                self._family_to_file[family] = path.name
        self._registered_dirs.add(directory)

    def _family_for_file(self, filename: str) -> str:
        for family, mapped in self._family_to_file.items():
            if mapped == filename:
                return family
        return ""


def _utf16_boundaries(text: str) -> tuple[tuple[int, ...], tuple[int, ...]]:
    codepoints = [0]
    utf16 = [0]
    units = 0
    for index, char in enumerate(text, start=1):
        units += len(char.encode("utf-16-le")) // 2
        codepoints.append(index)
        utf16.append(units)
    return tuple(codepoints), tuple(utf16)


def _utf16_to_codepoint(
    index: int, codepoint_boundaries: tuple[int, ...], utf16_boundaries: tuple[int, ...]
) -> int:
    position = bisect_right(utf16_boundaries, index) - 1
    return codepoint_boundaries[max(0, position)]


def _line_direction(request: LayoutRequest, text: str) -> str:
    if request.direction in {"ltr", "rtl"}:
        return request.direction
    from bidi.algorithm import get_base_level

    return "rtl" if get_base_level(text) else "ltr"


def _union_bounds(values: object) -> tuple[float, float, float, float]:
    bounds = tuple(value for value in values if value[2] or value[3])
    if not bounds:
        return (0.0, 0.0, 0.0, 0.0)
    left = min(value[0] for value in bounds)
    top = min(value[1] for value in bounds)
    right = max(value[0] + value[2] for value in bounds)
    bottom = max(value[1] + value[3] for value in bounds)
    return (left, top, right - left, bottom - top)
