"""文字图层图形项 — 可交互的 QGraphicsItem。

绘制对应 TextLayer 的矩形框，选中时显示缩放手柄和旋转手柄。
支持选中、拖动移动、四角缩放和旋转。
"""

from __future__ import annotations

from dataclasses import replace
from math import atan2, cos, degrees, radians, sin

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetricsF,
    QImage,
    QPainter,
    QPen,
    QPolygonF,
)
from PySide6.QtWidgets import (
    QGraphicsItem,
    QGraphicsSceneMouseEvent,
    QStyleOptionGraphicsItem,
)

from src.domain.layout import TextLayer
from src.domain.composition import WatermarkLayer
from src.domain.layout import TextBox, TextStyle

_HANDLE_RADIUS = 5.0
_ROTATE_HANDLE_OFFSET = 24.0
_MIN_SIZE = 10.0


class TextLayerItem(QGraphicsItem):
    """对应一个 TextLayer 的可交互图形项。

    绘制轮廓边框，选中时显示手柄。
    """

    box_changed = Signal(object)  # TextBox — 拖动时实时发射

    def __init__(self, layer: TextLayer, index: int = 0, status: str = "translated") -> None:
        super().__init__()
        self._layer = layer
        self._index = index
        self._status = status  # "translated" | "review_required" | "overflow" | "skipped" | "failed"
        self._hovered = False
        self._drag_mode: str | None = None
        self._drag_start_pos: QPointF | None = None
        self._drag_start_scene_pos: QPointF | None = None
        self._drag_start_box = layer.box

        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QGraphicsItem.GraphicsItemFlag.ItemIsFocusable
        )
        self.setAcceptHoverEvents(True)
        self.setZValue(1)
        self._sync_transform()

    # —— 属性 ——

    @property
    def region_id(self) -> str:
        return self._layer.region_id

    @property
    def text_layer(self) -> TextLayer:
        return self._layer

    @property
    def index(self) -> int:
        return self._index

    def update_layer(self, layer: TextLayer) -> None:
        """外部更新图层数据后同步变换和重绘。"""
        if layer.box != self._layer.box:
            self.prepareGeometryChange()
        self._layer = layer
        self.setVisible(layer.visible)
        self._sync_transform()
        self.update()

    # —— 几何 ——

    def _sync_transform(self) -> None:
        box = self._layer.box
        self.setPos(QPointF(box.center_x, box.center_y))
        self.setRotation(box.rotation_degrees)
        self.setTransformOriginPoint(QPointF(0, 0))

    def _handle_rects(self) -> tuple[list[QRectF], QRectF]:
        """返回 (角部手柄列表, 旋转手柄矩形)。"""
        box = self._layer.box
        half_w = box.width / 2
        half_h = box.height / 2
        r = _HANDLE_RADIUS

        corners = [
            QRectF(-half_w - r, -half_h - r, r * 2, r * 2),  # 左上
            QRectF(half_w - r, -half_h - r, r * 2, r * 2),  # 右上
            QRectF(half_w - r, half_h - r, r * 2, r * 2),  # 右下
            QRectF(-half_w - r, half_h - r, r * 2, r * 2),  # 左下
        ]
        rotate = QRectF(
            -r,
            -half_h - _ROTATE_HANDLE_OFFSET - r,
            r * 2,
            r * 2,
        )
        return corners, rotate

    def _handle_at(self, pos: QPointF) -> int | None:
        """返回命中的角部手柄索引 (0-3) 或 None。"""
        corners, rotate = self._handle_rects()
        for i, corner in enumerate(corners):
            if corner.contains(pos):
                return i
        if rotate.contains(pos):
            return 4
        return None

    def _body_rect(self) -> QRectF:
        box = self._layer.box
        return QRectF(-box.width / 2, -box.height / 2, box.width, box.height)

    # —— QGraphicsItem 接口 ——

    def boundingRect(self) -> QRectF:
        box = self._layer.box
        pad = _ROTATE_HANDLE_OFFSET + _HANDLE_RADIUS * 2 + 4
        return QRectF(
            -box.width / 2 - pad,
            -box.height / 2 - pad,
            box.width + pad * 2,
            box.height + pad * 2,
        )

    def shape(self) -> QPainterPath:
        from PySide6.QtGui import QPainterPath

        path = QPainterPath()
        path.addRect(self._body_rect())
        if self.isSelected():
            corners, rotate = self._handle_rects()
            for corner in corners:
                path.addRect(corner)
            path.addEllipse(rotate)
        return path

    def paint(
        self,
        painter: QPainter,
        _option: QStyleOptionGraphicsItem,
        _widget: object | None = None,
    ) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        box = self._layer.box
        body = self._body_rect()
        selected = self.isSelected()

        # 按状态选择颜色
        if self._status == "review_required":
            base_color = QColor("#e5b83c")  # 琥珀色 — 待复核
        elif self._status in ("overflow", "failed"):
            base_color = QColor("#e55353")  # 红色 — 溢出/失败
        elif self._status in ("skipped_language", "skipped_protected"):
            base_color = QColor("#9898b0")  # 灰色 — 跳过
        else:
            base_color = QColor("#3973db")  # 蓝色 — 正常翻译

        # 边框
        border_alpha = 220 if (selected or self._hovered) else 120
        border_color = QColor(base_color.red(), base_color.green(), base_color.blue(), border_alpha)
        border_width = 2.0 if selected else 1.0
        pen = QPen(border_color, border_width)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.drawRect(body)

        # 选中态手柄
        if not selected:
            return

        painter.setPen(QPen(base_color, 1.0))
        painter.setBrush(QBrush(base_color))

        corners, rotate_handle = self._handle_rects()
        for corner in corners:
            painter.drawRect(corner)

        # 旋转手柄及连线
        painter.setBrush(QBrush(QColor("#e0e0f0")))
        painter.drawEllipse(rotate_handle)
        painter.setPen(QPen(QColor("#3973db"), 1.0, Qt.PenStyle.DotLine))
        painter.drawLine(QPointF(0, -box.height / 2), QPointF(0, -box.height / 2 - _ROTATE_HANDLE_OFFSET))

    # —— 状态 ——

    def set_status(self, status: str) -> None:
        self._status = status
        self.update()

    # —— 交互 ——

    def mousePressEvent(self, event: QGraphicsSceneMouseEvent) -> None:
        if (
            event.button() == Qt.MouseButton.LeftButton
            and not self._layer.locked
        ):
            self._drag_start_pos = event.pos()
            self._drag_start_scene_pos = event.scenePos()
            self._drag_start_box = self._layer.box
            handle = self._handle_at(event.pos()) if self.isSelected() else None
            self._drag_mode = (
                "rotate"
                if handle == 4
                else f"resize-{handle}"
                if handle is not None
                else "move"
            )
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QGraphicsSceneMouseEvent) -> None:
        if self._drag_mode is None or self._drag_start_scene_pos is None:
            super().mouseMoveEvent(event)
            return
        start = self._drag_start_box
        if self._drag_mode == "move":
            delta = event.scenePos() - self._drag_start_scene_pos
            candidate = replace(
                start,
                center_x=start.center_x + delta.x(),
                center_y=start.center_y + delta.y(),
            )
        elif self._drag_mode == "rotate":
            vector = event.scenePos() - QPointF(start.center_x, start.center_y)
            candidate = replace(
                start,
                rotation_degrees=degrees(atan2(vector.y(), vector.x())) + 90,
            )
        else:
            handle = int(self._drag_mode.rsplit("-", 1)[1])
            current = _scene_to_local(event.scenePos(), start)
            opposite = (
                QPointF(start.width / 2, start.height / 2),
                QPointF(-start.width / 2, start.height / 2),
                QPointF(-start.width / 2, -start.height / 2),
                QPointF(start.width / 2, -start.height / 2),
            )[handle]
            width = max(_MIN_SIZE, abs(current.x() - opposite.x()))
            height = max(_MIN_SIZE, abs(current.y() - opposite.y()))
            midpoint = QPointF(
                (current.x() + opposite.x()) / 2,
                (current.y() + opposite.y()) / 2,
            )
            center = _local_to_scene(midpoint, start)
            candidate = replace(
                start,
                center_x=center.x(),
                center_y=center.y(),
                width=width,
                height=height,
            )
        candidate = self._bounded_box(candidate)
        self.prepareGeometryChange()
        self._layer = replace(self._layer, box=candidate)
        self._sync_transform()
        self.update()
        self.box_changed.emit(self._layer.box)

    def mouseReleaseEvent(self, event: QGraphicsSceneMouseEvent) -> None:
        if self._drag_mode is not None:
            self._drag_mode = None
            self._drag_start_pos = None
            self._drag_start_scene_pos = None
        super().mouseReleaseEvent(event)

    def _bounded_box(self, box):
        scene = self.scene()
        if scene is None:
            return box
        bounds = scene.sceneRect()
        angle = radians(box.rotation_degrees)
        extent_x = abs(cos(angle)) * box.width / 2 + abs(sin(angle)) * box.height / 2
        extent_y = abs(sin(angle)) * box.width / 2 + abs(cos(angle)) * box.height / 2
        if extent_x * 2 > bounds.width() or extent_y * 2 > bounds.height():
            return replace(
                box,
                center_x=bounds.center().x(),
                center_y=bounds.center().y(),
            )
        return replace(
            box,
            center_x=min(max(box.center_x, bounds.left() + extent_x), bounds.right() - extent_x),
            center_y=min(max(box.center_y, bounds.top() + extent_y), bounds.bottom() - extent_y),
        )

    def hoverEnterEvent(self, _event: object) -> None:
        self._hovered = True
        self.update()

    def hoverLeaveEvent(self, _event: object) -> None:
        self._hovered = False
        self.update()


def _scene_to_local(point: QPointF, box) -> QPointF:
    angle = radians(box.rotation_degrees)
    dx = point.x() - box.center_x
    dy = point.y() - box.center_y
    return QPointF(
        dx * cos(angle) + dy * sin(angle),
        -dx * sin(angle) + dy * cos(angle),
    )


def _local_to_scene(point: QPointF, box) -> QPointF:
    angle = radians(box.rotation_degrees)
    return QPointF(
        box.center_x + point.x() * cos(angle) - point.y() * sin(angle),
        box.center_y + point.x() * sin(angle) + point.y() * cos(angle),
    )


class WatermarkLayerItem(TextLayerItem):
    def __init__(self, watermark: WatermarkLayer, index: int = 0) -> None:
        self._watermark = watermark
        super().__init__(self._as_text_layer(watermark), index, "watermark")
        self.setZValue(2)

    @property
    def watermark_layer(self) -> WatermarkLayer:
        box = self.text_layer.box
        style = self._watermark.style
        if style is not None:
            scale = min(
                box.width / self._watermark.width,
                box.height / self._watermark.height,
            )
            style = replace(
                style,
                font_size=max(4.0, style.font_size * scale),
            )
        return replace(
            self._watermark,
            center_x=box.center_x,
            center_y=box.center_y,
            width=box.width,
            height=box.height,
            rotation_degrees=box.rotation_degrees,
            style=style,
        )

    def update_watermark(self, watermark: WatermarkLayer) -> None:
        self._watermark = watermark
        self.update_layer(self._as_text_layer(watermark))

    def paint(
        self,
        painter: QPainter,
        _option: QStyleOptionGraphicsItem,
        _widget: object | None = None,
    ) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        watermark = self.watermark_layer
        body = self._body_rect()
        painter.save()
        painter.setOpacity(watermark.opacity)
        if watermark.kind == "image":
            channels = 4 if watermark.image_mode == "RGBA" else 3
            image_format = (
                QImage.Format.Format_RGBA8888
                if channels == 4
                else QImage.Format.Format_RGB888
            )
            image = QImage(
                watermark.image_pixels,
                watermark.image_width,
                watermark.image_height,
                watermark.image_width * channels,
                image_format,
            ).copy()
            painter.drawImage(body, image)
        else:
            style = watermark.style
            assert style is not None
            font = QFont(style.font_family)
            font.setPixelSize(max(1, round(style.font_size)))
            font.setWeight(QFont.Weight(style.font_weight))
            font.setStretch(style.font_stretch)
            metrics = QFontMetricsF(font)
            available_width = max(1.0, body.width() - 4)
            available_height = max(1.0, body.height() - 4)
            text_width = metrics.horizontalAdvance(watermark.text)
            text_height = metrics.height()
            if text_width > available_width or text_height > available_height:
                scale = min(
                    available_width / max(1.0, text_width),
                    available_height / max(1.0, text_height),
                )
                font.setPixelSize(
                    max(1, round(font.pixelSize() * scale))
                )
            painter.setFont(font)
            painter.setPen(QPen(QColor(*style.fill_rgb)))
            painter.drawText(
                body,
                Qt.AlignmentFlag.AlignCenter
                | Qt.TextFlag.TextSingleLine,
                watermark.text,
            )
        painter.restore()

        if not self.isSelected():
            return
        painter.setPen(QPen(QColor("#2d9cff"), 2.0))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(body)
        corners, rotate_handle = self._handle_rects()
        painter.setPen(QPen(QColor("#2d9cff"), 1.0))
        painter.setBrush(QBrush(QColor("#2d9cff")))
        for corner in corners:
            painter.drawRect(corner)
        painter.setBrush(QBrush(QColor("#ffffff")))
        painter.drawEllipse(rotate_handle)
        painter.setPen(QPen(QColor("#2d9cff"), 1.0, Qt.PenStyle.DotLine))
        painter.drawLine(
            QPointF(0, -body.height() / 2),
            QPointF(0, -body.height() / 2 - _ROTATE_HANDLE_OFFSET),
        )

    @staticmethod
    def _as_text_layer(watermark: WatermarkLayer) -> TextLayer:
        return TextLayer(
            watermark.watermark_id,
            watermark.text if watermark.kind == "text" else "图片水印",
            TextBox(
                watermark.center_x,
                watermark.center_y,
                watermark.width,
                watermark.height,
                watermark.rotation_degrees,
            ),
            watermark.style or TextStyle("Arial", 12, (255, 255, 255)),
            visible=watermark.visible,
            locked=watermark.locked,
        )
