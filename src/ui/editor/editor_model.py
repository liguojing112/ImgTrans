"""编辑器状态中心。

非 MVVM 架构 — 仅作为信号驱动的状态聚合器。
持有当前图片文档、文字图层集合和选中状态。
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from src.domain.image import ImageDocument
from src.domain.layout import TextLayer, TextLayout


class EditorModel(QObject):
    """编辑器核心状态容器，通过信号驱动 view / property_panel 同步。"""

    document_changed = Signal(object)  # ImageDocument | None
    text_layout_changed = Signal(object)  # TextLayout
    selected_layer_changed = Signal(object)  # TextLayer | None

    def __init__(self) -> None:
        super().__init__()
        self._document: ImageDocument | None = None
        self._text_layout = TextLayout(())
        self._selected_layer_id: str | None = None
        self._zoom_factor = 1.0

    # —— document ——

    @property
    def document(self) -> ImageDocument | None:
        return self._document

    @document.setter
    def document(self, value: ImageDocument | None) -> None:
        if value is self._document:
            return
        self._document = value
        self.document_changed.emit(value)

    # —— text_layout ——

    @property
    def text_layout(self) -> TextLayout:
        return self._text_layout

    @text_layout.setter
    def text_layout(self, value: TextLayout) -> None:
        if value is not self._text_layout:
            self._text_layout = value
            self.text_layout_changed.emit(value)
            # 检查当前选中图层是否还存在
            if self._selected_layer_id is not None:
                try:
                    value.layer_by_id(self._selected_layer_id)
                except KeyError:
                    self.selected_layer_id = None

    # —— selected_layer_id ——

    @property
    def selected_layer_id(self) -> str | None:
        return self._selected_layer_id

    @selected_layer_id.setter
    def selected_layer_id(self, region_id: str | None) -> None:
        if region_id == self._selected_layer_id:
            return
        self._selected_layer_id = region_id
        layer = None
        if region_id is not None:
            try:
                layer = self._text_layout.layer_by_id(region_id)
            except KeyError:
                self._selected_layer_id = None
        self.selected_layer_changed.emit(layer)

    @property
    def selected_layer(self) -> TextLayer | None:
        if self._selected_layer_id is None:
            return None
        try:
            return self._text_layout.layer_by_id(self._selected_layer_id)
        except KeyError:
            return None

    # —— zoom ——

    @property
    def zoom_factor(self) -> float:
        return self._zoom_factor

    @zoom_factor.setter
    def zoom_factor(self, value: float) -> None:
        self._zoom_factor = max(0.1, min(20.0, value))

    # —— 图层操作方法（不可变 domain 对象，使用 TextLayout 方法） ——

    def replace_layer(self, before: TextLayer, after: TextLayer) -> None:
        """替换图层并通知。"""
        self.text_layout = self._text_layout.replace_layer(after)
        if self._selected_layer_id == before.region_id:
            self._selected_layer_id = after.region_id
            self.selected_layer_changed.emit(after)

    def add_layer(self, layer: TextLayer) -> None:
        """添加图层并通知。"""
        self.text_layout = self._text_layout.add_layer(
            layer, len(self._text_layout.layers)
        )

    def remove_layer(self, region_id: str) -> None:
        """删除图层并通知。"""
        layout, _, _ = self._text_layout.remove_layer(region_id)
        self.text_layout = layout
