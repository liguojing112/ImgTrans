from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QButtonGroup,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFontComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from src.domain.layout import TextBox
from src.ui.common import wrap_spin
from src.ui.editor.theme import EDITOR_DARK_THEME


def _apply_editor_theme(dialog: QDialog) -> None:
    """给顶层工具对话框套用编辑器浅色主题。

    对话框是独立顶层窗口，主窗口的样式表不会级联进来；不套主题时
    系统深色模式下会出现深底 + 深色文字的不可读组合。
    """
    dialog.setProperty("editorStyle", True)
    dialog.setStyleSheet(EDITOR_DARK_THEME)


class EraseToolDialog(QDialog):
    rectangle_requested = Signal()
    brush_changed = Signal(str, int)
    preview_changed = Signal(bool)
    clear_requested = Signal()
    apply_requested = Signal()
    undo_requested = Signal()
    add_text_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("AI 消除")
        _apply_editor_theme(self)
        self.setModal(False)
        self.setMinimumWidth(340)
        layout = QVBoxLayout(self)
        title = QLabel("AI 消除")
        title.setObjectName("propertyTitle")
        layout.addWidget(title)
        hint = QLabel("先框选或用画笔涂抹要消除的区域；橡皮擦可修正蒙版。")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        tools = QHBoxLayout()
        self.tool_group = QButtonGroup(self)
        self.tool_group.setExclusive(True)
        self.rectangle_button = QPushButton("矩形框选")
        self.paint_button = QPushButton("涂抹画笔")
        self.erase_button = QPushButton("蒙版橡皮擦")
        # 主题通用 QPushButton 规则不分状态，选中/未选中无法区分；
        # 模式按钮用控件级内联样式保持选中态高亮（控件级优先于窗口级样式表）
        for button in (
            self.rectangle_button,
            self.paint_button,
            self.erase_button,
        ):
            button.setCheckable(True)
            button.setStyleSheet(
                "QPushButton {"
                " background: #ffffff; color: #212733;"
                " border: 1px solid #d5d9e0; border-radius: 6px;"
                " padding: 6px 10px;"
                "}"
                "QPushButton:checked {"
                " background: qlineargradient(x1:0, y1:0, x2:0, y2:1,"
                " stop:0 #4a8af4, stop:1 #3973db);"
                " color: #ffffff; border: 1px solid #5a9af4;"
                "}"
            )
            self.tool_group.addButton(button)
            tools.addWidget(button)
        self.rectangle_button.clicked.connect(
            lambda: self.activate_mode("rectangle")
        )
        self.paint_button.clicked.connect(lambda: self.activate_mode("paint"))
        self.erase_button.clicked.connect(lambda: self.activate_mode("erase"))
        layout.addLayout(tools)

        form = QFormLayout()
        self.brush_size = QSpinBox()
        self.brush_size.setRange(2, 240)
        self.brush_size.setValue(28)
        self.brush_size.valueChanged.connect(
            lambda _value: self._emit_current_brush()
        )
        form.addRow("画笔大小", wrap_spin(self.brush_size, width=90, label="画笔大小"))
        self.preview = QCheckBox("查看蒙版（蓝色区域）")
        self.preview.setChecked(True)
        self.preview.toggled.connect(self.preview_changed.emit)
        form.addRow("", self.preview)
        layout.addLayout(form)

        clear = QPushButton("清空蒙版")
        clear.clicked.connect(self.clear_requested.emit)
        layout.addWidget(clear)

        self.mask_status = QLabel("尚未选择消除区域，请直接在画布拖动框选。")
        self.mask_status.setObjectName("propertyNoSelection")
        self.mask_status.setWordWrap(True)
        layout.addWidget(self.mask_status)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Apply
            | QDialogButtonBox.StandardButton.Cancel
        )
        self.apply_button = buttons.button(QDialogButtonBox.StandardButton.Apply)
        self.apply_button.setText("确认消除")
        self.apply_button.setEnabled(False)
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        # Apply 按钮点击只发 clicked 信号（不发 accepted），需单独连接
        self.apply_button.clicked.connect(self.apply_requested.emit)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        follow_up = QHBoxLayout()
        self.undo_button = QPushButton("撤销上次消除")
        self.undo_button.setEnabled(False)
        self.undo_button.clicked.connect(self.undo_requested.emit)
        self.add_text_button = QPushButton("在修复背景上新增文字")
        self.add_text_button.clicked.connect(self.add_text_requested.emit)
        follow_up.addWidget(self.undo_button)
        follow_up.addWidget(self.add_text_button)
        layout.addLayout(follow_up)

        self._current_mode = "paint"
        self.paint_button.setChecked(True)

    def set_mask_ready(self, ready: bool) -> None:
        self.apply_button.setEnabled(ready)
        self.mask_status.setText(
            "已选择消除区域，可以继续涂抹修正或确认消除。"
            if ready
            else "尚未选择消除区域，请直接在画布拖动框选。"
        )

    def activate_mode(self, mode: str) -> None:
        self._current_mode = mode
        if mode == "rectangle":
            self.rectangle_button.setChecked(True)
            self.rectangle_requested.emit()
            self.mask_status.setText("矩形框选已启用，请在画布拖动选择区域。")
            return
        button = self.paint_button if mode == "paint" else self.erase_button
        button.setChecked(True)
        self.brush_changed.emit(mode, self.brush_size.value())
        self.mask_status.setText(
            "涂抹画笔已启用，请按住鼠标左键涂抹。"
            if mode == "paint"
            else "蒙版橡皮擦已启用，请涂抹要移出蒙版的部分。"
        )

    def _emit_current_brush(self) -> None:
        if self._current_mode in {"paint", "erase"}:
            self.brush_changed.emit(
                self._current_mode,
                self.brush_size.value(),
            )

    def set_running(self, running: bool) -> None:
        for widget in (
            self.rectangle_button,
            self.paint_button,
            self.erase_button,
            self.brush_size,
            self.preview,
            self.apply_button,
        ):
            widget.setEnabled(not running)
        # 消除执行中禁止新增文字/撤销，避免文字合成到未修复的旧背景上
        self.add_text_button.setEnabled(not running)
        self.undo_button.setEnabled(not running)
        if running:
            self.mask_status.setText("正在执行 AI 消除，请稍候…")

    def set_completed(self, backend_id: str) -> None:
        self.set_running(False)
        self.apply_button.setEnabled(False)
        self.undo_button.setEnabled(True)
        self.mask_status.setText(
            f"AI 消除完成（{backend_id}）。可继续涂抹、撤销消除或新增文字。"
        )

    def set_failed(self, message: str) -> None:
        self.set_running(False)
        self.apply_button.setEnabled(True)
        self.mask_status.setText(f"AI 消除失败：{message}")

    def set_undo_available(self, available: bool) -> None:
        self.undo_button.setEnabled(available)


class CropToolDialog(QDialog):
    selection_requested = Signal()
    apply_requested = Signal(object)
    transform_requested = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("裁剪")
        _apply_editor_theme(self)
        self.setModal(False)
        self.setMinimumWidth(320)
        self._box: TextBox | None = None
        layout = QVBoxLayout(self)
        title = QLabel("裁剪与图片变换")
        title.setObjectName("propertyTitle")
        layout.addWidget(title)
        form = QFormLayout()
        self.ratio = QComboBox()
        for label, value in (
            ("自由比例", ""),
            ("1:1", "1:1"),
            ("4:3", "4:3"),
            ("3:4", "3:4"),
            ("16:9", "16:9"),
            ("9:16", "9:16"),
            ("自定义比例", "custom"),
        ):
            self.ratio.addItem(label, value)
        form.addRow("裁剪比例", self.ratio)
        self.custom_width = QDoubleSpinBox()
        self.custom_width.setRange(0.1, 100)
        self.custom_width.setValue(3)
        self.custom_width.setDecimals(1)
        self.custom_height = QDoubleSpinBox()
        self.custom_height.setRange(0.1, 100)
        self.custom_height.setValue(2)
        self.custom_height.setDecimals(1)
        custom = QHBoxLayout()
        custom.addWidget(wrap_spin(self.custom_width, width=70, label="宽"))
        custom.addWidget(QLabel(":"))
        custom.addWidget(wrap_spin(self.custom_height, width=70, label="高"))
        form.addRow("自定义宽高比", custom)
        layout.addLayout(form)
        self.selection_label = QLabel("尚未框选裁剪区域")
        layout.addWidget(self.selection_label)
        select = QPushButton("在画布框选")
        select.clicked.connect(self._request_selection)
        layout.addWidget(select)
        transform_row = QHBoxLayout()
        for label, operation in (
            ("左转 90°", "rotate_90_ccw"),
            ("右转 90°", "rotate_90_cw"),
            ("旋转 180°", "rotate_180"),
        ):
            button = QPushButton(label)
            button.clicked.connect(
                lambda _checked=False, value=operation: self.transform_requested.emit(
                    value
                )
            )
            transform_row.addWidget(button)
        layout.addLayout(transform_row)
        flip_row = QHBoxLayout()
        for label, operation in (
            ("水平翻转", "flip_horizontal"),
            ("垂直翻转", "flip_vertical"),
        ):
            button = QPushButton(label)
            button.clicked.connect(
                lambda _checked=False, value=operation: self.transform_requested.emit(
                    value
                )
            )
            flip_row.addWidget(button)
        layout.addLayout(flip_row)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Apply
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Apply).setText("应用裁剪")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        # Apply 按钮点击只发 clicked 信号（不发 accepted），需单独连接
        buttons.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(
            self._apply
        )
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def set_selection(self, box: TextBox) -> None:
        ratio = str(self.ratio.currentData())
        if ratio:
            if ratio == "custom":
                target = self.custom_width.value() / self.custom_height.value()
            else:
                numerator, denominator = (float(value) for value in ratio.split(":"))
                target = numerator / denominator
            if box.width / box.height > target:
                box = TextBox(
                    box.center_x,
                    box.center_y,
                    box.height * target,
                    box.height,
                )
            else:
                box = TextBox(
                    box.center_x,
                    box.center_y,
                    box.width,
                    box.width / target,
                )
        self._box = box
        self.selection_label.setText(
            f"裁剪区域：{box.width:.0f} × {box.height:.0f} px"
        )

    def selected_aspect_ratio(self) -> float | None:
        """Return the active crop ratio, or ``None`` for free-form cropping."""
        value = str(self.ratio.currentData() or "")
        if not value:
            return None
        if value == "custom":
            height = self.custom_height.value()
            return self.custom_width.value() / height if height > 0 else None
        try:
            numerator, denominator = (float(part) for part in value.split(":"))
        except (TypeError, ValueError):
            return None
        return numerator / denominator if denominator > 0 else None

    def clear_selection(self) -> None:
        """Clear the pending crop box before a new crop operation."""
        self._box = None
        self.selection_label.setText("尚未框选裁剪区域")

    def _request_selection(self) -> None:
        self.selection_requested.emit()

    def _apply(self) -> None:
        if self._box is not None:
            self.apply_requested.emit(self._box)
        else:
            self.selection_label.setText("请先在画布框选裁剪区域")
            self._request_selection()


class WatermarkToolDialog(QDialog):
    add_text_requested = Signal(str, float, bool)
    add_image_requested = Signal(object, float, bool)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("添加水印")
        _apply_editor_theme(self)
        self.setModal(False)
        self.setMinimumWidth(360)
        layout = QVBoxLayout(self)
        title = QLabel("添加水印")
        title.setObjectName("propertyTitle")
        layout.addWidget(title)
        form = QFormLayout()
        self.text = QLineEdit("水印")
        form.addRow("文字水印", self.text)
        self.font = QFontComboBox()
        form.addRow("字体", self.font)
        self.font_size = QSpinBox()
        self.font_size.setRange(8, 360)
        self.font_size.setValue(42)
        self.font_size.setSuffix(" px")
        form.addRow("字号", wrap_spin(self.font_size, width=110, label="字号"))
        self.color = QLineEdit("#FFFFFF")
        self.color.setMaxLength(7)
        form.addRow("颜色", self.color)
        self.opacity = QDoubleSpinBox()
        self.opacity.setRange(5, 100)
        self.opacity.setValue(55)
        self.opacity.setSuffix("%")
        form.addRow("透明度", wrap_spin(self.opacity, width=110, label="透明度"))
        self.tiled = QCheckBox("平铺水印")
        form.addRow("", self.tiled)
        self.position = QComboBox()
        for label, value in (
            ("左上", "top_left"),
            ("上中", "top_center"),
            ("右上", "top_right"),
            ("左中", "middle_left"),
            ("居中", "center"),
            ("右中", "middle_right"),
            ("左下", "bottom_left"),
            ("下中", "bottom_center"),
            ("右下", "bottom_right"),
        ):
            self.position.addItem(label, value)
        self.position.setCurrentIndex(4)
        form.addRow("位置", self.position)
        layout.addLayout(form)

        add_text = QPushButton("添加文字水印")
        add_text.clicked.connect(
            lambda: self.add_text_requested.emit(
                self.text.text(),
                self.opacity.value() / 100,
                self.tiled.isChecked(),
            )
        )
        add_image = QPushButton("选择本地图片水印…")
        add_image.clicked.connect(self._choose_image)
        layout.addWidget(add_text)
        layout.addWidget(add_image)
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.button(QDialogButtonBox.StandardButton.Close).setText("关闭")
        close.rejected.connect(self.reject)
        layout.addWidget(close)

    def _choose_image(self) -> None:
        value, _ = QFileDialog.getOpenFileName(
            self,
            "选择图片水印",
            "",
            "图片 (*.png *.jpg *.jpeg *.webp *.bmp)",
        )
        if value:
            self.add_image_requested.emit(
                Path(value),
                self.opacity.value() / 100,
                self.tiled.isChecked(),
            )

    @property
    def selected_font_family(self) -> str:
        return self.font.currentFont().family()

    @property
    def selected_font_size(self) -> float:
        return float(self.font_size.value())

    @property
    def selected_rgb(self) -> tuple[int, int, int]:
        value = self.color.text().strip().lstrip("#")
        try:
            if len(value) != 6:
                raise ValueError
            return tuple(
                int(value[index : index + 2], 16)
                for index in (0, 2, 4)
            )
        except ValueError:
            return 255, 255, 255

    @property
    def selected_position(self) -> str:
        return str(self.position.currentData())


class BatchExportDialog(QDialog):
    """批量导出：选择导出格式与目标文件夹。

    逐图导出一个文件；PDF 格式为每张图一个单页 PDF。
    """

    _FORMAT_ITEMS = (
        ("PNG（推荐，保留透明通道）", ".png"),
        ("JPG", ".jpg"),
        ("WebP", ".webp"),
        ("GIF（静态单帧）", ".gif"),
        ("TIFF（单页）", ".tiff"),
        ("PDF（每张图片一个文件）", ".pdf"),
    )

    def __init__(self, default_suffix: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("批量导出")
        _apply_editor_theme(self)
        self.setMinimumWidth(400)
        layout = QVBoxLayout(self)
        title = QLabel("批量导出工作台图片")
        title.setObjectName("propertyTitle")
        layout.addWidget(title)
        hint = QLabel("工作台中每张图片导出为一个文件。")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        form = QFormLayout()
        self.format = QComboBox()
        for label, value in self._FORMAT_ITEMS:
            self.format.addItem(label, value)
        index = self.format.findData(default_suffix)
        self.format.setCurrentIndex(index if index >= 0 else 0)
        form.addRow("导出格式", self.format)
        self.directory = QLineEdit()
        self.directory.setPlaceholderText("选择保存导出的文件夹")
        dir_row = QHBoxLayout()
        dir_row.addWidget(self.directory)
        browse = QPushButton("浏览...")
        browse.setFixedWidth(70)
        browse.clicked.connect(self._browse)
        dir_row.addWidget(browse)
        form.addRow("目标文件夹", dir_row)
        layout.addLayout(form)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("导出")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _browse(self) -> None:
        value = QFileDialog.getExistingDirectory(self, "选择批量导出目录")
        if value:
            self.directory.setText(value)

    def _accept(self) -> None:
        if not self.directory.text().strip():
            self._browse()
            return
        self.accept()

    @property
    def selected_suffix(self) -> str:
        return str(self.format.currentData())

    @property
    def selected_directory(self) -> Path:
        return Path(self.directory.text().strip())
