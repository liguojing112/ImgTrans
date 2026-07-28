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
        self._editor_page.undo_requested.connect(self._undo_stack.undo)
        self._editor_page.redo_requested.connect(self._undo_stack.redo)
        self._editor_page.zoom_in_requested.connect(
            lambda: self._editor_page.view.apply_zoom(1.15)
        )
        self._editor_page.zoom_out_requested.connect(
            lambda: self._editor_page.view.apply_zoom(1.0 / 1.15)
        )
        self._editor_page.fit_requested.connect(
            self._editor_page.view.fit_to_window
        )

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
        if self._task_runner is not None:
            self.statusBar().showMessage(f"正在导入 {source.name}…")
            self._task_runner.submit(
                lambda: self._import_usecase.execute(source),
                self._on_image_loaded,
                self._on_import_failed,
            )
            return
        if self._codec is None:
            self.statusBar().showMessage("图片编解码器不可用")
            return
        try:
            document = self._codec.load(source)
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
        self._model.translation_result = None
        self._model.composition_editor = None
        self._model.rendered_document = None
        self._model.showing_original = False
        self._editor_page.scene.clear_regions()
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

        selection = TranslationSelection(
            mode=TranslationMode.ALL,
            target_language=target_language,
        )

        def on_stage(stage: ImageStage) -> None:
            self._model.translation_stage_changed.emit(stage)
            self._editor_page.translate_controls.set_stage(stage)

        self.statusBar().showMessage(
            f"正在翻译（OCR：{ocr_language} → 目标：{target_language}）…"
        )

        self._task_runner.submit(
            lambda: self._translate_image.execute(
                document, ocr_language, selection, (), on_stage
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

        # 翻译完成后清除 OCR 区域，显示译图层
        self._editor_page.scene.clear_regions()
        self._editor_page.set_document(result.document)
        self._editor_page.set_text_layout(result.layout)
        self._editor_page.top_bar.set_has_result(True)
        self._editor_page.top_bar.set_has_layers(len(result.layout.layers) > 0)
        self._editor_page.top_bar.set_translating(False)
        self._editor_page.top_bar.set_showing_original(False)

        if result.layout.layers:
            self._model.selected_layer_id = result.layout.layers[0].region_id

        self._editor_page.view.fit_to_window()

        layer_count = len(result.layout.layers)
        provider = result.translation.provider
        self.statusBar().showMessage(
            f"翻译完成：{layer_count} 个文字图层（{provider}）"
        )
        self._model.translation_finished.emit(result)

    def _on_translation_failed(self, error: Exception) -> None:
        self._model.translating = False
        self._model.translation_failed.emit(str(error))
        self._editor_page.translate_controls.reset_progress()
        self._editor_page.translate_controls.set_translating(False)
        self._editor_page.top_bar.set_translating(False)
        self.statusBar().showMessage(f"翻译失败：{error}")

    # —— 原图/译图切换 ——

    def _on_toggle_original(self) -> None:
        if self._model.translation_result is None:
            return
        showing = not self._model.showing_original
        self._model.showing_original = showing

        if showing and self._model.source_document is not None:
            self._editor_page.set_document(self._model.source_document)
            self._editor_page.set_text_layout(self._model.text_layout)
        else:
            rendered = self._model.rendered_document
            if rendered is not None:
                self._editor_page.set_document(rendered)
                self._editor_page.set_text_layout(self._model.text_layout)

        self._editor_page.top_bar.set_showing_original(showing)

    # —— 显示/隐藏文字图层 ——

    def _on_toggle_layers(self) -> None:
        visible = not self._model.layers_visible
        self._model.layers_visible = visible
        self._editor_page.set_layers_visible(visible)

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
                self.statusBar().showMessage(f"已导出：{target.name}")
            except Exception as exc:
                self.statusBar().showMessage(f"导出失败：{exc}")
            return

        if self._task_runner is not None:
            self.statusBar().showMessage(f"正在导出 {target.name}…")
            self._task_runner.submit(
                lambda: self._export_usecase.execute(document, target),
                lambda p: self.statusBar().showMessage(f"已导出：{Path(p).name}"),
                lambda e: self.statusBar().showMessage(f"导出失败：{e}"),
            )
            return

        try:
            result = self._export_usecase.execute(document, target)
            self.statusBar().showMessage(f"已导出：{result.name}")
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
