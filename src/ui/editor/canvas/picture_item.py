"""图片图层图形项 — 移动从图片中剥离出来的元素。"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QGraphicsItem,
    QGraphicsObject,
    QGraphicsSceneMouseEvent,
    QStyleOptionGraphicsItem,
)

from src.domain.composition import PictureLayer

_Z = 1.8


class PictureLayerItem(QGraphicsObject):
    """图片图层：显示选中虚框，拖动时移动元素。"""

    moved = Signal(str, float, float)  # layer_id, center_x, center_y

    def __init__(self, layer: PictureLayer) -> None:
        super().__init__()
        self._layer = layer
        self._drag_origin: QPointF | None = None
        self._drag_start = QPointF()
        self._image_cache: QImage | None = None
        self.setFlags(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.setZValue(_Z)
        self._sync()

    @property
    def layer_id(self) -> str:
        return self._layer.layer_id

    @property
    def picture(self) -> PictureLayer:
        return self._layer

    def update_layer(self, layer: PictureLayer) -> None:
        if (layer.width, layer.height) != (self._layer.width, self._layer.height):
            self.prepareGeometryChange()
        if layer.pixels != self._layer.pixels:
            self._image_cache = None
        self._layer = layer
        self._sync()
        self.update()

    def _sync(self) -> None:
        self.setPos(QPointF(self._layer.center_x, self._layer.center_y))
        self.setRotation(self._layer.rotation_degrees)

    # —— QGraphicsItem 接口 ——

    def boundingRect(self) -> QRectF:
        return QRectF(
            -self._layer.width / 2,
            -self._layer.height / 2,
            self._layer.width,
            self._layer.height,
        )

    def shape(self) -> QPainterPath:
        path = QPainterPath()
        path.addRect(self.boundingRect())
        return path

    def paint(
        self,
        painter: QPainter,
        _option: QStyleOptionGraphicsItem,
        _widget: object | None = None,
    ) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        # 图片层始终由本图元绘制（编辑底图不含图片层），拖动时自然跟随、无重影
        image = self._image()
        if image is not None and not image.isNull():
            painter.drawImage(self.boundingRect(), image)
        pen = QPen(QColor("#22c55e"), 1.2)
        pen.setCosmetic(True)
        if self.isSelected():
            pen.setWidthF(2.0)
            pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(self.boundingRect())

    def _image(self) -> QImage | None:
        if self._image_cache is None:
            channels = (
                4
                if len(self._layer.pixels)
                == self._layer.width * self._layer.height * 4
                else 3
            )
            format_ = (
                QImage.Format.Format_RGBA8888
                if channels == 4
                else QImage.Format.Format_RGB888
            )
            image = QImage(
                self._layer.pixels,
                self._layer.width,
                self._layer.height,
                self._layer.width * channels,
                format_,
            )
            self._image_cache = image.copy()
        return self._image_cache

    # —— 拖动移动 ——

    def mousePressEvent(self, event: QGraphicsSceneMouseEvent) -> None:
        if event.button() is Qt.MouseButton.LeftButton:
            self._drag_origin = event.scenePos()
            self._drag_start = self.pos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QGraphicsSceneMouseEvent) -> None:
        if self._drag_origin is not None:
            delta = event.scenePos() - self._drag_origin
            self.setPos(self._drag_start + delta)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QGraphicsSceneMouseEvent) -> None:
        if self._drag_origin is not None:
            self._drag_origin = None
            self.moved.emit(
                self._layer.layer_id, self.pos().x(), self.pos().y()
            )
        super().mouseReleaseEvent(event)
