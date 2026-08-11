"""编辑器页面 — 顶部操作栏 + 左右编辑面板 + 中央画布。

TopBar | [左工具栏 | 文字区域列表 | 中央 QGraphicsView | 翻译与属性面板]
属性修改通过 edit_requested 信号发射给 MainWindow，由 MainWindow 在后台调用
EditComposition 重渲染后通过 model.edit_finished 信号回传 CompositionEditResult。
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSlider,
    QSplitter,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from src.domain.layout import (
    ArcTextPath,
    ArtisticPreset,
    CircularTextPath,
    PathPoint,
    TextBox,
    TextLayer,
    TextLayout,
    TextStyle,
    default_arc_path,
)
from src.ui.editor.canvas.scene import EditorScene
from src.ui.editor.canvas.view import EditorView
from src.ui.editor.widgets.top_bar import TopBar
from src.ui.editor.widgets.translate_controls import TranslateControls
from src.ui.editor.undo_commands import ReplaceLayerUndoCommand
from src.ui.editor.widgets.property_panel import PropertyPanel
from src.ui.editor.widgets.ocr_result_panel import OcrResultPanel
from src.ui.editor.widgets.toolbar import EditorToolBar
from src.ui.editor.widgets.layer_state_panel import LayerStatePanel
from src.ui.editor.widgets.export_settings_panel import ExportSettingsPanel
from src.ui.editor.widgets.tool_dialogs import (
    CropToolDialog,
    EraseToolDialog,
    WatermarkToolDialog,
)
from src.ui.manual_region_panel import ManualRegionPanel
from src.ui.batch_panel import BatchPanel


class EditorPage(QWidget):
    """图片翻译编辑器页：左侧文字列表、中央画布、右侧编辑属性。"""

    import_requested = Signal(object)  # Path
    translate_requested = Signal(str, str)
    export_requested = Signal(object)  # Path
    save_requested = Signal()
    back_requested = Signal()
    feature_requested = Signal(str)
    tool_changed = Signal(str)
    manual_region_requested = Signal(object)
    ai_erase_requested = Signal(object)
    crop_requested = Signal(object)
    image_transform_requested = Signal(str)
    watermark_text_requested = Signal(str, float, bool)
    watermark_image_requested = Signal(object, float, bool)
    layer_state_requested = Signal(str, str, bool)
    watermark_state_requested = Signal(str, str, bool)
    watermark_property_requested = Signal(str, str, object)
    watermark_edit_requested = Signal(object)
    watermark_delete_requested = Signal(str)
    watermark_duplicate_requested = Signal(str)
    layer_move_requested = Signal(str, str, int)

    ocr_requested = Signal()
    undo_requested = Signal()
    redo_requested = Signal()
    zoom_in_requested = Signal()
    zoom_out_requested = Signal()
    fit_requested = Signal()
    toggle_original_requested = Signal()
    split_compare_requested = Signal()
    slider_compare_requested = Signal()
    compare_hold_started = Signal()
    compare_hold_finished = Signal()
    toggle_layers_requested = Signal()
    delete_requested = Signal(str)  # region_id
    duplicate_requested = Signal(str)  # region_id
    add_layer_requested = Signal(str)  # default text
    layer_edit_requested = Signal(str)  # 双击画布文字请求编辑
    restore_layout_requested = Signal(str)
    source_text_changed = Signal(str, str)
    translated_text_changed = Signal(str, str)
    remove_document_requested = Signal(str)  # doc_id
    retranslate_requested = Signal(str)
    keep_original_requested = Signal(str)
    confirm_review_requested = Signal(str)
    manual_translate_requested = Signal(str, str, str, str)
    history_state_changed = Signal(bool, bool)
    ocr_preview_changed = Signal(str, object)

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

        # 原图只读场景
        self.original_scene = EditorScene(readonly=True)
        self.original_view = EditorView(self.original_scene, readonly=True)
        self.original_view.setMinimumWidth(220)
        self.view.setMinimumWidth(220)
        self._original_document = None
        self._slider_compare = False
        self._ocr_property_overrides: dict[str, dict[str, object]] = {}

        self.property_panel = PropertyPanel()

        # 翻译控件
        self.translate_controls = TranslateControls()

        # OCR 结果面板
        self.ocr_result_panel = OcrResultPanel()
        self.ocr_result_panel.show_regions_changed.connect(
            self.scene.set_regions_visible
        )
        self.layer_state_panel = LayerStatePanel()
        self.export_settings = ExportSettingsPanel()
        self.erase_dialog = EraseToolDialog(self)
        self.crop_dialog = CropToolDialog(self)
        self.watermark_dialog = WatermarkToolDialog(self)
        self.manual_region_dialog = QDialog(self)
        self.manual_region_dialog.setWindowTitle("框选翻译")
        self.manual_region_dialog.setModal(False)
        manual_layout = QVBoxLayout(self.manual_region_dialog)
        manual_layout.setContentsMargins(0, 0, 0, 0)
        self.manual_region_panel = ManualRegionPanel()
        manual_layout.addWidget(self.manual_region_panel)
        self.manual_region_dialog.resize(430, 720)
        self.batch_dialog = QDialog(self)
        self.batch_dialog.setWindowTitle("多图批量翻译")
        self.batch_dialog.setModal(False)
        batch_layout = QVBoxLayout(self.batch_dialog)
        batch_layout.setContentsMargins(0, 0, 0, 0)
        self.batch_panel = BatchPanel()
        batch_layout.addWidget(self.batch_panel)
        self.batch_dialog.resize(760, 620)

        # 右侧翻译与属性面板
        self.right_panel = QFrame()
        self.right_panel.setObjectName("editorRightPanel")
        self.right_panel.setMinimumWidth(380)
        self.right_panel.setMaximumWidth(540)
        right_layout = QVBoxLayout(self.right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)
        self.right_tabs = QTabWidget()
        self.right_tabs.setObjectName("editorRightTabs")
        self.translate_scroll = QScrollArea()
        self.translate_scroll.setObjectName("translateSettingsScroll")
        self.translate_scroll.setWidgetResizable(True)
        self.translate_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.translate_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.translate_scroll.setWidget(self.translate_controls)
        self.translate_controls.activity_changed.connect(
            self._on_translation_activity_changed
        )
        self.right_tabs.addTab(self.translate_scroll, "翻译设置")
        self.right_tabs.addTab(self.ocr_result_panel, "OCR结果")
        self.right_tabs.addTab(self.property_panel, "文字属性")
        self.layer_tools_stack = QStackedWidget()
        self.layer_tools_stack.setObjectName("layerToolsStack")
        self._layer_tool_pages = {
            "layers": self.layer_state_panel,
            "ai_erase": self.erase_dialog,
            "crop": self.crop_dialog,
            "watermark": self.watermark_dialog,
        }
        for panel in self._layer_tool_pages.values():
            if isinstance(panel, QDialog):
                panel.setModal(False)
                panel.setWindowFlags(Qt.WindowType.Widget)
                panel.setMinimumWidth(0)
            self.layer_tools_stack.addWidget(panel)
        self.right_tabs.addTab(self.layer_tools_stack, "图层状态")
        self.right_tabs.addTab(self.export_settings, "导出设置")
        right_layout.addWidget(self.right_tabs)

        # 中央区域
        center_widget = QWidget()
        center_layout = QHBoxLayout(center_widget)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(0)
        center_layout.addWidget(self.toolbar)

        # 左侧图片列表（工作台多文档切换）
        from src.ui.editor.widgets.image_list_panel import ImageListPanel
        self.image_list_panel = ImageListPanel()
        self.image_list_panel.remove_requested.connect(
            self.remove_document_requested.emit
        )
        center_layout.addWidget(self.image_list_panel)

        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.main_splitter.setChildrenCollapsible(False)
        self.main_splitter.addWidget(self.original_view)
        self.main_splitter.addWidget(self.view)
        self.main_splitter.addWidget(self.right_panel)
        self.main_splitter.setStretchFactor(0, 0)
        self.main_splitter.setStretchFactor(1, 1)
        self.main_splitter.setStretchFactor(2, 0)
        self.main_splitter.setSizes([0, 820, 380])
        self.original_view.setVisible(False)

        self._sidebar_visible = False

        self.view.bind_sync(self.original_view)
        self.view.transform_synced.connect(self.original_view.sync_transform)
        self.original_view.transform_synced.connect(self.view.sync_transform)
        self.main_splitter.splitterMoved.connect(self._on_splitter_moved)

        canvas_area = QWidget()
        canvas_layout = QVBoxLayout(canvas_area)
        canvas_layout.setContentsMargins(0, 0, 0, 0)
        canvas_layout.setSpacing(0)
        canvas_layout.addWidget(self.main_splitter, stretch=1)
        self.comparison_slider_bar = QFrame()
        self.comparison_slider_bar.setObjectName("comparisonSliderBar")
        comparison_layout = QHBoxLayout(self.comparison_slider_bar)
        comparison_layout.setContentsMargins(16, 4, 16, 4)
        comparison_layout.addWidget(QLabel("原图"))
        self.comparison_slider = QSlider(Qt.Orientation.Horizontal)
        self.comparison_slider.setRange(0, 100)
        self.comparison_slider.setValue(50)
        self.comparison_slider.valueChanged.connect(
            self.scene.set_comparison_position
        )
        comparison_layout.addWidget(self.comparison_slider, stretch=1)
        comparison_layout.addWidget(QLabel("译图"))
        self.comparison_slider_bar.setVisible(False)
        canvas_layout.addWidget(self.comparison_slider_bar)
        center_layout.addWidget(canvas_area, stretch=1)

        # 整体布局
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.top_bar)
        layout.addWidget(center_widget, stretch=1)

        self._connect_signals()

    def _connect_signals(self) -> None:
        self.toolbar.add_text_requested.connect(self._on_add_text_requested)
        self.toolbar.tool_changed.connect(self._on_toolbar_tool_changed)
        self.toolbar.feature_requested.connect(self.feature_requested.emit)
        self.scene.layer_selected.connect(self._on_scene_selection)
        self.scene.layer_edit_requested.connect(self.layer_edit_requested.emit)
        self.scene.selection_cleared.connect(self.property_panel.set_layer)
        self.scene.layer_dropped.connect(self._on_layer_dropped)
        self.scene.watermark_dropped.connect(
            lambda _watermark_id, watermark: self.watermark_edit_requested.emit(
                watermark
            )
        )
        self.scene.watermark_selected.connect(
            self.layer_state_panel.select_watermark
        )
        self.scene.manual_region_selected.connect(self._on_manual_selection)
        self.scene.area_selected.connect(self._on_area_selected)
        self.scene.area_selection_cleared.connect(
            self._on_area_selection_cleared
        )
        self.property_panel.layer_property_changed.connect(self._on_property_changed)
        self.property_panel.ocr_property_changed.connect(
            self._on_ocr_property_changed
        )
        self.property_panel.delete_layer_requested.connect(self.delete_requested.emit)
        self.property_panel.duplicate_layer_requested.connect(self.duplicate_requested.emit)
        self.property_panel.add_layer_requested.connect(self.add_layer_requested.emit)
        self.property_panel.restore_layout_requested.connect(
            self.restore_layout_requested.emit
        )
        self.property_panel.source_text_changed.connect(self.source_text_changed.emit)
        self.property_panel.translated_text_changed.connect(
            self.translated_text_changed.emit
        )
        # 主翻译设置的目标语言变化 → 同步到属性面板的二次翻译语言
        self.translate_controls.target_language.currentIndexChanged.connect(
            lambda _index: self.property_panel.set_retranslate_target(
                self.translate_controls.selected_target_language
            )
        )
        self.property_panel.retranslate_requested.connect(self.retranslate_requested.emit)
        self.property_panel.keep_original_requested.connect(self.keep_original_requested.emit)
        self.property_panel.confirm_review_requested.connect(self.confirm_review_requested.emit)
        self.property_panel.manual_translate_requested.connect(
            self.manual_translate_requested.emit
        )
        self.layer_state_panel.layer_selected.connect(
            self._on_layer_state_region_selected
        )
        self.layer_state_panel.layer_visibility_changed.connect(
            self._on_layer_visibility_changed
        )
        self.layer_state_panel.layer_lock_changed.connect(
            lambda layer_id, locked: self.layer_state_requested.emit(
                layer_id, "locked", locked
            )
        )
        self.layer_state_panel.watermark_visibility_changed.connect(
            lambda layer_id, visible: self.watermark_state_requested.emit(
                layer_id, "visible", visible
            )
        )
        self.layer_state_panel.watermark_lock_changed.connect(
            lambda layer_id, locked: self.watermark_state_requested.emit(
                layer_id, "locked", locked
            )
        )
        self.layer_state_panel.watermark_selected.connect(
            self.scene.select_watermark
        )
        self.layer_state_panel.watermark_delete_requested.connect(
            self.watermark_delete_requested.emit
        )
        self.layer_state_panel.watermark_duplicate_requested.connect(
            self.watermark_duplicate_requested.emit
        )
        self.layer_state_panel.watermark_property_changed.connect(
            self.watermark_property_requested.emit
        )
        self.layer_state_panel.watermark_preview_changed.connect(
            self.scene.preview_watermark
        )
        self.layer_state_panel.layer_move_requested.connect(
            self.layer_move_requested.emit
        )

        # OCR 结果面板 → 画布选中
        self.ocr_result_panel.region_selected.connect(self._on_ocr_region_selected)
        self.ocr_result_panel.edit_region_requested.connect(
            self._on_edit_ocr_region_requested
        )
        self.ocr_result_panel.retranslate_requested.connect(
            self.retranslate_requested.emit
        )

        self.top_bar.import_requested.connect(self._on_import_clicked)
        self.top_bar.batch_requested.connect(self.show_batch_dialog)
        self.top_bar.back_requested.connect(self.back_requested.emit)
        self.top_bar.ocr_requested.connect(self.ocr_requested.emit)
        self.top_bar.translate_requested.connect(self._on_topbar_translate)
        self.translate_controls.translate_requested.connect(self.translate_requested.emit)
        self.translate_controls.ocr_only_requested.connect(self.ocr_requested.emit)
        self.top_bar.toggle_original_requested.connect(self.toggle_original_requested.emit)
        self.top_bar.split_compare_requested.connect(
            self.split_compare_requested.emit
        )
        self.top_bar.slider_compare_requested.connect(
            self.slider_compare_requested.emit
        )
        self.top_bar.compare_hold_started.connect(
            self.compare_hold_started.emit
        )
        self.top_bar.compare_hold_finished.connect(
            self.compare_hold_finished.emit
        )
        self.top_bar.toggle_layers_requested.connect(self.toggle_layers_requested.emit)
        self.top_bar.zoom_in_requested.connect(self.zoom_in_requested.emit)
        self.top_bar.zoom_out_requested.connect(self.zoom_out_requested.emit)
        self.top_bar.fit_requested.connect(self.fit_requested.emit)
        self.top_bar.save_requested.connect(self.save_requested.emit)
        self.top_bar.undo_requested.connect(self.undo_requested.emit)
        self.top_bar.redo_requested.connect(self.redo_requested.emit)

        self.top_bar.export_requested.connect(self._on_export_clicked)
        self.export_settings.export_requested.connect(self._on_export_clicked)
        self.view.zoom_changed.connect(self._on_zoom_changed)
        self.manual_region_panel.select_requested.connect(
            lambda: self.scene.set_area_selection_mode("manual_translate")
        )
        self.manual_region_panel.process_requested.connect(
            lambda: self.manual_region_requested.emit(
                self.manual_region_panel.spec
            )
        )
        self.erase_dialog.rectangle_requested.connect(
            self._on_erase_rectangle_requested
        )
        self.erase_dialog.brush_changed.connect(self._on_erase_brush_changed)
        self.erase_dialog.preview_changed.connect(
            self.scene.set_edit_mask_visible
        )
        self.erase_dialog.clear_requested.connect(self.scene.clear_edit_mask)
        self.erase_dialog.apply_requested.connect(self._request_ai_erase)
        # 涂抹松手自动消除（客户期望"涂完松手 AI 自动变没"）
        self.scene.mask_brush_finished.connect(self._request_ai_erase)
        self.erase_dialog.undo_requested.connect(self.undo_requested.emit)
        self.erase_dialog.add_text_requested.connect(self._on_add_text_requested)
        self.crop_dialog.selection_requested.connect(
            self._on_crop_selection_requested
        )
        self.crop_dialog.ratio.currentIndexChanged.connect(
            lambda _index: self._on_crop_ratio_changed()
        )
        self.crop_dialog.custom_width.valueChanged.connect(
            lambda _value: self._on_crop_ratio_changed()
        )
        self.crop_dialog.custom_height.valueChanged.connect(
            lambda _value: self._on_crop_ratio_changed()
        )
        self.crop_dialog.apply_requested.connect(self.crop_requested.emit)
        self.crop_dialog.transform_requested.connect(
            self.image_transform_requested.emit
        )
        self.watermark_dialog.add_text_requested.connect(
            self.watermark_text_requested.emit
        )
        self.watermark_dialog.add_image_requested.connect(
            self.watermark_image_requested.emit
        )
        self.scene.edit_mask_changed.connect(self._on_edit_mask_changed)
        self.erase_dialog.rejected.connect(self._close_erase_tool)
        self.erase_dialog.accepted.connect(lambda: self._show_layer_tool("layers"))
        self.crop_dialog.rejected.connect(self._close_crop_tool)
        self.crop_dialog.accepted.connect(lambda: self._show_layer_tool("layers"))
        self.watermark_dialog.rejected.connect(lambda: self._show_layer_tool("layers"))

    def _on_topbar_translate(self) -> None:
        ocr = self.translate_controls.selected_ocr_language
        target = self.translate_controls.selected_target_language
        self.translate_requested.emit(ocr, target)

    # —— 公开方法 ——

    def set_document(self, document, pixmap=None) -> None:
        self.erase_dialog.set_undo_available(False)
        self.scene.set_document(document)
        if (
            self._slider_compare
            and self._original_document is not None
            and self.scene.scene_size
            == (
                self._original_document.asset.width,
                self._original_document.asset.height,
            )
        ):
            self.scene.set_comparison_document(
                self._original_document,
                self.comparison_slider.value(),
            )
        self.export_settings.set_source_size(
            document.asset.width,
            document.asset.height,
            document.asset.has_alpha,
        )

    def set_original_document(self, document) -> None:
        self._original_document = document
        self.original_scene.set_document(document)
        if (
            self._slider_compare
            and self.scene.scene_size
            == (document.asset.width, document.asset.height)
        ):
            self.scene.set_comparison_document(
                document,
                self.comparison_slider.value(),
            )

    def set_text_layout(self, layout: TextLayout) -> None:
        self.scene.set_text_layout(layout)
        self.layer_state_panel.set_layout(layout)

    def select_layer(self, layer: TextLayer) -> None:
        self.scene.select_layer(layer.region_id)
        ocr_region = self._find_ocr_region(layer.region_id)
        translation_unit = self._find_translation_unit(layer.region_id)
        self.property_panel.set_layer(layer, ocr_region, translation_unit)

    def clear_layer_selection(self) -> None:
        self.scene.clear_selection()
        self.property_panel.set_layer(None)

    def open_manual_region_dialog(self) -> None:
        self.manual_region_panel.set_available(True)
        self.manual_region_dialog.show()
        self.manual_region_dialog.raise_()
        self.scene.set_area_selection_mode("manual_translate")

    def open_erase_dialog(self) -> None:
        self.scene.clear_edit_mask()
        self.scene.set_edit_mask_visible(True)
        self._show_layer_tool("ai_erase")
        self.erase_dialog.activate_mode("paint")

    def open_crop_dialog(self) -> None:
        self.crop_dialog.clear_selection()
        self.scene.clear_crop_selection()
        self._show_layer_tool("crop")
        self._on_crop_selection_requested()

    def _on_crop_selection_requested(self) -> None:
        self.scene.set_area_selection_mode(
            "crop",
            self.crop_dialog.selected_aspect_ratio(),
        )

    def _on_crop_ratio_changed(self) -> None:
        self.scene.set_selection_aspect_ratio(
            self.crop_dialog.selected_aspect_ratio()
        )

    def _close_crop_tool(self) -> None:
        self.scene.set_area_selection_mode(None)
        self.crop_dialog.clear_selection()
        self.toolbar.set_active_tool("select")
        self._show_layer_tool("layers")

    def open_watermark_dialog(self) -> None:
        self._show_layer_tool("watermark")

    def _show_layer_tool(self, tool_id: str) -> None:
        panel = self._layer_tool_pages.get(tool_id, self.layer_state_panel)
        self.layer_tools_stack.setCurrentWidget(panel)
        panel.show()
        self.right_tabs.setCurrentIndex(3)

    def _on_edit_mask_changed(self, mask) -> None:
        self.erase_dialog.set_mask_ready(not mask.is_empty)

    def _request_ai_erase(self) -> None:
        mask = self.scene.edit_mask
        if mask.is_empty:
            self.erase_dialog.set_mask_ready(False)
            self.scene.set_area_selection_mode("ai_erase")
            return
        self.erase_dialog.set_running(True)
        self.ai_erase_requested.emit(mask)

    def _on_erase_brush_changed(self, mode: str, size: int) -> None:
        self.scene.set_area_selection_mode(None)
        self.scene.set_mask_brush(mode, size)

    def _on_erase_rectangle_requested(self) -> None:
        self.scene.set_mask_brush(None)
        self.scene.set_area_selection_mode("ai_erase")

    def _close_erase_tool(self) -> None:
        self.scene.set_area_selection_mode(None)
        self.scene.set_mask_brush(None)
        self.scene.set_edit_mask_visible(False)
        self.scene.clear_edit_mask()
        self.toolbar.set_active_tool("select")
        self._show_layer_tool("layers")

    def complete_ai_erase(self, backend_id: str) -> None:
        self.scene.clear_edit_mask()
        self.scene.set_edit_mask_visible(True)
        self._show_layer_tool("ai_erase")
        self.erase_dialog.activate_mode("paint")
        self.erase_dialog.set_completed(backend_id)

    def fail_ai_erase(self, message: str) -> None:
        self._show_layer_tool("ai_erase")
        self.erase_dialog.set_failed(message)

    def set_model(self, model) -> None:
        self._model = model
        model.document_changed.connect(self._on_model_document_changed)
        model.text_layout_changed.connect(self._on_model_layout_changed)
        model.selected_layer_changed.connect(self._on_model_selection_changed)
        model.translation_finished.connect(self._on_model_translation_finished)
        model.translation_stage_changed.connect(self.translate_controls.set_stage)
        model.edit_finished.connect(self._on_model_edit_finished)
        model.showing_original_changed.connect(self._on_model_showing_original_changed)
        model.ocr_finished.connect(self._on_model_ocr_finished)
        model.documents_changed.connect(self._sync_image_list)
        model.active_document_changed.connect(self._sync_active_document)

    def _sync_image_list(self) -> None:
        """同步左侧图片列表。"""
        self.image_list_panel.set_documents(self._model.documents())

    def _sync_active_document(self, doc_id: str) -> None:
        self.image_list_panel.set_active(doc_id)

    def set_layers_visible(self, visible: bool) -> None:
        for region_id, item in self.scene._layer_items.items():
            item.setVisible(
                visible and self.layer_state_panel.is_layer_visible(region_id)
            )

    def set_split_view(self, enabled: bool) -> None:
        """启用/禁用左右分屏。"""
        self._sidebar_visible = enabled
        total = max(1, self.main_splitter.width())
        handle_space = self.main_splitter.handleWidth() * 2
        available = max(1, total - handle_space)
        right_w = min(480, max(380, self.right_panel.width()))
        if enabled:
            self.original_view.setVisible(True)
            canvas_w = max(440, available - right_w)
            first = canvas_w // 2
            self.main_splitter.setSizes(
                [first, canvas_w - first, right_w]
            )
            QTimer.singleShot(0, self._fit_split_views)
        else:
            self.original_view.setVisible(False)
            canvas_w = max(220, available - right_w)
            self.main_splitter.setSizes([0, canvas_w, right_w])
            QTimer.singleShot(0, self.view.fit_to_window)

    def set_slider_compare(self, enabled: bool) -> None:
        self._slider_compare = enabled
        self.comparison_slider_bar.setVisible(enabled)
        self.top_bar.set_slider_compare(enabled)
        self.scene.set_comparison_document(
            self._original_document if enabled else None,
            self.comparison_slider.value(),
        )

    def is_slider_compare(self) -> bool:
        return self._slider_compare

    def is_split_view(self) -> bool:
        return self._sidebar_visible

    def refit_canvas_views(self) -> None:
        if self._sidebar_visible:
            QTimer.singleShot(0, self._fit_split_views)
        else:
            QTimer.singleShot(0, self.view.fit_to_window)

    def _fit_split_views(self) -> None:
        if not self._sidebar_visible or not self.original_view.isVisible():
            return
        common_zoom = min(
            self.original_view.fit_zoom(),
            self.view.fit_zoom(),
        )
        self.original_view.set_zoom_absolute(common_zoom, False)
        self.view.set_zoom_absolute(common_zoom, False)

    def _on_splitter_moved(self, _position: int, _index: int) -> None:
        if self._sidebar_visible:
            QTimer.singleShot(0, self._fit_split_views)

    # —— 应用编辑结果（由 MainWindow 在后台线程完成后回调）——

    def apply_edit_result(self, edit_result: object) -> None:
        """接收 CompositionEditResult，更新画布和图层。"""
        self.erase_dialog.set_undo_available(False)
        if hasattr(self, "_model") and self._model is not None:
            self._model.rendered_document = edit_result.document
            self._model.text_layout = edit_result.layout
            self._model.is_dirty = True
            display_document = edit_result.document
            if (
                self._model.preview_mode == "layers"
                and self._model.composition_editor is not None
            ):
                display_document = (
                    self._model.composition_editor.editing_document
                )
            self.set_document(display_document)
            if self._model.preview_mode == "layers":
                self.scene.set_text_layout(edit_result.layout)
            self.layer_state_panel.set_composition(
                edit_result.layout,
                getattr(edit_result, "watermarks", ()),
                self._model.composition_editor.patch_count
                if self._model.composition_editor is not None
                else 0,
            )
            self.scene.set_watermarks(
                getattr(edit_result, "watermarks", ())
            )
            self.top_bar.set_can_undo(edit_result.can_undo)
            self.top_bar.set_can_redo(edit_result.can_redo)
            self.history_state_changed.emit(
                edit_result.can_undo,
                edit_result.can_redo,
            )
            # 同步更新翻译结果中的渲染图
            if self._model.translation_result is not None:
                from dataclasses import replace
                try:
                    self._model.translation_result = replace(
                        self._model.translation_result,
                        document=edit_result.document,
                        layout=edit_result.layout,
                    )
                except Exception:
                    pass
            if self._model.selected_layer is not None:
                layer = self._model.selected_layer
                self.property_panel.set_layer(
                    layer,
                    self._find_ocr_region(layer.region_id),
                    self._find_translation_unit(layer.region_id),
                )

    # —— 内部槽 ——

    def _on_import_clicked(self) -> None:
        value, _ = QFileDialog.getOpenFileName(
            self, "导入图片", "",
            "图片 (*.jpg *.jpeg *.png *.webp *.bmp);;所有文件 (*)",
        )
        if value:
            self.import_requested.emit(Path(value))

    def show_batch_dialog(self) -> None:
        self.batch_dialog.show()
        self.batch_dialog.raise_()
        self.batch_dialog.activateWindow()

    def _on_export_clicked(self) -> None:
        default_name = ""
        suffix = self.export_settings.selected_suffix
        if hasattr(self, "_model") and self._model is not None:
            src = self._model.rendered_document or self._model.document
            if src is not None:
                stem = src.asset.source_path.stem
                default_name = str(
                    src.asset.source_path.with_name(f"{stem}_translated{suffix}")
                )
        value, _ = QFileDialog.getSaveFileName(
            self, "导出图片", default_name,
            _export_filter_for_suffix(suffix),
        )
        if value:
            target = Path(value)
            if not target.suffix:
                target = target.with_suffix(suffix)
            self.export_requested.emit(target)

    def _on_toolbar_tool_changed(self, tool_id: str) -> None:
        if tool_id != "ai_erase":
            self.scene.set_mask_brush(None)
            self.scene.set_edit_mask_visible(False)
        if tool_id not in {"ai_erase", "crop", "manual_translate"}:
            self.scene.set_area_selection_mode(None)
        tab_by_tool = {
            "text_regions": 1,
            "layers": 3,
            "ai_erase": 3,
            "crop": 3,
            "watermark": 3,
        }
        if tool_id in tab_by_tool:
            self.right_tabs.setCurrentIndex(tab_by_tool[tool_id])
        if tool_id in self._layer_tool_pages:
            self._show_layer_tool(tool_id)
        self.tool_changed.emit(tool_id)

    def _on_translation_activity_changed(self, active: bool) -> None:
        if not active:
            return
        self.right_tabs.setCurrentIndex(0)
        QTimer.singleShot(
            0,
            lambda: self.translate_scroll.verticalScrollBar().setValue(
                self.translate_scroll.verticalScrollBar().maximum()
            ),
        )

    def _on_manual_selection(self, box: TextBox) -> None:
        self.manual_region_panel.set_selection(box)
        self.manual_region_panel.set_available(True)
        self.manual_region_dialog.show()
        self.manual_region_dialog.raise_()

    def _on_area_selected(self, mode: str, box: TextBox) -> None:
        if mode == "ai_erase":
            self.scene.add_rect_to_edit_mask(box)
            self._show_layer_tool("ai_erase")
            # 框选松手即自动消除（与涂抹体验一致）
            self._request_ai_erase()
        elif mode == "crop":
            self.scene.set_crop_selection(box)
            self.crop_dialog.set_selection(box)
            self._show_layer_tool("crop")

    def _on_area_selection_cleared(self, mode: str) -> None:
        if mode == "crop":
            self.crop_dialog.clear_selection()

    def _on_add_text_requested(self) -> None:
        self.scene.set_area_selection_mode(None)
        self.scene.set_mask_brush(None)
        self.scene.set_edit_mask_visible(False)
        self.toolbar.set_active_tool("add_text")
        self.right_tabs.setCurrentIndex(2)
        self.add_layer_requested.emit("新文本")

    def _on_layer_visibility_changed(
        self,
        region_id: str,
        visible: bool,
    ) -> None:
        self.layer_state_requested.emit(region_id, "visible", visible)

    def _on_scene_selection(self, region_id: str) -> None:
        if hasattr(self, "_model") and self._model is not None:
            self._model.selected_layer_id = region_id
        # 画布选中 → 右侧 OCR 列表同步选中对应行（不跳转标签页）
        self.ocr_result_panel.select_region(region_id)

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

    def _on_ocr_region_selected(self, region_id: str) -> None:
        """OCR 面板点击行 → 画布选中对应 OCR 区域。"""
        has_layer = False
        if hasattr(self, "_model") and self._model is not None:
            ocr_result = getattr(self._model, "ocr_result", None)
            if ocr_result is not None:
                self.scene.set_regions(tuple(getattr(ocr_result, "regions", ())))
                self.scene.set_regions_visible(
                    self.ocr_result_panel.show_regions.isChecked()
                )
            try:
                self._model.text_layout.layer_by_id(region_id)
            except KeyError:
                pass
            else:
                has_layer = True
                self._model.selected_layer_id = region_id
        region_rect = self.scene.highlight_ocr_region(region_id)
        if region_rect is not None:
            self.view.ensureVisible(region_rect, 80, 80)
        ocr_region = self._find_ocr_region(region_id)
        if ocr_region is not None and not has_layer:
            self.property_panel.set_ocr_region(
                ocr_region,
                self._find_translation_unit(region_id),
                self._ocr_property_overrides.get(region_id),
            )
        # OCR-only 模式直接打开属性页编辑；翻译完成后点选行不跳转标签页，
        # 由「重新翻译选中区域」按钮等显式操作才跳转到文字属性。
        has_translation = bool(
            getattr(getattr(self, "_model", None), "translation_result", None)
        )
        if not has_translation:
            self.right_tabs.setCurrentIndex(2)

    def _on_layer_state_region_selected(self, region_id: str) -> None:
        if not hasattr(self, "_model") or self._model is None:
            return
        try:
            self._model.text_layout.layer_by_id(region_id)
        except KeyError:
            return
        self._model.selected_layer_id = region_id
        self.right_tabs.setCurrentIndex(2)

    def _on_edit_ocr_region_requested(self, region_id: str) -> None:
        self._on_ocr_region_selected(region_id)
        self.right_tabs.setCurrentIndex(2)

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
        elif field in {
            "font_size",
            "auto_fit",
            "fill_rgb",
            "font_weight",
            "font_family",
            "font_stretch",
            "wrap",
            "alignment",
            "vertical_alignment",
            "stroke_rgb",
            "stroke_width",
            "shadow_rgb",
            "shadow_enabled",
            "shadow_opacity",
            "shadow_offset_x",
            "shadow_offset_y",
            "line_height",
            "letter_spacing",
            "text_opacity",
            "background_rgb",
            "background_opacity",
            "effect_preset",
        }:
            kind = "style"
        elif field == "text_path":
            kind = "path"
        else:
            kind = "box"

        self.edit_requested.emit(region_id, kind, after, before)

    def _on_ocr_property_changed(
        self, region_id: str, field: str, value: object
    ) -> None:
        """Persist OCR-only properties and refresh their editable preview."""
        overrides = self._ocr_property_overrides.setdefault(region_id, {})
        overrides[field] = value
        model = getattr(self, "_model", None)
        ocr_result = getattr(model, "ocr_result", None)
        if model is None or ocr_result is None:
            return
        region = next(
            (item for item in ocr_result.regions if item.region_id == region_id),
            None,
        )
        if region is None:
            return
        updated_region = region
        if field == "text":
            updated_region = replace(region, text=str(value))
            updated = replace(
                ocr_result,
                regions=tuple(
                    updated_region if item.region_id == region_id else item
                    for item in ocr_result.regions
                ),
            )
            model.ocr_result = updated
            self.scene.set_regions(updated.regions)
            self.ocr_result_panel.set_result(updated)
        self.ocr_preview_changed.emit(region_id, updated_region)

    def apply_ocr_property_overrides(self, layout: TextLayout) -> TextLayout:
        """将仅 OCR 阶段编辑的属性应用到即将生成的文字图层。"""
        updated = layout
        for layer in layout.layers:
            changes = self._ocr_property_overrides.get(layer.region_id)
            if not changes:
                continue
            candidate = layer
            for field, value in changes.items():
                candidate = self._apply_field_change(candidate, field, value) or candidate
            updated = updated.replace_layer(candidate)
        return updated

    def _on_zoom_changed(self, zoom: float) -> None:
        self.top_bar.set_zoom(int(zoom * 100))
        if hasattr(self, "_model") and self._model is not None:
            self._model.zoom_factor = zoom

    def _on_model_document_changed(self, document) -> None:
        if document is not None:
            self.set_document(document)

    def _on_model_layout_changed(self, layout: TextLayout) -> None:
        if (
            not hasattr(self, "_model")
            or self._model is None
            or self._model.preview_mode == "layers"
        ):
            self.scene.set_text_layout(layout)
        self.layer_state_panel.set_layout(layout)
        has_layers = len(layout.layers) > 0
        self.top_bar.set_has_layers(has_layers)
        if hasattr(self, "_model") and self._model is not None:
            layer = self._model.selected_layer
            if layer is not None:
                self.property_panel.set_layer(
                    layer,
                    self._find_ocr_region(layer.region_id),
                    self._find_translation_unit(layer.region_id),
                )

    def _on_model_selection_changed(self, layer: TextLayer | None) -> None:
        if layer is not None:
            self.scene.select_layer(layer.region_id)
            self.layer_state_panel.select_region(layer.region_id)
            self.ocr_result_panel.select_region(layer.region_id)
            ocr_region = self._find_ocr_region(layer.region_id)
            translation_unit = self._find_translation_unit(layer.region_id)
            self.property_panel.set_layer(layer, ocr_region, translation_unit)
        else:
            self.scene.clear_selection()
            self.layer_state_panel.select_region(None)
            self.property_panel.set_layer(None)

    def _on_model_translation_finished(self, result) -> None:
        self.translate_controls.reset_progress()
        self.translate_controls.set_translating(False)
        self.export_settings.set_export_enabled(True)
        self.top_bar.set_translating(False)
        self.top_bar.set_has_result(True)
        self.view.fit_to_window()
        # 翻译完成后自动跳转到 OCR 结果页查看原文/译文列表
        self.right_tabs.setCurrentIndex(1)

    def _on_model_edit_finished(self, edit_result) -> None:
        self.apply_edit_result(edit_result)

    def _on_model_showing_original_changed(self, showing: bool) -> None:
        self.top_bar.set_showing_original(showing)

    def _on_model_ocr_finished(self, result) -> None:
        """OCR 完成后保持左侧识别列表可见。"""
        self.ocr_result_panel.set_result(result)
        self.property_panel._no_selection_label.setText("点击画布中的文字框可查看属性")

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
        elif field == "font_size":
            style = replace(style, font_size=float(value), auto_fit=False)
        elif field == "auto_fit":
            style = replace(style, auto_fit=bool(value))
        elif field == "fill_rgb": style = replace(style, fill_rgb=tuple(value))
        elif field == "font_family": style = replace(style, font_family=str(value))
        elif field == "font_weight":
            weight = int(value)
            if weight in (400, 600, 700): style = replace(style, font_weight=weight)
            else: return None
        elif field == "wrap": style = replace(style, wrap=bool(value))
        elif field == "alignment": style = replace(style, alignment=value)
        elif field == "vertical_alignment": style = replace(style, vertical_alignment=value)
        elif field == "stroke_rgb": style = replace(style, stroke_rgb=tuple(value))
        elif field == "stroke_width": style = replace(style, stroke_width=float(value))
        elif field == "shadow_rgb": style = replace(style, shadow_rgb=tuple(value))
        elif field == "shadow_enabled":
            opacity = 0.5 if value else 0.0
            style = replace(style, shadow_opacity=opacity)
        elif field == "shadow_opacity": style = replace(style, shadow_opacity=float(value) / 100.0)
        elif field == "shadow_offset_x": style = replace(style, shadow_offset_x=float(value))
        elif field == "shadow_offset_y": style = replace(style, shadow_offset_y=float(value))
        elif field == "font_stretch": style = replace(style, font_stretch=int(value))
        elif field == "line_height": style = replace(style, line_height=float(value))
        elif field == "letter_spacing": style = replace(style, letter_spacing=float(value))
        elif field == "text_opacity": style = replace(style, text_opacity=float(value) / 100)
        elif field == "background_rgb": style = replace(style, background_rgb=tuple(value))
        elif field == "background_opacity": style = replace(style, background_opacity=float(value) / 100)
        elif field == "effect_preset":
            preset = value if isinstance(value, ArtisticPreset) else ArtisticPreset(value)
            if preset is ArtisticPreset.OUTLINE:
                style = replace(
                    style,
                    effect_preset=preset,
                    stroke_width=max(2.0, style.stroke_width),
                    stroke_rgb=(255, 255, 255),
                    shadow_opacity=0.0,
                )
            elif preset is ArtisticPreset.POSTER:
                style = replace(
                    style,
                    effect_preset=preset,
                    stroke_width=max(3.0, style.stroke_width),
                    stroke_rgb=(24, 32, 51),
                    shadow_opacity=0.55,
                    shadow_offset_x=4.0,
                    shadow_offset_y=4.0,
                )
            elif preset is ArtisticPreset.SHADOW:
                style = replace(
                    style,
                    effect_preset=preset,
                    stroke_width=max(1.0, style.stroke_width),
                    shadow_opacity=0.7,
                    shadow_offset_x=6.0,
                    shadow_offset_y=6.0,
                )
            else:
                style = replace(style, effect_preset=preset)
        elif field == "text_path":
            data = dict(value)
            mode = str(data["mode"])
            if mode == "straight":
                return replace(layer, path=None)
            if mode == "arc":
                path = default_arc_path(box, float(data["bend"]))
                return replace(
                    layer,
                    path=ArcTextPath(
                        path.start,
                        path.control,
                        path.end,
                        bool(data["reverse"]),
                    ),
                )
            start = float(data["start"])
            end = float(data["end"])
            if abs(end - start) < 0.01:
                end = start + 1
            return replace(
                layer,
                path=CircularTextPath(
                    PathPoint(
                        float(data["center_x"]),
                        float(data["center_y"]),
                    ),
                    max(1.0, float(data["radius"])),
                    start,
                    end,
                    bool(data["reverse"]),
                ),
            )
        else: return None
        return replace(layer, text=text, box=box, style=style)

    # —— OCR / Translation 查找辅助 ——

    def _find_ocr_region(self, region_id: str) -> object | None:
        if not hasattr(self, "_model") or self._model is None:
            return None
        ocr = self._model.ocr_result
        if ocr is None:
            return None
        for r in ocr.regions:
            if r.region_id == region_id:
                return r
        result = self._model.translation_result
        if result is not None and result.ocr is not None:
            for r in result.ocr.regions:
                if r.region_id == region_id:
                    return r
        return None

    def _find_translation_unit(self, region_id: str) -> object | None:
        if not hasattr(self, "_model") or self._model is None:
            return None
        result = self._model.translation_result
        if result is None:
            return None
        for u in result.translation.units:
            if u.region_id == region_id:
                return u
        return None


def _export_filter_for_suffix(suffix: str) -> str:
    filters = {
        ".png": "PNG (*.png)",
        ".jpg": "JPEG (*.jpg *.jpeg)",
        ".webp": "WebP (*.webp)",
        ".gif": "GIF (*.gif)",
        ".tiff": "TIFF (*.tif *.tiff)",
    }
    selected = filters.get(suffix, filters[".png"])
    remaining = [value for value in filters.values() if value != selected]
    return ";;".join((selected, *remaining))
