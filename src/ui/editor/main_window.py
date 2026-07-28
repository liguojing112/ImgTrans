"""编辑器主窗口 — QStackedWidget 切换首页 / 编辑器页。

集成 QUndoStack + 翻译流水线 + 编辑合成 + 导出。
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QUndoStack
from PySide6.QtWidgets import (
    QFileDialog,
    QMainWindow,
    QStackedWidget,
    QStatusBar,
)

from src.application.composition import EditComposition
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

        # 状态中心
        self._model = EditorModel()

        # 撤销栈
        self._undo_stack = QUndoStack(self)

        # 首页 & 编辑器页
        self._home_page = HomePage()
        self._editor_page = EditorPage(self._undo_stack)

        # QStackedWidget 切换
        self._stack = QStackedWidget()
        self._stack.addWidget(self._home_page)
        self._stack.addWidget(self._editor_page)
        self.setCentralWidget(self._stack)

        # 菜单栏 + 状态栏
        self._build_menus()
        self.setStatusBar(QStatusBar(self))
        self.statusBar().showMessage("就绪")

        # 信号连接
        self._connect_signals()

        # 深色主题
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
            lambda: self._editor_page.view._apply_zoom(1.15)
        )
        view_menu.addAction(zoom_in_action)

        zoom_out_action = QAction("缩小", self)
        zoom_out_action.setShortcut("Ctrl+-")
        zoom_out_action.triggered.connect(
            lambda: self._editor_page.view._apply_zoom(1.0 / 1.15)
        )
        view_menu.addAction(zoom_out_action)

    # —— 信号连接 ——

    def _connect_signals(self) -> None:
        self._home_page.image_translation_requested.connect(self._enter_editor)
        self._editor_page.import_requested.connect(self._on_import)
        self._editor_page.translate_requested.connect(self._on_translate)
        self._editor_page.export_requested.connect(self._on_export)
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
        self._editor_page.set_document(document)
        self._editor_page.set_text_layout(self._model.text_layout)
        self._editor_page.set_export_enabled(True)
        self._editor_page.clear_layer_selection()
        self._editor_page.translate_controls.reset_progress()
        self._stack.setCurrentWidget(self._editor_page)

        asset = document.asset
        self.statusBar().showMessage(
            f"已导入：{asset.source_path.name}  {asset.width}×{asset.height}"
        )
        self._editor_page.view.fit_to_window()

    def _on_import_failed(self, error: Exception) -> None:
        self.statusBar().showMessage(f"导入失败：{error}")

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
        self._undo_stack.clear()

        selection = TranslationSelection(
            mode=TranslationMode.ALL,
            target_language=target_language,
        )

        def on_stage(stage: ImageStage) -> None:
            self._model.translation_stage_changed.emit(stage)
            self._editor_page.translate_controls.set_stage(stage)

        self.statusBar().showMessage(f"正在翻译（OCR：{ocr_language} → 目标：{target_language}）…")

        self._task_runner.submit(
            lambda: self._translate_image.execute(
                document,
                ocr_language,
                selection,
                (),
                on_stage,
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

        # 初始化 EditComposition
        if self._create_composition_editor is not None:
            editor = self._create_composition_editor.execute(
                result.repair.result.document,
                result.document,
                result.layout,
            )
            self._model.composition_editor = editor

        # 更新显示
        self._model.text_layout = result.layout
        self._model.rendered_document = result.document
        self._editor_page.set_document(result.document)
        self._editor_page.set_text_layout(result.layout)
        self._editor_page.set_export_enabled(True)

        # 选中第一个图层
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
        self.statusBar().showMessage(f"翻译失败：{error}")

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
