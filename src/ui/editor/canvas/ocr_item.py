"""OCR 文字区域图形项 — 只读半透明红色四边形。

视觉外观与生产 UI (image_canvas.py _paint_ocr_regions) 一致：
边框 #e5484d 1px cosmetic, 填充 rgba(229,72,77,18)。
选中时增强填充和边框，显示 region_id 标签。
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
)
from PySide6.QtWidgets import (
    QGraphicsItem,
    QStyleOptionGraphicsItem,
)

from src.domain.ocr import TextRegion, TextRegionStatus


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

    def update_region(self, region: TextRegion) -> None:
        """Refresh displayed OCR text/geometry without recreating selection."""
        if region.region_id != self._region.region_id:
            return
        self.prepareGeometryChange()
        self._region = region
        self.setToolTip(region.text)
        self.update()

    @property
    def is_low_confidence(self) -> bool:
        return self._region.status is TextRegionStatus.LOW_CONFIDENCE

    # —— 几何 ——

    def _polygon(self) -> QPolygonF:
        return QPolygonF([
            QPointF(p.x, p.y) for p in self._region.polygon
        ])

    def boundingRect(self) -> QRectF:
        return self._polygon().boundingRect().adjusted(-5, -5, 5, 5)

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

        # 填充
        if selected:
            alpha = 50
        elif self.is_low_confidence:
            alpha = 30
        else:
            alpha = 18
        brush_color = QColor(229, 72, 77, alpha)
        if self.is_low_confidence:
            brush_color = QColor(229, 154, 45, alpha)
        painter.setBrush(QBrush(brush_color))

        # 边框
        if selected:
            width = 2.5
            pen_color = QColor("#ff6b6b")
        elif self.is_low_confidence:
            width = 1.5
            pen_color = QColor("#e59a2d")
        else:
            width = 1.0
            pen_color = QColor("#e5484d")
        pen = QPen(pen_color, width)
        pen.setCosmetic(True)
        painter.setPen(pen)

        painter.drawPolygon(poly)

        # 选中时绘制 region_id 标签
        if selected or self._hovered:
            center = poly.boundingRect().center()
            if selected:
                label = self._region.region_id[-6:] if len(self._region.region_id) > 6 else self._region.region_id
                painter.setPen(QPen(QColor("#ffffff")))
                bg_rect = QRectF(center.x() - 50, poly.boundingRect().top() - 20, 100, 18)
                painter.fillRect(bg_rect, QBrush(QColor(40, 40, 60, 200)))
                painter.drawText(bg_rect, Qt.AlignmentFlag.AlignCenter, label)

            if self._hovered and self._region.text:
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
