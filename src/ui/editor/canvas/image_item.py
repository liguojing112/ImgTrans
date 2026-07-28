"""背景图片图形项 — 只读 QGraphicsPixmapItem。"""

from __future__ import annotations

from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QGraphicsPixmapItem


class BackgroundImageItem(QGraphicsPixmapItem):
    """只读背景图片，置于 Z 值 0，不可选中、不可移动。"""

    def __init__(self, pixmap: QPixmap) -> None:
        super().__init__(pixmap)
        self.setFlag(QGraphicsPixmapItem.GraphicsItemFlag.ItemIsSelectable, False)
        self.setFlag(QGraphicsPixmapItem.GraphicsItemFlag.ItemIsMovable, False)
        self.setZValue(0)
        self.setAcceptHoverEvents(False)
