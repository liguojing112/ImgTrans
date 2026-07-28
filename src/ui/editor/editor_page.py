"""编辑器页面 — 三栏布局容器。

左工具栏 | 中央 QGraphicsView | 右属性面板。
连接所有信号/槽，实现双向属性同步。
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QSplitter,
    QWidget,
)

from src.domain.layout import TextBox, TextLayer, TextLayout, TextStyle
from src.ui.editor.canvas.scene import EditorScene
from src.ui.editor.canvas.view import EditorView
from src.ui.editor.undo_commands import ReplaceLayerUndoCommand
from src.ui.editor.property_panel import PropertyPanel
from src.ui.editor.toolbar import EditorToolBar


class EditorPage(QWidget):
    """图片翻译编辑器页：工具栏 | 画布 | 属性面板。"""

    back_requested = Signal()
    import_requested = Signal(object)  # Path
    fit_requested = Signal()
    undo_available_changed = Signal(bool)
    redo_available_changed = Signal(bool)

    def __init__(
        self,
        undo_stack: QUndoStack,
        property_change_callback: object = None,
    ) -> None:
        super().__init__()
        self.setProperty("editorStyle", True)

        self._undo_stack = undo_stack
        self._undo_stack.canUndoChanged.connect(self.undo_available_changed.emit)
        self._undo_stack.canRedoChanged.connect(self.redo_available_changed.emit)

        # 子组件
        self.toolbar = EditorToolBar()
        self.scene = EditorScene()
        self.view = EditorView(self.scene)
        self.property_panel = PropertyPanel()

        # 布局：水平三栏
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        layout.addWidget(self.toolbar)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.view)
        splitter.addWidget(self.property_panel)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        splitter.setSizes([600, 280])
        layout.addWidget(splitter, stretch=1)

        # 信号连接
        self._connect_signals()

    def _connect_signals(self) -> None:
        """连接所有信号/槽，实现双向同步。"""

        # 工具栏 → 外部
        self.toolbar.import_requested.connect(self._on_import_clicked)

        # 场景 → 属性面板（选中同步）
        self.scene.layer_selected.connect(self._on_scene_selection)
        self.scene.selection_cleared.connect(self.property_panel.set_layer)

        # 场景 → 拖动结束
        self.scene.layer_dropped.connect(self._on_layer_dropped)

        # 属性面板 → 场景（属性变更）
        self.property_panel.layer_property_changed.connect(self._on_property_changed)

        # 适应窗口
        self.fit_requested.connect(self.view.fit_to_window)

        # 缩放
        self.view.zoom_changed.connect(self._on_zoom_changed)

    # —— 公开方法 ——

    def set_document(self, document, pixmap) -> None:
        """加载图片到场景。"""
        self.scene.set_document(document)

    def set_text_layout(self, layout: TextLayout) -> None:
        """设置文字图层。"""
        self.scene.set_text_layout(layout)

    def select_layer(self, layer: TextLayer) -> None:
        """外部选中图层 → 同步场景 + 属性面板。"""
        self.scene.select_layer(layer.region_id)
        self.property_panel.set_layer(layer)

    def clear_layer_selection(self) -> None:
        self.scene.clear_selection()
        self.property_panel.set_layer(None)

    def set_zoom(self, factor: float) -> None:
        self.view._zoom = factor

    def zoom_factor(self) -> float:
        return self.view.zoom_factor

    def set_model(self, model) -> None:
        """绑定 EditorModel 以实现完整同步。"""
        self._model = model
        model.document_changed.connect(self._on_model_document_changed)
        model.text_layout_changed.connect(self._on_model_layout_changed)
        model.selected_layer_changed.connect(self._on_model_selection_changed)

    # —— 内部槽 ——

    def _on_import_clicked(self) -> None:
        value, _ = QFileDialog.getOpenFileName(
            self,
            "导入图片",
            "",
            "图片 (*.jpg *.jpeg *.png *.webp)",
        )
        if value:
            self.import_requested.emit(Path(value))

    def _on_scene_selection(self, region_id: str) -> None:
        if hasattr(self, "_model") and self._model is not None:
            self._model.selected_layer_id = region_id
        else:
            self.property_panel.set_layer(None)

    def _on_layer_dropped(self, region_id: str, box: TextBox) -> None:
        if not hasattr(self, "_model") or self._model is None:
            return
        try:
            before = self._model.text_layout.layer_by_id(region_id)
        except KeyError:
            return
        after = replace(before, box=box)
        if after == before:
            return
        cmd = ReplaceLayerUndoCommand(self._model, before, after)
        self._undo_stack.push(cmd)

    def _on_property_changed(self, region_id: str, field: str, value: object) -> None:
        if not hasattr(self, "_model") or self._model is None:
            return
        try:
            before = self._model.text_layout.layer_by_id(region_id)
        except KeyError:
            return
        after = self._apply_field_change(before, field, value)
        if after is None or after == before:
            return
        cmd = ReplaceLayerUndoCommand(self._model, before, after)
        self._undo_stack.push(cmd)

    def _on_zoom_changed(self, zoom: float) -> None:
        if hasattr(self, "_model") and self._model is not None:
            self._model.zoom_factor = zoom

    def _on_model_document_changed(self, document) -> None:
        if document is not None:
            self.set_document(document, None)

    def _on_model_layout_changed(self, layout: TextLayout) -> None:
        self.scene.set_text_layout(layout)
        # 刷新属性面板（保持选中）
        if hasattr(self, "_model") and self._model is not None:
            layer = self._model.selected_layer
            if layer is not None:
                self.property_panel.set_layer(layer)

    def _on_model_selection_changed(self, layer: TextLayer | None) -> None:
        if layer is not None:
            self.scene.select_layer(layer.region_id)
            self.property_panel.set_layer(layer)
        else:
            self.scene.clear_selection()
            self.property_panel.set_layer(None)

    # —— 字段变更映射 ——

    def _apply_field_change(
        self, layer: TextLayer, field: str, value: object
    ) -> TextLayer | None:
        """将字段名/值映射为新的 TextLayer。"""
        box = layer.box
        style = layer.style
        text = layer.text

        if field in ("center_x", "center_y", "width", "height", "rotation_degrees"):
            box_kwargs = {
                "center_x": box.center_x,
                "center_y": box.center_y,
                "width": box.width,
                "height": box.height,
                "rotation_degrees": box.rotation_degrees,
            }
            box_kwargs[field] = float(value)
            box = TextBox(**box_kwargs)
        elif field == "text":
            text = str(value)
        elif field == "font_size":
            style = replace(style, font_size=float(value))
        elif field == "fill_rgb":
            style = replace(style, fill_rgb=tuple(value))
        elif field == "font_weight":
            weight = int(value)
            if weight in (400, 600, 700):
                style = replace(style, font_weight=weight)
            else:
                return None
        else:
            return None

        return replace(layer, text=text, box=box, style=style)
