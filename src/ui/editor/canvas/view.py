"""编辑器视图 — QGraphicsView 子类，支持滚轮缩放、中键平移、适应窗口。"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QWheelEvent, QMouseEvent, QPainter
from PySide6.QtWidgets import (
    QGraphicsView,
    QGraphicsScene,
)


class EditorView(QGraphicsView):
    """图片编辑器视图 — 滚轮缩放 / 中键平移 / 适应窗口。"""

    zoom_changed = Signal(float)  # 当前缩放因子
    fit_requested = Signal()

    def __init__(self, scene: QGraphicsScene) -> None:
        super().__init__(scene)
        self.setObjectName("editorCanvas")
        self.setRenderHints(
            QPainter.RenderHint.Antialiasing
            | QPainter.RenderHint.SmoothPixmapTransform
        )
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setTransformationAnchor(
            QGraphicsView.ViewportAnchor.AnchorUnderMouse
        )
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setViewportUpdateMode(
            QGraphicsView.ViewportUpdateMode.SmartViewportUpdate
        )
        self.setFrameShape(QGraphicsView.Shape.NoFrame)

        self._zoom = 1.0
        self._panning = False
        self._pan_start = None
        self._min_zoom = 0.1
        self._max_zoom = 20.0

    @property
    def zoom_factor(self) -> float:
        return self._zoom

    # —— 缩放 ——

    def wheelEvent(self, event: QWheelEvent) -> None:
        delta = event.angleDelta().y()
        factor = 1.0 + (abs(delta) / 1200.0)
        if delta > 0:
            self.apply_zoom(factor)
        else:
            self.apply_zoom(1.0 / factor)

    def apply_zoom(self, factor: float) -> None:
        """应用缩放因子 (new_zoom = current * factor)。"""
        new_zoom = self._zoom * factor
        if new_zoom < self._min_zoom or new_zoom > self._max_zoom:
            factor = self._min_zoom / self._zoom if new_zoom < self._min_zoom else self._max_zoom / self._zoom
            new_zoom = self._min_zoom if new_zoom < self._min_zoom else self._max_zoom
        self._zoom = new_zoom
        self.scale(factor, factor)
        self.zoom_changed.emit(self._zoom)

    # —— 平移（中键拖动） ——

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.MiddleButton:
            self._panning = True
            self._pan_start = event.pos()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._panning and self._pan_start is not None:
            delta = event.pos() - self._pan_start
            self._pan_start = event.pos()
            self.horizontalScrollBar().setValue(
                self.horizontalScrollBar().value() - delta.x()
            )
            self.verticalScrollBar().setValue(
                self.verticalScrollBar().value() - delta.y()
            )
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.MiddleButton and self._panning:
            self._panning = False
            self._pan_start = None
            self.setCursor(Qt.CursorShape.ArrowCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    # —— 适应窗口 ——

    def fit_to_window(self) -> None:
        """缩放场景以完整适应视口。"""
        scene = self.scene()
        if scene is None:
            return
        self.fitInView(scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
        # 重新计算缩放因子
        transform = self.transform()
        self._zoom = transform.m11()
        self.zoom_changed.emit(self._zoom)
