"""编辑器顶部操作栏 — 14 个 QToolButton + 文件名标签 + 缩放比例标签。

所有按钮使用 Qt 标准图标 (QStyle.StandardPixmap)，中文 tooltip。
"""

from __future__ import annotations

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QStyle,
    QToolButton,
)

from src.ui.editor.icons import standard_icon


class TopBar(QFrame):
    """顶部操作栏。"""

    import_requested = Signal()
    batch_requested = Signal()
    ocr_requested = Signal()
    translate_requested = Signal()
    toggle_original_requested = Signal()
    split_compare_requested = Signal()
    slider_compare_requested = Signal()
    compare_hold_started = Signal()
    compare_hold_finished = Signal()
    toggle_layers_requested = Signal()
    undo_requested = Signal()
    redo_requested = Signal()
    zoom_in_requested = Signal()
    zoom_out_requested = Signal()
    fit_requested = Signal()
    save_requested = Signal()
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
            "color: #626b7a; padding: 0 8px;"
        )

        layout.addWidget(self.back_btn)
        layout.addWidget(self.file_label)

        # 分隔
        layout.addWidget(_separator())

        # 3. 导入
        self.import_btn = _make_tool_button(
            QStyle.StandardPixmap.SP_DialogOpenButton, "导入图片 (Ctrl+O)", "导入"
        )
        self.import_btn.clicked.connect(self.import_requested.emit)

        layout.addWidget(self.import_btn)
        self.batch_btn = _make_tool_button(
            QStyle.StandardPixmap.SP_FileDialogListView,
            "批量导入、处理和选择性导出",
            "批量",
        )
        self.batch_btn.clicked.connect(self.batch_requested.emit)
        layout.addWidget(self.batch_btn)

        # 分隔
        layout.addWidget(_separator())

        # 4. OCR
        self.ocr_btn = _make_tool_button(
            QStyle.StandardPixmap.SP_FileDialogContentsView, "OCR 文字识别", "OCR"
        )
        self.ocr_btn.clicked.connect(self.ocr_requested.emit)

        # 5. 一键翻译
        self.translate_btn = _make_tool_button(
            QStyle.StandardPixmap.SP_MediaPlay, "开始翻译", "开始翻译"
        )
        self.translate_btn.clicked.connect(self.translate_requested.emit)

        layout.addWidget(self.ocr_btn)
        layout.addWidget(self.translate_btn)

        # 分隔
        layout.addWidget(_separator())

        # 6. 原图/译图单视图切换，下拉菜单保留分屏
        self.toggle_original_btn = _make_tool_button(
            QStyle.StandardPixmap.SP_TitleBarContextHelpButton,
            "单击切换原图/译图；长按临时查看原图；菜单可选择更多对比方式",
            "对比",
        )
        self.toggle_original_btn.setCheckable(True)
        self.toggle_original_btn.setChecked(False)
        self._compare_hold_active = False
        self._suppress_compare_click = False
        self._compare_checked_before_hold = False
        self._compare_hold_timer = QTimer(self)
        self._compare_hold_timer.setSingleShot(True)
        self._compare_hold_timer.setInterval(350)
        self._compare_hold_timer.timeout.connect(self._begin_compare_hold)
        self.toggle_original_btn.pressed.connect(self._start_compare_hold)
        self.toggle_original_btn.released.connect(self._finish_compare_hold)
        self.toggle_original_btn.clicked.connect(self._on_compare_clicked)
        comparison_menu = QMenu(self.toggle_original_btn)
        split_action = comparison_menu.addAction("左右分屏对比")
        split_action.triggered.connect(self.split_compare_requested.emit)
        self._slider_compare_action = comparison_menu.addAction("滑块拖动对比")
        self._slider_compare_action.setCheckable(True)
        self._slider_compare_action.triggered.connect(
            self.slider_compare_requested.emit
        )
        self.toggle_original_btn.setMenu(comparison_menu)
        self.toggle_original_btn.setPopupMode(
            QToolButton.ToolButtonPopupMode.MenuButtonPopup
        )

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
            "color: #626b7a; min-width: 44px;"
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

        # 14. 保存当前成品图
        self.save_btn = _make_tool_button(
            QStyle.StandardPixmap.SP_DialogSaveButton,
            "保存当前译图 (Ctrl+Shift+S)",
            "保存",
        )
        self.save_btn.clicked.connect(self.save_requested.emit)
        layout.addWidget(self.save_btn)

        # 15. 导出
        self.export_btn = _make_tool_button(
            QStyle.StandardPixmap.SP_DialogSaveButton, "导出图片 (Ctrl+S)", "导出"
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
        self._has_image = has
        """有图片时启用 OCR / 翻译 / 缩放按钮。"""
        self.import_btn.setEnabled(not self._translating)
        self.ocr_btn.setEnabled(has and not self._translating)
        self.translate_btn.setEnabled(has and not self._translating)
        self.zoom_in_btn.setEnabled(has)
        self.zoom_out_btn.setEnabled(has)
        self.fit_btn.setEnabled(has)

    def set_has_result(self, has: bool) -> None:
        """有翻译结果时启用分屏对比 / 导出。"""
        self.toggle_original_btn.setEnabled(has)
        self.save_btn.setEnabled(has)
        self.export_btn.setEnabled(has)
        if not has:
            self.toggle_original_btn.setChecked(False)

    def set_export_available(self, available: bool) -> None:
        """允许在没有翻译结果时导出已导入/OCR-only 的原图。"""
        self.save_btn.setEnabled(available)
        self.export_btn.setEnabled(available)

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

    def set_preview_mode(self, mode: str) -> None:
        self._preview_mode = mode

    def set_split_view(self, enabled: bool) -> None:
        self.toggle_original_btn.setToolTip(
            "单击切换原图/译图；长按临时查看原图；当前已启用左右分屏"
            if enabled
            else "单击切换原图/译图；长按临时查看原图；菜单可选择更多对比方式"
        )

    def set_slider_compare(self, enabled: bool) -> None:
        self._slider_compare_action.setChecked(enabled)

    def _start_compare_hold(self) -> None:
        self._compare_hold_active = False
        self._compare_checked_before_hold = self.toggle_original_btn.isChecked()
        self._compare_hold_timer.start()

    def _begin_compare_hold(self) -> None:
        self._compare_hold_active = True
        self._suppress_compare_click = True
        self.compare_hold_started.emit()

    def _finish_compare_hold(self) -> None:
        self._compare_hold_timer.stop()
        if self._compare_hold_active:
            self._compare_hold_active = False
            self.compare_hold_finished.emit()

    def _on_compare_clicked(self) -> None:
        if self._suppress_compare_click:
            self._suppress_compare_click = False
            self.toggle_original_btn.setChecked(
                self._compare_checked_before_hold
            )
            return
        self.toggle_original_requested.emit()

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
        self.save_btn.setEnabled(False)


def _make_tool_button(
    pixmap: QStyle.StandardPixmap,
    tooltip: str,
    text: str = "",
) -> QToolButton:
    btn = QToolButton()
    btn.setIcon(standard_icon(pixmap))
    btn.setToolTip(tooltip)
    if text:
        btn.setText(text)
        btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
    btn.setAutoRaise(True)
    btn.setIconSize(btn.iconSize())
    btn.setStyleSheet(
        "QToolButton { border: none; border-radius: 4px; padding: 4px; }"
        "QToolButton:hover { background: #eef0f4; }"
        "QToolButton:checked { background: qlineargradient(x1:0, y1:0, x2:0, y2:1,"
        "  stop:0 #4a8af4, stop:1 #3973db); border: 1px solid #5a9af4; }"
        "QToolButton:disabled { color: #98a0ad; }"
    )
    return btn


def _separator() -> QFrame:
    sep = QFrame()
    sep.setFrameShape(QFrame.Shape.VLine)
    sep.setStyleSheet("color: #d5d9e0;")
    sep.setFixedWidth(1)
    return sep
