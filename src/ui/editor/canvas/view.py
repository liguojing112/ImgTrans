"""编辑器视图 — QGraphicsView 子类，支持滚轮缩放、中键平移、适应窗口、双屏同步。"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QWheelEvent, QMouseEvent, QPainter
from PySide6.QtWidgets import (
    QGraphicsView,
    QGraphicsScene,
)


class EditorView(QGraphicsView):
    """图片编辑器视图 — 滚轮缩放 / 中键平移 / 适应窗口 / 双屏同步。"""

    zoom_changed = Signal(float)  # 当前缩放因子
    fit_requested = Signal()
    transform_synced = Signal(float, float, float)  # zoom, h_scroll, v_scroll

    def __init__(self, scene: QGraphicsScene, readonly: bool = False) -> None:
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
        self._readonly = readonly
        self._sync_source: EditorView | None = None

    @property
    def zoom_factor(self) -> float:
        return self._zoom

    @property
    def readonly(self) -> bool:
        return self._readonly

    def bind_sync(self, other: EditorView) -> None:
        """双向同步缩放和平移。"""
        self._sync_source = other
        other._sync_source = self

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
        self._emit_sync()

    # —— 平移（中键拖动） ——

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.MiddleButton:
            self._panning = True
            self._pan_start = event.pos()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            self._prev_h = self.horizontalScrollBar().value()
            self._prev_v = self.verticalScrollBar().value()
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
            self._emit_sync()
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
        self._emit_sync()

    def fit_zoom(self) -> float:
        scene = self.scene()
        if scene is None or scene.sceneRect().isEmpty():
            return 1.0
        viewport = self.viewport().size()
        rect = scene.sceneRect()
        return max(
            self._min_zoom,
            min(
                self._max_zoom,
                viewport.width() / max(1.0, rect.width()),
                viewport.height() / max(1.0, rect.height()),
            ),
        )

    def set_zoom_absolute(self, zoom: float, emit_sync: bool = True) -> None:
        zoom = max(self._min_zoom, min(self._max_zoom, zoom))
        self.resetTransform()
        self.scale(zoom, zoom)
        self._zoom = zoom
        if self.scene() is not None:
            self.centerOn(self.scene().sceneRect().center())
        self.zoom_changed.emit(self._zoom)
        if emit_sync:
            self._emit_sync()

    # —— 同步 ——

    def sync_transform(self, zoom: float, h_scroll: float, v_scroll: float) -> None:
        """从配对 View 同步相同的缩放和滚动位置。"""
        if self._sync_source is None:
            return
        self._zoom = zoom
        self.resetTransform()
        self.scale(zoom, zoom)
        self.horizontalScrollBar().setValue(round(h_scroll))
        self.verticalScrollBar().setValue(round(v_scroll))

    def _emit_sync(self) -> None:
        """发射当前变换状态供配对 View 同步。"""
        if self._sync_source is not None:
            self.transform_synced.emit(
                self._zoom,
                self.horizontalScrollBar().value(),
                self.verticalScrollBar().value(),
            )
