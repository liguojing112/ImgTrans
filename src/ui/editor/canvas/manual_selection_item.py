"""画布上的手动框选区域：鼠标可拖动移动、拖四角改大小，并随旋转角一起转。"""

from __future__ import annotations

import math
from dataclasses import replace

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPen
from PySide6.QtWidgets import QGraphicsObject

from src.domain.layout import TextBox

_HANDLE = 6.0
_MIN_SIZE = 8.0


def _rotate(x: float, y: float, degrees: float) -> tuple[float, float]:
    angle = math.radians(degrees)
    cos_a, sin_a = math.cos(angle), math.sin(angle)
    return x * cos_a - y * sin_a, x * sin_a + y * cos_a


class ManualSelectionItem(QGraphicsObject):
    """常驻的框选区域：拖动框体移动，拖动四角改宽高（保持在自身旋转方向上）。"""

    box_changed = Signal(object)

    def __init__(self, box: TextBox) -> None:
        super().__init__()
        self._box = box
        self._drag_mode: str | None = None
        self._drag_start_box = box
        self._drag_start_scene = QPointF()
        self.setZValue(10000)
        self.setAcceptHoverEvents(True)
        self._sync_transform()

    @property
    def box(self) -> TextBox:
        return self._box

    def set_box(self, box: TextBox) -> None:
        if box == self._box:
            return
        self.prepareGeometryChange()
        self._box = box
        self._sync_transform()
        self.update()

    def _sync_transform(self) -> None:
        self.setPos(self._box.center_x, self._box.center_y)
        self.setRotation(self._box.rotation_degrees)
        self.setTransformOriginPoint(QPointF(0, 0))

    def _body_rect(self) -> QRectF:
        return QRectF(
            -self._box.width / 2,
            -self._box.height / 2,
            self._box.width,
            self._box.height,
        )

    def _handle_rects(self) -> list[QRectF]:
        body = self._body_rect()
        handle = _HANDLE
        return [
            QRectF(body.left() - handle, body.top() - handle, handle * 2, handle * 2),
            QRectF(body.right() - handle, body.top() - handle, handle * 2, handle * 2),
            QRectF(body.right() - handle, body.bottom() - handle, handle * 2, handle * 2),
            QRectF(body.left() - handle, body.bottom() - handle, handle * 2, handle * 2),
        ]

    def boundingRect(self) -> QRectF:
        pad = _HANDLE * 2
        return self._body_rect().adjusted(-pad, -pad, pad, pad)

    def paint(self, painter: QPainter, _option, _widget=None) -> None:  # noqa: ANN001
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor("#1b6ef3"), 2)
        pen.setCosmetic(True)
        pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.setBrush(QBrush(QColor(45, 156, 255, 45)))
        painter.drawRect(self._body_rect())
        painter.setBrush(QBrush(QColor("#1b6ef3")))
        for rect in self._handle_rects():
            painter.drawRect(rect)
        painter.setBrush(Qt.BrushStyle.NoBrush)

    # —— 鼠标交互 ——

    def mousePressEvent(self, event) -> None:  # noqa: ANN001
        if event.button() is not Qt.MouseButton.LeftButton:
            event.ignore()
            return
        pos = event.pos()
        self._drag_mode = None
        for index, rect in enumerate(self._handle_rects()):
            if rect.contains(pos):
                self._drag_mode = f"resize-{index}"
                break
        if self._drag_mode is None and self._body_rect().contains(pos):
            self._drag_mode = "move"
        if self._drag_mode is None:
            event.ignore()
            return
        self._drag_start_box = self._box
        self._drag_start_scene = event.scenePos()
        event.accept()

    def mouseMoveEvent(self, event) -> None:  # noqa: ANN001
        if self._drag_mode is None:
            event.ignore()
            return
        delta_x = event.scenePos().x() - self._drag_start_scene.x()
        delta_y = event.scenePos().y() - self._drag_start_scene.y()
        start = self._drag_start_box
        if self._drag_mode == "move":
            self._box = replace(
                start,
                center_x=start.center_x + delta_x,
                center_y=start.center_y + delta_y,
            )
        else:
            angle = start.rotation_degrees
            local_x, local_y = _rotate(delta_x, delta_y, -angle)
            index = int(self._drag_mode.split("-")[1])
            sign_x = 1 if index in (1, 2) else -1
            sign_y = 1 if index in (2, 3) else -1
            width = max(_MIN_SIZE, start.width + sign_x * local_x)
            height = max(_MIN_SIZE, start.height + sign_y * local_y)
            offset_x, offset_y = _rotate(
                sign_x * (width - start.width) / 2,
                sign_y * (height - start.height) / 2,
                angle,
            )
            self._box = replace(
                start,
                center_x=start.center_x + offset_x,
                center_y=start.center_y + offset_y,
                width=width,
                height=height,
            )
        self.prepareGeometryChange()
        self._sync_transform()
        self.update()
        event.accept()

    def mouseReleaseEvent(self, event) -> None:  # noqa: ANN001
        if self._drag_mode is None:
            event.ignore()
            return
        self._drag_mode = None
        self.box_changed.emit(self._box)
        event.accept()
