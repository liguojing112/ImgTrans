"""编辑器主窗口 — QStackedWidget 切换首页 / 编辑器页。

集成 QUndoStack + 翻译流水线 + 编辑合成 + 导出 + TopBar 操作栏。
"""

from __future__ import annotations

from dataclasses import replace
from math import atan2, degrees, hypot
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QAction, QDragEnterEvent, QDropEvent, QUndoStack
from PySide6.QtWidgets import (
    QFileDialog,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
    QStatusBar,
)

from src.application.image_io import ExportImage, ImportImage
from src.application.batch import RunBatch
from src.application.batch_export import (
    BatchExportOptions,
    BatchResizeMode,
    BatchWatermarkOptions,
    ExportBatchSelection,
)
from src.application.translate_image import TranslateImage, TranslateImageResult
from src.domain.image import ImageDocument
from src.domain.image import ImageLimits
from src.domain.language import SUPPORTED_LANGUAGE_CODES
from src.domain.job import ImageStage
from src.domain.batch import BatchSnapshot, BatchStatus
from src.domain.inpainting import EraseMask, InpaintingResult
from src.domain.composition import ImageTransform
from src.domain.layout import CircularTextPath, TextBox, TextLayout, TextStyle
from src.domain.manual_region import ManualInputMode, ManualRegionSpec
from src.domain.ocr import OcrResult, TextRegion
from src.domain.translation import (
    TranslationSelection,
    TranslationMode,
    TranslationResult,
    TranslationStatus,
    TranslationUnit,
)
from src.domain.terminology import (
    TerminologyCatalog,
    TerminologyEntry,
    normalize_terminology_entries,
)
from src.infrastructure.pillow_image_codec import PillowImageCodec
from src.infrastructure.text_renderer import circular_text_path_for_region
from src.platform.fonts import resolve_system_font

from src.ui.editor.editor_model import EditorModel
from src.ui.editor.editor_page import EditorPage
from src.ui.editor.error_handler import classify_error
from src.ui.editor.home_page import HomePage
from src.ui.editor.services.editor_import_service import load_document
from src.ui.editor.services.editor_export_service import export_document
from src.ui.editor.theme import EDITOR_DARK_THEME
from src.application.composition import crop_image_document, transform_image_document
from src.application.coordinate_transform import crop_ocr_result, transform_ocr_result


class EditorMainWindow(QMainWindow):
    """编辑器应用主窗口。"""

    batch_snapshot_changed = Signal(object)

    def __init__(
        self,
        import_image: ImportImage,
        export_image: ExportImage | None = None,
        codec: PillowImageCodec | None = None,
        task_runner: object | None = None,
        translate_image: TranslateImage | None = None,
        create_composition_editor: object | None = None,
        recognize_text: object | None = None,
        process_manual_region: object | None = None,
        repair_selection: object | None = None,
        mask_rasterizer: object | None = None,
        erase_mask_builder: object | None = None,
        text_layout_adapter: object | None = None,
        brand_terms: tuple[str, ...] = (),
        model_terms: tuple[str, ...] = (),
        brand_terms_preferences: object | None = None,
        model_terms_preferences: object | None = None,
        run_batch: RunBatch | None = None,
        batch_result_store: object | None = None,
        export_batch_selection: ExportBatchSelection | None = None,
        terminology_catalog: TerminologyCatalog | None = None,
        terminology_preferences: object | None = None,
        translation_service_label: str = "翻译服务：可用",
        translation_service_available: bool = True,
        manual_translation_adapter: object | None = None,
        activate_device=None,
        activation_status=None,
        clear_activation=None,
        payment_client=None,
        quota_client=None,
        access_token=None,
        refresh_image_limits=None,
        backend_url=None,
    ) -> None:
        super().__init__()
        self.setProperty("editorStyle", True)
        self.setObjectName("editorMainWindow")
        self.setWindowTitle("优译图AI - 图片翻译编辑器")
        self.setMinimumSize(1024, 640)
        self.resize(1280, 800)
        self.setAcceptDrops(True)

        self._import_usecase = import_image
        self._export_usecase = export_image
        self._codec = codec
        self._task_runner = task_runner
        self._translate_image = translate_image
        self._create_composition_editor = create_composition_editor
        self._recognize_text = recognize_text
        self._process_manual_region = process_manual_region
        self._repair_selection = repair_selection
        self._mask_rasterizer = mask_rasterizer
        self._erase_mask_builder = erase_mask_builder
        self._text_layout_adapter = text_layout_adapter
        self._brand_terms = brand_terms
        self._model_terms = model_terms
        self._brand_terms_preferences = brand_terms_preferences
        self._model_terms_preferences = model_terms_preferences
        self._run_batch = run_batch
        self._batch_result_store = batch_result_store
        self._export_batch_selection = export_batch_selection
        self._batch_snapshot: BatchSnapshot | None = None
        self._terminology_catalog = terminology_catalog
        self._terminology_preferences = terminology_preferences
        self._terminology_entries: tuple[TerminologyEntry, ...] = ()
        self._updating_terminology = False
        self._translation_service_label = translation_service_label
        self._translation_service_available = translation_service_available
        self._manual_translation_adapter = manual_translation_adapter
        self._activate_device = activate_device
        self._activation_status = activation_status
        self._clear_activation = clear_activation
        self._payment_client = payment_client
        self._quota_client = quota_client
        self._access_token = access_token
        self._refresh_image_limits = refresh_image_limits
        self._backend_url = backend_url
        if self._refresh_image_limits is not None:
            QTimer.singleShot(0, self._apply_image_limits_refresh)
        self._activation_dialog = None
        self._quick_save_path: Path | None = None
        self._source_undo: list[ImageDocument] = []
        self._source_redo: list[ImageDocument] = []
        self._last_non_original_preview = "translated"
        self._hold_preview_mode: str | None = None
        self._hold_slider_compare = False
        self._translation_document_id: str | None = None
        self._translation_stage: ImageStage | None = None
        self._ocr_preview_layers: dict[str, str] = {}
        # Keep the first OCR geometry as the anchor for OCR-only corrections.
        # Editing the source text must never resize or reflow the detected box.
        self._ocr_preview_boxes: dict[str, TextBox] = {}
        # Original OCR text is kept separately from the editable result.  It
        # lets the OCR-only preview avoid adding a second copy when a row is
        # merely selected or when a correction is reverted to its source text.
        self._ocr_original_texts: dict[str, str] = {}

        self._model = EditorModel()
        self._undo_stack = QUndoStack(self)

        self._home_page = HomePage(self._payment_client)
        self._editor_page = EditorPage(self._undo_stack)
        self._toolbox_page = self._create_toolbox_page()

        self._stack = QStackedWidget()
        self._stack.addWidget(self._home_page)
        self._stack.addWidget(self._editor_page)
        self._stack.addWidget(self._toolbox_page)
        self.setCentralWidget(self._stack)

        self._build_menus()
        self.setStatusBar(QStatusBar(self))
        self.statusBar().showMessage("就绪")

        self._connect_signals()

        self.setStyleSheet(EDITOR_DARK_THEME)

    # —— 菜单栏 ——

    def _build_menus(self) -> None:
        menu = self.menuBar()

        file_menu = menu.addMenu("文件")
        import_action = QAction("导入图片…", self)
        import_action.setShortcut("Ctrl+O")
        import_action.triggered.connect(self._editor_page._on_import_clicked)
        file_menu.addAction(import_action)

        export_action = QAction("导出图片…", self)
        export_action.setShortcut("Ctrl+S")
        export_action.triggered.connect(self._editor_page._on_export_clicked)
        file_menu.addAction(export_action)

        save_action = QAction("快速保存译图", self)
        save_action.setShortcut("Ctrl+Shift+S")
        save_action.triggered.connect(self._on_quick_save)
        file_menu.addAction(save_action)

        file_menu.addSeparator()
        back_action = QAction("返回首页", self)
        back_action.triggered.connect(self._go_home)
        file_menu.addAction(back_action)

        quit_action = QAction("退出", self)
        quit_action.setShortcut("Ctrl+Q")
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        edit_menu = menu.addMenu("编辑")
        self._undo_action = QAction("撤销", self)
        self._undo_action.setShortcut("Ctrl+Z")
        self._undo_action.setEnabled(False)
        self._undo_action.triggered.connect(self._on_undo)
        edit_menu.addAction(self._undo_action)

        self._redo_action = QAction("重做", self)
        self._redo_action.setShortcut("Ctrl+Shift+Z")
        self._redo_action.setEnabled(False)
        self._redo_action.triggered.connect(self._on_redo)
        edit_menu.addAction(self._redo_action)

        view_menu = menu.addMenu("视图")
        fit_action = QAction("适应窗口", self)
        fit_action.setShortcut("Ctrl+0")
        fit_action.triggered.connect(self._editor_page.view.fit_to_window)
        view_menu.addAction(fit_action)

        zoom_in_action = QAction("放大", self)
        zoom_in_action.setShortcut("Ctrl+=")
        zoom_in_action.triggered.connect(
            lambda: self._editor_page.view.apply_zoom(1.15)
        )
        view_menu.addAction(zoom_in_action)

        zoom_out_action = QAction("缩小", self)
        zoom_out_action.setShortcut("Ctrl+-")
        zoom_out_action.triggered.connect(
            lambda: self._editor_page.view.apply_zoom(1.0 / 1.15)
        )
        view_menu.addAction(zoom_out_action)

        account_menu = menu.addMenu("账户")
        self.activation_action = QAction("激活…", self)
        self.activation_action.setEnabled(
            self._activate_device is not None
            and self._activation_status is not None
            and self._clear_activation is not None
        )
        self.activation_action.triggered.connect(self.show_activation_dialog)
        account_menu.addAction(self.activation_action)
        renew_action = QAction("续购时长/次数…", self)
        renew_action.triggered.connect(self._open_renew_dialog)
        account_menu.addAction(renew_action)

    def show_activation_dialog(self) -> None:
        if (
            self._activate_device is None
            or self._activation_status is None
            or self._clear_activation is None
            or self._task_runner is None
        ):
            return
        from src.ui.activation_dialog import ActivationDialog

        dialog = ActivationDialog(
            self._activate_device,
            self._activation_status,
            self._clear_activation,
            self._task_runner,
            self,
            purchase_available=self._payment_client is not None,
            unbind=self._quota_client.unbind if self._quota_client is not None else None,
        )
        dialog.purchase_requested.connect(self._open_purchase_dialog)
        dialog.finished.connect(lambda: self._release_activation_dialog(dialog))
        self._activation_dialog = dialog
        dialog.show()

    def _open_renew_dialog(self) -> None:
        session = self._activation_status() if self._activation_status else None
        code = getattr(session, "code", None) if session else None
        if not code:
            QMessageBox.warning(self, "提示", "请先激活后，再续购时长/次数")
            return
        if self._payment_client is None:
            return
        from src.ui.purchase_dialog import PurchaseDialog

        purchase = PurchaseDialog(
            self._payment_client,
            self._task_runner,
            self,
            renew_code=code,
        )
        purchase.renew_completed.connect(lambda: self._refresh_after_renew(code))
        purchase.show()

    def _refresh_after_renew(self, code: str) -> None:
        if self._activate_device is None:
            return
        try:
            self._activate_device(code)
            QMessageBox.information(self, "续购成功", "时长/次数已更新到当前激活码")
        except Exception as error:
            QMessageBox.warning(self, "提示", f"刷新激活状态失败：{error}")

    def _open_purchase_dialog(self) -> None:
        if self._payment_client is None:
            return
        from src.ui.purchase_dialog import PurchaseDialog

        purchase = PurchaseDialog(self._payment_client, self._task_runner, self)

        def _on_completed(code: str) -> None:
            dialog = self._activation_dialog
            if dialog is not None:
                dialog.code_edit.setText(code)
                dialog.request_activation()

        purchase.purchase_completed.connect(_on_completed)
        purchase.show()

    def _open_purchase_for_plan(self, plan) -> None:
        if self._payment_client is None:
            return
        from src.ui.purchase_dialog import PurchaseDialog

        purchase = PurchaseDialog(
            self._payment_client,
            self._task_runner,
            self,
            preselect_plan_id=plan.plan_id,
        )

        def _on_completed(code: str) -> None:
            dialog = self._activation_dialog
            if dialog is not None:
                dialog.code_edit.setText(code)
                dialog.request_activation()

        purchase.purchase_completed.connect(_on_completed)
        purchase.show()

    def _release_activation_dialog(self, dialog) -> None:
        if self._activation_dialog is dialog:
            self._activation_dialog = None

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        urls = event.mimeData().urls()
        if any(url.isLocalFile() for url in urls):
            event.acceptProposedAction()
            return
        event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        supported = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
        sources: list[Path] = []
        unsupported: list[str] = []
        for url in event.mimeData().urls():
            if not url.isLocalFile():
                continue
            path = Path(url.toLocalFile())
            if path.is_dir():
                sources.extend(
                    item.resolve()
                    for item in sorted(
                        path.iterdir(), key=lambda value: value.name.casefold()
                    )
                    if item.is_file() and item.suffix.lower() in supported
                )
            elif path.is_file() and path.suffix.lower() in supported:
                sources.append(path.resolve())
            else:
                unsupported.append(path.name)
        unique = tuple(dict.fromkeys(sources))
        if len(unique) == 1:
            self._on_import(unique[0])
        elif unique:
            self._editor_page.batch_panel.add_sources(unique)
            self._editor_page.show_batch_dialog()
            self.statusBar().showMessage(
                f"已通过拖拽添加 {len(unique)} 张批量图片"
            )
        if unsupported:
            self.statusBar().showMessage(
                "已忽略不支持的文件：" + "、".join(unsupported[:5]),
                8000,
            )
        if unique:
            event.acceptProposedAction()
        else:
            event.ignore()

    # —— 信号连接 ——

    def _connect_signals(self) -> None:
        # 首页
        self._home_page.image_translation_requested.connect(self._enter_editor)
        self._home_page.product_detail_requested.connect(self._enter_product)
        self._home_page.toolbox_requested.connect(self._enter_toolbox)
        self._home_page.purchase_requested.connect(self._open_purchase_for_plan)

        # EditorPage 核心
        self._editor_page.import_requested.connect(self._on_import)
        self._editor_page.translate_requested.connect(self._on_translate)
        self._editor_page.export_requested.connect(self._on_export)
        self._editor_page.save_requested.connect(self._on_quick_save)
        self._editor_page.feature_requested.connect(self._on_feature_requested)
        self._editor_page.tool_changed.connect(self._on_editor_tool_changed)
        self._editor_page.manual_region_requested.connect(
            self._on_manual_region_selected
        )
        self._editor_page.ai_erase_requested.connect(self._on_ai_erase_requested)
        self._editor_page.crop_requested.connect(self._on_crop_requested)
        self._editor_page.image_transform_requested.connect(
            self._on_image_transform_requested
        )
        self._editor_page.watermark_text_requested.connect(
            self._on_add_text_watermark
        )
        self._editor_page.watermark_image_requested.connect(
            self._on_add_image_watermark
        )
        self._editor_page.layer_state_requested.connect(
            self._on_layer_state_requested
        )
        self._editor_page.watermark_state_requested.connect(
            self._on_watermark_state_requested
        )
        self._editor_page.watermark_edit_requested.connect(
            self._on_watermark_edit_requested
        )
        self._editor_page.watermark_property_requested.connect(
            self._on_watermark_property_requested
        )
        self._editor_page.watermark_delete_requested.connect(
            self._on_delete_watermark
        )
        self._editor_page.watermark_duplicate_requested.connect(
            self._on_duplicate_watermark
        )
        self._editor_page.layer_move_requested.connect(
            self._on_layer_move_requested
        )
        self._editor_page.back_requested.connect(self._go_home)

        # TopBar 操作
        self._editor_page.ocr_requested.connect(self._on_ocr)
        self._editor_page.toggle_original_requested.connect(self._on_toggle_original)
        self._editor_page.split_compare_requested.connect(
            self._on_toggle_split_compare
        )
        self._editor_page.slider_compare_requested.connect(
            self._on_toggle_slider_compare
        )
        self._editor_page.compare_hold_started.connect(
            self._on_compare_hold_started
        )
        self._editor_page.compare_hold_finished.connect(
            self._on_compare_hold_finished
        )
        self._editor_page.toggle_layers_requested.connect(self._on_toggle_layers)
        self._editor_page.undo_requested.connect(self._on_undo)
        self._editor_page.redo_requested.connect(self._on_redo)
        self._editor_page.history_state_changed.connect(
            self._sync_history_actions
        )
        self._editor_page.delete_requested.connect(self._on_delete_layer)
        self._editor_page.duplicate_requested.connect(self._on_duplicate_layer)
        self._editor_page.add_layer_requested.connect(self._on_add_layer)
        self._editor_page.restore_layout_requested.connect(
            self._on_restore_auto_layout
        )
        self._editor_page.zoom_in_requested.connect(
            lambda: self._editor_page.view.apply_zoom(1.15)
        )
        self._editor_page.zoom_out_requested.connect(
            lambda: self._editor_page.view.apply_zoom(1.0 / 1.15)
        )
        self._editor_page.fit_requested.connect(
            self._editor_page.view.fit_to_window
        )

        # 属性编辑
        self._editor_page.edit_requested.connect(self._on_edit)
        self._editor_page.ocr_preview_changed.connect(
            self._on_ocr_preview_changed
        )
        self._editor_page.source_text_changed.connect(self._on_source_text_changed)
        self._editor_page.translated_text_changed.connect(
            self._on_translated_text_changed
        )
        self._editor_page.manual_translate_requested.connect(
            self._on_manual_translate_text
        )
        self._editor_page.retranslate_requested.connect(self._on_retranslate_region)
        self._editor_page.confirm_review_requested.connect(
            self._on_retranslate_region
        )
        self._editor_page.keep_original_requested.connect(
            self._on_keep_original_region
        )

        # 翻译取消
        self._editor_page.translate_controls.cancel_requested.connect(self._on_cancel_translate)

        # Model
        self._editor_page.set_model(self._model)
        self._editor_page.translate_controls.set_service_status(
            self._translation_service_label,
            self._translation_service_available,
        )
        self._editor_page.translate_controls.brand_terms.editingFinished.connect(
            self._persist_protection_terms
        )
        self._editor_page.translate_controls.model_terms.editingFinished.connect(
            self._persist_protection_terms
        )
        controls = self._editor_page.translate_controls
        self._terminology_timer = QTimer(self)
        self._terminology_timer.setSingleShot(True)
        self._terminology_timer.setInterval(400)
        self._terminology_timer.timeout.connect(self._persist_terminology)
        controls.terminology_editor.textChanged.connect(
            self._schedule_terminology_save
        )
        controls.ocr_language.currentIndexChanged.connect(
            self._show_current_terminology
        )
        controls.source_language.currentIndexChanged.connect(
            self._show_current_terminology
        )
        controls.target_language.currentIndexChanged.connect(
            self._show_current_terminology
        )
        controls.all_mode_radio.toggled.connect(
            self._show_current_terminology
        )
        controls.specific_mode_radio.toggled.connect(
            self._show_current_terminology
        )
        batch = self._editor_page.batch_panel
        batch.set_target_language(controls.selected_target_language)
        controls.target_language.currentIndexChanged.connect(
            lambda *_: batch.set_target_language(controls.selected_target_language)
        )
        batch.add_requested.connect(self._choose_batch_images)
        batch.add_folder_requested.connect(self._choose_batch_folder)
        batch.remove_requested.connect(batch.remove_selected_sources)
        batch.clear_requested.connect(batch.clear_batch)
        batch.start_requested.connect(self._on_start_batch)
        batch.pause_requested.connect(self._on_pause_batch)
        batch.resume_requested.connect(self._on_resume_batch)
        batch.cancel_requested.connect(self._on_cancel_batch)
        batch.retry_failed_requested.connect(self._on_retry_failed_batch)
        batch.export_requested.connect(self._on_export_batch)
        batch.preview_requested.connect(self._on_preview_batch_item)
        batch.send_to_editor_requested.connect(self._on_send_batch_to_editor)
        batch.set_available(self._run_batch is not None, False)
        self.batch_snapshot_changed.connect(
            self._on_batch_snapshot_changed,
            Qt.ConnectionType.QueuedConnection,
        )
        # 工作台左侧图片列表：点击切换文档
        self._editor_page.image_list_panel.document_activated.connect(
            self._on_activate_document
        )
        self._editor_page.remove_document_requested.connect(
            self._on_remove_document
        )
        self._load_terminology()

    # —— 操作 ——

    def _enter_editor(self) -> None:
        self._stack.setCurrentWidget(self._editor_page)
        # 加载持久化的品牌词到 UI
        if self._brand_terms:
            self._editor_page.translate_controls.set_configured_brand_terms(
                self._brand_terms
            )
        if self._model_terms:
            self._editor_page.translate_controls.set_configured_model_terms(
                self._model_terms
            )
        self.statusBar().showMessage("导入图片开始编辑")

    def _persist_protection_terms(self) -> None:
        controls = self._editor_page.translate_controls
        try:
            if self._brand_terms_preferences is not None:
                self._brand_terms_preferences.save(
                    controls.configured_brand_terms
                )
            if self._model_terms_preferences is not None:
                self._model_terms_preferences.save(
                    controls.configured_model_terms
                )
        except Exception as error:
            self.statusBar().showMessage(f"保护词保存失败：{error}", 7000)

    def _load_terminology(self) -> None:
        try:
            values = (
                self._terminology_preferences.load()
                if self._terminology_preferences is not None
                else (
                    self._terminology_catalog.snapshot()
                    if self._terminology_catalog is not None
                    else ()
                )
            )
            self._terminology_entries = normalize_terminology_entries(values)
            if self._terminology_catalog is not None:
                self._terminology_catalog.replace(self._terminology_entries)
            self._show_current_terminology()
        except Exception as error:
            self.statusBar().showMessage(f"术语表加载失败：{error}", 7000)

    def _terminology_pair(self) -> tuple[str, str]:
        controls = self._editor_page.translate_controls
        mode = TranslationMode(controls.selected_mode)
        source = (
            controls.selected_source_language
            if mode is TranslationMode.SPECIFIC_LANGUAGE
            else controls.selected_ocr_language
        )
        return str(source or controls.selected_ocr_language), controls.selected_target_language

    def _show_current_terminology(self, *_: object) -> None:
        if self._updating_terminology:
            return
        source, target = self._terminology_pair()
        self._updating_terminology = True
        try:
            self._editor_page.translate_controls.set_terminology_entries(
                source,
                target,
                self._terminology_entries,
            )
        finally:
            self._updating_terminology = False

    def _schedule_terminology_save(self) -> None:
        if not self._updating_terminology:
            self._terminology_timer.start()

    def _persist_terminology(self) -> None:
        controls = self._editor_page.translate_controls
        source, target = self._terminology_pair()
        try:
            configured = controls.configured_terminology_entries(source, target)
            retained = tuple(
                entry
                for entry in self._terminology_entries
                if (
                    entry.source_language != source
                    or entry.target_language != target
                    or not entry.enabled
                )
            )
            entries = normalize_terminology_entries((*retained, *configured))
            if self._terminology_catalog is not None:
                self._terminology_catalog.replace(entries)
            if self._terminology_preferences is not None:
                self._terminology_preferences.save(entries)
            self._terminology_entries = entries
            controls.terminology_status.setText(
                f"当前语言对：{source} → {target} · 已保存 {len(configured)} 条"
            )
        except Exception as error:
            controls.terminology_status.setText(f"术语表未保存：{error}")

    def _choose_batch_images(self) -> None:
        values, _ = QFileDialog.getOpenFileNames(
            self,
            "添加批量图片",
            "",
            "图片 (*.jpg *.jpeg *.png *.webp *.bmp)",
        )
        if values:
            self._editor_page.batch_panel.add_sources(
                tuple(Path(value) for value in values)
            )

    def _choose_batch_folder(self) -> None:
        value = QFileDialog.getExistingDirectory(self, "选择图片文件夹")
        if not value:
            return
        directory = Path(value)
        suffixes = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
        sources = tuple(
            path
            for path in sorted(directory.iterdir(), key=lambda item: item.name.casefold())
            if path.is_file() and path.suffix.lower() in suffixes
        )
        if not sources:
            self.statusBar().showMessage("所选文件夹没有支持的图片")
            return
        self._editor_page.batch_panel.add_sources(sources)

    def _on_start_batch(self) -> None:
        if self._run_batch is None or self._task_runner is None:
            return
        panel = self._editor_page.batch_panel
        sources = panel.sources
        if not sources:
            return
        if not self._check_translation_access():
            return
        ctrl = self._editor_page.translate_controls
        selection = self._translation_selection(panel.selected_target_language)
        panel.set_available(True, True)
        self.statusBar().showMessage(f"正在批量处理 {len(sources)} 张图片…")
        self._task_runner.submit(
            lambda: self._run_batch.execute(
                sources,
                ctrl.selected_ocr_language,
                selection,
                ctrl.configured_protection_terms,
                self.batch_snapshot_changed.emit,
                allow_low_confidence=ctrl.should_process_low_confidence,
                automatic_confidence_threshold=(
                    ctrl.automatic_confidence_threshold
                    if ctrl.automatic_confidence_threshold != 0.75
                    else None
                ),
                preserve_numbers=ctrl.should_preserve_numbers,
                ocr_mode=panel.selected_ocr_mode,
                high_recall_options=ctrl.configured_high_recall_options,
            ),
            self._on_batch_finished,
            self._on_batch_failed,
        )

    def _on_batch_snapshot_changed(self, value: object) -> None:
        if not isinstance(value, BatchSnapshot):
            return
        self._batch_snapshot = value
        self._editor_page.batch_panel.set_snapshot(value)
        self._editor_page.batch_panel.set_available(
            self._run_batch is not None,
            value.status
            in {
                BatchStatus.RUNNING,
                BatchStatus.PAUSING,
                BatchStatus.PAUSED,
            },
        )

    def _on_batch_finished(self, value: object) -> None:
        self._on_batch_snapshot_changed(value)
        if isinstance(value, BatchSnapshot):
            self.statusBar().showMessage(
                f"批量完成：成功 {value.completed_count}，失败 {value.failed_count}，"
                f"取消 {value.cancelled_count}"
            )

    def _on_batch_failed(self, error: Exception) -> None:
        panel = self._editor_page.batch_panel
        panel.set_available(
            self._run_batch is not None, False
        )
        panel.set_error(str(error) or type(error).__name__)
        self.statusBar().showMessage(f"批量处理失败：{error}", 8000)

    def _on_cancel_batch(self) -> None:
        if self._run_batch is not None:
            self._run_batch.cancel()
            self.statusBar().showMessage("正在取消剩余批量任务…")

    def _on_pause_batch(self) -> None:
        if self._run_batch is not None:
            self._run_batch.pause()
            self.statusBar().showMessage("当前图片完成后将暂停批次…")

    def _on_resume_batch(self) -> None:
        if self._run_batch is not None:
            self._run_batch.resume()
            self.statusBar().showMessage("批量任务已恢复")

    def _on_retry_failed_batch(self) -> None:
        panel = self._editor_page.batch_panel
        failed = panel.failed_sources
        if not failed:
            return
        panel.replace_sources(failed)
        self._on_start_batch()

    def _on_export_batch(self) -> None:
        if (
            self._export_batch_selection is None
            or self._batch_snapshot is None
            or self._task_runner is None
        ):
            return
        directory = QFileDialog.getExistingDirectory(self, "选择批量导出目录")
        if not directory:
            return
        panel = self._editor_page.batch_panel
        selected = panel.selected_result_ids
        suffix = panel.selected_output_suffix
        config = panel.batch_export_config

        def build_options() -> BatchExportOptions:
            watermark = None
            if bool(config["watermark_enabled"]):
                kind = str(config["watermark_kind"])
                value = str(config["watermark_value"])
                if kind == "text":
                    watermark = BatchWatermarkOptions(
                        "text",
                        float(config["watermark_opacity"]),
                        bool(config["watermark_tiled"]),
                        str(config["watermark_position"]),
                        text=value,
                        style=TextStyle(
                            resolve_system_font("zh-Hans"),
                            32,
                            (255, 255, 255),
                            stroke_rgb=(0, 0, 0),
                            stroke_width=1,
                            font_weight=600,
                        ),
                    )
                else:
                    if self._codec is None or not value:
                        raise ValueError("请选择批量水印图片")
                    watermark_image = self._codec.load(
                        Path(value),
                        ImageLimits(
                            min_width=1,
                            min_height=1,
                            max_bytes=50 * 1024 * 1024,
                        ),
                    )
                    watermark = BatchWatermarkOptions(
                        "image",
                        float(config["watermark_opacity"]),
                        bool(config["watermark_tiled"]),
                        str(config["watermark_position"]),
                        image=watermark_image,
                    )
            return BatchExportOptions(
                quality=int(config["quality"]),
                resize_mode=BatchResizeMode(str(config["resize_mode"])),
                resize_value=int(config["resize_value"]),
                watermark=watermark,
                subdirectory_name=(
                    str(config["subdirectory_name"])
                    or f"优译图AI-{self._batch_snapshot.batch_id[-8:]}"
                    if bool(config["separate_subdirectory"])
                    else None
                ),
            )

        self._task_runner.submit(
            lambda: self._export_batch_selection.execute(
                self._batch_snapshot,
                selected,
                Path(directory),
                suffix,
                build_options(),
            ),
            lambda result: self._on_batch_export_finished(
                result,
                Path(directory),
            ),
            lambda error: self.statusBar().showMessage(
                f"批量导出失败：{error}", 8000
            ),
        )

    def _on_batch_export_finished(
        self,
        result: object,
        requested_directory: Path,
    ) -> None:
        succeeded_count = int(getattr(result, "succeeded_count", 0))
        failed_count = int(getattr(result, "failed_count", 0))
        item_results = tuple(getattr(result, "items", ()))
        target_directories = {
            item.target.parent
            for item in item_results
            if getattr(item, "target", None) is not None
        }
        output_directory = next(iter(target_directories), requested_directory)
        summary = (
            f"成功导出 {succeeded_count} 张图片。\n\n"
            f"导出路径：\n{output_directory}"
        )
        self.statusBar().showMessage(
            f"批量导出完成：成功 {succeeded_count}，失败 {failed_count}",
            8000,
        )
        if failed_count:
            QMessageBox.warning(
                self,
                "批量导出部分完成",
                f"{summary}\n\n失败 {failed_count} 张，请查看批量结果。",
            )
        else:
            QMessageBox.information(self, "批量导出成功", summary)

    def _on_preview_batch_item(self, item_id: str) -> None:
        if (
            self._batch_snapshot is None
            or self._batch_result_store is None
            or self._task_runner is None
        ):
            return
        item = next(
            (
                candidate
                for candidate in self._batch_snapshot.items
                if candidate.item_id == item_id
            ),
            None,
        )
        if item is None or not item.result_ref:
            return

        def operation():
            return (
                self._batch_result_store.load(item.result_ref),
                self._import_usecase.execute(item.source),
            )

        self._task_runner.submit(
            operation,
            lambda value: self._show_batch_preview(item.source, value),
            lambda error: self.statusBar().showMessage(
                f"批量预览失败：{error}", 8000
            ),
        )

    def _show_batch_preview(self, source: Path, value: object) -> None:
        rendered, original = value
        self._model.document = rendered
        self._model.source_document = original
        self._model.rendered_document = rendered
        self._model.translation_result = None
        self._model.composition_editor = None
        self._model.text_layout = TextLayout(())
        self._editor_page.set_original_document(original)
        self._editor_page.set_document(rendered)
        self._editor_page.top_bar.set_file_name(f"批量预览 · {source.name}")
        self._editor_page.top_bar.set_has_image(True)
        self._editor_page.top_bar.set_has_result(True)
        self._editor_page.export_settings.set_export_enabled(True)
        self._sync_history_actions(False, False)
        self._editor_page.batch_dialog.hide()
        self._stack.setCurrentWidget(self._editor_page)
        self._editor_page.view.fit_to_window()
        self.statusBar().showMessage(f"正在预览批量结果：{source.name}")

    # —— 批量图片进入工作台 ——

    def _on_send_batch_to_editor(self) -> None:
        """将批量面板中的图片逐张送入工作台编辑（无需先翻译）。"""
        batch = self._editor_page.batch_panel
        sources = batch.sources
        if not sources:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(
                self, "发送到工作台",
                "批量面板中没有图片。\n请先添加图片。",
            )
            return
        if self._task_runner is None:
            return

        self.statusBar().showMessage(
            f"正在加载 {len(sources)} 张图片到工作台...")

        def operation():
            loaded = []
            for source in sources:
                try:
                    doc = self._import_usecase.execute(source)
                    loaded.append((source, doc))
                except Exception as exc:
                    print(f"[BatchToEditor] 加载失败 {source.name}: {exc}")
            return loaded

        def on_success(loaded):
            if not loaded:
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.warning(self, "发送到工作台", "图片加载失败，请检查文件。")
                return
            for source, doc in loaded:
                self._model.add_document(source, doc, name=source.name)
            # 切换到第一张
            first = self._model.documents()[0].doc_id
            self._model.set_active_document(first)
            self._load_active_document()
            self._editor_page.batch_dialog.hide()
            self.statusBar().showMessage(
                f"已发送 {len(loaded)} 张图片到工作台，可点击左侧列表切换编辑")

        def on_error(error: Exception):
            self.statusBar().showMessage(f"加载图片到工作台失败：{error}", 8000)

        self._task_runner.submit(operation, on_success, on_error)

    def _on_activate_document(self, doc_id: str) -> None:
        """点击左侧图片列表切换工作台文档。"""
        self._model.set_active_document(doc_id)
        self._load_active_document()

    def _on_remove_document(self, doc_id: str) -> None:
        """从工作台移除一张图片（不影响磁盘文件）。"""
        ref = next(
            (d for d in self._model.documents() if d.doc_id == doc_id),
            None,
        )
        if ref is None:
            return
        was_active = self._model.active_document_id == doc_id
        self._model.remove_document(doc_id)
        if was_active:
            if self._model.active_document() is not None:
                self._load_active_document()
            else:
                self._clear_active_editor()
        self.statusBar().showMessage(f"已从工作台移除：{ref.name}")

    def _clear_active_editor(self) -> None:
        """工作台无剩余文档时清空画布。"""
        self._model.document = None
        self._model.source_document = None
        self._model.ocr_result = None
        self._model.translation_result = None
        self._model.composition_editor = None
        self._model.rendered_document = None
        self._ocr_preview_layers.clear()
        self._ocr_preview_boxes.clear()
        self._ocr_original_texts.clear()
        self._model.selected_layer_id = None
        self._model.text_layout = TextLayout(())
        self._model.showing_original = False
        self._quick_save_path = None
        self._source_undo.clear()
        self._source_redo.clear()
        self._undo_stack.clear()
        self._editor_page.scene.clear_regions()
        self._editor_page.ocr_result_panel.clear_result()
        self._editor_page.set_text_layout(self._model.text_layout)
        self._editor_page.clear_layer_selection()
        self._editor_page.translate_controls.reset_progress()
        self._editor_page.top_bar.set_file_name("")
        self._editor_page.top_bar.set_has_image(False)
        self._editor_page.top_bar.set_has_result(False)
        self._editor_page.top_bar.set_has_layers(False)
        self._editor_page.top_bar.set_showing_original(False)
        self._editor_page.top_bar.set_split_view(False)
        self._editor_page.top_bar.set_zoom(100)
        self._sync_history_actions(False, False)
        self._editor_page.export_settings.set_export_enabled(False)
        self.statusBar().showMessage("工作台已无图片")

    def _sync_translation_activity_for_active_document(self) -> None:
        """Keep an in-flight translation visible while documents are switched."""
        running = self._translation_document_id is not None
        self._model.translating = running
        controls = self._editor_page.translate_controls
        top_bar = self._editor_page.top_bar
        if getattr(top_bar, "_translating", False) != running:
            top_bar.set_translating(running)
        controls.set_translating(running)
        if not running:
            return
        if self._model.active_document_id == self._translation_document_id:
            if self._translation_stage is None:
                controls.set_preparing()
            else:
                controls.set_stage(self._translation_stage)
            self.statusBar().showMessage("正在翻译当前图片…")
        else:
            controls.set_preparing()
            self.statusBar().showMessage("另一张图片正在后台翻译，可切回查看进度")

    def _load_active_document(self) -> None:
        """把当前活动文档加载到画布（编辑状态已由模型快照恢复）。"""
        ref = self._model.active_document()
        if ref is None:
            return
        source = ref.source_document
        rendered = self._model.rendered_document or source
        self._model.document = rendered
        self._model.source_document = source
        self._model.selected_layer_id = None
        self._model.showing_original = False
        self._model.preview_mode = "layers"
        self._hold_preview_mode = None
        self._quick_save_path = None
        self._source_undo.clear()
        self._source_redo.clear()
        self._undo_stack.clear()
        self._editor_page.scene.clear_regions()
        self._editor_page.set_document(rendered)
        self._editor_page.set_original_document(source)
        self._editor_page.set_split_view(False)
        self._editor_page.set_slider_compare(False)
        self._editor_page.set_text_layout(self._model.text_layout)
        self._editor_page.clear_layer_selection()
        self._editor_page.translate_controls.reset_progress()

        result = self._model.translation_result
        if isinstance(result, TranslateImageResult):
            self._editor_page.ocr_result_panel.set_result(
                result.ocr, result.translation
            )
        elif self._model.ocr_result is not None:
            self._editor_page.ocr_result_panel.set_result(
                self._model.ocr_result
            )
        else:
            self._editor_page.ocr_result_panel.clear_result()

        asset = source.asset
        self._editor_page.top_bar.set_file_name(asset.source_path.name)
        self._editor_page.top_bar.set_has_image(True)
        self._editor_page.top_bar.set_has_result(result is not None)
        self._editor_page.top_bar.set_export_available(source is not None)
        has_layers = len(self._model.text_layout.layers) > 0
        self._editor_page.top_bar.set_has_layers(has_layers)
        # Each workbench document owns its composition editor and therefore
        # its own history. Restore that state when switching documents.
        editor = self._model.composition_editor
        if editor is not None:
            self._sync_history_actions(editor.can_undo, editor.can_redo)
        else:
            self._sync_history_actions(bool(self._source_undo), bool(self._source_redo))
        # A loaded document is a valid export source even when it only has an
        # OCR result and no TranslateImageResult yet.
        self._editor_page.export_settings.set_export_enabled(source is not None)
        self._editor_page.top_bar.set_showing_original(False)
        self._editor_page.top_bar.set_split_view(False)
        self._editor_page.top_bar.set_zoom(100)

        self._stack.setCurrentWidget(self._editor_page)
        self.statusBar().showMessage(
            f"已切换：{asset.source_path.name}  {asset.width}×{asset.height}"
        )
        self._editor_page.view.fit_to_window()
        self._sync_translation_activity_for_active_document()

    def _go_home(self) -> None:
        self._stack.setCurrentWidget(self._home_page)
        self.statusBar().showMessage("就绪")

    @property
    def _product_window(self) -> object | None:
        return getattr(self, "__product_window", None)

    @_product_window.setter
    def _product_window(self, value: object | None) -> None:
        self.__product_window = value

    def _enter_product(self) -> None:
        """打开商品详情生成窗口（LLM 由服务端代理）。"""
        from src.ui.product.product_window import ProductWindow
        from src.infrastructure.server_llm_adapter import ServerLLMAdapter

        llm_adapter = ServerLLMAdapter(self._backend_url, self._access_token)
        win = ProductWindow(
            task_runner=self._task_runner,
            codec=self._codec,
            ocr_adapter=getattr(self._recognize_text, "_adapter", self._recognize_text),
            llm_adapter=llm_adapter,
            quota_client=self._quota_client,
            access_token=self._access_token,
        )
        win.back_requested.connect(self._on_product_back)
        self._product_window = win
        self.hide()
        win.show()

    def _on_product_back(self) -> None:
        if self._product_window:
            self._product_window.close()
            self._product_window = None
        self.show()

    # —— 图片工具箱 ——

    def _create_toolbox_page(self) -> "ToolBoxPage":
        from src.ui.toolbox.tool_box_page import ToolBoxPage
        page = ToolBoxPage()
        page.set_task_runner(self._task_runner)
        page.set_codec(self._codec)
        page.back_requested.connect(self._go_home)
        return page

    def _enter_toolbox(self) -> None:
        self._stack.setCurrentWidget(self._toolbox_page)
        self.statusBar().showMessage("图片工具箱：导入图片开始操作")

    # —— 导入 ——

    def _on_import(self, source: Path) -> None:
        # 检查未保存修改
        if self._model.is_dirty:
            from PySide6.QtWidgets import QMessageBox
            reply = QMessageBox.question(
                self, "未保存的修改",
                "当前项目有未导出的修改。导入新图片会丢失这些修改。\n\n确定要导入新图片吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        if self._task_runner is not None:
            self.statusBar().showMessage(f"正在导入 {source.name}…")
            self._task_runner.submit(
                lambda: load_document(source, self._import_usecase, self._codec),
                self._on_image_loaded,
                self._on_import_failed,
            )
            return
        if self._codec is None:
            self.statusBar().showMessage("图片编解码器不可用")
            return
        try:
            document = load_document(source, self._import_usecase, self._codec)
        except Exception as exc:
            self._on_import_failed(exc)
            return
        self._on_image_loaded(document)

    def _on_image_loaded(self, value: object) -> None:
        if not isinstance(value, ImageDocument):
            self._on_import_failed(TypeError("导入返回了无效结果"))
            return

        document: ImageDocument = value
        # 单张导入也登记到工作台文档列表
        self._model.add_document(
            document.asset.source_path, document, name=document.asset.source_path.name
        )
        self._model.document = document
        self._model.source_document = document
        self._model.ocr_result = None
        self._model.translation_result = None
        self._model.composition_editor = None
        self._model.rendered_document = None
        self._ocr_preview_layers.clear()
        self._ocr_preview_boxes.clear()
        self._ocr_original_texts.clear()
        self._model.selected_layer_id = None
        self._model.showing_original = False
        self._quick_save_path = None
        self._source_undo.clear()
        self._source_redo.clear()
        self._undo_stack.clear()
        self._editor_page.scene.clear_regions()
        self._editor_page.ocr_result_panel.clear_result()
        self._editor_page.set_document(document)
        self._editor_page.set_original_document(document)
        self._editor_page.set_split_view(False)
        self._editor_page.set_slider_compare(False)
        self._editor_page.set_text_layout(self._model.text_layout)
        self._editor_page.clear_layer_selection()
        self._editor_page.translate_controls.reset_progress()

        asset = document.asset
        self._editor_page.top_bar.set_file_name(asset.source_path.name)
        self._editor_page.top_bar.set_has_image(True)
        self._editor_page.top_bar.set_has_result(False)
        self._editor_page.top_bar.set_export_available(True)
        self._editor_page.top_bar.set_has_layers(False)
        self._sync_history_actions(False, False)
        # Keep export available after OCR-only workflows; the source document
        # remains the export fallback until a rendered result exists.
        self._editor_page.export_settings.set_export_enabled(True)
        self._editor_page.top_bar.set_showing_original(False)
        self._editor_page.top_bar.set_split_view(False)
        self._editor_page.top_bar.set_zoom(100)

        self._stack.setCurrentWidget(self._editor_page)
        self.statusBar().showMessage(
            f"已导入：{asset.source_path.name}  {asset.width}×{asset.height}"
        )
        self._editor_page.view.fit_to_window()

    def _on_import_failed(self, error: Exception) -> None:
        title, msg, suggestion = classify_error(error)
        self.statusBar().showMessage(f"{title}：{msg}。{suggestion}", 10000)
        from src.domain.image import ImageValidationError

        if isinstance(error, ImageValidationError):
            from PySide6.QtWidgets import QMessageBox

            QMessageBox.warning(self, title, f"{msg}\n\n{suggestion}")

    def _apply_image_limits_refresh(self) -> None:
        """启动时同步远程图片限制，并在状态栏显示结果（便于排查）。"""
        try:
            result = self._refresh_image_limits()
        except Exception as error:  # noqa: BLE001
            self.statusBar().showMessage(f"图片限制同步失败：{error}", 10000)
            return
        if getattr(result, "remote_applied", False):
            limits = result.limits
            self.statusBar().showMessage(
                f"图片限制已同步：{limits.min_width}×{limits.min_height} ~ "
                f"{limits.max_width}×{limits.max_height}，≤{limits.max_bytes} 字节",
                10000,
            )
        else:
            self.statusBar().showMessage(
                f"图片限制未生效：{getattr(result, 'warning', '未知原因')}",
                10000,
            )

    # —— OCR ——

    def _on_ocr(self) -> None:
        """独立 OCR 识别（不翻译），在当前图片上运行 OCR 并显示识别区域。"""
        if self._recognize_text is None or self._task_runner is None:
            self.statusBar().showMessage("OCR 服务不可用")
            return
        document = self._model.source_document
        if document is None:
            self.statusBar().showMessage("请先导入图片")
            return

        ctrl = self._editor_page.translate_controls
        ocr_language = ctrl.selected_ocr_language

        self._model.ocr_started.emit()
        self._editor_page.top_bar.set_translating(True)
        ctrl.set_translating(True)
        ctrl.set_preparing()
        ctrl.cancel_button.setVisible(False)  # 独立 OCR 无取消操作
        self._editor_page.right_tabs.setCurrentIndex(1)  # 跳转 OCR 结果页
        self.statusBar().showMessage(f"正在 OCR 识别（{ocr_language}）…")

        self._task_runner.submit(
            lambda: self._recognize_text.execute(
                document,
                ocr_language,
                ctrl.selected_ocr_mode,
                ctrl.configured_high_recall_options,
                fast=True,
            ),
            self._on_ocr_succeeded,
            self._on_ocr_failed,
        )

    def _on_ocr_succeeded(self, value: object) -> None:
        from src.domain.ocr import OcrResult
        if not isinstance(value, OcrResult):
            self._on_ocr_failed(TypeError("OCR 返回了无效结果"))
            return

        result: OcrResult = value
        self._model.ocr_result = result
        self._ocr_preview_boxes = {
            region.region_id: self._ocr_preview_box(region)
            for region in result.regions
        }
        self._ocr_original_texts = {
            region.region_id: region.text for region in result.regions
        }
        self._model.ocr_elapsed_ms = result.elapsed_ms
        self._editor_page.top_bar.set_translating(False)
        self._editor_page.translate_controls.set_translating(False)
        self._editor_page.translate_controls.reset_progress()

        self._editor_page.scene.set_regions(result.regions)
        self._editor_page.ocr_result_panel.set_result(result)

        region_count = len(result.regions)
        self.statusBar().showMessage(
            f"OCR 完成：识别到 {region_count} 个文字区域（{result.elapsed_ms:.0f}ms）"
        )
        self._model.ocr_finished.emit(result)

    def _on_ocr_failed(self, error: Exception) -> None:
        self._editor_page.top_bar.set_translating(False)
        self._editor_page.translate_controls.set_translating(False)
        self._editor_page.translate_controls.reset_progress()
        title, msg, suggestion = classify_error(error)
        self.statusBar().showMessage(f"{title}：{msg}。{suggestion}")

    # —— 翻译 ——

    def _check_translation_access(self) -> bool:
        """图片翻译前检查是否已激活且时长未过期；未购买时长包弹窗提示。"""
        try:
            session = self._activation_status() if self._activation_status else None
        except Exception:
            session = None
        if session is None or not getattr(session, "active", False):
            from PySide6.QtWidgets import QMessageBox

            QMessageBox.warning(self, "提示", "您还没有可用的翻译时长，请先购买时长包")
            return False
        return True

    def _on_translate(self, ocr_language: str, target_language: str) -> None:
        if self._translation_document_id is not None:
            self.statusBar().showMessage("已有图片正在翻译，请等待完成或先取消")
            return
        if self._translate_image is None or self._task_runner is None:
            self.statusBar().showMessage("翻译服务不可用")
            return
        document = self._model.source_document
        if document is None:
            self.statusBar().showMessage("请先导入图片")
            return
        if not self._check_translation_access():
            return

        translating_doc_id = self._model.active_document_id
        self._translation_document_id = translating_doc_id
        self._translation_stage = None
        self._model.translating = True
        self._model.translation_started.emit()
        self._editor_page.translate_controls.set_translating(True)
        self._editor_page.translate_controls.set_preparing()
        self._editor_page.top_bar.set_translating(True)
        self._editor_page.right_tabs.setCurrentIndex(1)  # 跳转 OCR 结果页
        self._undo_stack.clear()
        self._sync_history_actions(False, False)

        ctrl = self._editor_page.translate_controls
        mode = TranslationMode(ctrl.selected_mode)
        source_lang = ctrl.selected_source_language if mode is TranslationMode.SPECIFIC_LANGUAGE else None
        selection = TranslationSelection(
            mode=mode,
            target_language=target_language,
            source_language=source_lang,
        )
        brand_terms = ctrl.configured_protection_terms

        def on_stage(stage: ImageStage) -> None:
            self._translation_stage = stage
            if self._model.active_document_id == translating_doc_id:
                self._model.translation_stage_changed.emit(stage)

        self.statusBar().showMessage(
            f"正在翻译（OCR：{ocr_language} → 目标：{target_language}）…"
        )

        self._task_runner.submit(
            lambda: self._translate_image.execute(
                document,
                ocr_language,
                selection,
                brand_terms,
                on_stage,
                ocr_mode=ctrl.selected_ocr_mode,
                high_recall_options=ctrl.configured_high_recall_options,
                allow_low_confidence=ctrl.should_process_low_confidence,
                automatic_confidence_threshold=ctrl.automatic_confidence_threshold,
                preserve_numbers=ctrl.should_preserve_numbers,
            ),
            lambda value: self._on_translation_succeeded(
                value, translating_doc_id
            ),
            lambda error: self._on_translation_failed(error, translating_doc_id),
        )

    def _on_translation_succeeded(
        self,
        value: object,
        doc_id: str | None = None,
    ) -> None:
        if not isinstance(value, TranslateImageResult):
            self._on_translation_failed(TypeError("翻译返回了无效结果"), doc_id)
            return

        if doc_id == self._translation_document_id:
            self._translation_document_id = None
            self._translation_stage = None

        result: TranslateImageResult = value
        self._ocr_preview_layers.clear()
        self._ocr_preview_boxes = {
            region.region_id: self._ocr_preview_box(region)
            for region in result.ocr.regions
        }
        self._ocr_original_texts = {
            region.region_id: region.text for region in result.ocr.regions
        }
        # 仅 OCR 阶段用户修改的几何/文字样式，在正式生成文字图层前应用。
        result = replace(
            result,
            layout=self._editor_page.apply_ocr_property_overrides(result.layout),
        )

        # 定位本次翻译的目标文档（翻译期间用户可能已切到其他图片）
        target_ref = None
        if doc_id is not None:
            target_ref = next(
                (
                    ref
                    for ref in self._model.documents()
                    if ref.doc_id == doc_id
                ),
                None,
            )
        if target_ref is None:
            target_ref = self._model.active_document()
        # 无目标文档（未登记到工作台）时按活动文档处理
        is_active = (
            target_ref is None
            or self._model.active_document_id == target_ref.doc_id
        )

        # 水印与源图必须取目标文档的，不能取当前 model 状态
        existing_watermarks = (
            target_ref.composition_editor.watermarks
            if target_ref is not None
            and target_ref.composition_editor is not None
            else ()
        )
        source_document = (
            target_ref.source_document
            if target_ref is not None
            else self._model.source_document
        )
        editor = None
        if self._create_composition_editor is not None:
            editor = self._create_composition_editor.execute(
                result.repair.result.document,
                result.document,
                result.layout,
                source_document,
                record_initial_translation=True,
                initial_watermarks=existing_watermarks,
            )
            result = replace(result, document=editor.document)

        # 翻译结果写回目标文档（后台完成时画布不更新，切回时可见）
        if target_ref is not None:
            target_ref.translation_result = result
            target_ref.ocr_result = result.ocr
            target_ref.text_layout = result.layout
            target_ref.composition_editor = editor
            target_ref.rendered_document = result.document
            target_ref.repaired_background = result.repair.result.document
            target_ref.is_dirty = True

        if not is_active:
            # 用户已切到其他文档：仅保存结果，不打扰当前画布
            self._sync_translation_activity_for_active_document()
            self._editor_page.translate_controls.reset_progress()
            active_ref = self._model.active_document()
            if active_ref is not None:
                self._editor_page.top_bar.set_file_name(active_ref.name)
            name = target_ref.name if target_ref is not None else "该图片"
            self.statusBar().showMessage(
                f"「{name}」翻译完成，可切换到该图片查看结果"
            )
            return

        self._model.translating = False
        self._model.translation_result = result
        self._model.ocr_result = result.ocr
        self._model.is_dirty = True
        if editor is not None:
            self._model.composition_editor = editor
            self._model.translation_result = result
            self._sync_history_actions(editor.can_undo, editor.can_redo)

        self._model.text_layout = result.layout
        self._model.rendered_document = result.document
        self._model.repaired_background = result.repair.result.document
        self._model.showing_original = False

        # 原图 View 始终显示原始图片
        if self._model.source_document is not None:
            self._editor_page.set_original_document(self._model.source_document)

        # 翻译完成后先显示冻结算法生成的成品图；辅助层仅在编辑模式显示。
        self._editor_page.scene.clear_regions()
        self._editor_page.ocr_result_panel.set_result(
            result.ocr,
            result.translation,
        )
        self._editor_page.scene.set_erase_mask(result.repair.erase_mask)
        self._editor_page.set_text_layout(result.layout)
        self._editor_page.top_bar.set_has_result(True)
        self._editor_page.top_bar.set_has_layers(len(result.layout.layers) > 0)
        self._editor_page.top_bar.set_translating(False)
        self._editor_page.top_bar.set_showing_original(False)
        self._apply_preview_mode("translated")

        if result.layout.layers:
            self._model.selected_layer_id = result.layout.layers[0].region_id

        self._editor_page.refit_canvas_views()

        # 翻译摘要统计
        units = result.translation.units
        ocr_count = len(result.ocr.regions) if result.ocr else 0
        translated = sum(1 for u in units if u.status.value == "translated")
        review = sum(1 for u in units if u.status.value == "review_required")
        skipped = sum(1 for u in units if u.status.value in ("skipped_language", "skipped_protected"))
        failed = sum(1 for u in units if u.status.value == "failed")
        overflow = sum(1 for layer in result.layout.layers if layer.overflow)

        ocr_ms = result.ocr.elapsed_ms if result.ocr else 0
        total_ms = result.translation.elapsed_ms
        self._model.ocr_elapsed_ms = ocr_ms
        self._model.translation_elapsed_ms = total_ms

        self._editor_page.translate_controls.set_summary(
            ocr_count, translated, review, skipped, failed, overflow,
            ocr_ms=ocr_ms, total_ms=total_ms,
        )
        self._model.translation_finished.emit(result)

    def _on_translation_failed(
        self,
        error: Exception,
        doc_id: str | None = None,
    ) -> None:
        if doc_id is None or doc_id == self._translation_document_id:
            self._translation_document_id = None
            self._translation_stage = None
        self._model.translating = self._translation_document_id is not None
        self._model.translation_failed.emit(str(error))
        self._editor_page.translate_controls.reset_progress()
        self._sync_translation_activity_for_active_document()
        active_ref = self._model.active_document()
        if self._translation_document_id is None and active_ref is not None:
            self._editor_page.top_bar.set_file_name(active_ref.name)
        title, msg, suggestion = classify_error(error)
        self.statusBar().showMessage(f"{title}：{msg}。{suggestion}")

    # —— 原图/译图与分屏对比 ——

    def _on_toggle_original(self) -> None:
        if self._model.translation_result is None:
            return
        if self._editor_page.is_slider_compare():
            self._editor_page.set_slider_compare(False)
        if self._editor_page.is_split_view():
            self._editor_page.set_split_view(False)
            self._editor_page.top_bar.set_split_view(False)
        if self._model.preview_mode == "original":
            self._apply_preview_mode(self._last_non_original_preview)
        else:
            self._last_non_original_preview = (
                self._model.preview_mode
                if self._model.preview_mode in {"translated", "layers"}
                else "translated"
            )
            self._apply_preview_mode("original")

    def _on_toggle_split_compare(self) -> None:
        if self._model.translation_result is None:
            return
        enabled = not self._editor_page.is_split_view()
        if enabled:
            self._editor_page.set_slider_compare(False)
            if self._model.preview_mode != "original":
                self._last_non_original_preview = self._model.preview_mode
            self._apply_preview_mode("translated")
        else:
            self._apply_preview_mode(self._last_non_original_preview)
        self._editor_page.set_split_view(enabled)
        self._editor_page.top_bar.set_split_view(enabled)

    def _on_toggle_slider_compare(self) -> None:
        if self._model.translation_result is None:
            self._editor_page.top_bar.set_slider_compare(False)
            return
        enabled = not self._editor_page.is_slider_compare()
        if enabled:
            if self._editor_page.is_split_view():
                self._editor_page.set_split_view(False)
                self._editor_page.top_bar.set_split_view(False)
            if self._model.preview_mode != "original":
                self._last_non_original_preview = self._model.preview_mode
            self._apply_preview_mode("translated")
        self._editor_page.set_slider_compare(enabled)
        if not enabled:
            self._apply_preview_mode(self._last_non_original_preview)

    def _on_compare_hold_started(self) -> None:
        if self._model.translation_result is None:
            return
        self._hold_preview_mode = self._model.preview_mode
        self._hold_slider_compare = self._editor_page.is_slider_compare()
        if self._hold_slider_compare:
            self._editor_page.set_slider_compare(False)
        self._apply_preview_mode("original")

    def _on_compare_hold_finished(self) -> None:
        if self._hold_preview_mode is None:
            return
        restore_mode = self._hold_preview_mode
        restore_slider = self._hold_slider_compare
        self._hold_preview_mode = None
        self._hold_slider_compare = False
        self._apply_preview_mode(restore_mode)
        if restore_slider:
            self._editor_page.set_slider_compare(True)

    def _apply_preview_mode(self, mode: str) -> None:
        """切换原图、干净成品图和可编辑辅助层。"""
        self._model.preview_mode = mode
        self._model.showing_original = mode == "original"
        if mode == "original":
            doc = self._model.source_document
            show_mask = False
            show_layers = False
            enable_properties = False
        elif mode in {"layers", "mask"}:
            editor = self._model.composition_editor
            doc = (
                editor.editing_document
                if editor is not None
                else self._model.rendered_document
            )
            show_mask = mode == "mask"
            show_layers = mode == "layers"
            enable_properties = True
        else:
            mode = "translated"
            self._model.preview_mode = mode
            editor = self._model.composition_editor
            doc = (
                editor._document
                if editor is not None and self._model.is_dirty
                else self._model.rendered_document
            )
            show_mask = False
            show_layers = False
            enable_properties = True
        if doc is not None:
            self._editor_page.set_document(doc)
        if show_layers:
            self._editor_page.set_text_layout(self._model.text_layout)
            if self._model.composition_editor is not None:
                self._editor_page.scene.set_watermarks(
                    self._model.composition_editor.watermarks
                )
                self._editor_page.layer_state_panel.set_composition(
                    self._model.text_layout,
                    self._model.composition_editor.watermarks,
                    self._model.composition_editor.patch_count,
                )
        self._editor_page.scene.set_mask_visible(show_mask)
        self._editor_page.set_layers_visible(show_layers)
        self._model.layers_visible = show_layers
        self._editor_page.property_panel.setEnabled(enable_properties)
        self._editor_page.top_bar.set_preview_mode(mode)

    # —— 显示/隐藏文字图层 ——

    def _on_toggle_layers(self) -> None:
        if self._model.preview_mode == "layers":
            self._apply_preview_mode("translated")
        else:
            self._apply_preview_mode("layers")

    def _on_editor_tool_changed(self, tool_id: str) -> None:
        if self._model.translation_result is None:
            if tool_id not in {"select", "ai_erase"}:
                self.statusBar().showMessage("请先导入图片并完成 OCR 或翻译")
                return
        if tool_id == "select":
            self._apply_preview_mode("layers")
        elif tool_id in {"text_regions", "layers"}:
            self._apply_preview_mode("layers")
        elif tool_id == "ai_erase":
            if self._repair_selection is None:
                self.statusBar().showMessage("AI 消除服务当前不可用")
                self._editor_page.toolbar.set_active_tool("select")
                return
            # AI 消除是公共背景工具：导入图片后即可使用，不要求先完成翻译。
            # 若尚未创建合成编辑器，先以当前图片建立空图层会话，保证消除可撤销，
            # 且完成后仍可继续新增文字或执行翻译。
            if not self._ensure_composition_editor():
                self.statusBar().showMessage("请先导入图片，再使用 AI 消除")
                self._editor_page.toolbar.set_active_tool("select")
                return
            self._apply_preview_mode("layers")
            self._editor_page.open_erase_dialog()
        elif tool_id == "manual_translate":
            if (
                self._process_manual_region is None
                or self._model.composition_editor is None
            ):
                self.statusBar().showMessage("请先完成一次自动翻译，再框选漏翻区域")
                self._editor_page.toolbar.set_active_tool("select")
                return
            self._apply_preview_mode("layers")
            self._editor_page.open_manual_region_dialog()
            self.statusBar().showMessage("请在图片上拖动框选漏翻文字区域")

    def _on_feature_requested(self, feature_id: str) -> None:
        labels = {
            "crop": "裁剪",
            "watermark": "水印",
        }
        if (
            feature_id == "watermark"
            and self._model.composition_editor is None
            and not self._ensure_composition_editor()
        ):
            self.statusBar().showMessage("请先导入图片，再添加水印")
            self._editor_page.toolbar.set_active_tool("select")
            return
        if self._model.composition_editor is None and feature_id != "crop":
            self.statusBar().showMessage(
                f"请先完成一次自动翻译，再使用{labels.get(feature_id, feature_id)}"
            )
            self._editor_page.toolbar.set_active_tool("select")
            return
        if feature_id == "crop":
            self._apply_preview_mode("layers")
            self._editor_page.open_crop_dialog()
        elif feature_id == "watermark":
            self._apply_preview_mode("layers")
            self._editor_page.open_watermark_dialog()

    def _ensure_composition_editor(self) -> bool:
        if self._model.composition_editor is not None:
            return True
        document = self._model.document or self._model.source_document
        if document is None or self._create_composition_editor is None:
            return False
        editor = self._create_composition_editor.execute(
            document,
            document,
            TextLayout(()),
            self._model.source_document or document,
        )
        self._model.composition_editor = editor
        self._model.text_layout = editor.layout
        self._model.rendered_document = editor.document
        self._sync_history_actions(editor.can_undo, editor.can_redo)
        # 同步到活动文档条目，保证切换文档后编辑器状态不丢失
        ref = self._model.active_document()
        if ref is not None:
            ref.composition_editor = editor
            ref.rendered_document = editor.document
            ref.text_layout = editor.layout
        return True

    def _on_manual_region_selected(self, value) -> None:
        editor = self._model.composition_editor
        source = self._model.source_document
        processor = self._process_manual_region
        if (
            editor is None
            or source is None
            or processor is None
            or self._task_runner is None
        ):
            self.statusBar().showMessage("框选翻译当前不可用")
            return

        controls = self._editor_page.translate_controls
        mode = TranslationMode(controls.selected_mode)
        selection = TranslationSelection(
            mode=mode,
            target_language=controls.selected_target_language,
            source_language=(
                controls.selected_source_language
                if mode is TranslationMode.SPECIFIC_LANGUAGE
                else None
            ),
        )
        spec = (
            value
            if isinstance(value, ManualRegionSpec)
            else ManualRegionSpec(
                ManualInputMode.AUTO,
                selection_box=value,
                erase_box=value,
                text_box=value,
            )
        )
        working_background = editor.background_document
        brand_terms = controls.configured_protection_terms

        def operation():
            manual = processor.execute(
                working_background,
                working_background,
                spec,
                controls.selected_ocr_language,
                selection,
                brand_terms,
                preserve_numbers=controls.should_preserve_numbers,
            )
            edit = editor.apply_manual_region(
                manual.repaired_background.document,
                manual.layer,
                manual.erase_mask,
            )
            return manual, edit

        self.statusBar().showMessage("正在识别、翻译并修复框选区域…")
        self._task_runner.submit(
            operation,
            self._on_manual_region_succeeded,
            self._on_manual_region_failed,
        )

    def _on_manual_region_succeeded(self, value: object) -> None:
        try:
            manual, edit = value
        except Exception:
            self._on_manual_region_failed(TypeError("框选翻译返回了无效结果"))
            return
        self._editor_page.apply_edit_result(edit)
        self._model.repaired_background = (
            self._model.composition_editor.background_document
            if self._model.composition_editor is not None
            else manual.repaired_background.document
        )
        self._model.rendered_document = edit.document
        self._model.text_layout = edit.layout
        self._model.selected_layer_id = manual.region_id
        self._editor_page.top_bar.set_has_layers(True)
        self._editor_page.manual_region_dialog.accept()
        self._editor_page.toolbar.set_active_tool("select")
        self._apply_preview_mode("translated")
        self.statusBar().showMessage(
            f"框选翻译完成：{manual.source_text} → {manual.translated_text}",
            7000,
        )

    def _on_ai_erase_requested(self, mask: EraseMask) -> None:
        if mask.is_empty:
            self.statusBar().showMessage("请先在画布框选或涂抹要消除的区域")
            self._editor_page.open_erase_dialog()
            return
        editor = self._model.composition_editor
        repair = self._repair_selection
        if (
            editor is None
            or repair is None
            or self._task_runner is None
        ):
            self.statusBar().showMessage("AI 消除当前不可用")
            return

        def operation():
            # 膨胀后的蒙版同时用于修复请求与背景补丁，避免膨胀边缘残留
            expanded = repair.expand_mask(mask)
            result = repair.execute(editor.background_document, mask)
            return (
                result,
                editor.apply_background_repair(result.document, expanded),
            )

        self.statusBar().showMessage("正在进行 AI 背景修复…")
        self._task_runner.submit(
            operation,
            self._on_ai_erase_succeeded,
            self._on_ai_erase_failed,
        )

    def _on_ai_erase_succeeded(self, value: object) -> None:
        result, edit = value
        self._editor_page.apply_edit_result(edit)
        self._model.repaired_background = (
            self._model.composition_editor.background_document
            if self._model.composition_editor is not None
            else result.document
        )
        self._apply_preview_mode("layers")
        self._editor_page.complete_ai_erase(result.backend_id)
        self.statusBar().showMessage(
            f"AI 消除完成（{result.backend_id}）",
            6000,
        )

    def _on_ai_erase_failed(self, error: Exception) -> None:
        self._editor_page.fail_ai_erase(str(error))
        self.statusBar().showMessage(f"AI 消除失败：{error}", 8000)

    def _on_crop_requested(self, box: TextBox) -> None:
        editor = self._model.composition_editor
        if editor is None:
            source = self._model.source_document
            if source is None:
                return
            self._source_undo.append(source)
            if len(self._source_undo) > 100:
                self._source_undo.pop(0)
            self._source_redo.clear()
            try:
                cropped = crop_image_document(source, box)
            except Exception as error:
                self.statusBar().showMessage(f"裁剪失败：{error}")
                return
            self._apply_pretranslation_document(cropped)
            self._editor_page.crop_dialog.accept()
            self._editor_page.toolbar.set_active_tool("select")
            self.statusBar().showMessage(
                f"裁剪完成：{cropped.asset.width}×{cropped.asset.height}；"
                "已有 OCR 结果已清除"
            )
            return
        if self._task_runner is None:
            return
        self.statusBar().showMessage("正在应用裁剪…")
        self._task_runner.submit(
            lambda: editor.crop(box),
            lambda edit: self._on_crop_succeeded(edit, box),
            lambda error: self.statusBar().showMessage(f"裁剪失败：{error}"),
        )

    def _on_crop_succeeded(self, edit, box: TextBox | None = None) -> None:
        source = self._model.source_document
        if source is not None and box is not None:
            left = max(0, int(box.center_x - box.width / 2))
            top = max(0, int(box.center_y - box.height / 2))
            ocr = self._model.ocr_result
            if isinstance(ocr, OcrResult):
                cropped_ocr = crop_ocr_result(
                    ocr,
                    left,
                    top,
                    edit.document.asset.width,
                    edit.document.asset.height,
                )
                self._model.ocr_result = cropped_ocr
                result = self._model.translation_result
                if isinstance(result, TranslateImageResult):
                    self._model.translation_result = replace(
                        result,
                        ocr=cropped_ocr,
                        document=edit.document,
                        layout=edit.layout,
                    )
                    self._editor_page.ocr_result_panel.set_result(
                        cropped_ocr,
                        self._model.translation_result.translation,
                    )
        if edit.reference_document is not None:
            self._model.source_document = edit.reference_document
            self._editor_page.set_original_document(edit.reference_document)
        self._editor_page.apply_edit_result(edit)
        self._editor_page.crop_dialog.accept()
        self._editor_page.toolbar.set_active_tool("select")
        self._apply_preview_mode("translated")
        self._editor_page.refit_canvas_views()
        self.statusBar().showMessage(
            f"裁剪完成：{edit.document.asset.width}×{edit.document.asset.height}"
        )

    def _on_image_transform_requested(self, value: str) -> None:
        try:
            operation = ImageTransform(value)
        except ValueError:
            self.statusBar().showMessage("不支持的图片变换")
            return
        editor = self._model.composition_editor
        if editor is not None and self._task_runner is not None:
            source = self._model.source_document
            width = source.asset.width if source is not None else editor.document.asset.width
            height = source.asset.height if source is not None else editor.document.asset.height
            self.statusBar().showMessage("正在变换整张图片…")
            self._task_runner.submit(
                lambda: editor.transform_canvas(operation),
                lambda edit: self._on_canvas_transform_succeeded(
                    edit, operation, width, height
                ),
                lambda error: self.statusBar().showMessage(
                    f"图片变换失败：{error}", 8000
                ),
            )
            return
        source = self._model.source_document
        if source is None:
            self.statusBar().showMessage("请先导入图片")
            return
        self._source_undo.append(source)
        if len(self._source_undo) > 100:
            self._source_undo.pop(0)
        self._source_redo.clear()
        transformed = transform_image_document(source, operation)
        self._apply_pretranslation_document(transformed)
        self.statusBar().showMessage(
            f"图片变换完成：{transformed.asset.width}×{transformed.asset.height}；"
            "已有 OCR 结果已清除"
        )

    def _apply_pretranslation_document(self, document: ImageDocument) -> None:
        self._model.source_document = document
        self._model.document = document
        self._model.rendered_document = None
        self._model.ocr_result = None
        self._model.translation_result = None
        self._model.text_layout = TextLayout(())
        self._model.is_dirty = True
        self._editor_page.scene.clear_regions()
        self._editor_page.ocr_result_panel.clear_result()
        self._editor_page.set_document(document)
        self._editor_page.set_original_document(document)
        self._editor_page.set_text_layout(TextLayout(()))
        self._editor_page.top_bar.set_has_result(False)
        self._sync_history_actions(
            bool(self._source_undo),
            bool(self._source_redo),
        )
        self._editor_page.refit_canvas_views()

    def _on_canvas_transform_succeeded(
        self,
        edit,
        operation: ImageTransform,
        width: int,
        height: int,
    ) -> None:
        ocr = self._model.ocr_result
        if isinstance(ocr, OcrResult):
            transformed_ocr = transform_ocr_result(
                ocr, operation, width, height
            )
            self._model.ocr_result = transformed_ocr
            result = self._model.translation_result
            if isinstance(result, TranslateImageResult):
                self._model.translation_result = replace(
                    result,
                    ocr=transformed_ocr,
                    document=edit.document,
                    layout=edit.layout,
                )
                self._editor_page.ocr_result_panel.set_result(
                    transformed_ocr,
                    self._model.translation_result.translation,
                )
        self._model.source_document = edit.reference_document
        self._editor_page.set_original_document(edit.reference_document)
        self._editor_page.apply_edit_result(edit)
        self._editor_page.crop_dialog.set_selection(
            TextBox(
                edit.document.asset.width / 2,
                edit.document.asset.height / 2,
                edit.document.asset.width,
                edit.document.asset.height,
            )
        )
        self._editor_page.refit_canvas_views()
        self.statusBar().showMessage(
            f"图片变换完成：{edit.document.asset.width}×{edit.document.asset.height}"
        )

    def _on_add_text_watermark(
        self,
        text: str,
        opacity: float,
        tiled: bool,
    ) -> None:
        editor = self._model.composition_editor
        if editor is None or self._task_runner is None:
            self.statusBar().showMessage("水印编辑器当前不可用")
            return
        dialog = self._editor_page.watermark_dialog
        style = TextStyle(
            dialog.selected_font_family or resolve_system_font("zh-Hans"),
            dialog.selected_font_size,
            dialog.selected_rgb,
            stroke_rgb=(0, 0, 0),
            stroke_width=1.0,
            font_weight=600,
        )
        self._task_runner.submit(
            lambda: editor.add_text_watermark(
                text,
                style,
                tiled,
                opacity,
                dialog.selected_position,
            ),
            self._on_watermark_succeeded,
            lambda error: self.statusBar().showMessage(f"添加水印失败：{error}"),
        )

    def _on_add_image_watermark(
        self,
        path: Path,
        opacity: float,
        tiled: bool,
    ) -> None:
        editor = self._model.composition_editor
        if editor is None or self._task_runner is None or self._codec is None:
            return

        def operation():
            watermark = self._codec.load(path, ImageLimits())
            return editor.add_image_watermark(
                watermark,
                tiled,
                opacity,
                self._editor_page.watermark_dialog.selected_position,
            )

        self._task_runner.submit(
            operation,
            self._on_watermark_succeeded,
            lambda error: self.statusBar().showMessage(f"添加水印失败：{error}"),
        )

    def _on_watermark_succeeded(self, edit) -> None:
        self._editor_page.apply_edit_result(edit)
        self._editor_page.layer_state_panel.set_composition(
            edit.layout,
            edit.watermarks,
            self._model.composition_editor.patch_count
            if self._model.composition_editor is not None
            else 0,
        )
        self._editor_page._show_layer_tool("layers")
        self._editor_page.toolbar.set_active_tool("select")
        self._apply_preview_mode("layers")
        if edit.affected_region_id is not None:
            self._editor_page.layer_state_panel.select_watermark(
                edit.affected_region_id
            )
            self._editor_page.scene.select_watermark(
                edit.affected_region_id
            )
        self.statusBar().showMessage(
            "水印已添加；可在右侧“图层状态”中调整、复制或删除",
            8000,
        )

    def _on_layer_state_requested(
        self,
        region_id: str,
        field: str,
        value: bool,
    ) -> None:
        editor = self._model.composition_editor
        if editor is None or self._task_runner is None:
            return
        try:
            layer = editor.layout.layer_by_id(region_id)
        except KeyError:
            return
        replacement = replace(layer, **{field: value})
        self._task_runner.submit(
            lambda: editor.replace_layer(replacement),
            self._editor_page.apply_edit_result,
            lambda error: self.statusBar().showMessage(f"图层状态更新失败：{error}"),
        )

    def _on_watermark_state_requested(
        self,
        watermark_id: str,
        field: str,
        value: bool,
    ) -> None:
        editor = self._model.composition_editor
        if editor is None or self._task_runner is None:
            return
        watermark = next(
            (
                item
                for item in editor.watermarks
                if item.watermark_id == watermark_id
            ),
            None,
        )
        if watermark is None:
            return
        replacement = replace(watermark, **{field: value})
        self._task_runner.submit(
            lambda: editor.replace_watermark(replacement),
            self._on_watermark_updated,
            lambda error: self.statusBar().showMessage(f"水印状态更新失败：{error}"),
        )

    def _on_watermark_edit_requested(self, watermark) -> None:
        editor = self._model.composition_editor
        if editor is None or self._task_runner is None:
            return
        self._task_runner.submit(
            lambda: editor.replace_watermark(watermark),
            self._on_watermark_updated,
            lambda error: self.statusBar().showMessage(f"水印编辑失败：{error}"),
        )

    def _on_watermark_property_requested(
        self,
        watermark_id: str,
        field: str,
        value: object,
    ) -> None:
        editor = self._model.composition_editor
        if editor is None or self._task_runner is None:
            return
        watermark = next(
            (
                item
                for item in editor.watermarks
                if item.watermark_id == watermark_id
            ),
            None,
        )
        if watermark is None:
            return
        if field == "size":
            width, height = value
            replacement = replace(
                watermark,
                width=float(width),
                height=float(height),
            )
        elif (
            field == "style"
            and watermark.style is not None
            and value.font_size != watermark.style.font_size
        ):
            scale = value.font_size / watermark.style.font_size
            replacement = replace(
                watermark,
                width=watermark.width * scale,
                height=watermark.height * scale,
                style=value,
            )
        else:
            replacement = replace(watermark, **{field: value})
        self._editor_page.scene.set_watermarks(
            tuple(
                replacement if item.watermark_id == watermark_id else item
                for item in editor.watermarks
            )
        )
        self._task_runner.submit(
            lambda: editor.replace_watermark(replacement),
            self._on_watermark_updated,
            lambda error: self.statusBar().showMessage(f"水印属性更新失败：{error}"),
        )

    def _on_watermark_updated(self, edit) -> None:
        self._editor_page.apply_edit_result(edit)
        if edit.affected_region_id is not None:
            self._editor_page.layer_state_panel.select_watermark(
                edit.affected_region_id
            )
            self._editor_page.scene.select_watermark(
                edit.affected_region_id
            )

    def _on_delete_watermark(self, watermark_id: str) -> None:
        editor = self._model.composition_editor
        if editor is None or self._task_runner is None:
            return
        self._task_runner.submit(
            lambda: editor.delete_watermark(watermark_id),
            self._editor_page.apply_edit_result,
            lambda error: self.statusBar().showMessage(f"删除水印失败：{error}"),
        )

    def _on_duplicate_watermark(self, watermark_id: str) -> None:
        editor = self._model.composition_editor
        if editor is None or self._task_runner is None:
            return
        self._task_runner.submit(
            lambda: editor.duplicate_watermark(watermark_id),
            self._editor_page.apply_edit_result,
            lambda error: self.statusBar().showMessage(f"复制水印失败：{error}"),
        )

    def _on_layer_move_requested(
        self,
        kind: str,
        layer_id: str,
        offset: int,
    ) -> None:
        editor = self._model.composition_editor
        if editor is None or self._task_runner is None:
            return
        if kind == "text":
            operation = lambda: editor.move_layer(layer_id, offset)
        else:
            operation = lambda: editor.move_watermark(layer_id, offset)
        self._task_runner.submit(
            operation,
            self._editor_page.apply_edit_result,
            lambda error: self.statusBar().showMessage(f"图层排序失败：{error}"),
        )

    def _on_manual_region_failed(self, error: Exception) -> None:
        self._editor_page.toolbar.set_active_tool("select")
        title, message, suggestion = classify_error(error)
        self.statusBar().showMessage(
            f"{title}：{message}。{suggestion}",
            8000,
        )

    # —— 撤销/重做（桥接 EditComposition）——

    def _on_undo(self) -> None:
        editor = self._model.composition_editor
        if editor is None:
            current = self._model.source_document
            if current is None or not self._source_undo:
                self.statusBar().showMessage("没有可撤销的操作", 3000)
                return
            self._source_redo.append(current)
            self._apply_pretranslation_document(self._source_undo.pop())
            return
        if self._task_runner is None:
            return
        if not editor.can_undo:
            self._editor_page.top_bar.set_can_undo(False)
            self.statusBar().showMessage("没有可撤销的编辑", 3000)
            return
        self.statusBar().showMessage("正在撤销…")
        self._task_runner.submit(
            editor.undo,
            lambda edit: self._on_history_applied(edit, "已撤销"),
            lambda e: self.statusBar().showMessage(f"撤销失败：{e}"),
        )

    def _on_redo(self) -> None:
        editor = self._model.composition_editor
        if editor is None:
            current = self._model.source_document
            if current is None or not self._source_redo:
                self.statusBar().showMessage("没有可重做的操作", 3000)
                return
            self._source_undo.append(current)
            self._apply_pretranslation_document(self._source_redo.pop())
            return
        if self._task_runner is None:
            return
        if not editor.can_redo:
            self._editor_page.top_bar.set_can_redo(False)
            self.statusBar().showMessage("没有可重做的编辑", 3000)
            return
        self.statusBar().showMessage("正在重做…")
        self._task_runner.submit(
            editor.redo,
            lambda edit: self._on_history_applied(edit, "已重做"),
            lambda e: self.statusBar().showMessage(f"重做失败：{e}"),
        )

    def _on_history_applied(self, edit: object, message: str) -> None:
        self._editor_page.apply_edit_result(edit)
        self._sync_history_actions(edit.can_undo, edit.can_redo)
        self.statusBar().showMessage(message, 3000)

    def _sync_history_actions(self, can_undo: bool, can_redo: bool) -> None:
        self._editor_page.top_bar.set_can_undo(can_undo)
        self._editor_page.top_bar.set_can_redo(can_redo)
        self._undo_action.setEnabled(can_undo)
        self._redo_action.setEnabled(can_redo)

    # —— 属性编辑（分发到 EditComposition）——

    def _on_edit(self, region_id: str, kind: str, after_layer: object, before_layer: object) -> None:
        """属性面板编辑 → 按字段组分发到 EditComposition 后台渲染。"""
        editor = self._model.composition_editor
        if editor is None or self._task_runner is None:
            return
        self.statusBar().showMessage("正在应用编辑…")

        if kind == "text":
            op = lambda: editor.replace_text(region_id, after_layer.text)
        elif kind == "box":
            op = lambda: editor.replace_box(region_id, after_layer.box)
        elif kind == "style":
            op = lambda: editor.replace_style(
                region_id, after_layer.style, after_layer.box.rotation_degrees
            )
        elif kind == "path":
            op = lambda: editor.replace_path(region_id, after_layer.path)
        else:
            return

        self._task_runner.submit(
            op,
            self._editor_page.apply_edit_result,
            lambda e: self.statusBar().showMessage(f"编辑失败：{e}"),
        )

    def _on_restore_auto_layout(self, region_id: str) -> None:
        editor = self._model.composition_editor
        result = self._model.translation_result
        if editor is None or self._task_runner is None or not isinstance(
            result, TranslateImageResult
        ):
            self.statusBar().showMessage("当前文字没有可恢复的自动布局", 3000)
            return
        try:
            original_layer = result.layout.layer_by_id(region_id)
        except KeyError:
            self.statusBar().showMessage("当前文字没有可恢复的自动布局", 3000)
            return

        self.statusBar().showMessage("正在恢复自动布局…")
        self._task_runner.submit(
            lambda: editor.replace_layer(original_layer),
            lambda edit: self._on_history_applied(edit, "已恢复自动布局"),
            lambda error: self.statusBar().showMessage(
                f"恢复自动布局失败：{error}", 6000
            ),
        )

    # —— 删除 / 复制图层 ——

    def _ocr_preview_box(self, region: TextRegion) -> TextBox:
        remembered = self._ocr_preview_boxes.get(region.region_id)
        if remembered is not None:
            return remembered
        p0, p1, _, p3 = region.polygon
        return TextBox(
            sum(point.x for point in region.polygon) / 4,
            sum(point.y for point in region.polygon) / 4,
            max(1.0, hypot(p1.x - p0.x, p1.y - p0.y)),
            max(1.0, hypot(p3.x - p0.x, p3.y - p0.y)),
            degrees(atan2(p1.y - p0.y, p1.x - p0.x)),
        )

    def _ocr_preview_mask(self, region: TextRegion) -> EraseMask | None:
        source = self._model.source_document
        if source is None:
            return None
        if self._erase_mask_builder is not None:
            ocr_result, translation_result = self._ocr_preview_pipeline_inputs(region)
            return self._erase_mask_builder.execute(
                source,
                ocr_result,
                translation_result,
            )
        if self._mask_rasterizer is None:
            return None
        return self._mask_rasterizer.rasterize(
            source.asset.width,
            source.asset.height,
            (tuple((point.x, point.y) for point in region.polygon),),
            1,
        )

    def _ocr_preview_pipeline_inputs(
        self, region: TextRegion
    ) -> tuple[OcrResult, TranslationResult]:
        current = self._model.ocr_result
        regions = current.regions if isinstance(current, OcrResult) else (region,)
        language_code = (
            region.language_code
            if region.language_code in SUPPORTED_LANGUAGE_CODES
            else "zh-Hans"
        )
        ocr_result = (
            replace(current, regions=regions)
            if isinstance(current, OcrResult)
            else OcrResult(
                regions,
                language_code,
                region.model_id,
                0,
            )
        )
        units = tuple(
            TranslationUnit(
                item.region_id,
                item.text,
                item.language_code
                if item.language_code in SUPPORTED_LANGUAGE_CODES
                else language_code,
                language_code,
                item.text,
                (
                    TranslationStatus.TRANSLATED
                    if item.region_id == region.region_id
                    else TranslationStatus.SKIPPED_LANGUAGE
                ),
            )
            for item in regions
        )
        return ocr_result, TranslationResult(
            units,
            TranslationSelection(TranslationMode.ALL, language_code),
            "ocr-property-preview",
            0,
        )

    def _ocr_preview_base_layer(
        self, region: TextRegion
    ):
        source = self._model.source_document
        if source is None or self._text_layout_adapter is None:
            return None
        ocr_result, translation_result = self._ocr_preview_pipeline_inputs(region)
        layout = self._text_layout_adapter.layout(
            source,
            ocr_result,
            translation_result,
        )
        return layout.layer_by_id(region.region_id)

    def _on_ocr_preview_changed(self, region_id: str, region: TextRegion) -> None:
        """Render an OCR-only correction as an editable preview layer."""
        existing_id = self._ocr_preview_layers.get(region_id)
        overrides = self._editor_page._ocr_property_overrides.get(region_id, {})
        has_visual_overrides = any(field != "text" for field in overrides)

        # Selecting a row (or restoring its original OCR text) must not add a
        # duplicate layer over the source pixels.  Only a genuinely changed
        # OCR value gets an editable preview layer.
        original_text = self._ocr_original_texts.get(region_id)
        if (
            original_text is not None
            and region.text == original_text
            and not has_visual_overrides
        ):
            if existing_id is None:
                return

        if self._task_runner is None or not self._ensure_composition_editor():
            return
        editor = self._model.composition_editor
        if editor is None:
            return

        if (
            original_text is not None
            and region.text == original_text
            and not has_visual_overrides
        ):

            restore_mask = self._ocr_preview_mask(region)
            source = self._model.source_document

            def remove_preview():
                if restore_mask is not None and source is not None:
                    return editor.restore_original_region(
                        existing_id, source, restore_mask
                    )
                return editor.delete_layer(existing_id)

            def on_removed(edit):
                self._ocr_preview_layers.pop(region_id, None)
                self._editor_page.apply_edit_result(edit)

            self._task_runner.submit(
                remove_preview,
                on_removed,
                lambda error: self.statusBar().showMessage(
                    f"OCR 原文预览清理失败：{error}", 6000
                ),
            )
            return

        repair_mask = self._ocr_preview_mask(region)

        def operation():
            layer_id = existing_id
            if layer_id is None:
                if (
                    repair_mask is not None
                    and self._repair_selection is not None
                ):
                    repaired = self._repair_selection.execute(
                        editor.background_document,
                        repair_mask,
                    )
                    editor.apply_background_repair(repaired.document, repair_mask)
                last_edit = editor.add_layer(region.text)
                layer_id = last_edit.affected_region_id
                if layer_id is None:
                    return last_edit
                self._ocr_preview_layers[region_id] = layer_id
                base_layer = self._ocr_preview_base_layer(region)
                if base_layer is not None:
                    last_edit = editor.replace_layer(
                        replace(base_layer, region_id=layer_id)
                    )
                    self._ocr_preview_boxes[region_id] = base_layer.box
                else:
                    box = self._ocr_preview_box(region)
                    layer = editor.layout.layer_by_id(layer_id)
                    style = replace(
                        layer.style,
                        auto_fit=False,
                        font_size=max(6.0, min(160.0, box.height * 0.85)),
                        font_weight=(
                            600
                            if any(ord(char) > 0x2E80 for char in region.text)
                            else layer.style.font_weight
                        ),
                    )
                    last_edit = editor.replace_style(
                        layer_id,
                        style,
                        box.rotation_degrees,
                    )
                    last_edit = editor.replace_box(layer_id, box)
            else:
                last_edit = editor.replace_text(layer_id, region.text)

            field_order = (
                "center_x", "center_y", "width", "height",
                "rotation_degrees", "font_family", "font_weight",
                "font_size", "auto_fit", "font_stretch", "wrap",
                "alignment", "vertical_alignment", "line_height",
                "letter_spacing", "text_opacity", "background_rgb",
                "background_opacity", "fill_rgb", "stroke_width",
                "stroke_rgb", "shadow_enabled", "shadow_offset_x",
                "shadow_offset_y", "shadow_opacity", "shadow_rgb",
                "effect_preset", "text_path",
            )
            for field in field_order:
                if field not in overrides:
                    continue
                before = editor.layout.layer_by_id(layer_id)
                after = self._editor_page._apply_field_change(
                    before, field, overrides[field]
                )
                if after is None or after == before:
                    continue
                if field in {
                    "center_x", "center_y", "width", "height",
                    "rotation_degrees",
                }:
                    last_edit = editor.replace_box(layer_id, after.box)
                elif field == "text_path":
                    last_edit = editor.replace_path(layer_id, after.path)
                else:
                    last_edit = editor.replace_style(
                        layer_id,
                        after.style,
                        after.box.rotation_degrees,
                    )
            return last_edit

        def on_success(edit):
            self._editor_page.apply_edit_result(edit)
            self._apply_preview_mode("layers")
            self._editor_page.top_bar.set_has_layers(True)

        self._task_runner.submit(
            operation,
            on_success,
            lambda error: self.statusBar().showMessage(
                f"OCR 原文预览更新失败：{error}", 6000
            ),
        )

    def _on_delete_layer(self, region_id: str) -> None:
        editor = self._model.composition_editor
        if editor is None or self._task_runner is None:
            return
        self.statusBar().showMessage("正在删除图层…")
        self._task_runner.submit(
            lambda: editor.delete_layer(region_id),
            self._editor_page.apply_edit_result,
            lambda e: self.statusBar().showMessage(f"删除失败：{e}"),
        )

    def _on_duplicate_layer(self, region_id: str) -> None:
        editor = self._model.composition_editor
        if editor is None or self._task_runner is None:
            return
        try:
            layer = self._model.text_layout.layer_by_id(region_id)
        except KeyError:
            return
        self.statusBar().showMessage("正在复制图层…")
        self._task_runner.submit(
            lambda: editor.duplicate_layer(region_id),
            self._on_layer_created,
            lambda e: self.statusBar().showMessage(f"复制失败：{e}"),
        )

    def _on_add_layer(self, default_text: str) -> None:
        editor = self._model.composition_editor
        if editor is None or self._task_runner is None:
            return
        self.statusBar().showMessage("正在新增文字图层…")
        self._task_runner.submit(
            lambda: editor.add_layer(default_text),
            self._on_layer_created,
            lambda e: self.statusBar().showMessage(f"新增失败：{e}"),
        )

    def _on_layer_created(self, edit) -> None:
        self._editor_page.apply_edit_result(edit)
        if edit.affected_region_id:
            self._model.text_layout = edit.layout
            self._model.selected_layer_id = edit.affected_region_id
        self._editor_page.right_tabs.setCurrentIndex(2)

    def _on_cancel_translate(self) -> None:
        if self._translate_image is not None:
            self._translate_image.cancel()
            self.statusBar().showMessage("正在取消翻译…")

    def _on_manual_translate_text(
        self,
        region_id: str,
        source_text: str,
        source_language: str,
        target_language: str,
    ) -> None:
        editor = self._model.composition_editor
        adapter = self._manual_translation_adapter
        if editor is None or adapter is None or self._task_runner is None:
            self.statusBar().showMessage("当前翻译服务不可用")
            return
        self.statusBar().showMessage("正在翻译新增文字…")

        def operation():
            result = adapter.translate(
                (source_text,),
                source_language or None,
                target_language,
            )
            if not result:
                raise RuntimeError("翻译服务未返回结果")
            item = result[0]
            if getattr(item, "error_code", None):
                raise RuntimeError(getattr(item, "error_message", None) or item.error_code)
            return getattr(item, "translated_text", None)

        self._task_runner.submit(
            operation,
            lambda translated: self._on_manual_translation_finished(
                region_id, translated
            ),
            lambda error: self.statusBar().showMessage(
                f"新增文字翻译失败：{error}", 8000
            ),
        )

    def _on_manual_translation_finished(
        self,
        region_id: str,
        translated_text: object,
    ) -> None:
        if not isinstance(translated_text, str) or not translated_text.strip():
            self.statusBar().showMessage("翻译服务返回了空译文", 8000)
            return
        editor = self._model.composition_editor
        if editor is None or self._task_runner is None:
            return
        self._task_runner.submit(
            lambda: editor.replace_text(region_id, translated_text.strip()),
            self._on_layer_created,
            lambda error: self.statusBar().showMessage(
                f"应用新增文字译文失败：{error}", 8000
            ),
        )
        self.statusBar().showMessage("新增文字翻译完成")

    def _on_source_text_changed(self, region_id: str, text: str) -> None:
        result = self._model.translation_result
        ocr = self._model.ocr_result
        if not text.strip() or not isinstance(ocr, OcrResult):
            return
        regions = tuple(
            replace(region, text=text.strip())
            if region.region_id == region_id
            else region
            for region in ocr.regions
        )
        updated_ocr = replace(ocr, regions=regions)
        self._model.ocr_result = updated_ocr
        updated_region = next(
            region
            for region in updated_ocr.regions
            if region.region_id == region_id
        )
        self._editor_page._ocr_property_overrides.setdefault(
            region_id, {}
        )["text"] = text.strip()
        self._editor_page.scene.set_regions(updated_ocr.regions)
        if isinstance(result, TranslateImageResult):
            units = tuple(
                replace(
                    unit,
                    source_text=text.strip(),
                    translated_text=(
                        text.strip()
                        if unit.status
                        in {
                            TranslationStatus.REVIEW_REQUIRED,
                            TranslationStatus.SKIPPED_LANGUAGE,
                            TranslationStatus.SKIPPED_PROTECTED,
                            TranslationStatus.SKIPPED_USER,
                        }
                        else unit.translated_text
                    ),
                )
                if unit.region_id == region_id
                else unit
                for unit in result.translation.units
            )
            result = replace(
                result,
                ocr=updated_ocr,
                translation=replace(result.translation, units=units),
            )
            self._model.translation_result = result
            self._editor_page.ocr_result_panel.set_result(
                updated_ocr, result.translation
            )
        else:
            self._editor_page.ocr_result_panel.set_result(updated_ocr)
        self._editor_page.ocr_preview_changed.emit(region_id, updated_region)
        self.statusBar().showMessage(
            "OCR 原文已更新，正在同步画布与导出图片…"
        )
        self.statusBar().showMessage("OCR 原文已更新，可点击“重新翻译”应用")

    def _on_translated_text_changed(self, region_id: str, text: str) -> None:
        """属性面板直接编辑译文 → 更新翻译结果单元与图层文字。"""
        editor = self._model.composition_editor
        if editor is None or self._task_runner is None:
            return
        text = text.strip()
        if not text:
            self.statusBar().showMessage("译文内容不能为空", 4000)
            return
        # 同步更新翻译结果（供导出/OCR 面板使用），编辑即视为确认
        result = self._model.translation_result
        updated_unit = None
        if isinstance(result, TranslateImageResult):
            units = tuple(
                replace(
                    unit,
                    translated_text=text,
                    status=TranslationStatus.TRANSLATED,
                    error_code=None,
                    error_message=None,
                )
                if unit.region_id == region_id
                else unit
                for unit in result.translation.units
            )
            result = replace(
                result,
                translation=replace(result.translation, units=units),
            )
            self._model.translation_result = result
            self._editor_page.ocr_result_panel.set_result(
                result.ocr, result.translation
            )
            updated_unit = next(
                (unit for unit in units if unit.region_id == region_id),
                None,
            )
        try:
            layer = self._model.text_layout.layer_by_id(region_id)
        except KeyError:
            self.statusBar().showMessage("译文已更新（该区域暂无文字图层）")
            return
        if layer.text == text:
            self._editor_page.property_panel.set_layer(
                layer,
                self._find_ocr_region(region_id),
                updated_unit,
            )
            self.statusBar().showMessage("译文已更新")
            return
        self.statusBar().showMessage("正在应用译文…")
        self._on_edit(region_id, "text", replace(layer, text=text), layer)

    def _on_retranslate_region(self, region_id: str) -> None:
        if (
            self._process_manual_region is None
            or self._task_runner is None
            or self._model.composition_editor is None
            or self._model.source_document is None
        ):
            self.statusBar().showMessage("当前区域无法重新翻译")
            return
        region = self._find_ocr_region(region_id)
        if region is None:
            self.statusBar().showMessage("找不到对应 OCR 区域")
            return
        box = self._region_box(region_id, region)
        circular_path = self._circular_path_for_retranslation(
            region_id,
            region,
            box,
        )
        ctrl = self._editor_page.translate_controls
        selection = self._translation_selection()
        spec = ManualRegionSpec(
            ManualInputMode.SOURCE_TEXT,
            box,
            box,
            box,
            source_text=region.text,
            circular_path=circular_path,
        )
        editor = self._model.composition_editor
        source = self._model.source_document
        background = editor.background_document
        brand_terms = ctrl.configured_protection_terms

        def operation():
            manual = self._process_manual_region.execute(
                source,
                background,
                spec,
                ctrl.selected_ocr_language,
                selection,
                brand_terms,
                preserve_numbers=ctrl.should_preserve_numbers,
            )
            edit = editor.replace_region_from_manual(
                region_id,
                manual.repaired_background.document,
                manual.layer,
                manual.erase_mask,
            )
            return manual, edit

        self.statusBar().showMessage("正在重新翻译选中区域…")
        self._task_runner.submit(
            operation,
            lambda value: self._on_region_retranslated(region_id, value),
            lambda error: self.statusBar().showMessage(
                f"区域重新翻译失败：{error}", 8000
            ),
        )

    def _on_region_retranslated(self, region_id: str, value: object) -> None:
        manual, edit = value
        result = self._model.translation_result
        region = self._find_ocr_region(region_id)
        if isinstance(result, TranslateImageResult) and region is not None:
            replacement = TranslationUnit(
                region_id,
                manual.source_text,
                region.language_code,
                result.translation.selection.target_language,
                manual.translated_text,
                TranslationStatus.TRANSLATED,
            )
            units = tuple(
                replacement if unit.region_id == region_id else unit
                for unit in result.translation.units
            )
            if all(unit.region_id != region_id for unit in result.translation.units):
                units = (*units, replacement)
            result = replace(
                result,
                document=edit.document,
                translation=replace(result.translation, units=units),
                layout=edit.layout,
            )
            self._model.translation_result = result
            self._editor_page.ocr_result_panel.set_result(
                result.ocr, result.translation
            )
        self._editor_page.apply_edit_result(edit)
        self._sync_history_actions(edit.can_undo, edit.can_redo)
        self._model.text_layout = edit.layout
        self._model.selected_layer_id = region_id
        self.statusBar().showMessage("选中区域已重新翻译")

    def _on_keep_original_region(self, region_id: str) -> None:
        if (
            self._mask_rasterizer is None
            or self._task_runner is None
            or self._model.composition_editor is None
            or self._model.source_document is None
        ):
            self.statusBar().showMessage("当前区域无法恢复原文")
            return
        region = self._find_ocr_region(region_id)
        if region is None:
            return
        source = self._model.source_document
        mask = self._mask_rasterizer.rasterize(
            source.asset.width,
            source.asset.height,
            (tuple((point.x, point.y) for point in region.polygon),),
            0,
        )
        editor = self._model.composition_editor
        self._task_runner.submit(
            lambda: editor.restore_original_region(region_id, source, mask),
            lambda edit: self._on_original_region_restored(region_id, edit),
            lambda error: self.statusBar().showMessage(
                f"保留原文失败：{error}", 8000
            ),
        )

    def _on_original_region_restored(self, region_id: str, edit: object) -> None:
        result = self._model.translation_result
        if isinstance(result, TranslateImageResult):
            units = tuple(
                replace(
                    unit,
                    translated_text=unit.source_text,
                    status=TranslationStatus.SKIPPED_USER,
                    error_code=None,
                    error_message=None,
                )
                if unit.region_id == region_id
                else unit
                for unit in result.translation.units
            )
            result = replace(
                result,
                document=edit.document,
                translation=replace(result.translation, units=units),
                layout=edit.layout,
            )
            self._model.translation_result = result
            self._editor_page.ocr_result_panel.set_result(
                result.ocr, result.translation
            )
        self._editor_page.apply_edit_result(edit)
        self._model.text_layout = edit.layout
        self._model.selected_layer_id = None
        self.statusBar().showMessage("已保留该区域原文")

    def _translation_selection(
        self, target_language: str | None = None
    ) -> TranslationSelection:
        ctrl = self._editor_page.translate_controls
        mode = TranslationMode(ctrl.selected_mode)
        return TranslationSelection(
            mode=mode,
            target_language=target_language or ctrl.selected_target_language,
            source_language=(
                ctrl.selected_source_language
                if mode is TranslationMode.SPECIFIC_LANGUAGE
                else None
            ),
        )

    def _find_ocr_region(self, region_id: str) -> TextRegion | None:
        ocr = self._model.ocr_result
        if not isinstance(ocr, OcrResult):
            return None
        return next(
            (region for region in ocr.regions if region.region_id == region_id),
            None,
        )

    def _region_box(self, region_id: str, region: TextRegion) -> TextBox:
        enhanced_rotated = region.enhanced_only or any(
            observation.source.startswith("polar")
            for observation in region.observations
        )
        if not enhanced_rotated:
            try:
                return self._model.text_layout.layer_by_id(region_id).box
            except KeyError:
                pass
        p0, p1, _, p3 = region.polygon
        rotation = degrees(atan2(p1.y - p0.y, p1.x - p0.x))
        width = max(1, hypot(p1.x - p0.x, p1.y - p0.y))
        height = max(1, hypot(p3.x - p0.x, p3.y - p0.y))
        if enhanced_rotated and height > width:
            width, height = height, width
            rotation += 90
        return TextBox(
            sum(point.x for point in region.polygon) / 4,
            sum(point.y for point in region.polygon) / 4,
            width,
            height,
            rotation,
        )

    def _circular_path_for_retranslation(
        self,
        region_id: str,
        region: TextRegion,
        box: TextBox,
    ) -> CircularTextPath | None:
        try:
            existing = self._model.text_layout.layer_by_id(region_id)
        except KeyError:
            existing = None
        if existing is not None and isinstance(existing.path, CircularTextPath):
            return existing.path
        ocr_result = self._model.ocr_result
        if not isinstance(ocr_result, OcrResult) or not ocr_result.preview_strips:
            return None
        center = ocr_result.preview_strips[0].center
        return circular_text_path_for_region(
            region,
            box,
            (center.x, center.y),
        )

    # —— 导出 ——

    def _on_export(self, target: Path) -> None:
        # 优先使用最新编辑结果（EditComposition），其次使用预渲染成品图
        document = self._model.rendered_document or self._model.document
        if self._model.composition_editor is not None:
            document = self._model.composition_editor._document
        if document is None:
            self.statusBar().showMessage("没有可导出的图片")
            return

        if self._task_runner is not None:
            self.statusBar().showMessage(f"正在导出 {target.name}…")
            def _on_export_ok(p):
                self._model.is_dirty = False
                self.statusBar().showMessage(f"已导出：{Path(p)}")
            self._task_runner.submit(
                lambda: export_document(
                    document,
                    target,
                    self._export_usecase,
                    self._codec,
                    self._editor_page.export_settings.options,
                ),
                _on_export_ok,
                lambda e: self.statusBar().showMessage(f"导出失败：{e}"),
            )
            return

        try:
            result = export_document(
                document,
                target,
                self._export_usecase,
                self._codec,
                self._editor_page.export_settings.options,
            )
            self._model.is_dirty = False
            self.statusBar().showMessage(f"已导出：{result}")
        except Exception as exc:
            self.statusBar().showMessage(f"导出失败：{exc}")

    def _on_quick_save(self) -> None:
        source = self._model.source_document or self._model.document
        if source is None:
            self.statusBar().showMessage("没有可保存的图片")
            return
        if self._quick_save_path is None:
            source_path = source.asset.source_path
            default = source_path.with_name(f"{source_path.stem}-translated.png")
            value, _ = QFileDialog.getSaveFileName(
                self,
                "保存译图",
                str(default),
                "PNG (*.png);;JPEG (*.jpg *.jpeg);;WebP (*.webp);;GIF (*.gif);;TIFF (*.tif *.tiff)",
            )
            if not value:
                return
            self._quick_save_path = Path(value)
        self._on_export(self._quick_save_path)

    def request_runtime_recovery(self, reason: str = "runtime") -> None:
        self.statusBar().showMessage("运行时已恢复", 5000)

    # —— 公开接口 ——

    @property
    def editor_page(self) -> EditorPage:
        return self._editor_page

    @property
    def model(self) -> EditorModel:
        return self._model

    @property
    def undo_stack(self) -> QUndoStack:
        return self._undo_stack
