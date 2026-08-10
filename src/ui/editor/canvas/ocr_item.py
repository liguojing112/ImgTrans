"""OCR 文字区域图形项。

画布只绘制半透明区域和选中边框。区域编号及原文通过右侧结果表和
tooltip 展示，避免编号浮层遮住小字、旋转文字或译文预览。
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

        # 选中项用半透明黄色背景高亮，增加识别度；填充较淡不影响译文可读
        if selected:
            painter.setBrush(QBrush(QColor(250, 204, 21, 70)))
        elif self.is_low_confidence:
            alpha = 30
            painter.setBrush(QBrush(QColor(229, 154, 45, alpha)))
        else:
            alpha = 18
            painter.setBrush(QBrush(QColor(229, 72, 77, alpha)))

        # 边框
        if selected:
            width = 2.5
            pen_color = QColor("#dc2626")
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

        # 不在图片上绘制 region_id 或 OCR 文本。小型、倾斜及圆环区域的
        # 标签会覆盖实际译文；详细信息已经由 tooltip 和右侧 OCR 表提供。

    # —— 交互 ——

    def hoverEnterEvent(self, _event: object) -> None:
        self._hovered = True
        self.update()

    def hoverLeaveEvent(self, _event: object) -> None:
        self._hovered = False
        self.update()
