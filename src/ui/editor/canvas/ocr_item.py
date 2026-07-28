"""OCR 文字区域图形项 — 只读半透明红色四边形。

视觉外观与生产 UI (image_canvas.py _paint_ocr_regions) 一致：
边框 #e5484d 1px cosmetic, 填充 rgba(229,72,77,18)。
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
)
from PySide6.QtWidgets import (
    QGraphicsItem,
    QStyleOptionGraphicsItem,
)

from src.domain.ocr import TextRegion


class OcrRegionItem(QGraphicsItem):
    """对应一个 OCR TextRegion 的只读四边形图形项。"""

    def __init__(self, region: TextRegion) -> None:
        super().__init__()
        self._region = region
        self._hovered = False

        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
        )
        self.setAcceptHoverEvents(True)
        self.setZValue(0.5)
        self.setToolTip(region.text)

    @property
    def region_id(self) -> str:
        return self._region.region_id

    @property
    def text_region(self) -> TextRegion:
        return self._region

    # —— 几何 ——

    def _polygon(self) -> QPolygonF:
        return QPolygonF([
            QPointF(p.x, p.y) for p in self._region.polygon
        ])

    def boundingRect(self) -> QRectF:
        return self._polygon().boundingRect().adjusted(-3, -3, 3, 3)

    def shape(self) -> QPainterPath:
        path = QPainterPath()
        path.addPolygon(self._polygon())
        return path

    # —— 绘制 ——

    def paint(
        self,
        painter: QPainter,
        _option: QStyleOptionGraphicsItem,
        _widget: object | None = None,
    ) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        poly = self._polygon()
        selected = self.isSelected()

        # 填充：选中时稍深
        alpha = 30 if selected else 18
        painter.setBrush(QBrush(QColor(229, 72, 77, alpha)))

        # 边框
        width = 2.0 if selected else 1.0
        pen = QPen(QColor("#e5484d"), width)
        pen.setCosmetic(True)
        painter.setPen(pen)

        painter.drawPolygon(poly)

        # hover 时显示文字标签
        if self._hovered and self._region.text:
            center = poly.boundingRect().center()
            text = self._region.text
            if len(text) > 30:
                text = text[:30] + "…"
            painter.setPen(QPen(QColor("#ffffff")))
            painter.drawText(
                QRectF(center.x() - 100, center.y() - 12, 200, 24),
                Qt.AlignmentFlag.AlignCenter,
                text,
            )

    # —— 交互 ——

    def hoverEnterEvent(self, _event: object) -> None:
        self._hovered = True
        self.update()

    def hoverLeaveEvent(self, _event: object) -> None:
        self._hovered = False
        self.update()
