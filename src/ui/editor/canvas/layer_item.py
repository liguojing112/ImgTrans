"""文字图层图形项 — 可交互的 QGraphicsItem。

绘制对应 TextLayer 的矩形框，选中时显示缩放手柄和旋转手柄。
支持选中、拖动移动。缩放/旋转手柄交互为后续预留。
"""

from __future__ import annotations

from math import atan2, cos, degrees, hypot, radians, sin

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
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

_HANDLE_RADIUS = 5.0
_ROTATE_HANDLE_OFFSET = 24.0
_MIN_SIZE = 10.0


class TextLayerItem(QGraphicsItem):
    """对应一个 TextLayer 的可交互图形项。

    绘制填充矩形 + 边框，选中时显示手柄。
    """

    def __init__(self, layer: TextLayer, index: int = 0) -> None:
        super().__init__()
        self._layer = layer
        self._index = index
        self._hovered = False
        self._drag_mode: str | None = None
        self._drag_start_pos: QPointF | None = None
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
        self._layer = layer
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

        # 文字背景
        fill_color = QColor(57, 115, 219, 40) if selected else QColor(57, 115, 219, 20)
        painter.fillRect(body, QBrush(fill_color))

        # 边框
        border_color = QColor(57, 115, 219, 200) if (selected or self._hovered) else QColor(57, 115, 219, 100)
        border_width = 2.0 if selected else 1.0
        pen = QPen(border_color, border_width)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.drawRect(body)

        # 文字标签
        text = self._layer.text or f"[{self._index + 1}]"
        font = QFont("Segoe UI", 11)
        painter.setFont(font)
        painter.setPen(QColor("#e0e0f0"))
        text_rect = QRectF(body.left() + 4, body.top() + 2, body.width() - 8, body.height() - 4)
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, text)

        # 选中态手柄
        if not selected:
            return

        painter.setPen(QPen(QColor("#3973db"), 1.0))
        painter.setBrush(QBrush(QColor("#3973db")))

        corners, rotate_handle = self._handle_rects()
        for corner in corners:
            painter.drawRect(corner)

        # 旋转手柄及连线
        painter.setBrush(QBrush(QColor("#e0e0f0")))
        painter.drawEllipse(rotate_handle)
        painter.setPen(QPen(QColor("#3973db"), 1.0, Qt.PenStyle.DotLine))
        painter.drawLine(QPointF(0, -box.height / 2), QPointF(0, -box.height / 2 - _ROTATE_HANDLE_OFFSET))

    # —— 交互 ——

    def mousePressEvent(self, event: QGraphicsSceneMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start_pos = event.pos()
            self._drag_start_box = self._layer.box
            self._drag_mode = "move"
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QGraphicsSceneMouseEvent) -> None:
        if self._drag_mode == "move" and self._drag_start_pos is not None:
            delta = event.pos() - self._drag_start_pos
            self._drag_start_pos = event.pos()
            box = self._layer.box
            self._layer = self._layer.__class__(
                region_id=self._layer.region_id,
                text=self._layer.text,
                box=box.__class__(
                    center_x=box.center_x + delta.x(),
                    center_y=box.center_y + delta.y(),
                    width=box.width,
                    height=box.height,
                    rotation_degrees=box.rotation_degrees,
                ),
                style=self._layer.style,
                overflow=self._layer.overflow,
                path=self._layer.path,
            )
            self._sync_transform()
        self.update()

    def mouseReleaseEvent(self, event: QGraphicsSceneMouseEvent) -> None:
        if self._drag_mode == "move":
            self._drag_mode = None
            self._drag_start_pos = None
        super().mouseReleaseEvent(event)

    def hoverEnterEvent(self, _event: object) -> None:
        self._hovered = True
        self.update()

    def hoverLeaveEvent(self, _event: object) -> None:
        self._hovered = False
        self.update()
