"""编辑器场景 — 管理背景图片、OCR 文字区域和文字图层图形项。"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QGraphicsScene, QGraphicsSceneMouseEvent

from src.domain.image import ImageDocument
from src.domain.layout import TextLayout
from src.domain.ocr import TextRegion

from .image_item import BackgroundImageItem
from .layer_item import TextLayerItem
from .ocr_item import OcrRegionItem


class EditorScene(QGraphicsScene):
    """管理图片、OCR 区域和文字图层的场景。"""

    layer_selected = Signal(str)
    layer_dropped = Signal(str, object)
    selection_cleared = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setBackgroundBrush(Qt.GlobalColor.transparent)
        self._background: BackgroundImageItem | None = None
        self._layer_items: dict[str, TextLayerItem] = {}
        self._ocr_items: dict[str, OcrRegionItem] = {}
        self._scene_width = 800
        self._scene_height = 600

    # —— 图片 ——

    def set_document(self, document: ImageDocument) -> None:
        self.clear()
        self._background = None
        self._layer_items.clear()
        self._ocr_items.clear()

        asset = document.asset
        self._scene_width = asset.width
        self._scene_height = asset.height

        pixmap = _document_to_pixmap(document)
        self._background = BackgroundImageItem(pixmap)
        self.addItem(self._background)
        self.setSceneRect(0, 0, asset.width, asset.height)

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

    # —— OCR Regions ——

    def set_regions(self, regions: tuple[TextRegion, ...]) -> None:
        """设置 OCR 识别区域。diff 现有 items → 增删。"""
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

    def clear_regions(self) -> None:
        """清除所有 OCR 区域图形项。"""
        for item in self._ocr_items.values():
            self.removeItem(item)
        self._ocr_items.clear()

    # —— 选择 ——

    def select_layer(self, region_id: str) -> None:
        self.clear_selection()
        item = self._layer_items.get(region_id)
        if item is not None:
            item.setSelected(True)

    def clear_selection(self) -> None:
        for item in self._layer_items.values():
            item.setSelected(False)

    @property
    def scene_size(self) -> tuple[int, int]:
        return self._scene_width, self._scene_height

    def set_layers_visible(self, visible: bool) -> None:
        for item in self._layer_items.values():
            item.setVisible(visible)

    # —— 鼠标事件 ——

    def mousePressEvent(self, event: QGraphicsSceneMouseEvent) -> None:
        pos = event.scenePos()
        clicked = None
        for item in self._layer_items.values():
            if item.contains(item.mapFromScene(pos)):
                clicked = item
                break

        if clicked is None:
            self.clear_selection()
            self.selection_cleared.emit()

        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QGraphicsSceneMouseEvent) -> None:
        super().mouseReleaseEvent(event)
        for item in self._layer_items.values():
            if item.isSelected():
                self.layer_dropped.emit(item.region_id, item.text_layer.box)
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


def _document_to_pixmap(document: ImageDocument) -> QPixmap:
    asset = document.asset
    channels = 4 if document.mode == "RGBA" else 3
    fmt = QImage.Format.Format_RGBA8888 if document.mode == "RGBA" else QImage.Format.Format_RGB888
    bpl = asset.width * channels
    image = QImage(document.pixels, asset.width, asset.height, bpl, fmt)
    return QPixmap.fromImage(image.copy())
