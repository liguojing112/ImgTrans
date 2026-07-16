from __future__ import annotations

from dataclasses import replace
from math import atan2, cos, degrees, hypot, radians, sin

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QImage,
    QMouseEvent,
    QPaintEvent,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
    QResizeEvent,
    QWheelEvent,
)
from PySide6.QtWidgets import QLabel

from src.domain.image import ImageDocument
from src.domain.inpainting import EraseMask
from src.domain.layout import (
    ArcTextPath,
    PathPoint,
    TextBox,
    TextLayout,
    transform_arc_path,
)
from src.domain.ocr import TextRegion


class ImageCanvas(QLabel):
    layer_selected = Signal(str)
    geometry_edit_requested = Signal(str, object)
    path_edit_requested = Signal(str, object)
    manual_region_selected = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("imageCanvas")
        self.setMinimumSize(320, 240)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._source: QPixmap | None = None
        self._document_size: tuple[int, int] | None = None
        self._regions: tuple[TextRegion, ...] = ()
        self._erase_mask: QImage | None = None
        self._mask_visible = True
        self._text_layout = TextLayout(())
        self._selected_region_id: str | None = None
        self._zoom = 1.0
        self._pan = QPointF()
        self._drag_mode: str | None = None
        self._drag_start_view = QPointF()
        self._drag_start_document = QPointF()
        self._drag_start_pan = QPointF()
        self._drag_original_box: TextBox | None = None
        self._drag_original_path: ArcTextPath | None = None
        self._manual_selection_enabled = False
        self._manual_preview_box: TextBox | None = None

    @property
    def region_count(self) -> int:
        return len(self._regions)

    @property
    def zoom_factor(self) -> float:
        return self._zoom

    @property
    def selected_region_id(self) -> str | None:
        return self._selected_region_id

    @property
    def manual_selection_enabled(self) -> bool:
        return self._manual_selection_enabled

    def set_document(self, document: ImageDocument) -> None:
        image_format = (
            QImage.Format.Format_RGBA8888
            if document.mode == "RGBA"
            else QImage.Format.Format_RGB888
        )
        bytes_per_line = document.asset.width * (4 if document.mode == "RGBA" else 3)
        image = QImage(
            document.pixels,
            document.asset.width,
            document.asset.height,
            bytes_per_line,
            image_format,
        ).copy()
        self._source = QPixmap.fromImage(image)
        super().setPixmap(self._source)
        self._document_size = (document.asset.width, document.asset.height)
        self._regions = ()
        self._erase_mask = None
        self._text_layout = TextLayout(())
        self._selected_region_id = None
        self._manual_selection_enabled = False
        self._manual_preview_box = None
        self.unsetCursor()
        self.update()

    def set_regions(self, regions: tuple[TextRegion, ...]) -> None:
        self._regions = regions
        self.update()

    def set_text_layout(self, text_layout: TextLayout) -> None:
        self._text_layout = text_layout
        if self._selected_region_id is not None:
            try:
                text_layout.layer_by_id(self._selected_region_id)
            except KeyError:
                self._selected_region_id = None
        self.update()

    def select_layer(self, region_id: str) -> None:
        try:
            self._text_layout.layer_by_id(region_id)
        except KeyError:
            return
        self._selected_region_id = region_id
        self.update()

    def set_erase_mask(self, mask: EraseMask | None) -> None:
        self._erase_mask = (
            QImage(
                mask.pixels,
                mask.width,
                mask.height,
                mask.width,
                QImage.Format.Format_Alpha8,
            ).copy()
            if mask is not None
            else None
        )
        self.update()

    def set_mask_visible(self, visible: bool) -> None:
        self._mask_visible = visible
        self.update()

    def set_manual_selection_enabled(self, enabled: bool) -> None:
        self._manual_selection_enabled = enabled and self._source is not None
        self._manual_preview_box = None
        self._drag_mode = None
        self.setCursor(Qt.CursorShape.CrossCursor) if self._manual_selection_enabled else self.unsetCursor()
        self.update()

    def reset_view(self) -> None:
        self._zoom = 1.0
        self._pan = QPointF()
        self.update()

    def document_to_view(self, point: object) -> QPointF:
        rect = self._display_rect()
        if rect is None or self._document_size is None:
            return QPointF()
        width, height = self._document_size
        point_x = point.x() if callable(getattr(point, "x", None)) else getattr(point, "x")
        point_y = point.y() if callable(getattr(point, "y", None)) else getattr(point, "y")
        return QPointF(
            rect.left() + point_x * rect.width() / width,
            rect.top() + point_y * rect.height() / height,
        )

    def view_to_document(self, point: QPointF) -> QPointF:
        rect = self._display_rect()
        if rect is None or self._document_size is None:
            return QPointF()
        width, height = self._document_size
        return QPointF(
            (point.x() - rect.left()) * width / rect.width(),
            (point.y() - rect.top()) * height / rect.height(),
        )

    def clear_document(self) -> None:
        self._source = None
        self._document_size = None
        self._regions = ()
        self._erase_mask = None
        self._text_layout = TextLayout(())
        self._selected_region_id = None
        self._manual_selection_enabled = False
        self._manual_preview_box = None
        self.reset_view()
        self.clear()

    def paintEvent(self, event: QPaintEvent) -> None:
        del event
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#ffffff"))
        target = self._display_rect()
        if self._source is None or target is None or self._document_size is None:
            painter.end()
            return
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawPixmap(target, self._source, QRectF(self._source.rect()))
        if self._erase_mask is not None and self._mask_visible:
            tinted = QImage(self._erase_mask.size(), QImage.Format.Format_ARGB32)
            tinted.fill(QColor(139, 92, 246, 105))
            tint_painter = QPainter(tinted)
            tint_painter.setCompositionMode(
                QPainter.CompositionMode.CompositionMode_DestinationIn
            )
            tint_painter.drawImage(0, 0, self._erase_mask)
            tint_painter.end()
            painter.drawImage(target, tinted)
        self._paint_ocr_regions(painter)
        self._paint_text_layers(painter)
        self._paint_manual_selection(painter)
        painter.end()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self.update()

    def wheelEvent(self, event: QWheelEvent) -> None:
        if self._source is None:
            return
        anchor = event.position()
        document_anchor = self.view_to_document(anchor)
        factor = 1.2 if event.angleDelta().y() > 0 else 1 / 1.2
        self._zoom = max(0.2, min(8.0, self._zoom * factor))
        mapped = self.document_to_view(document_anchor)
        self._pan += anchor - mapped
        self.update()
        event.accept()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() is Qt.MouseButton.MiddleButton:
            self._drag_mode = "pan"
            self._drag_start_view = event.position()
            self._drag_start_pan = QPointF(self._pan)
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        if event.button() is not Qt.MouseButton.LeftButton or self._source is None:
            return
        view_point = event.position()
        document_point = self.view_to_document(view_point)
        if self._manual_selection_enabled:
            self._drag_mode = "manual-select"
            self._drag_start_document = _clamp_point(document_point, self._document_size)
            self._manual_preview_box = None
            event.accept()
            return
        selected = self._selected_layer()
        if selected is not None:
            path_handle = self._path_handle_at(selected.path, view_point)
            if path_handle is not None:
                self._drag_mode = f"path-{path_handle}"
                self._drag_original_path = selected.path
                event.accept()
                return
            if _distance(view_point, self.document_to_view(_rotate_handle(selected.box, self._scale()))) <= 11:
                self._begin_geometry_drag("rotate", view_point, document_point, selected.box)
                return
            if _distance(view_point, self.document_to_view(_box_corners(selected.box)[2])) <= 11:
                self._begin_geometry_drag("resize", view_point, document_point, selected.box)
                return
        hit = next(
            (
                layer
                for layer in reversed(self._text_layout.layers)
                if _box_contains(layer.box, document_point)
            ),
            None,
        )
        if hit is None:
            self._selected_region_id = None
            self.update()
            return
        self._selected_region_id = hit.region_id
        self.layer_selected.emit(hit.region_id)
        self._begin_geometry_drag("move", view_point, document_point, hit.box)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_mode == "pan":
            self._pan = self._drag_start_pan + event.position() - self._drag_start_view
            self.update()
            return
        if self._drag_mode == "manual-select":
            point = _clamp_point(
                self.view_to_document(event.position()), self._document_size
            )
            self._manual_preview_box = _box_between(
                self._drag_start_document, point
            )
            self.update()
            return
        if self._drag_mode in {"path-start", "path-control", "path-end"}:
            selected = self._selected_layer()
            path = self._drag_original_path
            if selected is None or path is None:
                return
            point = _clamp_point(
                self.view_to_document(event.position()), self._document_size
            )
            replacement = PathPoint(point.x(), point.y())
            if self._drag_mode == "path-start":
                candidate = replace(path, start=replacement)
            elif self._drag_mode == "path-control":
                candidate = replace(path, control=replacement)
            else:
                candidate = replace(path, end=replacement)
            self._set_preview_path(candidate)
            return
        if self._drag_mode not in {"move", "resize", "rotate"}:
            return
        selected = self._selected_layer()
        original = self._drag_original_box
        if selected is None or original is None:
            return
        point = self.view_to_document(event.position())
        if self._drag_mode == "move":
            delta = point - self._drag_start_document
            box = replace(
                original,
                center_x=original.center_x + delta.x(),
                center_y=original.center_y + delta.y(),
            )
        elif self._drag_mode == "resize":
            angle = radians(original.rotation_degrees)
            dx = point.x() - original.center_x
            dy = point.y() - original.center_y
            local_x = dx * cos(angle) + dy * sin(angle)
            local_y = -dx * sin(angle) + dy * cos(angle)
            box = replace(
                original,
                width=max(8.0, abs(local_x) * 2),
                height=max(8.0, abs(local_y) * 2),
            )
        else:
            angle = degrees(atan2(point.y() - original.center_y, point.x() - original.center_x))
            rotation = (angle + 90 + 180) % 360 - 180
            box = replace(original, rotation_degrees=rotation)
        self._set_preview_box(box)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() is Qt.MouseButton.MiddleButton and self._drag_mode == "pan":
            self._drag_mode = None
            self.unsetCursor()
            return
        if event.button() is not Qt.MouseButton.LeftButton:
            return
        if self._drag_mode == "manual-select":
            selection = self._manual_preview_box
            self._drag_mode = None
            self._manual_selection_enabled = False
            self._manual_preview_box = None
            self.unsetCursor()
            self.update()
            if selection is not None and selection.width >= 4 and selection.height >= 4:
                self.manual_region_selected.emit(selection)
            return
        if self._drag_mode in {"path-start", "path-control", "path-end"}:
            selected = self._selected_layer()
            if (
                selected is not None
                and selected.path is not None
                and self._drag_original_path is not None
                and selected.path != self._drag_original_path
            ):
                self.path_edit_requested.emit(selected.region_id, selected.path)
            self._drag_mode = None
            self._drag_original_path = None
            return
        if self._drag_mode in {"move", "resize", "rotate"}:
            selected = self._selected_layer()
            if (
                selected is not None
                and self._drag_original_box is not None
                and selected.box != self._drag_original_box
            ):
                self.geometry_edit_requested.emit(selected.region_id, selected.box)
        self._drag_mode = None
        self._drag_original_box = None
        self._drag_original_path = None

    def _display_rect(self) -> QRectF | None:
        if self._document_size is None:
            return None
        document_width, document_height = self._document_size
        if document_width <= 0 or document_height <= 0:
            return None
        fit = min(self.width() / document_width, self.height() / document_height)
        scale = fit * self._zoom
        width = document_width * scale
        height = document_height * scale
        return QRectF(
            (self.width() - width) / 2 + self._pan.x(),
            (self.height() - height) / 2 + self._pan.y(),
            width,
            height,
        )

    def _scale(self) -> float:
        rect = self._display_rect()
        return rect.width() / self._document_size[0] if rect and self._document_size else 1

    def _selected_layer(self):
        if self._selected_region_id is None:
            return None
        try:
            return self._text_layout.layer_by_id(self._selected_region_id)
        except KeyError:
            return None

    def _begin_geometry_drag(
        self,
        mode: str,
        view_point: QPointF,
        document_point: QPointF,
        box: TextBox,
    ) -> None:
        self._drag_mode = mode
        self._drag_start_view = view_point
        self._drag_start_document = document_point
        self._drag_original_box = box
        self.update()

    def _set_preview_box(self, box: TextBox) -> None:
        selected = self._selected_layer()
        if selected is None:
            return
        path = (
            transform_arc_path(selected.path, selected.box, box)
            if selected.path is not None
            else None
        )
        self._text_layout = self._text_layout.replace_layer(
            replace(selected, box=box, path=path)
        )
        self.update()

    def _set_preview_path(self, path: ArcTextPath) -> None:
        selected = self._selected_layer()
        if selected is None:
            return
        self._text_layout = self._text_layout.replace_layer(
            replace(selected, path=path)
        )
        self.update()

    def _path_handle_at(
        self,
        path: ArcTextPath | None,
        view_point: QPointF,
    ) -> str | None:
        if path is None:
            return None
        for name, point in (
            ("start", path.start),
            ("control", path.control),
            ("end", path.end),
        ):
            if _distance(view_point, self.document_to_view(point)) <= 11:
                return name
        return None

    def _paint_ocr_regions(self, painter: QPainter) -> None:
        pen = QPen(QColor("#e5484d"), 1)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(QColor(229, 72, 77, 18))
        for region in self._regions:
            painter.drawPolygon(
                QPolygonF([self.document_to_view(point) for point in region.polygon])
            )

    def _paint_text_layers(self, painter: QPainter) -> None:
        for layer in self._text_layout.layers:
            selected = layer.region_id == self._selected_region_id
            pen = QPen(QColor("#3973db" if selected else "#63a1ff"), 2 if selected else 1)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.setBrush(QColor(57, 115, 219, 24 if selected else 10))
            polygon = QPolygonF(
                [self.document_to_view(point) for point in _box_corners(layer.box)]
            )
            painter.drawPolygon(polygon)
            if layer.path is not None:
                self._paint_text_path(painter, layer.path, selected)
            if selected:
                resize = self.document_to_view(_box_corners(layer.box)[2])
                rotate = self.document_to_view(_rotate_handle(layer.box, self._scale()))
                top = self.document_to_view(_box_corners(layer.box)[0])
                painter.drawLine(top, rotate)
                painter.setBrush(QColor("#ffffff"))
                painter.drawEllipse(resize, 5, 5)
                painter.drawEllipse(rotate, 5, 5)

    def _paint_text_path(
        self,
        painter: QPainter,
        path: ArcTextPath,
        selected: bool,
    ) -> None:
        start = self.document_to_view(path.start)
        control = self.document_to_view(path.control)
        end = self.document_to_view(path.end)
        curve = QPainterPath(start)
        curve.quadTo(control, end)
        pen = QPen(QColor("#20a464" if selected else "#63a1ff"), 2)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(curve)
        if selected:
            guide = QPen(QColor("#20a464"), 1, Qt.PenStyle.DashLine)
            guide.setCosmetic(True)
            painter.setPen(guide)
            painter.drawPolyline(QPolygonF((start, control, end)))
            painter.setBrush(QColor("#ffffff"))
            for point in (start, control, end):
                painter.drawEllipse(point, 5, 5)

    def _paint_manual_selection(self, painter: QPainter) -> None:
        if self._manual_preview_box is None:
            return
        pen = QPen(QColor("#20a464"), 2, Qt.PenStyle.DashLine)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(QColor(32, 164, 100, 35))
        painter.drawPolygon(
            QPolygonF(
                [
                    self.document_to_view(point)
                    for point in _box_corners(self._manual_preview_box)
                ]
            )
        )


def _box_corners(box: TextBox) -> tuple[QPointF, QPointF, QPointF, QPointF]:
    angle = radians(box.rotation_degrees)
    result = []
    for x, y in (
        (-box.width / 2, -box.height / 2),
        (box.width / 2, -box.height / 2),
        (box.width / 2, box.height / 2),
        (-box.width / 2, box.height / 2),
    ):
        result.append(
            QPointF(
                box.center_x + x * cos(angle) - y * sin(angle),
                box.center_y + x * sin(angle) + y * cos(angle),
            )
        )
    return tuple(result)  # type: ignore[return-value]


def _rotate_handle(box: TextBox, scale: float) -> QPointF:
    distance = box.height / 2 + 24 / max(scale, 1e-6)
    angle = radians(box.rotation_degrees)
    return QPointF(
        box.center_x + distance * sin(angle),
        box.center_y - distance * cos(angle),
    )


def _box_contains(box: TextBox, point: QPointF) -> bool:
    angle = radians(box.rotation_degrees)
    dx = point.x() - box.center_x
    dy = point.y() - box.center_y
    local_x = dx * cos(angle) + dy * sin(angle)
    local_y = -dx * sin(angle) + dy * cos(angle)
    return abs(local_x) <= box.width / 2 and abs(local_y) <= box.height / 2


def _distance(first: QPointF, second: QPointF) -> float:
    return hypot(first.x() - second.x(), first.y() - second.y())


def _clamp_point(point: QPointF, size: tuple[int, int] | None) -> QPointF:
    if size is None:
        return QPointF(point)
    return QPointF(
        max(0.0, min(float(size[0]), point.x())),
        max(0.0, min(float(size[1]), point.y())),
    )


def _box_between(first: QPointF, second: QPointF) -> TextBox:
    return TextBox(
        (first.x() + second.x()) / 2,
        (first.y() + second.y()) / 2,
        max(0.01, abs(second.x() - first.x())),
        max(0.01, abs(second.y() - first.y())),
    )
