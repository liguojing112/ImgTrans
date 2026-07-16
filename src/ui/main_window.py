from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QFileDialog,
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from src.application.bootstrap import StartupSnapshot
from src.application.batch import RunBatch
from src.application.batch_export import BatchExportResult, ExportBatchSelection
from src.application.composition import (
    CompositionEditResult,
    CreateCompositionEditor,
    EditComposition,
)
from src.application.image_io import ExportImage, ImportImage
from src.application.image_limits import ImageLimitsRefreshResult
from src.domain.models import ModelUpdateResult
from src.domain.activation import ActivationSession
from src.application.inpainting import RepairTranslatedRegions
from src.application.manual_region import ProcessManualRegion
from src.application.ports import BatchResultStore
from src.application.ocr import RecognizeText
from src.application.translation import TranslateRegions
from src.application.translate_image import TranslateImage, TranslateImageResult
from src.domain.image import ImageDocument
from src.domain.batch import BatchItemStatus, BatchSnapshot, BatchStatus
from src.domain.job import ImageStage, JobCancelled
from src.domain.layout import ArcTextPath, TextBox, TextLayout
from src.domain.manual_region import ManualRegionResult
from src.domain.ocr import OcrResult
from src.domain.inpainting import RepairOutcome
from src.domain.translation import TranslationResult, TranslationStatus
from src.domain.session import SessionChanges
from src.ui.image_canvas import ImageCanvas
from src.ui.batch_panel import BatchPanel
from src.ui.curved_text_panel import CurvedTextPanel
from src.ui.inpainting_panel import InpaintingPanel
from src.ui.layer_style_panel import LayerStylePanel
from src.ui.manual_region_panel import ManualRegionPanel
from src.ui.ocr_panel import OcrPanel
from src.ui.pipeline_panel import PipelinePanel
from src.ui.translation_panel import TranslationPanel
from src.ui.text_edit_panel import TextEditPanel
from src.ui.activation_dialog import ActivationDialog


class TaskRunner(Protocol):
    def submit(
        self,
        operation: Callable[[], Any],
        on_success: Callable[[Any], None],
        on_error: Callable[[Exception], None],
    ) -> None: ...


class MainWindow(QMainWindow):
    image_imported = Signal(object)
    image_exported = Signal(str)
    ocr_completed = Signal(object)
    translation_completed = Signal(object)
    repair_completed = Signal(object)
    workflow_completed = Signal(object)
    manual_region_completed = Signal(object)
    batch_completed = Signal(object)
    batch_snapshot_changed = Signal(object)
    workflow_stage_changed = Signal(object)
    operation_failed = Signal(str)

    def __init__(
        self,
        startup: StartupSnapshot,
        import_image: ImportImage | None = None,
        export_image: ExportImage | None = None,
        task_runner: TaskRunner | None = None,
        recognize_text: RecognizeText | None = None,
        translate_regions: TranslateRegions | None = None,
        repair_regions: RepairTranslatedRegions | None = None,
        translate_image: TranslateImage | None = None,
        create_composition_editor: CreateCompositionEditor | None = None,
        process_manual_region: ProcessManualRegion | None = None,
        run_batch: RunBatch | None = None,
        batch_result_store: BatchResultStore | None = None,
        export_batch_selection: ExportBatchSelection | None = None,
        confirm_discard: Callable[[str], bool] | None = None,
        refresh_image_limits: Callable[[], ImageLimitsRefreshResult] | None = None,
        update_models: Callable[[], ModelUpdateResult] | None = None,
        activate_device: Callable[[str], ActivationSession] | None = None,
        activation_status: Callable[[], ActivationSession | None] | None = None,
        clear_activation: Callable[[], None] | None = None,
    ) -> None:
        super().__init__()
        self.startup = startup
        self._import_image = import_image
        self._export_image = export_image
        self._recognize_text = recognize_text
        self._translate_regions = translate_regions
        self._repair_regions = repair_regions
        self._translate_image = translate_image
        self._create_composition_editor = create_composition_editor
        self._process_manual_region = process_manual_region
        self._run_batch = run_batch
        self._batch_result_store = batch_result_store
        self._export_batch_selection = export_batch_selection
        self._confirm_discard_callback = confirm_discard
        self._refresh_image_limits = refresh_image_limits
        self._update_models = update_models
        self._activate_device = activate_device
        self._activation_status = activation_status
        self._clear_activation = clear_activation
        self._task_runner = task_runner
        self._current_document: ImageDocument | None = None
        self._source_document: ImageDocument | None = None
        self._ocr_result: OcrResult | None = None
        self._translation_result: TranslationResult | None = None
        self._repair_outcome: RepairOutcome | None = None
        self._composition_editor: EditComposition | None = None
        self._batch_snapshot: BatchSnapshot | None = None
        self._batch_previewing = False
        self._pending_batch_preview_name: str | None = None
        self._session_changes = SessionChanges()
        self._previewing_original = False
        self._active_operation: str | None = None
        self.last_error: str | None = None
        self._activation_dialog: ActivationDialog | None = None
        self._image_limits_refresh_running = False
        self._model_update_running = False
        self._activation_check_running = False
        self.setObjectName("mainWindow")
        self.setWindowTitle(startup.product.name)
        self.setMinimumSize(900, 620)
        self.resize(1100, 720)
        self._build_menus()
        self.setCentralWidget(self._build_workspace())
        self.workflow_stage_changed.connect(self._workflow_stage_updated)
        self.batch_snapshot_changed.connect(
            self._batch_snapshot_updated,
            Qt.ConnectionType.QueuedConnection,
        )
        self.statusBar().showMessage("应用已就绪")
        self.setStyleSheet(_STYLE)

    @property
    def current_document(self) -> ImageDocument | None:
        return self._current_document

    def request_image_limits_refresh(self) -> None:
        if (
            self._refresh_image_limits is None
            or self._task_runner is None
            or self._image_limits_refresh_running
        ):
            return
        self._image_limits_refresh_running = True
        self._task_runner.submit(
            self._refresh_image_limits,
            self._image_limits_refreshed,
            self._image_limits_refresh_failed,
        )

    def _image_limits_refreshed(self, result: ImageLimitsRefreshResult) -> None:
        self._image_limits_refresh_running = False
        limits = result.limits
        version = (
            f" v{limits.config_version}"
            if limits.config_version is not None
            else ""
        )
        if result.remote_applied:
            self.statusBar().showMessage(f"远程图片限制已更新{version}", 5000)
        elif result.warning:
            self.statusBar().showMessage(
                f"{result.warning}；继续使用{limits.source}配置{version}",
                7000,
            )

    def _image_limits_refresh_failed(self, error: Exception) -> None:
        self._image_limits_refresh_running = False
        self.statusBar().showMessage(f"图片限制刷新失败：{error}", 7000)

    def request_model_update(self) -> None:
        if (
            self._update_models is None
            or self._task_runner is None
            or self._model_update_running
        ):
            return
        self._model_update_running = True
        self.statusBar().showMessage("正在后台检查本地模型…")
        self._task_runner.submit(
            self._update_models,
            self._model_update_finished,
            self._model_update_failed,
        )

    def show_activation_dialog(self) -> None:
        if (
            self._activate_device is None
            or self._activation_status is None
            or self._clear_activation is None
            or self._task_runner is None
        ):
            return
        dialog = ActivationDialog(
            self._activate_device,
            self._activation_status,
            self._clear_activation,
            self._task_runner,
            self,
        )
        dialog.activated.connect(self._activation_succeeded)
        dialog.activation_cleared.connect(self._activation_cleared)
        dialog.finished.connect(lambda: self._release_activation_dialog(dialog))
        self._activation_dialog = dialog
        dialog.show()

    def request_activation_check(self) -> None:
        if (
            self._activation_status is None
            or self._task_runner is None
            or self._activation_check_running
        ):
            return
        self._activation_check_running = True
        self._task_runner.submit(
            self._activation_status,
            self._activation_check_finished,
            self._activation_check_failed,
        )

    def _activation_check_finished(self, result: object) -> None:
        self._activation_check_running = False
        if isinstance(result, ActivationSession):
            self.request_model_update()

    def _activation_check_failed(self, error: Exception) -> None:
        self._activation_check_running = False
        self.statusBar().showMessage(f"无法读取本机激活状态：{error}", 7000)

    def request_runtime_recovery(self, reason: str = "runtime") -> None:
        del reason
        self.statusBar().showMessage("系统或网络已恢复，正在后台刷新服务状态…", 5000)
        self.request_image_limits_refresh()
        if self._activation_status is not None:
            self.request_activation_check()
        else:
            self.request_model_update()

    def _activation_succeeded(self, _session: ActivationSession) -> None:
        self.statusBar().showMessage("设备激活成功，安全凭据已保存", 8000)
        self.request_model_update()

    def _activation_cleared(self) -> None:
        self.statusBar().showMessage("本机激活凭据已清除", 6000)

    def _release_activation_dialog(self, dialog: ActivationDialog) -> None:
        if self._activation_dialog is dialog:
            self._activation_dialog = None

    def _build_menus(self) -> None:
        account_menu = self.menuBar().addMenu("账户")
        self.activation_action = QAction("激活…", self)
        self.activation_action.setObjectName("activationAction")
        self.activation_action.setEnabled(
            self._activate_device is not None
            and self._activation_status is not None
            and self._clear_activation is not None
            and self._task_runner is not None
        )
        self.activation_action.triggered.connect(self.show_activation_dialog)
        account_menu.addAction(self.activation_action)

    def _model_update_finished(self, result: ModelUpdateResult) -> None:
        self._model_update_running = False
        if result.failed_count:
            self.statusBar().showMessage(
                f"模型检查完成：{result.failed_count} 项失败，继续保留旧版本",
                8000,
            )
        elif result.installed_count:
            self.statusBar().showMessage(
                f"已安全安装 {result.installed_count} 个模型，新版本将在下次启动加载",
                8000,
            )
        else:
            self.statusBar().showMessage("本地模型已是最新版本", 5000)

    def _model_update_failed(self, error: Exception) -> None:
        self._model_update_running = False
        self.statusBar().showMessage(f"模型更新不可用，继续使用本地版本：{error}", 8000)

    def request_import(self, source: Path) -> None:
        if not self._import_image or not self._task_runner:
            return
        if self._session_changes.single_image_dirty and not self._confirm_discard(
            "导入新图片会丢失当前单图尚未导出的处理和编辑结果。"
        ):
            return
        self._active_operation = "import"
        self._set_busy(True, "正在导入并验证图片…")
        self._task_runner.submit(
            lambda: self._import_image.execute(source),
            self._import_succeeded,
            self._operation_failed,
        )

    def request_export(self, target: Path) -> None:
        if not self._current_document or not self._export_image or not self._task_runner:
            return
        document = self._current_document
        self._active_operation = "export"
        self._set_busy(True, "正在导出图片…")
        self._task_runner.submit(
            lambda: self._export_image.execute(document, target),
            self._export_succeeded,
            self._operation_failed,
        )

    def request_batch(self) -> None:
        sources = self.batch_panel.sources
        if not sources or self._run_batch is None or self._task_runner is None:
            return
        if self._session_changes.pending_batch_items and not self._confirm_discard(
            "重新运行批次会清除上一次尚未导出的批量结果。"
        ):
            return
        self._session_changes.clear_batch()
        ocr_language = self.ocr_panel.selected_language_code
        selection = self.translation_panel.selection
        brand_terms = self.translation_panel.configured_brand_terms
        previous_batch_id = (
            self._batch_snapshot.batch_id if self._batch_snapshot is not None else None
        )

        def operation() -> BatchSnapshot:
            if previous_batch_id is not None and self._batch_result_store is not None:
                self._batch_result_store.clear(previous_batch_id)
            return self._run_batch.execute(
                sources,
                ocr_language,
                selection,
                brand_terms,
                self.batch_snapshot_changed.emit,
            )

        self._batch_snapshot = None
        self._active_operation = "batch"
        self._set_busy(True, f"正在批量处理 {len(sources)} 张图片…")
        self.batch_panel.status_label.setText("批量任务正在运行，可随时取消…")
        self._task_runner.submit(
            operation,
            self._batch_succeeded,
            self._operation_failed,
        )

    def cancel_batch(self) -> None:
        if self._active_operation != "batch" or self._run_batch is None:
            return
        self.batch_panel.status_label.setText("正在取消批次，不再启动新图片…")
        self._run_batch.cancel()

    def request_batch_preview(self, item_id: str) -> None:
        if (
            self._batch_snapshot is None
            or self._batch_result_store is None
            or self._task_runner is None
        ):
            return
        item = next(
            (value for value in self._batch_snapshot.items if value.item_id == item_id),
            None,
        )
        if (
            item is None
            or item.status is not BatchItemStatus.COMPLETED
            or not item.result_ref
        ):
            return
        result_ref = item.result_ref
        self._pending_batch_preview_name = item.source.name
        self._active_operation = "batch_preview"
        self._set_busy(True, f"正在载入批量结果：{item.source.name}")
        self._task_runner.submit(
            lambda: self._batch_result_store.load(result_ref),
            self._batch_preview_succeeded,
            self._operation_failed,
        )

    def request_batch_export(self, directory: Path) -> None:
        if (
            self._batch_snapshot is None
            or self._export_batch_selection is None
            or self._task_runner is None
        ):
            return
        selected_ids = self.batch_panel.selected_result_ids
        if not selected_ids:
            self.batch_panel.status_label.setText("请至少勾选一张成功图片")
            return
        snapshot = self._batch_snapshot
        suffix = self.batch_panel.selected_output_suffix
        self._active_operation = "batch_export"
        self._set_busy(True, f"正在导出 {len(selected_ids)} 张图片…")
        self._task_runner.submit(
            lambda: self._export_batch_selection.execute(
                snapshot,
                selected_ids,
                directory,
                suffix,
            ),
            self._batch_export_succeeded,
            self._operation_failed,
        )

    def request_clear_batch(self) -> None:
        if self._active_operation is not None:
            return
        if self._session_changes.pending_batch_items and not self._confirm_discard(
            "清空批次会删除尚未导出的批量结果。"
        ):
            return
        if (
            self._batch_snapshot is None
            or self._batch_result_store is None
            or self._task_runner is None
        ):
            self._clear_batch_succeeded(None)
            return
        batch_id = self._batch_snapshot.batch_id
        self._active_operation = "batch_clear"
        self._set_busy(True, "正在清理批量缓存…")
        self._task_runner.submit(
            lambda: self._batch_result_store.clear(batch_id),
            self._clear_batch_succeeded,
            self._operation_failed,
        )

    def request_ocr(self, language_code: str | None = None) -> None:
        if not self._current_document or not self._recognize_text or not self._task_runner:
            return
        document = self._current_document
        if isinstance(language_code, str):
            index = self.ocr_panel.language_combo.findData(language_code)
            if index >= 0:
                self.ocr_panel.language_combo.setCurrentIndex(index)
        selected_language = self.ocr_panel.selected_language_code
        self._active_operation = "ocr"
        self._set_busy(True, "正在加载 OCR 模型并识别文字…")
        self.ocr_panel.status_label.setText("正在识别，首次加载模型可能需要数秒…")
        self._task_runner.submit(
            lambda: self._recognize_text.execute(document, selected_language),
            self._ocr_succeeded,
            self._operation_failed,
        )

    def request_translation(self) -> None:
        if not self._ocr_result or not self._translate_regions or not self._task_runner:
            return
        ocr_result = self._ocr_result
        selection = self.translation_panel.selection
        brand_terms = self.translation_panel.configured_brand_terms
        self._active_operation = "translation"
        provider_label = (
            "模拟翻译"
            if self._translate_regions.adapter_id == "mock-local"
            else "服务端翻译"
        )
        self._set_busy(True, f"正在执行{provider_label}和保护词处理…")
        self.translation_panel.status_label.setText(
            f"正在筛选语言、保护词并执行{provider_label}…"
        )
        self._task_runner.submit(
            lambda: self._translate_regions.execute(
                ocr_result, selection, brand_terms
            ),
            self._translation_succeeded,
            self._operation_failed,
        )

    def request_repair(self) -> None:
        if (
            not self._source_document
            or not self._ocr_result
            or not self._translation_result
            or not self._repair_regions
            or not self._task_runner
        ):
            return
        document = self._source_document
        ocr_result = self._ocr_result
        translation_result = self._translation_result
        self._active_operation = "repair"
        self._set_busy(True, "正在生成擦除蒙版并修复背景…")
        self.inpainting_panel.status_label.setText("正在本地修复，复杂图片可能需要一些时间…")
        self._task_runner.submit(
            lambda: self._repair_regions.execute(document, ocr_result, translation_result),
            self._repair_succeeded,
            self._operation_failed,
        )

    def request_workflow(self) -> None:
        if not self._source_document or not self._translate_image or not self._task_runner:
            return
        document = self._source_document
        ocr_language = self.ocr_panel.selected_language_code
        selection = self.translation_panel.selection
        brand_terms = self.translation_panel.configured_brand_terms
        self._active_operation = "workflow"
        self.pipeline_panel.reset()
        self._set_busy(True, "正在执行单图自动翻译…")
        self._task_runner.submit(
            lambda: self._translate_image.execute(
                document,
                ocr_language,
                selection,
                brand_terms,
                self.workflow_stage_changed.emit,
            ),
            self._workflow_succeeded,
            self._workflow_failed,
        )

    def cancel_workflow(self) -> None:
        if self._active_operation != "workflow" or self._translate_image is None:
            return
        self.pipeline_panel.status_label.setText("正在取消任务…")
        self.statusBar().showMessage("正在取消单图翻译任务…")
        self._translate_image.cancel()

    def request_text_edit(self) -> None:
        region_id = self.text_edit_panel.selected_region_id
        if (
            region_id is None
            or self._composition_editor is None
            or self._task_runner is None
        ):
            return
        text = self.text_edit_panel.text.toPlainText()
        self._active_operation = "edit"
        self._set_busy(True, "正在重新排版并渲染译文…")
        self._task_runner.submit(
            lambda: self._composition_editor.replace_text(region_id, text),
            self._edit_succeeded,
            self._operation_failed,
        )

    def request_undo_edit(self) -> None:
        if self._composition_editor is None or self._task_runner is None:
            return
        self._active_operation = "edit"
        self._set_busy(True, "正在撤销译文编辑…")
        self._task_runner.submit(
            self._composition_editor.undo,
            self._edit_succeeded,
            self._operation_failed,
        )

    def request_redo_edit(self) -> None:
        if self._composition_editor is None or self._task_runner is None:
            return
        self._active_operation = "edit"
        self._set_busy(True, "正在重做译文编辑…")
        self._task_runner.submit(
            self._composition_editor.redo,
            self._edit_succeeded,
            self._operation_failed,
        )

    def request_geometry_edit(self, region_id: str, value: object) -> None:
        if (
            not isinstance(value, TextBox)
            or self._composition_editor is None
            or self._task_runner is None
        ):
            return
        self._active_operation = "geometry"
        self._set_busy(True, "正在应用文字框几何并重新渲染…")
        self._task_runner.submit(
            lambda: self._composition_editor.replace_box(region_id, value),
            self._edit_succeeded,
            self._operation_failed,
        )

    def request_style_edit(self) -> None:
        region_id = self.layer_style_panel.selected_region_id
        if region_id is None or self._composition_editor is None or self._task_runner is None:
            return
        style, rotation = self.layer_style_panel.edited_style()
        self._active_operation = "style"
        self._set_busy(True, "正在应用文字样式并重新渲染…")
        self._task_runner.submit(
            lambda: self._composition_editor.replace_style(region_id, style, rotation),
            self._edit_succeeded,
            self._operation_failed,
        )

    def request_path_edit(self, region_id: str, value: object) -> None:
        if (
            not isinstance(value, ArcTextPath)
            or self._composition_editor is None
            or self._task_runner is None
        ):
            return
        self._active_operation = "curve"
        self._set_busy(True, "正在应用弧形路径并重新渲染…")
        self._task_runner.submit(
            lambda: self._composition_editor.replace_path(region_id, value),
            self._edit_succeeded,
            self._operation_failed,
        )

    def request_curve_apply(self) -> None:
        region_id = self.curved_text_panel.selected_region_id
        if region_id is not None:
            self.request_path_edit(region_id, self.curved_text_panel.edited_path)

    def request_curve_straight(self) -> None:
        region_id = self.curved_text_panel.selected_region_id
        if (
            region_id is None
            or self._composition_editor is None
            or self._task_runner is None
        ):
            return
        self._active_operation = "curve"
        self._set_busy(True, "正在恢复直线排版…")
        self._task_runner.submit(
            lambda: self._composition_editor.replace_path(region_id, None),
            self._edit_succeeded,
            self._operation_failed,
        )

    def request_add_layer(self) -> None:
        if self._composition_editor is None or self._task_runner is None:
            return
        self._active_operation = "style"
        self._set_busy(True, "正在新增文字框…")
        self._task_runner.submit(
            self._composition_editor.add_layer,
            self._edit_succeeded,
            self._operation_failed,
        )

    def request_delete_layer(self) -> None:
        region_id = self.layer_style_panel.selected_region_id
        if region_id is None or self._composition_editor is None or self._task_runner is None:
            return
        self._active_operation = "style"
        self._set_busy(True, "正在删除文字框…")
        self._task_runner.submit(
            lambda: self._composition_editor.delete_layer(region_id),
            self._edit_succeeded,
            self._operation_failed,
        )

    def request_manual_selection(self) -> None:
        if self._source_document is None:
            return
        self.manual_region_panel.status_label.setText("请在画布上拖动框选文字区域")
        self.image_canvas.set_manual_selection_enabled(True)

    def request_manual_region(self) -> None:
        if (
            self._source_document is None
            or self._current_document is None
            or self._process_manual_region is None
            or self._create_composition_editor is None
            or self._task_runner is None
        ):
            return
        try:
            spec = self.manual_region_panel.spec
        except ValueError as error:
            self.manual_region_panel.status_label.setText(str(error))
            return
        if self._composition_editor is None:
            self._composition_editor = self._create_composition_editor.execute(
                self._current_document,
                self._current_document,
                TextLayout(()),
            )
        editor = self._composition_editor
        source = self._source_document
        working_background = editor.background_document
        ocr_language = self.ocr_panel.selected_language_code
        selection = self.translation_panel.selection
        brand_terms = self.translation_panel.configured_brand_terms

        def operation() -> tuple[ManualRegionResult, CompositionEditResult]:
            manual = self._process_manual_region.execute(
                source,
                working_background,
                spec,
                ocr_language,
                selection,
                brand_terms,
            )
            edit = editor.apply_manual_region(
                manual.repaired_background.document,
                manual.layer,
                manual.erase_mask,
            )
            return manual, edit

        self._active_operation = "manual"
        self._set_busy(True, "正在处理手动框选区域…")
        self.manual_region_panel.status_label.setText(
            "正在识别、翻译、修复并渲染；该操作可撤销…"
        )
        self._task_runner.submit(
            operation,
            self._manual_region_succeeded,
            self._operation_failed,
        )

    def _layer_selection_changed(self, region_id: str) -> None:
        if self._composition_editor is None:
            return
        try:
            layer = self._composition_editor.layout.layer_by_id(region_id)
        except KeyError:
            return
        self.image_canvas.select_layer(region_id)
        self.text_edit_panel.select_region(region_id)
        self.layer_style_panel.set_layer(layer)
        self.curved_text_panel.set_layer(layer)

    def restore_original(self) -> None:
        if self._source_document is None:
            return
        self._current_document = self._source_document
        self._repair_outcome = None
        self._composition_editor = None
        self._previewing_original = False
        self.image_canvas.set_document(self._source_document)
        self.image_canvas.set_regions(self._ocr_result.regions if self._ocr_result else ())
        self.image_canvas.set_erase_mask(None)
        self.inpainting_panel.clear_result()
        self.text_edit_panel.clear_result()
        self.layer_style_panel.set_layer(None)
        self.curved_text_panel.set_layer(None)
        self._session_changes.mark_single_exported()
        self._set_busy(False, "已撤销修复并保留原图")

    def toggle_original_preview(self) -> None:
        if not self._repair_outcome or not self._source_document:
            return
        self._previewing_original = not self._previewing_original
        document = (
            self._source_document
            if self._previewing_original
            else self._current_document
        )
        self.image_canvas.set_document(document)
        self.image_canvas.set_regions(self._ocr_result.regions if self._ocr_result else ())
        if self._composition_editor is not None:
            self.image_canvas.set_text_layout(self._composition_editor.layout)
        self.image_canvas.set_erase_mask(self._repair_outcome.erase_mask)
        self.inpainting_panel.set_previewing_original(self._previewing_original)

    def _build_workspace(self) -> QWidget:
        root = QWidget(self)
        root.setObjectName("workspace")
        layout = QVBoxLayout(root)
        layout.setContentsMargins(36, 28, 36, 30)
        layout.setSpacing(20)

        header = QHBoxLayout()
        title_group = QVBoxLayout()
        title = QLabel(self.startup.product.name)
        title.setObjectName("productTitle")
        subtitle = QLabel(f"{self.startup.product.milestone} · 单张图片翻译")
        subtitle.setObjectName("productSubtitle")
        title_group.addWidget(title)
        title_group.addWidget(subtitle)
        header.addLayout(title_group)
        header.addStretch()
        self.header_import_button = QPushButton("导入图片")
        self.header_import_button.setObjectName("headerImportButton")
        self.header_import_button.clicked.connect(self._choose_image)
        self.header_import_button.setEnabled(self._import_image is not None)
        self.batch_import_button = QPushButton("批量导入")
        self.batch_import_button.setObjectName("batchImportButton")
        self.batch_import_button.clicked.connect(self._choose_batch_images)
        self.batch_import_button.setEnabled(self._run_batch is not None)
        self.export_button = QPushButton("导出图片")
        self.export_button.setObjectName("exportButton")
        self.export_button.clicked.connect(self._choose_export)
        self.export_button.setEnabled(False)
        header.addWidget(self.header_import_button)
        header.addWidget(self.batch_import_button)
        self.ocr_button = QPushButton("识别文字")
        self.ocr_button.setObjectName("ocrButton")
        self.ocr_button.clicked.connect(self.request_ocr)
        self.ocr_button.setEnabled(False)
        header.addWidget(self.ocr_button)
        provider_id = (
            self._translate_regions.adapter_id
            if self._translate_regions is not None
            else "mock-local"
        )
        provider_label = "模拟翻译" if provider_id == "mock-local" else "服务端翻译"
        self.translate_button = QPushButton(provider_label)
        self.translate_button.setObjectName("headerTranslateButton")
        self.translate_button.clicked.connect(self.request_translation)
        self.translate_button.setEnabled(False)
        header.addWidget(self.translate_button)
        self.repair_button = QPushButton("修复背景")
        self.repair_button.setObjectName("headerRepairButton")
        self.repair_button.clicked.connect(self.request_repair)
        self.repair_button.setEnabled(False)
        header.addWidget(self.repair_button)
        self.auto_button = QPushButton("一键翻译")
        self.auto_button.setObjectName("headerAutoButton")
        self.auto_button.clicked.connect(self.request_workflow)
        self.auto_button.setEnabled(False)
        header.addWidget(self.auto_button)
        header.addWidget(self.export_button)
        version = QLabel(f"v{self.startup.product.version}")
        version.setObjectName("versionLabel")
        header.addWidget(version, alignment=Qt.AlignmentFlag.AlignTop)
        layout.addLayout(header)

        pipeline = QFrame()
        pipeline.setObjectName("pipelineCard")
        pipeline_layout = QHBoxLayout(pipeline)
        pipeline_layout.setContentsMargins(24, 15, 24, 15)
        for index, name in enumerate(("导入", "OCR", "翻译", "修复", "导出"), start=1):
            stage = QLabel(f"{index}  {name}")
            stage.setObjectName("pipelineStage")
            stage.setAlignment(Qt.AlignmentFlag.AlignCenter)
            pipeline_layout.addWidget(stage)
        layout.addWidget(pipeline)

        self.content_stack = QStackedWidget()
        self.content_stack.setObjectName("contentStack")
        self.empty_state = self._build_empty_state()
        self.image_canvas = ImageCanvas()
        language_codes = self._recognize_text.language_codes if self._recognize_text else ()
        self.ocr_panel = OcrPanel(language_codes)
        self.ocr_panel.recognize_button.clicked.connect(self.request_ocr)
        translation_codes = (
            self._translate_regions.language_codes if self._translate_regions else ()
        )
        self.translation_panel = TranslationPanel(translation_codes, provider_id)
        self.translation_panel.translate_button.clicked.connect(self.request_translation)
        self.inpainting_panel = InpaintingPanel()
        self.inpainting_panel.repair_button.clicked.connect(self.request_repair)
        self.inpainting_panel.toggle_button.clicked.connect(self.toggle_original_preview)
        self.inpainting_panel.keep_original_button.clicked.connect(self.restore_original)
        self.inpainting_panel.show_mask.toggled.connect(
            self.image_canvas.set_mask_visible
        )
        self.pipeline_panel = PipelinePanel()
        self.pipeline_panel.start_button.clicked.connect(self.request_workflow)
        self.pipeline_panel.cancel_button.clicked.connect(self.cancel_workflow)
        self.text_edit_panel = TextEditPanel()
        self.text_edit_panel.apply_button.clicked.connect(self.request_text_edit)
        self.text_edit_panel.undo_button.clicked.connect(self.request_undo_edit)
        self.text_edit_panel.redo_button.clicked.connect(self.request_redo_edit)
        self.text_edit_panel.fit_view_button.clicked.connect(self.image_canvas.reset_view)
        self.image_canvas.geometry_edit_requested.connect(self.request_geometry_edit)
        self.layer_style_panel = LayerStylePanel()
        self.layer_style_panel.apply_button.clicked.connect(self.request_style_edit)
        self.layer_style_panel.add_button.clicked.connect(self.request_add_layer)
        self.layer_style_panel.delete_button.clicked.connect(self.request_delete_layer)
        self.curved_text_panel = CurvedTextPanel()
        self.curved_text_panel.apply_requested.connect(self.request_curve_apply)
        self.curved_text_panel.straight_requested.connect(self.request_curve_straight)
        self.image_canvas.path_edit_requested.connect(self.request_path_edit)
        self.manual_region_panel = ManualRegionPanel()
        self.manual_region_panel.select_requested.connect(self.request_manual_selection)
        self.manual_region_panel.process_requested.connect(self.request_manual_region)
        self.image_canvas.manual_region_selected.connect(
            self.manual_region_panel.set_selection
        )
        self.batch_panel = BatchPanel()
        self.batch_panel.add_requested.connect(self._choose_batch_images)
        self.batch_panel.clear_requested.connect(self.request_clear_batch)
        self.batch_panel.start_requested.connect(self.request_batch)
        self.batch_panel.cancel_requested.connect(self.cancel_batch)
        self.batch_panel.export_requested.connect(self._choose_batch_export_directory)
        self.batch_panel.preview_requested.connect(self.request_batch_preview)
        self.image_canvas.layer_selected.connect(self._layer_selection_changed)
        self.text_edit_panel.layer_selected.connect(self._layer_selection_changed)
        self.side_tabs = QTabWidget()
        self.side_tabs.setObjectName("sideTabs")
        self.side_tabs.setMinimumWidth(390)
        self.side_tabs.setMaximumWidth(480)
        self.side_tabs.addTab(self.pipeline_panel, "自动")
        self.side_tabs.addTab(self.ocr_panel, "OCR")
        self.side_tabs.addTab(self.translation_panel, "翻译")
        self.side_tabs.addTab(self.inpainting_panel, "修复")
        self.side_tabs.addTab(self.text_edit_panel, "编辑")
        self.side_tabs.addTab(self.layer_style_panel, "样式")
        self.side_tabs.addTab(self.curved_text_panel, "弧形")
        self.side_tabs.addTab(self.manual_region_panel, "手动")
        self.side_tabs.addTab(self.batch_panel, "批量")
        self.image_workspace = QSplitter(Qt.Orientation.Horizontal)
        self.image_workspace.setObjectName("imageWorkspace")
        self.image_workspace.addWidget(self.image_canvas)
        self.image_workspace.addWidget(self.side_tabs)
        self.image_workspace.setStretchFactor(0, 1)
        self.image_workspace.setStretchFactor(1, 0)
        self.content_stack.addWidget(self.empty_state)
        self.content_stack.addWidget(self.image_workspace)
        layout.addWidget(self.content_stack, stretch=1)

        self.readiness_label = QLabel("支持导入 JPG、PNG、WebP")
        self.readiness_label.setObjectName("readinessLabel")
        layout.addWidget(self.readiness_label)
        return root

    def _build_empty_state(self) -> QFrame:
        empty_state = QFrame()
        empty_state.setObjectName("emptyState")
        empty_state.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        empty_layout = QVBoxLayout(empty_state)
        empty_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.setSpacing(12)
        marker = QLabel("IMAGE")
        marker.setObjectName("imageMarker")
        marker.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_title = QLabel("尚未导入图片")
        empty_title.setObjectName("emptyStateTitle")
        empty_hint = QLabel("支持 JPG、JPEG、PNG、WebP；导出支持 JPG、PNG、WebP、GIF、TIFF")
        empty_hint.setObjectName("emptyStateHint")
        empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.import_button = QPushButton("导入图片")
        self.import_button.setObjectName("importButton")
        self.import_button.clicked.connect(self._choose_image)
        self.import_button.setEnabled(self._import_image is not None)
        self.import_button.setFixedWidth(150)
        empty_layout.addWidget(marker, alignment=Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(empty_title, alignment=Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(empty_hint, alignment=Qt.AlignmentFlag.AlignCenter)
        empty_layout.addSpacing(8)
        empty_layout.addWidget(self.import_button, alignment=Qt.AlignmentFlag.AlignCenter)
        return empty_state

    def _choose_image(self) -> None:
        value, _ = QFileDialog.getOpenFileName(
            self,
            "导入图片",
            "",
            "图片 (*.jpg *.jpeg *.png *.webp)",
        )
        if value:
            self.request_import(Path(value))

    def _choose_batch_images(self) -> None:
        values, _ = QFileDialog.getOpenFileNames(
            self,
            "添加批量图片",
            "",
            "图片 (*.jpg *.jpeg *.png *.webp)",
        )
        if not values:
            return
        self.batch_panel.add_sources(tuple(Path(value) for value in values))
        self.content_stack.setCurrentWidget(self.image_workspace)
        self.side_tabs.setCurrentWidget(self.batch_panel)
        self._set_busy(False, f"已添加 {len(self.batch_panel.sources)} 张批量图片")

    def _choose_batch_export_directory(self) -> None:
        value = QFileDialog.getExistingDirectory(self, "选择批量导出目录")
        if value:
            self.request_batch_export(Path(value))

    def _choose_export(self) -> None:
        if not self._current_document:
            return
        suggested = self._current_document.asset.source_path.with_name(
            f"{self._current_document.asset.source_path.stem}-export.png"
        )
        value, selected_filter = QFileDialog.getSaveFileName(
            self,
            "导出图片",
            str(suggested),
            "PNG (*.png);;JPEG (*.jpg);;WebP (*.webp);;GIF 静态单帧 (*.gif);;TIFF 单页 (*.tiff)",
        )
        if not value:
            return
        target = Path(value)
        if not target.suffix:
            suffixes = {
                "PNG (*.png)": ".png",
                "JPEG (*.jpg)": ".jpg",
                "WebP (*.webp)": ".webp",
                "GIF 静态单帧 (*.gif)": ".gif",
                "TIFF 单页 (*.tiff)": ".tiff",
            }
            target = target.with_suffix(suffixes.get(selected_filter, ".png"))
        self.request_export(target)

    def _import_succeeded(self, value: object) -> None:
        if not isinstance(value, ImageDocument):
            self._operation_failed(TypeError("图片适配器返回了无效结果"))
            return
        self._current_document = value
        self._source_document = value
        self._ocr_result = None
        self._translation_result = None
        self._repair_outcome = None
        self._composition_editor = None
        self._session_changes.mark_single_exported()
        self._batch_previewing = False
        self._previewing_original = False
        self.image_canvas.set_document(value)
        self.image_canvas.set_regions(())
        self.ocr_panel.clear_result()
        self.translation_panel.clear_result()
        self.inpainting_panel.clear_result()
        self.text_edit_panel.clear_result()
        self.layer_style_panel.set_layer(None)
        self.curved_text_panel.set_layer(None)
        self.manual_region_panel.clear_selection()
        self.pipeline_panel.reset()
        self.content_stack.setCurrentWidget(self.image_workspace)
        asset = value.asset
        alpha = " · Alpha" if asset.has_alpha else ""
        orientation = " · 已校正 EXIF 方向" if asset.orientation_applied else ""
        self.readiness_label.setText(
            f"{asset.source_path.name} · {asset.width}×{asset.height} · {asset.file_format.value}{alpha}{orientation}"
        )
        self.last_error = None
        self._active_operation = None
        self._set_busy(False, "图片导入成功")
        self.export_button.setEnabled(True)
        self.image_imported.emit(value)

    def _ocr_succeeded(self, value: object) -> None:
        if not isinstance(value, OcrResult):
            self._operation_failed(TypeError("OCR 适配器返回了无效结果"))
            return
        self._ocr_result = value
        self._translation_result = None
        self._repair_outcome = None
        self._composition_editor = None
        self.image_canvas.set_regions(value.regions)
        self.ocr_panel.set_result(value)
        self.translation_panel.clear_result()
        self.inpainting_panel.clear_result()
        self.text_edit_panel.clear_result()
        self.layer_style_panel.set_layer(None)
        self.curved_text_panel.set_layer(None)
        self.translation_panel.set_source_language(value.language_code)
        self.last_error = None
        self._active_operation = None
        self._set_busy(False, f"OCR 完成：识别到 {len(value.regions)} 个文字区域")
        self.ocr_completed.emit(value)

    def _translation_succeeded(self, value: object) -> None:
        if not isinstance(value, TranslationResult):
            self._operation_failed(TypeError("翻译适配器返回了无效结果"))
            return
        self._translation_result = value
        self._repair_outcome = None
        self._composition_editor = None
        if self._source_document is not None:
            self._current_document = self._source_document
            self.image_canvas.set_document(self._source_document)
            self.image_canvas.set_regions(self._ocr_result.regions if self._ocr_result else ())
        self.image_canvas.set_erase_mask(None)
        self.inpainting_panel.clear_result()
        self.text_edit_panel.clear_result()
        self.layer_style_panel.set_layer(None)
        self.curved_text_panel.set_layer(None)
        self.translation_panel.set_result(value)
        self.side_tabs.setCurrentWidget(self.translation_panel)
        self.last_error = None
        self._active_operation = None
        translated_count = sum(unit.should_erase_source for unit in value.units)
        provider_label = (
            "模拟翻译" if value.provider == "mock-local" else "服务端翻译"
        )
        failed_count = sum(
            unit.status is TranslationStatus.FAILED for unit in value.units
        )
        message = f"{provider_label}完成：{translated_count} 个区域生成译文"
        if failed_count:
            message += f"，{failed_count} 个区域失败并保留原文"
        self._set_busy(False, message)
        self.translation_completed.emit(value)

    def _repair_succeeded(self, value: object) -> None:
        if not isinstance(value, RepairOutcome):
            self._operation_failed(TypeError("修复适配器返回了无效结果"))
            return
        self._repair_outcome = value
        self._composition_editor = None
        self._current_document = value.result.document
        self._session_changes.mark_single_changed()
        self._previewing_original = False
        self.image_canvas.set_document(value.result.document)
        self.image_canvas.set_regions(self._ocr_result.regions if self._ocr_result else ())
        self.image_canvas.set_erase_mask(value.erase_mask)
        self.image_canvas.set_mask_visible(self.inpainting_panel.show_mask.isChecked())
        self.inpainting_panel.set_result(value)
        self.text_edit_panel.clear_result()
        self.layer_style_panel.set_layer(None)
        self.curved_text_panel.set_layer(None)
        self.side_tabs.setCurrentWidget(self.inpainting_panel)
        self.last_error = None
        self._active_operation = None
        message = f"背景修复完成：{value.result.backend_id}"
        if value.result.warning:
            message += "（已降级）"
        self._set_busy(False, message)
        self.repair_completed.emit(value)

    def _workflow_stage_updated(self, value: object) -> None:
        if isinstance(value, ImageStage):
            self.pipeline_panel.set_stage(value)

    def _workflow_succeeded(self, value: object) -> None:
        if not isinstance(value, TranslateImageResult):
            self._workflow_failed(TypeError("单图编排返回了无效结果"))
            return
        self._ocr_result = value.ocr
        self._translation_result = value.translation
        self._repair_outcome = value.repair
        self._current_document = value.document
        self._session_changes.mark_single_changed()
        self._previewing_original = False
        self.ocr_panel.set_result(value.ocr)
        self.translation_panel.set_result(value.translation)
        self.inpainting_panel.set_result(value.repair)
        self._composition_editor = (
            self._create_composition_editor.execute(
                value.repair.result.document,
                value.document,
                value.layout,
            )
            if self._create_composition_editor is not None
            else None
        )
        if self._composition_editor is not None:
            self.text_edit_panel.set_layout(value.layout)
            if value.layout.layers:
                self._layer_selection_changed(value.layout.layers[0].region_id)
        else:
            self.text_edit_panel.clear_result()
            self.layer_style_panel.set_layer(None)
            self.curved_text_panel.set_layer(None)
        self.image_canvas.set_document(value.document)
        self.image_canvas.set_regions(value.ocr.regions)
        self.image_canvas.set_text_layout(value.layout)
        self.image_canvas.set_erase_mask(value.repair.erase_mask)
        self.inpainting_panel.show_mask.setChecked(False)
        self.image_canvas.set_mask_visible(False)
        overflow_count = sum(layer.overflow for layer in value.layout.layers)
        self.pipeline_panel.set_completed(value.repair.result.warning, overflow_count)
        self.side_tabs.setCurrentWidget(self.pipeline_panel)
        self.last_error = None
        self._active_operation = None
        message = f"单图翻译完成：已渲染 {len(value.layout.layers)} 个译文区域"
        self._set_busy(False, message)
        self.workflow_completed.emit(value)

    def _edit_succeeded(self, value: object) -> None:
        if not isinstance(value, CompositionEditResult):
            self._operation_failed(TypeError("编辑用例返回了无效结果"))
            return
        operation = self._active_operation
        selected_region_id = value.affected_region_id or self.text_edit_panel.selected_region_id
        self._current_document = value.document
        self._session_changes.mark_single_changed()
        self._previewing_original = False
        self.image_canvas.set_document(value.document)
        self.image_canvas.set_regions(self._ocr_result.regions if self._ocr_result else ())
        self.image_canvas.set_text_layout(value.layout)
        self.image_canvas.set_erase_mask(
            self._repair_outcome.erase_mask if self._repair_outcome else None
        )
        self.image_canvas.set_mask_visible(False)
        self.text_edit_panel.set_layout(
            value.layout,
            value.can_undo,
            value.can_redo,
            selected_region_id,
        )
        selected_region_id = self.text_edit_panel.selected_region_id
        selected = None
        if selected_region_id is not None:
            try:
                selected = value.layout.layer_by_id(selected_region_id)
            except KeyError:
                selected = None
        self.layer_style_panel.set_layer(selected)
        self.curved_text_panel.set_layer(selected)
        if selected_region_id is not None:
            self.image_canvas.select_layer(selected_region_id)
        self.text_edit_panel.set_edit_completed(selected.overflow if selected else False)
        if operation == "curve":
            self.curved_text_panel.status_label.setText("弧形路径已应用，可继续拖动控制点")
        self.side_tabs.setCurrentWidget(
            self.curved_text_panel if operation == "curve" else self.text_edit_panel
        )
        self.last_error = None
        self._active_operation = None
        self._set_busy(False, "译文编辑已应用")

    def _manual_region_succeeded(self, value: object) -> None:
        if (
            not isinstance(value, tuple)
            or len(value) != 2
            or not isinstance(value[0], ManualRegionResult)
            or not isinstance(value[1], CompositionEditResult)
        ):
            self._operation_failed(TypeError("手动区域处理返回了无效结果"))
            return
        manual, edit = value
        self._edit_succeeded(edit)
        self.image_canvas.set_erase_mask(manual.erase_mask)
        self.image_canvas.set_mask_visible(False)
        self.manual_region_panel.status_label.setText(
            f"手动区域已处理：{manual.translated_text}"
        )
        self.side_tabs.setCurrentWidget(self.manual_region_panel)
        self.statusBar().showMessage("手动区域已加入，可使用编辑页撤销或调整")
        self.manual_region_completed.emit(manual)

    def _batch_snapshot_updated(self, value: object) -> None:
        if not isinstance(value, BatchSnapshot):
            return
        self._batch_snapshot = value
        self.batch_panel.set_snapshot(value)
        self.batch_panel.set_available(
            self._run_batch is not None and self._task_runner is not None,
            value.status is BatchStatus.RUNNING,
        )

    def _batch_succeeded(self, value: object) -> None:
        if not isinstance(value, BatchSnapshot):
            self._operation_failed(TypeError("批量调度返回了无效结果"))
            return
        self._batch_snapshot = value
        self._session_changes.replace_batch_results(
            {
                item.item_id
                for item in value.items
                if item.status is BatchItemStatus.COMPLETED
            }
        )
        self.batch_panel.set_snapshot(value)
        self.side_tabs.setCurrentWidget(self.batch_panel)
        self.last_error = None
        self._active_operation = None
        message = (
            f"批量任务已取消：成功 {value.completed_count}，"
            f"失败 {value.failed_count}"
            if value.status is BatchStatus.CANCELLED
            else f"批量任务完成：成功 {value.completed_count}，失败 {value.failed_count}"
        )
        self._set_busy(False, message)
        self.batch_completed.emit(value)

    def _batch_preview_succeeded(self, value: object) -> None:
        if not isinstance(value, ImageDocument):
            self._operation_failed(TypeError("批量结果缓存返回了无效图片"))
            return
        self._current_document = value
        self._source_document = None
        self._ocr_result = None
        self._translation_result = None
        self._repair_outcome = None
        self._composition_editor = None
        self._batch_previewing = True
        self.image_canvas.set_document(value)
        self.image_canvas.set_regions(())
        self.image_canvas.set_text_layout(TextLayout(()))
        self.image_canvas.set_erase_mask(None)
        self.text_edit_panel.clear_result()
        self.layer_style_panel.set_layer(None)
        self.curved_text_panel.set_layer(None)
        self.content_stack.setCurrentWidget(self.image_workspace)
        self.side_tabs.setCurrentWidget(self.batch_panel)
        self.last_error = None
        self._active_operation = None
        name = self._pending_batch_preview_name or value.asset.source_path.name
        self._pending_batch_preview_name = None
        self._set_busy(False, f"正在预览批量结果：{name}")

    def _batch_export_succeeded(self, value: object) -> None:
        if not isinstance(value, BatchExportResult):
            self._operation_failed(TypeError("选择性批量导出返回了无效结果"))
            return
        self.last_error = None
        self._session_changes.mark_batch_exported(
            {item.item_id for item in value.items if item.succeeded}
        )
        self._active_operation = None
        message = f"批量导出完成：成功 {value.succeeded_count}，失败 {value.failed_count}"
        self.batch_panel.status_label.setText(message)
        self.side_tabs.setCurrentWidget(self.batch_panel)
        self._set_busy(False, message)

    def _clear_batch_succeeded(self, value: object) -> None:
        del value
        self._batch_snapshot = None
        self._session_changes.clear_batch()
        self.batch_panel.clear_batch()
        if self._batch_previewing:
            self._batch_previewing = False
            self._current_document = None
            self._source_document = None
            self._composition_editor = None
            self.image_canvas.clear_document()
            self.content_stack.setCurrentWidget(self.empty_state)
        self.last_error = None
        self._active_operation = None
        self._set_busy(False, "批量列表和缓存已清理")

    def _workflow_failed(self, error: Exception) -> None:
        if isinstance(error, JobCancelled):
            self._active_operation = None
            self.last_error = None
            self.pipeline_panel.set_cancelled()
            if self._source_document is not None:
                self._current_document = self._source_document
                self.image_canvas.set_document(self._source_document)
                self.image_canvas.set_regions(())
            self._ocr_result = None
            self._translation_result = None
            self._repair_outcome = None
            self._composition_editor = None
            self.ocr_panel.clear_result()
            self.translation_panel.clear_result()
            self.inpainting_panel.clear_result()
            self.text_edit_panel.clear_result()
            self.layer_style_panel.set_layer(None)
            self.curved_text_panel.set_layer(None)
            self._set_busy(False, "单图翻译任务已取消")
            return
        self.pipeline_panel.status_label.setText(str(error) or type(error).__name__)
        self._operation_failed(error)

    def _export_succeeded(self, value: object) -> None:
        target = Path(value) if isinstance(value, (str, Path)) else None
        if target is None:
            self._operation_failed(TypeError("导出用例返回了无效结果"))
            return
        self.last_error = None
        self._session_changes.mark_single_exported()
        self._active_operation = None
        self._set_busy(False, f"已导出：{target.name}")
        self.image_exported.emit(str(target))

    def _operation_failed(self, error: Exception) -> None:
        self.last_error = str(error) or type(error).__name__
        if self._active_operation == "ocr":
            self.ocr_panel.status_label.setText(self.last_error)
        elif self._active_operation == "translation":
            self.translation_panel.status_label.setText(self.last_error)
        elif self._active_operation == "repair":
            self.inpainting_panel.status_label.setText(self.last_error)
        elif self._active_operation in {"edit", "geometry", "style"}:
            self.text_edit_panel.status_label.setText(self.last_error)
            if self._composition_editor is not None:
                self.image_canvas.set_text_layout(self._composition_editor.layout)
        elif self._active_operation == "curve":
            self.curved_text_panel.status_label.setText(self.last_error)
            if self._composition_editor is not None:
                self.image_canvas.set_text_layout(self._composition_editor.layout)
        elif self._active_operation == "manual":
            self.manual_region_panel.status_label.setText(self.last_error)
        elif self._active_operation in {
            "batch",
            "batch_preview",
            "batch_export",
            "batch_clear",
        }:
            self.batch_panel.status_label.setText(self.last_error)
            self._pending_batch_preview_name = None
        self._active_operation = None
        self._set_busy(False, self.last_error)
        self.export_button.setEnabled(self._current_document is not None)
        self.operation_failed.emit(self.last_error)
        QMessageBox.critical(self, "图片处理失败", self.last_error)

    def _set_busy(self, busy: bool, message: str) -> None:
        available = self._import_image is not None and self._task_runner is not None
        self.import_button.setEnabled(available and not busy)
        self.header_import_button.setEnabled(available and not busy)
        batch_available = (
            self._run_batch is not None
            and self._batch_result_store is not None
            and self._export_batch_selection is not None
            and self._task_runner is not None
        )
        self.batch_import_button.setEnabled(batch_available and not busy)
        self.export_button.setEnabled(
            not busy and self._current_document is not None and self._export_image is not None
        )
        ocr_available = self._recognize_text is not None and self._current_document is not None
        self.ocr_button.setEnabled(not busy and ocr_available)
        self.ocr_panel.recognize_button.setEnabled(not busy and ocr_available)
        translation_available = (
            self._translate_regions is not None and self._ocr_result is not None
        )
        self.translate_button.setEnabled(not busy and translation_available)
        self.translation_panel.translate_button.setEnabled(
            not busy and translation_available
        )
        repair_available = (
            self._repair_regions is not None
            and self._translation_result is not None
            and any(
                unit.should_erase_source for unit in self._translation_result.units
            )
        )
        self.repair_button.setEnabled(not busy and repair_available)
        self.inpainting_panel.repair_button.setEnabled(not busy and repair_available)
        workflow_available = (
            self._translate_image is not None and self._source_document is not None
        )
        self.auto_button.setEnabled(not busy and workflow_available)
        self.pipeline_panel.start_button.setEnabled(not busy and workflow_available)
        self.pipeline_panel.cancel_button.setEnabled(
            busy and self._active_operation == "workflow"
        )
        editor_available = self._composition_editor is not None
        self.text_edit_panel.apply_button.setEnabled(
            not busy
            and editor_available
            and self.text_edit_panel.selected_region_id is not None
        )
        self.text_edit_panel.undo_button.setEnabled(
            not busy and editor_available and self._composition_editor.can_undo
        )
        self.text_edit_panel.redo_button.setEnabled(
            not busy and editor_available and self._composition_editor.can_redo
        )
        self.layer_style_panel.set_editor_available(editor_available, busy)
        self.curved_text_panel.set_editor_available(editor_available, busy)
        manual_available = (
            self._process_manual_region is not None
            and self._create_composition_editor is not None
            and self._source_document is not None
        )
        self.manual_region_panel.set_available(manual_available, busy)
        batch_running = busy and self._active_operation == "batch"
        self.batch_panel.set_available(
            batch_available and (not busy or batch_running),
            batch_running,
        )
        self.image_canvas.setEnabled(not busy)
        self.statusBar().showMessage(message)

    def closeEvent(self, event: Any) -> None:
        if self._session_changes.has_unexported_changes and not self._confirm_discard(
            self._session_changes.warning_summary()
            + "。应用不保存可重新打开的项目，退出后这些结果将丢失。"
        ):
            event.ignore()
            return
        if self._run_batch is not None:
            self._run_batch.cancel()
        if self._batch_snapshot is not None and self._batch_result_store is not None:
            try:
                self._batch_result_store.clear(self._batch_snapshot.batch_id)
            except Exception:
                pass
        if self._repair_regions is not None:
            self._repair_regions.close()
        if self._translate_image is not None:
            self._translate_image.close()
        self._session_changes.clear_all()
        super().closeEvent(event)

    def _confirm_discard(self, message: str) -> bool:
        if self._confirm_discard_callback is not None:
            return self._confirm_discard_callback(message)
        if QApplication.platformName() == "offscreen":
            return True
        choice = QMessageBox.warning(
            self,
            "未导出的结果",
            message,
            QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        return choice == QMessageBox.StandardButton.Discard


_STYLE = """
QMainWindow, QWidget#workspace {
    background: #f4f6fa;
    color: #172033;
    font-family: "Segoe UI", "Microsoft YaHei", sans-serif;
}
QLabel#productTitle {
    color: #172033;
    font-size: 26px;
    font-weight: 700;
}
QLabel#productSubtitle, QLabel#versionLabel, QLabel#emptyStateHint {
    color: #647087;
    font-size: 13px;
}
QFrame#pipelineCard {
    background: #ffffff;
    border: 1px solid #e3e8f1;
    border-radius: 12px;
}
QLabel#pipelineStage {
    color: #546078;
    font-size: 13px;
    font-weight: 600;
    padding: 6px;
}
QFrame#emptyState, QLabel#imageCanvas {
    background: #ffffff;
    border: 2px dashed #ccd5e4;
    border-radius: 16px;
}
QLabel#imageMarker {
    background: #e9f0ff;
    color: #3667c8;
    border-radius: 28px;
    font-size: 11px;
    font-weight: 700;
    min-width: 64px;
    min-height: 56px;
}
QLabel#emptyStateTitle {
    color: #172033;
    font-size: 20px;
    font-weight: 650;
}
QPushButton#importButton, QPushButton#headerImportButton, QPushButton#batchImportButton, QPushButton#ocrButton,
QPushButton#recognizeButton, QPushButton#headerTranslateButton,
QPushButton#translateButton, QPushButton#headerRepairButton,
QPushButton#repairButton, QPushButton#headerAutoButton,
QPushButton#startWorkflowButton, QPushButton#exportButton {
    background: #3973db;
    color: #ffffff;
    border: none;
    border-radius: 8px;
    padding: 9px 16px;
    font-weight: 600;
}
QPushButton#exportButton {
    background: #ffffff;
    color: #315da9;
    border: 1px solid #b8c8e4;
}
QFrame#ocrPanel, QFrame#translationPanel, QFrame#inpaintingPanel,
QFrame#pipelinePanel, QFrame#textEditPanel, QFrame#layerStylePanel,
QFrame#manualRegionPanel, QFrame#batchPanel, QFrame#curvedTextPanel {
    background: #ffffff;
    border: none;
}
QTabWidget#sideTabs::pane {
    background: #ffffff;
    border: 1px solid #dfe5ef;
    border-radius: 10px;
}
QTabBar::tab {
    background: #e8edf5;
    color: #53627a;
    border: 1px solid #d5dce8;
    border-bottom: none;
    padding: 7px 18px;
}
QTabBar::tab:selected {
    background: #ffffff;
    color: #172033;
    font-weight: 600;
}
QLabel#panelTitle {
    color: #172033;
    font-size: 18px;
    font-weight: 650;
}
QLabel#panelHint, QLabel#ocrStatusLabel {
    color: #647087;
    font-size: 12px;
}
QLabel#translationStatusLabel, QLabel#protectionSummary {
    color: #647087;
    font-size: 12px;
}
QLabel#inpaintingStatusLabel {
    color: #647087;
    font-size: 12px;
}
QLabel#pipelineStatusLabel {
    color: #52647e;
    font-size: 12px;
}
QListWidget#pipelineStages {
    background: #f7f9fc;
    color: #34425a;
    border: 1px solid #e0e6ef;
    border-radius: 7px;
    padding: 5px;
}
QPushButton#cancelWorkflowButton, QPushButton#toggleOriginalButton,
QPushButton#keepOriginalButton, QPushButton#undoEditButton,
QPushButton#redoEditButton, QPushButton#fitCanvasButton {
    background: #ffffff;
    color: #415674;
    border: 1px solid #bdc9da;
    border-radius: 7px;
    padding: 8px 12px;
}
QPushButton#applyTextEditButton {
    background: #3973db;
    color: #ffffff;
    border: none;
    border-radius: 7px;
    padding: 8px 12px;
    font-weight: 600;
}
QPushButton#applyLayerStyleButton, QPushButton#addTextLayerButton {
    background: #3973db;
    color: #ffffff;
    border: none;
    border-radius: 7px;
    padding: 8px 12px;
    font-weight: 600;
}
QPushButton#selectManualRegionButton, QPushButton#processManualRegionButton {
    background: #3973db;
    color: #ffffff;
    border: none;
    border-radius: 7px;
    padding: 8px 12px;
    font-weight: 600;
}
QPushButton#addBatchImagesButton, QPushButton#startBatchButton,
QPushButton#exportBatchButton {
    background: #3973db;
    color: #ffffff;
    border: none;
    border-radius: 7px;
    padding: 8px 12px;
    font-weight: 600;
}
QPushButton#defaultCurveButton, QPushButton#applyCurveButton {
    background: #3973db;
    color: #ffffff;
    border: none;
    border-radius: 7px;
    padding: 8px 12px;
    font-weight: 600;
}
QPushButton#removeCurveButton {
    background: #ffffff;
    color: #415674;
    border: 1px solid #bdc9da;
    border-radius: 7px;
    padding: 8px 12px;
}
QPushButton#clearBatchButton, QPushButton#cancelBatchButton {
    background: #ffffff;
    color: #415674;
    border: 1px solid #bdc9da;
    border-radius: 7px;
    padding: 8px 12px;
}
QPushButton#deleteTextLayerButton {
    background: #ffffff;
    color: #b4232c;
    border: 1px solid #d8a6aa;
    border-radius: 7px;
    padding: 8px 12px;
}
QLabel#styleSelectedLabel {
    color: #52647e;
    font-size: 12px;
}
QListWidget#editableLayers, QPlainTextEdit#translatedTextEditor {
    background: #ffffff;
    color: #172033;
    border: 1px solid #d5dce8;
    border-radius: 6px;
    padding: 5px;
}
QLabel#editStatusLabel {
    color: #52647e;
    font-size: 12px;
}
QLabel#manualSelectionLabel, QLabel#manualRegionStatus {
    color: #52647e;
    font-size: 12px;
}
QLabel#batchStatusLabel {
    color: #52647e;
    font-size: 12px;
}
QLabel#curveSelectedLabel, QLabel#curveStatusLabel {
    color: #52647e;
    font-size: 12px;
}
QTreeWidget#batchItems {
    background: #ffffff;
    color: #172033;
    border: 1px solid #d5dce8;
    border-radius: 6px;
}
QComboBox#ocrLanguageCombo, QComboBox#translationModeCombo,
QComboBox#sourceLanguageCombo, QComboBox#targetLanguageCombo,
QLineEdit#brandTerms, QTreeWidget#ocrResults, QTreeWidget#translationResults {
    background: #ffffff;
    color: #172033;
    border: 1px solid #d5dce8;
    border-radius: 6px;
    padding: 6px;
}
QPushButton:disabled {
    background: #aebbd1;
    color: #eef2f8;
    border: none;
}
QLabel#readinessLabel {
    color: #53627a;
    font-size: 12px;
}
QStatusBar {
    background: #ffffff;
    color: #53627a;
    border-top: 1px solid #e3e8f1;
}
"""
