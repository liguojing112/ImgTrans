"""编辑器场景 — 管理背景图片、OCR 文字区域和文字图层图形项 + 擦除蒙版覆盖层。"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QGraphicsPixmapItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSceneMouseEvent,
)

from src.domain.image import ImageDocument
from src.domain.inpainting import EraseMask
from src.domain.layout import TextBox, TextLayout
from src.domain.composition import WatermarkLayer
from src.domain.ocr import TextRegion

from .image_item import BackgroundImageItem
from .layer_item import TextLayerItem, WatermarkLayerItem
from .ocr_item import OcrRegionItem


class EditorScene(QGraphicsScene):
    """管理图片、OCR 区域、文字图层和擦除蒙版的场景。"""

    layer_selected = Signal(str)
    layer_dropped = Signal(str, object)
    watermark_selected = Signal(str)
    watermark_dropped = Signal(str, object)
    selection_cleared = Signal()
    manual_region_selected = Signal(object)
    area_selected = Signal(str, object)
    edit_mask_changed = Signal(object)

    def __init__(self, readonly: bool = False) -> None:
        super().__init__()
        self.setBackgroundBrush(Qt.GlobalColor.transparent)
        self._background: BackgroundImageItem | None = None
        self._comparison_clip: QGraphicsRectItem | None = None
        self._layer_items: dict[str, TextLayerItem] = {}
        self._ocr_items: dict[str, OcrRegionItem] = {}
        self._regions_visible = True
        self._watermark_items: dict[str, WatermarkLayerItem] = {}
        self._erase_mask_image: QImage | None = None
        self._mask_visible = True
        self._scene_width = 800
        self._scene_height = 600
        self._readonly = readonly
        self._manual_selection_enabled = False
        self._manual_selection_origin = None
        self._manual_selection_item: QGraphicsRectItem | None = None
        self._selection_mode: str | None = None
        self._selection_aspect_ratio: float | None = None
        self._edit_mask = bytearray(self._scene_width * self._scene_height)
        self._edit_mask_image: QImage | None = None
        self._edit_mask_visible = False
        self._mask_brush_mode: str | None = None
        self._mask_brush_size = 24
        self._last_brush_point = None

    @property
    def readonly(self) -> bool:
        return self._readonly

    # —— 图片 ——

    def set_document(self, document: ImageDocument) -> None:
        self._manual_selection_item = None
        self._manual_selection_origin = None
        self._manual_selection_enabled = False
        self._selection_aspect_ratio = None
        self.clear()
        self._background = None
        self._comparison_clip = None
        self._layer_items.clear()
        self._ocr_items.clear()
        self._regions_visible = True
        self._watermark_items.clear()

        asset = document.asset
        self._scene_width = asset.width
        self._scene_height = asset.height
        self._edit_mask = bytearray(asset.width * asset.height)
        self._edit_mask_image = None
        self._edit_mask_visible = False
        self._mask_brush_mode = None

        pixmap = _document_to_pixmap(document)
        self._background = BackgroundImageItem(pixmap)
        self.addItem(self._background)
        self.setSceneRect(0, 0, asset.width, asset.height)

    def set_comparison_document(
        self,
        document: ImageDocument | None,
        position_percent: int = 50,
    ) -> None:
        if self._comparison_clip is not None:
            self.removeItem(self._comparison_clip)
            self._comparison_clip = None
        if document is None:
            return
        if (
            document.asset.width != self._scene_width
            or document.asset.height != self._scene_height
        ):
            raise ValueError("Comparison image dimensions must match the canvas")
        clip = QGraphicsRectItem()
        clip.setFlag(
            QGraphicsRectItem.GraphicsItemFlag.ItemClipsChildrenToShape,
            True,
        )
        clip.setPen(QPen(Qt.PenStyle.NoPen))
        clip.setZValue(0.5)
        QGraphicsPixmapItem(_document_to_pixmap(document), clip)
        self.addItem(clip)
        self._comparison_clip = clip
        self.set_comparison_position(position_percent)

    def set_comparison_position(self, position_percent: int) -> None:
        if self._comparison_clip is None:
            return
        ratio = min(100, max(0, int(position_percent))) / 100
        self._comparison_clip.setRect(
            0,
            0,
            self._scene_width * ratio,
            self._scene_height,
        )

    # —— TextLayer ——

    def set_text_layout(self, layout: TextLayout) -> None:
        new_ids = {layer.region_id for layer in layout.layers}
        old_ids = set(self._layer_items.keys())
        for region_id in old_ids - new_ids:
            item = self._layer_items.pop(region_id)
            self.removeItem(item)
        for index, layer in enumerate(layout.layers):
            if layer.region_id in self._layer_items:
                self._layer_items[layer.region_id].update_layer(layer)
            else:
                item = TextLayerItem(layer, index)
                self._layer_items[layer.region_id] = item
                self.addItem(item)

    def set_watermarks(
        self,
        watermarks: tuple[WatermarkLayer, ...],
    ) -> None:
        new_ids = {item.watermark_id for item in watermarks}
        for watermark_id in set(self._watermark_items) - new_ids:
            item = self._watermark_items.pop(watermark_id)
            self.removeItem(item)
        for index, watermark in enumerate(watermarks):
            item = self._watermark_items.get(watermark.watermark_id)
            if item is None:
                item = WatermarkLayerItem(watermark, index)
                self._watermark_items[watermark.watermark_id] = item
                self.addItem(item)
            else:
                item.update_watermark(watermark)

    def preview_watermark(self, watermark: WatermarkLayer) -> None:
        item = self._watermark_items.get(watermark.watermark_id)
        if item is not None:
            item.update_watermark(watermark)

    # —— OCR Regions ——

    def set_regions(self, regions: tuple[TextRegion, ...]) -> None:
        new_ids = {r.region_id for r in regions}
        old_ids = set(self._ocr_items.keys())
        for region_id in old_ids - new_ids:
            item = self._ocr_items.pop(region_id)
            self.removeItem(item)
        for region in regions:
            if region.region_id not in self._ocr_items:
                item = OcrRegionItem(region)
                self._ocr_items[region.region_id] = item
                self.addItem(item)
            else:
                self._ocr_items[region.region_id].update_region(region)

    def clear_regions(self) -> None:
        for item in self._ocr_items.values():
            self.removeItem(item)
        self._ocr_items.clear()

    def set_regions_visible(self, visible: bool) -> None:
        self._regions_visible = visible
        for item in self._ocr_items.values():
            item.setVisible(visible)
            if not visible:
                item.setSelected(False)

    def highlight_ocr_region(self, region_id: str) -> QRectF | None:
        target = self._ocr_items.get(region_id)
        for current_id, item in self._ocr_items.items():
            selected = current_id == region_id
            item.setSelected(selected)
            item.setVisible(self._regions_visible or selected)
        if target is None:
            return None
        target.update()
        return target.sceneBoundingRect()

    # —— 擦除蒙版 ——

    def set_erase_mask(self, mask: EraseMask | None) -> None:
        if mask is not None:
            self._erase_mask_image = QImage(
                mask.pixels, mask.width, mask.height,
                mask.width, QImage.Format.Format_Alpha8,
            ).copy()
        else:
            self._erase_mask_image = None
        self.update()

    def set_mask_visible(self, visible: bool) -> None:
        self._mask_visible = visible
        self.update()

    # —— 选择 ——

    def select_layer(self, region_id: str) -> None:
        self.clear_selection()
        item = self._layer_items.get(region_id)
        if item is not None:
            item.setSelected(True)

    def select_watermark(self, watermark_id: str) -> None:
        self.clear_selection()
        item = self._watermark_items.get(watermark_id)
        if item is not None:
            item.setSelected(True)

    def clear_selection(self) -> None:
        for item in self._layer_items.values():
            item.setSelected(False)
        for item in self._watermark_items.values():
            item.setSelected(False)
        for item in self._ocr_items.values():
            item.setSelected(False)
            item.setVisible(self._regions_visible)

    @property
    def scene_size(self) -> tuple[int, int]:
        return self._scene_width, self._scene_height

    def set_layers_visible(self, visible: bool) -> None:
        for item in self._layer_items.values():
            item.setVisible(visible)

    def set_manual_selection_enabled(self, enabled: bool) -> None:
        self._manual_selection_enabled = enabled and not self._readonly
        self._selection_mode = "manual_translate" if self._manual_selection_enabled else None
        self._selection_aspect_ratio = None
        if not self._manual_selection_enabled:
            self._clear_manual_selection_item()

    def set_area_selection_mode(
        self,
        mode: str | None,
        aspect_ratio: float | None = None,
    ) -> None:
        self._selection_mode = mode if mode and not self._readonly else None
        self._selection_aspect_ratio = (
            float(aspect_ratio)
            if aspect_ratio is not None and float(aspect_ratio) > 0
            else None
        )
        self._manual_selection_enabled = self._selection_mode is not None
        if not self._manual_selection_enabled:
            self._selection_aspect_ratio = None
            self._clear_manual_selection_item()

    def set_selection_aspect_ratio(self, aspect_ratio: float | None) -> None:
        """Update the active drag ratio without changing the selection mode."""
        if self._selection_mode != "crop" or self._readonly:
            return
        self._selection_aspect_ratio = (
            float(aspect_ratio)
            if aspect_ratio is not None and float(aspect_ratio) > 0
            else None
        )

    def set_mask_brush(
        self,
        mode: str | None,
        size: int = 24,
    ) -> None:
        if mode not in {None, "paint", "erase"}:
            raise ValueError("Mask brush mode must be paint, erase or None")
        self._mask_brush_mode = mode if not self._readonly else None
        self._mask_brush_size = max(1, int(size))
        self._edit_mask_visible = mode is not None or self._edit_mask_visible
        self.update()

    def set_edit_mask_visible(self, visible: bool) -> None:
        self._edit_mask_visible = visible
        self.update()

    def clear_edit_mask(self) -> None:
        self._edit_mask = bytearray(self._scene_width * self._scene_height)
        self._refresh_edit_mask()

    @property
    def edit_mask(self) -> EraseMask:
        return EraseMask(
            self._scene_width,
            self._scene_height,
            bytes(self._edit_mask),
        )

    def add_rect_to_edit_mask(self, box: TextBox) -> None:
        left = max(0, round(box.center_x - box.width / 2))
        top = max(0, round(box.center_y - box.height / 2))
        right = min(self._scene_width, round(box.center_x + box.width / 2))
        bottom = min(self._scene_height, round(box.center_y + box.height / 2))
        for y in range(top, bottom):
            start = y * self._scene_width + left
            self._edit_mask[start : start + right - left] = b"\xff" * (right - left)
        self._refresh_edit_mask()

    # —— QGraphicsScene 重写 ——

    def drawForeground(self, painter: QPainter, rect) -> None:
        """在场景顶层绘制擦除蒙版（半透明紫色覆盖）。"""
        super().drawForeground(painter, rect)
        if self._erase_mask_image is None or not self._mask_visible:
            pass
        else:
            self._draw_tinted_mask(
                painter,
                self._erase_mask_image,
                QColor(139, 92, 246, 105),
            )
        if self._edit_mask_image is not None and self._edit_mask_visible:
            self._draw_tinted_mask(
                painter,
                self._edit_mask_image,
                QColor(45, 156, 255, 125),
            )

    # —— 鼠标事件 ——

    def mousePressEvent(self, event: QGraphicsSceneMouseEvent) -> None:
        if (
            self._manual_selection_enabled
            and event.button() is Qt.MouseButton.LeftButton
        ):
            self._manual_selection_origin = self._clamp_to_scene(event.scenePos())
            self._clear_manual_selection_item()
            self._manual_selection_item = QGraphicsRectItem()
            self._manual_selection_item.setPen(QPen(QColor("#2d9cff"), 2))
            self._manual_selection_item.setBrush(QBrush(QColor(45, 156, 255, 35)))
            self._manual_selection_item.setZValue(10000)
            self.addItem(self._manual_selection_item)
            event.accept()
            return
        if (
            self._mask_brush_mode is not None
            and event.button() is Qt.MouseButton.LeftButton
        ):
            self._last_brush_point = self._clamp_to_scene(event.scenePos())
            self._paint_mask_segment(self._last_brush_point, self._last_brush_point)
            event.accept()
            return
        pos = event.scenePos()
        clicked = None
        clicked_kind = "text"
        for item in self._watermark_items.values():
            if item.contains(item.mapFromScene(pos)):
                clicked = item
                clicked_kind = "watermark"
                break
        for item in self._layer_items.values():
            if clicked is not None:
                break
            if item.contains(item.mapFromScene(pos)):
                clicked = item
                break
        if clicked is None:
            self.clear_selection()
            self.selection_cleared.emit()
        else:
            if clicked_kind == "watermark":
                self.clear_selection()
                clicked.setSelected(True)
                self.watermark_selected.emit(clicked.region_id)
            else:
                self._emit_selection(clicked)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QGraphicsSceneMouseEvent) -> None:
        if (
            self._manual_selection_enabled
            and self._manual_selection_origin is not None
            and event.button() is Qt.MouseButton.LeftButton
        ):
            end = self._clamp_to_scene(event.scenePos())
            rect = self._constrained_selection_rect(
                self._manual_selection_origin,
                end,
            )
            self._manual_selection_origin = None
            self._manual_selection_enabled = False
            self._clear_manual_selection_item()
            if rect.width() >= 4 and rect.height() >= 4:
                box = TextBox(
                    rect.center().x(),
                    rect.center().y(),
                    rect.width(),
                    rect.height(),
                )
                if self._selection_mode == "manual_translate":
                    self.manual_region_selected.emit(box)
                self.area_selected.emit(self._selection_mode or "", box)
            event.accept()
            return
        if (
            self._mask_brush_mode is not None
            and event.button() is Qt.MouseButton.LeftButton
        ):
            self._last_brush_point = None
            event.accept()
            return
        super().mouseReleaseEvent(event)
        for item in self._layer_items.values():
            if item.isSelected():
                self.layer_dropped.emit(item.region_id, item.text_layer.box)
                break
        for item in self._watermark_items.values():
            if item.isSelected():
                self.watermark_dropped.emit(
                    item.region_id,
                    item.watermark_layer,
                )
                break

    def mouseDoubleClickEvent(self, event: QGraphicsSceneMouseEvent) -> None:
        super().mouseDoubleClickEvent(event)
        pos = event.scenePos()
        for item in self._layer_items.values():
            if item.contains(item.mapFromScene(pos)):
                self._emit_selection(item)
                break

    def _emit_selection(self, item: TextLayerItem) -> None:
        self.clear_selection()
        item.setSelected(True)
        self.layer_selected.emit(item.region_id)

    def mouseMoveEvent(self, event: QGraphicsSceneMouseEvent) -> None:
        if (
            self._manual_selection_enabled
            and self._manual_selection_origin is not None
            and self._manual_selection_item is not None
        ):
            end = self._clamp_to_scene(event.scenePos())
            self._manual_selection_item.setRect(
                self._constrained_selection_rect(
                    self._manual_selection_origin,
                    end,
                )
            )
            event.accept()
            return
        if self._mask_brush_mode is not None and self._last_brush_point is not None:
            point = self._clamp_to_scene(event.scenePos())
            self._paint_mask_segment(self._last_brush_point, point)
            self._last_brush_point = point
            event.accept()
            return
        super().mouseMoveEvent(event)

    def _clamp_to_scene(self, point):
        rect = self.sceneRect()
        point.setX(min(max(point.x(), rect.left()), rect.right()))
        point.setY(min(max(point.y(), rect.top()), rect.bottom()))
        return point

    def _constrained_selection_rect(
        self,
        origin: QPointF,
        end: QPointF,
    ) -> QRectF:
        """Return the drag rectangle, honoring the selected crop ratio."""
        raw = QRectF(origin, end).normalized()
        ratio = self._selection_aspect_ratio
        if ratio is None or raw.width() < 1 or raw.height() < 1:
            return raw

        dx = end.x() - origin.x()
        dy = end.y() - origin.y()
        width = raw.width()
        height = raw.height()
        if width / height > ratio:
            height = width / ratio
        else:
            width = height * ratio

        # Keep the constrained corner inside the canvas while preserving the
        # drag direction. This avoids a fixed-ratio box spilling beyond edges.
        bounds = self.sceneRect()
        max_width = (
            origin.x() - bounds.left()
            if dx < 0
            else bounds.right() - origin.x()
        )
        max_height = (
            origin.y() - bounds.top()
            if dy < 0
            else bounds.bottom() - origin.y()
        )
        width = min(width, max_width, max_height * ratio)
        height = width / ratio if ratio else height
        corner = QPointF(
            origin.x() + (-width if dx < 0 else width),
            origin.y() + (-height if dy < 0 else height),
        )
        return QRectF(origin, corner).normalized()

    def _clear_manual_selection_item(self) -> None:
        if self._manual_selection_item is not None:
            self.removeItem(self._manual_selection_item)
            self._manual_selection_item = None

    def _paint_mask_segment(self, start, end) -> None:
        dx = end.x() - start.x()
        dy = end.y() - start.y()
        steps = max(1, int(max(abs(dx), abs(dy))))
        radius = max(1, self._mask_brush_size // 2)
        value = 255 if self._mask_brush_mode == "paint" else 0
        for step in range(steps + 1):
            ratio = step / steps
            center_x = round(start.x() + dx * ratio)
            center_y = round(start.y() + dy * ratio)
            for y in range(max(0, center_y - radius), min(self._scene_height, center_y + radius + 1)):
                span = int(max(0, radius * radius - (y - center_y) ** 2) ** 0.5)
                left = max(0, center_x - span)
                right = min(self._scene_width, center_x + span + 1)
                offset = y * self._scene_width + left
                self._edit_mask[offset : offset + right - left] = bytes([value]) * (right - left)
        self._refresh_edit_mask()

    def _refresh_edit_mask(self) -> None:
        self._edit_mask_image = QImage(
            bytes(self._edit_mask),
            self._scene_width,
            self._scene_height,
            self._scene_width,
            QImage.Format.Format_Alpha8,
        ).copy()
        self.edit_mask_changed.emit(self.edit_mask)
        self.update()

    @staticmethod
    def _draw_tinted_mask(
        painter: QPainter,
        mask: QImage,
        color: QColor,
    ) -> None:
        painter.save()
        tinted = QImage(mask.size(), QImage.Format.Format_ARGB32)
        tinted.fill(color)
        tint_painter = QPainter(tinted)
        tint_painter.setCompositionMode(
            QPainter.CompositionMode.CompositionMode_DestinationIn,
        )
        tint_painter.drawImage(0, 0, mask)
        tint_painter.end()
        painter.drawImage(0, 0, tinted)
        painter.restore()


def _document_to_pixmap(document: ImageDocument) -> QPixmap:
    asset = document.asset
    channels = 4 if document.mode == "RGBA" else 3
    fmt = QImage.Format.Format_RGBA8888 if document.mode == "RGBA" else QImage.Format.Format_RGB888
    bpl = asset.width * channels
    image = QImage(document.pixels, asset.width, asset.height, bpl, fmt)
    return QPixmap.fromImage(image.copy())
