"""编辑器顶部操作栏 — 14 个 QToolButton + 文件名标签 + 缩放比例标签。

所有按钮使用 Qt 标准图标 (QStyle.StandardPixmap)，中文 tooltip。
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QStyle,
    QToolButton,
)

from src.ui.editor.icons import standard_icon


class TopBar(QFrame):
    """顶部操作栏。"""

    import_requested = Signal()
    ocr_requested = Signal()
    translate_requested = Signal()
    toggle_original_requested = Signal()
    toggle_layers_requested = Signal()
    undo_requested = Signal()
    redo_requested = Signal()
    zoom_in_requested = Signal()
    zoom_out_requested = Signal()
    fit_requested = Signal()
    export_requested = Signal()
    back_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("topBar")
        self.setFixedHeight(44)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(4)

        # 1. 返回首页
        self.back_btn = _make_tool_button(
            QStyle.StandardPixmap.SP_ArrowBack, "返回首页"
        )
        self.back_btn.clicked.connect(self.back_requested.emit)

        # 2. 文件名
        self.file_label = QLabel("未打开图片")
        self.file_label.setStyleSheet(
            "color: #9898b0; font-size: 12px; padding: 0 8px;"
        )

        layout.addWidget(self.back_btn)
        layout.addWidget(self.file_label)

        # 分隔
        layout.addWidget(_separator())

        # 3. 导入
        self.import_btn = _make_tool_button(
            QStyle.StandardPixmap.SP_DialogOpenButton, "导入图片 (Ctrl+O)"
        )
        self.import_btn.clicked.connect(self.import_requested.emit)

        layout.addWidget(self.import_btn)

        # 分隔
        layout.addWidget(_separator())

        # 4. OCR
        self.ocr_btn = _make_tool_button(
            QStyle.StandardPixmap.SP_FileDialogContentsView, "OCR 文字识别"
        )
        self.ocr_btn.clicked.connect(self.ocr_requested.emit)

        # 5. 一键翻译
        self.translate_btn = _make_tool_button(
            QStyle.StandardPixmap.SP_MediaPlay, "一键翻译"
        )
        self.translate_btn.clicked.connect(self.translate_requested.emit)

        layout.addWidget(self.ocr_btn)
        layout.addWidget(self.translate_btn)

        # 分隔
        layout.addWidget(_separator())

        # 6. 原图/译图切换
        self.toggle_original_btn = _make_tool_button(
            QStyle.StandardPixmap.SP_BrowserReload, "切换原图/译图"
        )
        self.toggle_original_btn.setCheckable(True)
        self.toggle_original_btn.clicked.connect(self.toggle_original_requested.emit)

        # 7. 显示/隐藏文字图层
        self.toggle_layers_btn = _make_tool_button(
            QStyle.StandardPixmap.SP_FileDialogDetailedView, "显示/隐藏文字图层"
        )
        self.toggle_layers_btn.setCheckable(True)
        self.toggle_layers_btn.setChecked(True)
        self.toggle_layers_btn.clicked.connect(self.toggle_layers_requested.emit)

        layout.addWidget(self.toggle_original_btn)
        layout.addWidget(self.toggle_layers_btn)

        # 分隔
        layout.addWidget(_separator())

        # 8. 撤销
        self.undo_btn = _make_tool_button(
            QStyle.StandardPixmap.SP_ArrowBack, "撤销 (Ctrl+Z)"
        )
        self.undo_btn.clicked.connect(self.undo_requested.emit)

        # 9. 重做
        self.redo_btn = _make_tool_button(
            QStyle.StandardPixmap.SP_ArrowForward, "重做 (Ctrl+Shift+Z)"
        )
        self.redo_btn.clicked.connect(self.redo_requested.emit)

        layout.addWidget(self.undo_btn)
        layout.addWidget(self.redo_btn)

        # 分隔
        layout.addWidget(_separator())

        # 10. 缩小
        self.zoom_out_btn = _make_tool_button(
            QStyle.StandardPixmap.SP_MediaSeekBackward, "缩小 (Ctrl+-)"
        )
        self.zoom_out_btn.clicked.connect(self.zoom_out_requested.emit)

        # 11. 缩放比例
        self.zoom_label = QLabel("100%")
        self.zoom_label.setStyleSheet(
            "color: #9898b0; font-size: 12px; min-width: 44px;"
        )
        self.zoom_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # 12. 放大
        self.zoom_in_btn = _make_tool_button(
            QStyle.StandardPixmap.SP_MediaSeekForward, "放大 (Ctrl+=)"
        )
        self.zoom_in_btn.clicked.connect(self.zoom_in_requested.emit)

        layout.addWidget(self.zoom_out_btn)
        layout.addWidget(self.zoom_label)
        layout.addWidget(self.zoom_in_btn)

        # 13. 适应窗口
        self.fit_btn = _make_tool_button(
            QStyle.StandardPixmap.SP_DialogApplyButton, "适应窗口 (Ctrl+0)"
        )
        self.fit_btn.clicked.connect(self.fit_requested.emit)

        layout.addWidget(self.fit_btn)

        # 分隔
        layout.addWidget(_separator())

        # 14. 导出
        self.export_btn = _make_tool_button(
            QStyle.StandardPixmap.SP_DialogSaveButton, "导出图片 (Ctrl+S)"
        )
        self.export_btn.clicked.connect(self.export_requested.emit)

        layout.addWidget(self.export_btn)
        layout.addStretch()

        # 初始状态
        self._reset_state()

    # —— 公开更新方法 ——

    def set_file_name(self, name: str) -> None:
        self.file_label.setText(name)

    def set_zoom(self, percent: int) -> None:
        self.zoom_label.setText(f"{percent}%")

    def set_has_image(self, has: bool) -> None:
        """有图片时启用 OCR / 翻译 / 缩放按钮。"""
        self.import_btn.setEnabled(not self._translating)
        self.ocr_btn.setEnabled(has and not self._translating)
        self.translate_btn.setEnabled(has and not self._translating)
        self.zoom_in_btn.setEnabled(has)
        self.zoom_out_btn.setEnabled(has)
        self.fit_btn.setEnabled(has)

    def set_has_result(self, has: bool) -> None:
        """有翻译结果时启用原图切换 / 导出。"""
        self.toggle_original_btn.setEnabled(has)
        self.export_btn.setEnabled(has)

    def set_has_layers(self, has: bool) -> None:
        """有文字图层时启用图层切换按钮。"""
        self.toggle_layers_btn.setEnabled(has)

    def set_translating(self, translating: bool) -> None:
        """翻译进行中阻止导入/OCR/翻译。"""
        self._translating = translating
        self.import_btn.setEnabled(not translating)
        self.ocr_btn.setEnabled(self._has_image and not translating)
        self.translate_btn.setEnabled(self._has_image and not translating)
        if translating:
            self._saved_file_name = self.file_label.text()
            self.file_label.setText("正在翻译…")
        else:
            if hasattr(self, "_saved_file_name"):
                self.file_label.setText(self._saved_file_name)

    def set_can_undo(self, can: bool) -> None:
        self.undo_btn.setEnabled(can)

    def set_can_redo(self, can: bool) -> None:
        self.redo_btn.setEnabled(can)

    def set_showing_original(self, showing: bool) -> None:
        self.toggle_original_btn.setChecked(showing)

    def _reset_state(self) -> None:
        self._translating = False
        self._has_image = False
        self.file_label.setText("未打开图片")
        self.zoom_label.setText("100%")
        self.ocr_btn.setEnabled(False)
        self.translate_btn.setEnabled(False)
        self.toggle_original_btn.setEnabled(False)
        self.toggle_layers_btn.setEnabled(False)
        self.undo_btn.setEnabled(False)
        self.redo_btn.setEnabled(False)
        self.zoom_in_btn.setEnabled(False)
        self.zoom_out_btn.setEnabled(False)
        self.fit_btn.setEnabled(False)
        self.export_btn.setEnabled(False)


def _make_tool_button(pixmap: QStyle.StandardPixmap, tooltip: str) -> QToolButton:
    btn = QToolButton()
    btn.setIcon(standard_icon(pixmap))
    btn.setToolTip(tooltip)
    btn.setAutoRaise(True)
    btn.setIconSize(btn.iconSize())
    btn.setStyleSheet(
        "QToolButton { border: none; border-radius: 4px; padding: 4px; }"
        "QToolButton:hover { background: #363650; }"
        "QToolButton:checked { background: #3973db; }"
        "QToolButton:disabled { color: #686878; }"
    )
    return btn


def _separator() -> QFrame:
    sep = QFrame()
    sep.setFrameShape(QFrame.Shape.VLine)
    sep.setStyleSheet("color: #3d3d5c;")
    sep.setFixedWidth(1)
    return sep
