"""编辑器主窗口 — QStackedWidget 切换首页 / 编辑器页。

集成 QUndoStack，连接图片导入、模型同步、undo/redo。
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

from src.application.image_io import ImportImage
from src.domain.image import ImageDocument
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
        codec: PillowImageCodec | None = None,
        task_runner: object | None = None,
    ) -> None:
        super().__init__()
        self.setProperty("editorStyle", True)
        self.setObjectName("editorMainWindow")
        self.setWindowTitle("ImgTrans - 图片翻译编辑器")
        self.setMinimumSize(1024, 640)
        self.resize(1280, 800)

        self._import_usecase = import_image
        self._codec = codec
        self._task_runner = task_runner

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
        self._editor_page.set_model(self._model)

    # —— 操作 ——

    def _enter_editor(self) -> None:
        self._stack.setCurrentWidget(self._editor_page)
        self.statusBar().showMessage("导入图片开始编辑")

    def _go_home(self) -> None:
        self._stack.setCurrentWidget(self._home_page)
        self.statusBar().showMessage("就绪")

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
        self._editor_page.set_document(document, None)
        self._stack.setCurrentWidget(self._editor_page)

        asset = document.asset
        self.statusBar().showMessage(
            f"已导入：{asset.source_path.name}  {asset.width}×{asset.height}"
        )
        self._editor_page.view.fit_to_window()

    def _on_import_failed(self, error: Exception) -> None:
        self.statusBar().showMessage(f"导入失败：{error}")

    def request_runtime_recovery(self, reason: str = "runtime") -> None:
        """兼容生产 UI 接口 — 编辑器暂无运行时恢复需求。"""
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
