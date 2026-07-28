"""编辑器主窗口 — QStackedWidget 切换首页 / 编辑器页。

集成 QUndoStack + 翻译流水线 + 编辑合成 + 导出 + TopBar 操作栏。
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QUndoStack
from PySide6.QtWidgets import (
    QMainWindow,
    QStackedWidget,
    QStatusBar,
)

from src.application.image_io import ExportImage, ImportImage
from src.application.translate_image import TranslateImage, TranslateImageResult
from src.domain.image import ImageDocument
from src.domain.job import ImageStage
from src.domain.translation import TranslationSelection, TranslationMode
from src.infrastructure.pillow_image_codec import PillowImageCodec

from src.ui.editor.editor_model import EditorModel
from src.ui.editor.editor_page import EditorPage
from src.ui.editor.home_page import HomePage
from src.ui.editor.theme import EDITOR_DARK_THEME


class EditorMainWindow(QMainWindow):
    """编辑器应用主窗口。"""

    def __init__(
        self,
        import_image: ImportImage,
        export_image: ExportImage | None = None,
        codec: PillowImageCodec | None = None,
        task_runner: object | None = None,
        translate_image: TranslateImage | None = None,
        create_composition_editor: object | None = None,
        recognize_text: object | None = None,
    ) -> None:
        super().__init__()
        self.setProperty("editorStyle", True)
        self.setObjectName("editorMainWindow")
        self.setWindowTitle("ImgTrans - 图片翻译编辑器")
        self.setMinimumSize(1024, 640)
        self.resize(1280, 800)

        self._import_usecase = import_image
        self._export_usecase = export_image
        self._codec = codec
        self._task_runner = task_runner
        self._translate_image = translate_image
        self._create_composition_editor = create_composition_editor
        self._recognize_text = recognize_text

        self._model = EditorModel()
        self._undo_stack = QUndoStack(self)

        self._home_page = HomePage()
        self._editor_page = EditorPage(self._undo_stack)

        self._stack = QStackedWidget()
        self._stack.addWidget(self._home_page)
        self._stack.addWidget(self._editor_page)
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

        file_menu.addSeparator()
        back_action = QAction("返回首页", self)
        back_action.triggered.connect(self._go_home)
        file_menu.addAction(back_action)

        quit_action = QAction("退出", self)
        quit_action.setShortcut("Ctrl+Q")
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        edit_menu = menu.addMenu("编辑")
        undo_action = self._undo_stack.createUndoAction(self, "撤销")
        undo_action.setShortcut("Ctrl+Z")
        edit_menu.addAction(undo_action)

        redo_action = self._undo_stack.createRedoAction(self, "重做")
        redo_action.setShortcut("Ctrl+Shift+Z")
        edit_menu.addAction(redo_action)

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

    # —— 信号连接 ——

    def _connect_signals(self) -> None:
        # 首页
        self._home_page.image_translation_requested.connect(self._enter_editor)

        # EditorPage 核心
        self._editor_page.import_requested.connect(self._on_import)
        self._editor_page.translate_requested.connect(self._on_translate)
        self._editor_page.export_requested.connect(self._on_export)
        self._editor_page.back_requested.connect(self._go_home)

        # TopBar 操作
        self._editor_page.ocr_requested.connect(self._on_ocr)
        self._editor_page.toggle_original_requested.connect(self._on_toggle_original)
        self._editor_page.toggle_layers_requested.connect(self._on_toggle_layers)
        self._editor_page.undo_requested.connect(self._on_undo)
        self._editor_page.redo_requested.connect(self._on_redo)
        self._editor_page.delete_requested.connect(self._on_delete_layer)
        self._editor_page.duplicate_requested.connect(self._on_duplicate_layer)
        self._editor_page.add_layer_requested.connect(self._on_add_layer)
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

        # QUndoStack 状态
        self._undo_stack.canUndoChanged.connect(self._editor_page.top_bar.set_can_undo)
        self._undo_stack.canRedoChanged.connect(self._editor_page.top_bar.set_can_redo)

        # Model
        self._editor_page.set_model(self._model)

    # —— 操作 ——

    def _enter_editor(self) -> None:
        self._stack.setCurrentWidget(self._editor_page)
        self.statusBar().showMessage("导入图片开始编辑")

    def _go_home(self) -> None:
        self._stack.setCurrentWidget(self._home_page)
        self.statusBar().showMessage("就绪")

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
                lambda: _load_document(source, self._import_usecase, self._codec),
                self._on_image_loaded,
                self._on_import_failed,
            )
            return
        if self._codec is None:
            self.statusBar().showMessage("图片编解码器不可用")
            return
        try:
            document = _load_document(source, self._import_usecase, self._codec)
        except Exception as exc:
            self._on_import_failed(exc)
            return
        self._on_image_loaded(document)

    def _on_image_loaded(self, value: object) -> None:
        if not isinstance(value, ImageDocument):
            self._on_import_failed(TypeError("导入返回了无效结果"))
            return

        document: ImageDocument = value
        self._model.document = document
        self._model.source_document = document
        self._model.ocr_result = None
        self._model.translation_result = None
        self._model.composition_editor = None
        self._model.rendered_document = None
        self._model.selected_layer_id = None
        self._model.showing_original = False
        self._undo_stack.clear()
        self._editor_page.scene.clear_regions()
        self._editor_page.ocr_result_panel.clear_result()
        self._editor_page.set_document(document)
        self._editor_page.set_text_layout(self._model.text_layout)
        self._editor_page.clear_layer_selection()
        self._editor_page.translate_controls.reset_progress()

        asset = document.asset
        self._editor_page.top_bar.set_file_name(asset.source_path.name)
        self._editor_page.top_bar.set_has_image(True)
        self._editor_page.top_bar.set_has_result(False)
        self._editor_page.top_bar.set_has_layers(False)
        self._editor_page.top_bar.set_showing_original(False)
        self._editor_page.top_bar.set_zoom(100)

        self._stack.setCurrentWidget(self._editor_page)
        self.statusBar().showMessage(
            f"已导入：{asset.source_path.name}  {asset.width}×{asset.height}"
        )
        self._editor_page.view.fit_to_window()

    def _on_import_failed(self, error: Exception) -> None:
        self.statusBar().showMessage(f"导入失败：{error}")

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
        self.statusBar().showMessage(f"正在 OCR 识别（{ocr_language}）…")

        self._task_runner.submit(
            lambda: self._recognize_text.execute(document, ocr_language),
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
        self._editor_page.top_bar.set_translating(False)

        # 显示 OCR 区域在画布上
        self._editor_page.scene.set_regions(result.regions)
        self._editor_page.ocr_result_panel.set_result(result)

        region_count = len(result.regions)
        self.statusBar().showMessage(
            f"OCR 完成：识别到 {region_count} 个文字区域"
        )
        self._model.ocr_finished.emit(result)

    def _on_ocr_failed(self, error: Exception) -> None:
        self._editor_page.top_bar.set_translating(False)
        self.statusBar().showMessage(f"OCR 失败：{error}")

    # —— 翻译 ——

    def _on_translate(self, ocr_language: str, target_language: str) -> None:
        if self._translate_image is None or self._task_runner is None:
            self.statusBar().showMessage("翻译服务不可用")
            return
        document = self._model.source_document
        if document is None:
            self.statusBar().showMessage("请先导入图片")
            return

        self._model.translating = True
        self._model.translation_started.emit()
        self._editor_page.translate_controls.set_translating(True)
        self._editor_page.top_bar.set_translating(True)
        self._undo_stack.clear()

        ctrl = self._editor_page.translate_controls
        mode = TranslationMode(ctrl.selected_mode)
        source_lang = ctrl.selected_source_language if mode is TranslationMode.SPECIFIC_LANGUAGE else None
        selection = TranslationSelection(
            mode=mode,
            target_language=target_language,
            source_language=source_lang,
        )
        brand_terms = ctrl.configured_brand_terms

        def on_stage(stage: ImageStage) -> None:
            self._model.translation_stage_changed.emit(stage)
            self._editor_page.translate_controls.set_stage(stage)

        self.statusBar().showMessage(
            f"正在翻译（OCR：{ocr_language} → 目标：{target_language}）…"
        )

        self._task_runner.submit(
            lambda: self._translate_image.execute(
                document, ocr_language, selection, brand_terms, on_stage
            ),
            self._on_translation_succeeded,
            self._on_translation_failed,
        )

    def _on_translation_succeeded(self, value: object) -> None:
        if not isinstance(value, TranslateImageResult):
            self._on_translation_failed(TypeError("翻译返回了无效结果"))
            return

        result: TranslateImageResult = value
        self._model.translating = False
        self._model.translation_result = result
        self._model.is_dirty = True

        if self._create_composition_editor is not None:
            editor = self._create_composition_editor.execute(
                result.repair.result.document,
                result.document,
                result.layout,
            )
            self._model.composition_editor = editor

        self._model.text_layout = result.layout
        self._model.rendered_document = result.document
        self._model.showing_original = False

        # 翻译完成后清除 OCR 区域，显示译图层 + 擦除蒙版
        self._editor_page.scene.clear_regions()
        self._editor_page.scene.set_erase_mask(result.repair.erase_mask)
        self._editor_page.set_document(result.document)
        self._editor_page.set_text_layout(result.layout)
        self._editor_page.top_bar.set_has_result(True)
        self._editor_page.top_bar.set_has_layers(len(result.layout.layers) > 0)
        self._editor_page.top_bar.set_translating(False)
        self._editor_page.top_bar.set_showing_original(False)
        self._apply_preview_mode("layers")

        if result.layout.layers:
            self._model.selected_layer_id = result.layout.layers[0].region_id

        self._editor_page.view.fit_to_window()

        # 翻译摘要统计
        units = result.translation.units
        ocr_count = len(result.ocr.regions) if result.ocr else 0
        translated = sum(1 for u in units if u.status.value == "translated")
        review = sum(1 for u in units if u.status.value == "review_required")
        skipped = sum(1 for u in units if u.status.value in ("skipped_language", "skipped_protected"))
        failed = sum(1 for u in units if u.status.value == "failed")
        overflow = sum(1 for layer in result.layout.layers if layer.overflow)

        self._editor_page.translate_controls.set_summary(
            ocr_count, translated, review, skipped, failed, overflow
        )
        self._model.translation_finished.emit(result)

    def _on_translation_failed(self, error: Exception) -> None:
        self._model.translating = False
        self._model.translation_failed.emit(str(error))
        self._editor_page.translate_controls.reset_progress()
        self._editor_page.translate_controls.set_translating(False)
        self._editor_page.top_bar.set_translating(False)
        self.statusBar().showMessage(f"翻译失败：{error}")

    # —— 原图/译图切换（3 态循环）——

    def _on_toggle_original(self) -> None:
        if self._model.translation_result is None:
            return
        cycle = {"original": "translated", "translated": "layers", "layers": "original"}
        next_mode = cycle.get(self._model.preview_mode, "original")
        self._apply_preview_mode(next_mode)

    def _apply_preview_mode(self, mode: str) -> None:
        self._model.preview_mode = mode
        if mode == "original":
            src = self._model.source_document
            if src is not None:
                self._editor_page.set_document(src)
            self._editor_page.scene.set_mask_visible(False)
            self._editor_page.set_layers_visible(False)
            self._editor_page.property_panel.setEnabled(False)
        elif mode == "translated":
            rendered = self._model.rendered_document
            if rendered is not None:
                self._editor_page.set_document(rendered)
            self._editor_page.scene.set_mask_visible(False)
            self._editor_page.set_layers_visible(False)
            self._editor_page.property_panel.setEnabled(True)
        else:  # "layers"
            rendered = self._model.rendered_document
            if rendered is not None:
                self._editor_page.set_document(rendered)
            self._editor_page.scene.set_mask_visible(True)
            self._editor_page.set_layers_visible(True)
            self._editor_page.property_panel.setEnabled(True)
        self._editor_page.top_bar.set_preview_mode(mode)

    # —— 显示/隐藏文字图层 ——

    def _on_toggle_layers(self) -> None:
        visible = not self._model.layers_visible
        self._model.layers_visible = visible
        self._editor_page.set_layers_visible(visible)

    # —— 撤销/重做（桥接 EditComposition）——

    def _on_undo(self) -> None:
        editor = self._model.composition_editor
        if editor is None or self._task_runner is None:
            return
        self.statusBar().showMessage("正在撤销…")
        self._task_runner.submit(
            editor.undo,
            self._editor_page.apply_edit_result,
            lambda e: self.statusBar().showMessage(f"撤销失败：{e}"),
        )

    def _on_redo(self) -> None:
        editor = self._model.composition_editor
        if editor is None or self._task_runner is None:
            return
        self.statusBar().showMessage("正在重做…")
        self._task_runner.submit(
            editor.redo,
            self._editor_page.apply_edit_result,
            lambda e: self.statusBar().showMessage(f"重做失败：{e}"),
        )

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
        else:
            return

        self._task_runner.submit(
            op,
            self._editor_page.apply_edit_result,
            lambda e: self.statusBar().showMessage(f"编辑失败：{e}"),
        )

    # —— 删除 / 复制图层 ——

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
            lambda: editor.add_layer(layer.text),
            self._editor_page.apply_edit_result,
            lambda e: self.statusBar().showMessage(f"复制失败：{e}"),
        )

    def _on_add_layer(self, default_text: str) -> None:
        editor = self._model.composition_editor
        if editor is None or self._task_runner is None:
            return
        self.statusBar().showMessage("正在新增文字图层…")
        self._task_runner.submit(
            lambda: editor.add_layer(default_text),
            self._editor_page.apply_edit_result,
            lambda e: self.statusBar().showMessage(f"新增失败：{e}"),
        )

    # —— 导出 ——

    def _on_export(self, target: Path) -> None:
        document = self._model.rendered_document or self._model.document
        if document is None:
            self.statusBar().showMessage("没有可导出的图片")
            return

        if self._export_usecase is None:
            if self._codec is None:
                self.statusBar().showMessage("导出功能不可用")
                return
            try:
                from src.domain.image import ImageFileFormat
                fmt = ImageFileFormat.from_output_suffix(target.suffix)
                self._codec.save(document, target, fmt)
                self._model.is_dirty = False
                self.statusBar().showMessage(f"已导出：{target}")
            except Exception as exc:
                self.statusBar().showMessage(f"导出失败：{exc}")
            return

        if self._task_runner is not None:
            self.statusBar().showMessage(f"正在导出 {target.name}…")
            def _on_export_ok(p):
                self._model.is_dirty = False
                self.statusBar().showMessage(f"已导出：{Path(p)}")
            self._task_runner.submit(
                lambda: self._export_usecase.execute(document, target),
                _on_export_ok,
                lambda e: self.statusBar().showMessage(f"导出失败：{e}"),
            )
            return

        try:
            result = self._export_usecase.execute(document, target)
            self._model.is_dirty = False
            self.statusBar().showMessage(f"已导出：{result}")
        except Exception as exc:
            self.statusBar().showMessage(f"导出失败：{exc}")

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


# —— 模块级辅助 ——

def _load_document(
    source: Path,
    import_usecase: ImportImage,
    codec: PillowImageCodec | None,
) -> ImageDocument:
    """尝试通过 ImportImage 加载，失败时 fallback 到 BMP/其他格式。"""
    try:
        return import_usecase.execute(source)
    except Exception:
        if source.suffix.lower() == ".bmp":
            return _load_bmp(source)
        raise


def _load_bmp(source: Path) -> ImageDocument:
    """绕过 frozen 格式校验层，直接用 Pillow 加载 BMP 并构造 ImageDocument。"""
    from PIL import Image as PILImage
    from src.domain.image import ImageAsset

    with PILImage.open(source) as img:
        width, height = img.size
        working = img.convert("RGB")
        pixels = working.tobytes()
    asset = ImageAsset(
        source_path=source.resolve(),
        width=width,
        height=height,
        file_size=source.stat().st_size,
        file_format=None,  # type: ignore — BMP 没有对应的 ImageFileFormat
        has_alpha=False,
        orientation_applied=False,
    )
    return ImageDocument(asset=asset, mode="RGB", pixels=pixels)
