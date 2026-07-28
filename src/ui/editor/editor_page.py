"""编辑器页面 — 顶部操作栏 + 三栏布局 + 翻译控件 + 导出。

TopBar | [左工具栏 | 中央 QGraphicsView | 右属性面板+翻译控件+导出]
属性修改通过 edit_requested 信号发射给 MainWindow，由 MainWindow 在后台调用
EditComposition 重渲染后通过 model.edit_finished 信号回传 CompositionEditResult。
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from src.domain.layout import TextBox, TextLayer, TextLayout, TextStyle
from src.ui.editor.canvas.scene import EditorScene
from src.ui.editor.canvas.view import EditorView
from src.ui.editor.top_bar import TopBar
from src.ui.editor.translate_controls import TranslateControls
from src.ui.editor.undo_commands import ReplaceLayerUndoCommand
from src.ui.editor.property_panel import PropertyPanel
from src.ui.editor.toolbar import EditorToolBar


class EditorPage(QWidget):
    """图片翻译编辑器页：TopBar | 工具栏 | 画布 | 右侧面板。"""

    import_requested = Signal(object)  # Path
    translate_requested = Signal(str, str)
    export_requested = Signal(object)  # Path
    back_requested = Signal()

    ocr_requested = Signal()
    undo_requested = Signal()
    redo_requested = Signal()
    zoom_in_requested = Signal()
    zoom_out_requested = Signal()
    fit_requested = Signal()
    toggle_original_requested = Signal()
    toggle_layers_requested = Signal()

    # 属性编辑信号 — payload: (region_id, field_kind, value, before_layer)
    edit_requested = Signal(str, str, object, object)

    def __init__(self, undo_stack: QUndoStack) -> None:
        super().__init__()
        self.setProperty("editorStyle", True)

        self._undo_stack = undo_stack

        # TopBar
        self.top_bar = TopBar()

        # 子组件
        self.toolbar = EditorToolBar()
        self.scene = EditorScene()
        self.view = EditorView(self.scene)
        self.property_panel = PropertyPanel()

        # 翻译控件
        self.translate_controls = TranslateControls()

        # 导出按钮
        self.export_button = QPushButton("导出图片")
        self.export_button.setObjectName("applyPropertyButton")
        self.export_button.setEnabled(False)

        # 右侧面板
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)
        right_layout.addWidget(self.translate_controls)
        right_layout.addWidget(self.property_panel, stretch=1)
        right_layout.addWidget(self.export_button)

        # 中央区域
        center_widget = QWidget()
        center_layout = QHBoxLayout(center_widget)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(0)
        center_layout.addWidget(self.toolbar)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.view)
        splitter.addWidget(right_panel)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        splitter.setSizes([600, 280])
        center_layout.addWidget(splitter, stretch=1)

        # 整体布局
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.top_bar)
        layout.addWidget(center_widget, stretch=1)

        self._connect_signals()

    def _connect_signals(self) -> None:
        self.toolbar.import_requested.connect(self._on_import_clicked)
        self.scene.layer_selected.connect(self._on_scene_selection)
        self.scene.selection_cleared.connect(self.property_panel.set_layer)
        self.scene.layer_dropped.connect(self._on_layer_dropped)
        self.property_panel.layer_property_changed.connect(self._on_property_changed)

        self.top_bar.import_requested.connect(self._on_import_clicked)
        self.top_bar.back_requested.connect(self.back_requested.emit)
        self.top_bar.ocr_requested.connect(self.ocr_requested.emit)
        self.top_bar.translate_requested.connect(self._on_topbar_translate)
        self.top_bar.toggle_original_requested.connect(self.toggle_original_requested.emit)
        self.top_bar.toggle_layers_requested.connect(self.toggle_layers_requested.emit)
        self.top_bar.zoom_in_requested.connect(self.zoom_in_requested.emit)
        self.top_bar.zoom_out_requested.connect(self.zoom_out_requested.emit)
        self.top_bar.fit_requested.connect(self.fit_requested.emit)
        self.top_bar.undo_requested.connect(self.undo_requested.emit)
        self.redo_requested = self.top_bar.redo_requested

        self.top_bar.export_requested.connect(self._on_export_clicked)
        self.export_button.clicked.connect(self._on_export_clicked)
        self.view.zoom_changed.connect(self._on_zoom_changed)

    def _on_topbar_translate(self) -> None:
        ocr = self.translate_controls.selected_ocr_language
        target = self.translate_controls.selected_target_language
        self.translate_requested.emit(ocr, target)

    # —— 公开方法 ——

    def set_document(self, document, pixmap=None) -> None:
        self.scene.set_document(document)

    def set_text_layout(self, layout: TextLayout) -> None:
        self.scene.set_text_layout(layout)

    def select_layer(self, layer: TextLayer) -> None:
        self.scene.select_layer(layer.region_id)
        self.property_panel.set_layer(layer)

    def clear_layer_selection(self) -> None:
        self.scene.clear_selection()
        self.property_panel.set_layer(None)

    def set_model(self, model) -> None:
        self._model = model
        model.document_changed.connect(self._on_model_document_changed)
        model.text_layout_changed.connect(self._on_model_layout_changed)
        model.selected_layer_changed.connect(self._on_model_selection_changed)
        model.translation_finished.connect(self._on_model_translation_finished)
        model.edit_finished.connect(self._on_model_edit_finished)
        model.showing_original_changed.connect(self._on_model_showing_original_changed)

    def set_layers_visible(self, visible: bool) -> None:
        self.scene.set_layers_visible(visible)

    # —— 应用编辑结果（由 MainWindow 在后台线程完成后回调）——

    def apply_edit_result(self, edit_result: object) -> None:
        """接收 CompositionEditResult，更新画布和图层。"""
        if hasattr(self, "_model") and self._model is not None:
            self._model.rendered_document = edit_result.document
            self._model.text_layout = edit_result.layout
            self.set_document(edit_result.document)
            self.top_bar.set_can_undo(edit_result.can_undo)
            self.top_bar.set_can_redo(edit_result.can_redo)
            # 刷新属性面板保持选中
            if self._model.selected_layer is not None:
                self.property_panel.set_layer(self._model.selected_layer)

    # —— 内部槽 ——

    def _on_import_clicked(self) -> None:
        value, _ = QFileDialog.getOpenFileName(
            self, "导入图片", "", "图片 (*.jpg *.jpeg *.png *.webp)"
        )
        if value:
            self.import_requested.emit(Path(value))

    def _on_export_clicked(self) -> None:
        value, _ = QFileDialog.getSaveFileName(
            self, "导出图片", "",
            "PNG (*.png);;JPEG (*.jpg);;WebP (*.webp);;TIFF (*.tiff)",
        )
        if value:
            self.export_requested.emit(Path(value))

    def _on_scene_selection(self, region_id: str) -> None:
        if hasattr(self, "_model") and self._model is not None:
            self._model.selected_layer_id = region_id

    def _on_layer_dropped(self, region_id: str, box: TextBox) -> None:
        """拖动画布图层后发射 edit_requested。"""
        if not hasattr(self, "_model") or self._model is None:
            return
        try:
            before = self._model.text_layout.layer_by_id(region_id)
        except KeyError:
            return
        after = replace(before, box=box)
        if after == before:
            return
        self.edit_requested.emit(region_id, "box", after, before)

    def _on_property_changed(self, region_id: str, field: str, value: object) -> None:
        """属性面板变更 → 映射到字段组 → 发射 edit_requested。"""
        if not hasattr(self, "_model") or self._model is None:
            return
        try:
            before = self._model.text_layout.layer_by_id(region_id)
        except KeyError:
            return
        after = self._apply_field_change(before, field, value)
        if after is None or after == before:
            return

        # 分类字段组
        if field == "text":
            kind = "text"
        elif field in ("font_size", "fill_rgb", "font_weight"):
            kind = "style"
        else:
            kind = "box"

        self.edit_requested.emit(region_id, kind, after, before)

    def _on_zoom_changed(self, zoom: float) -> None:
        self.top_bar.set_zoom(int(zoom * 100))
        if hasattr(self, "_model") and self._model is not None:
            self._model.zoom_factor = zoom

    def _on_model_document_changed(self, document) -> None:
        if document is not None:
            self.set_document(document)

    def _on_model_layout_changed(self, layout: TextLayout) -> None:
        self.scene.set_text_layout(layout)
        has_layers = len(layout.layers) > 0
        self.top_bar.set_has_layers(has_layers)
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

    def _on_model_translation_finished(self, result) -> None:
        self.translate_controls.reset_progress()
        self.translate_controls.set_translating(False)
        self.export_button.setEnabled(True)
        self.top_bar.set_translating(False)
        self.top_bar.set_has_result(True)
        self.view.fit_to_window()

    def _on_model_edit_finished(self, edit_result) -> None:
        self.apply_edit_result(edit_result)

    def _on_model_showing_original_changed(self, showing: bool) -> None:
        pass

    # —— 字段变更映射 ——

    def _apply_field_change(
        self, layer: TextLayer, field: str, value: object
    ) -> TextLayer | None:
        box = layer.box; style = layer.style; text = layer.text
        if field in ("center_x", "center_y", "width", "height", "rotation_degrees"):
            box_kwargs = {"center_x": box.center_x, "center_y": box.center_y,
                          "width": box.width, "height": box.height,
                          "rotation_degrees": box.rotation_degrees}
            box_kwargs[field] = float(value)
            box = TextBox(**box_kwargs)
        elif field == "text": text = str(value)
        elif field == "font_size": style = replace(style, font_size=float(value))
        elif field == "fill_rgb": style = replace(style, fill_rgb=tuple(value))
        elif field == "font_weight":
            weight = int(value)
            if weight in (400, 600, 700): style = replace(style, font_weight=weight)
            else: return None
        else: return None
        return replace(layer, text=text, box=box, style=style)
