"""图片工具箱 — 中间功能面板（裁剪/旋转/翻转/格式/压缩/水印）。"""

from __future__ import annotations

import uuid
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QFontComboBox,
    QFrame,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from src.ui.toolbox.tool_box_model import OperationParams, WatermarkItem


class OperationPanel(QFrame):
    """中间面板：所有操作参数设置。"""

    apply_requested = Signal(object)  # OperationParams
    watermarks_changed = Signal()  # 水印列表变化（新增/删除/编辑）
    crop_mode_changed = Signal(bool)  # 进入/退出裁剪模式

    def __init__(self) -> None:
        super().__init__()
        self.setProperty("editorStyle", True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(12)

        title = QLabel("操作设置")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_widget = QWidget()
        scroll_widget.setStyleSheet("background: transparent;")
        form = QFormLayout(scroll_widget)
        form.setSpacing(10)
        form.setContentsMargins(0, 0, 0, 0)

        # ── 裁剪 ─
        crop_group = QGroupBox("裁剪")
        crop_group.setStyleSheet(
            "QGroupBox { color: #626b7a; border: 1px solid #d5d9e0;"
            "  border-radius: 6px; margin-top: 8px; padding-top: 12px; }"
        )
        crop_outer = QVBoxLayout(crop_group)
        crop_outer.setSpacing(4)

        # 模式按钮行：进入/取消裁剪模式 + 清空
        crop_btn_row = QHBoxLayout()
        crop_btn_row.setSpacing(6)
        self._crop_mode_btn = QPushButton("✂ 裁剪")
        self._crop_mode_btn.setStyleSheet(self._btn_style())
        self._crop_mode_btn.clicked.connect(self._on_crop_mode_clicked)
        self._crop_cancel_btn = QPushButton("取消")
        self._crop_cancel_btn.setStyleSheet(self._btn_style())
        self._crop_cancel_btn.setVisible(False)
        self._crop_cancel_btn.clicked.connect(self._on_crop_cancel_clicked)
        # 锁定按钮：切换锁定状态，锁定时 W/H 归 0（不裁剪）
        self._crop_lock_btn = QPushButton("锁定")
        self._crop_lock_btn.setCheckable(True)
        self._crop_lock_btn.setStyleSheet(self._btn_style())
        self._crop_lock_btn.setToolTip("锁定裁剪（W/H 归 0，不裁剪）；再点恢复默认")
        self._crop_lock_btn.toggled.connect(self._on_crop_lock_toggled)
        crop_btn_row.addWidget(self._crop_mode_btn)
        crop_btn_row.addWidget(self._crop_cancel_btn)
        crop_btn_row.addWidget(self._crop_lock_btn)
        crop_btn_row.addStretch()
        crop_outer.addLayout(crop_btn_row)

        # 第一行：X / Y
        crop_row1 = QHBoxLayout()
        crop_row1.setSpacing(6)

        self._crop_x_w, self._crop_x = self._make_spin(0, 99999, 0, 50)
        self._crop_y_w, self._crop_y = self._make_spin(0, 99999, 0, 50)
        crop_row1.addWidget(QLabel("X:"))
        crop_row1.addWidget(self._crop_x_w)
        crop_row1.addWidget(QLabel("Y:"))
        crop_row1.addWidget(self._crop_y_w)
        crop_row1.addStretch()
        crop_outer.addLayout(crop_row1)

        # 第二行：W / H
        crop_row2 = QHBoxLayout()
        crop_row2.setSpacing(6)

        self._crop_w_w, self._crop_w = self._make_spin(0, 99999, 100, 50)
        self._crop_h_w, self._crop_h = self._make_spin(0, 99999, 100, 50)
        crop_row2.addWidget(QLabel("W:"))
        crop_row2.addWidget(self._crop_w_w)
        crop_row2.addWidget(QLabel("H:"))
        crop_row2.addWidget(self._crop_h_w)
        crop_row2.addStretch()
        crop_outer.addLayout(crop_row2)
        form.addRow(crop_group)

        # ── 旋转 / 翻转 ──
        rot_group = QGroupBox("旋转 / 翻转")
        rot_group.setStyleSheet(crop_group.styleSheet())
        rot_layout = QHBoxLayout(rot_group)
        rot_layout.setSpacing(6)

        self._rotate_combo = QComboBox()
        self._rotate_combo.addItems(["0°", "90°", "180°", "270°"])
        self._rotate_combo.setStyleSheet(self._combo_style())
        rot_layout.addWidget(QLabel("旋转:"))
        rot_layout.addWidget(self._rotate_combo)

        self._flip_combo = QComboBox()
        self._flip_combo.addItems(["不翻转", "水平翻转", "垂直翻转"])
        self._flip_combo.setStyleSheet(self._combo_style())
        rot_layout.addWidget(QLabel("翻转:"))
        rot_layout.addWidget(self._flip_combo)
        rot_layout.addStretch()
        form.addRow(rot_group)

        # ─ 格式转换 / 压缩 ──
        fmt_group = QGroupBox("格式转换 / 压缩")
        fmt_group.setStyleSheet(crop_group.styleSheet())
        fmt_layout = QFormLayout(fmt_group)
        fmt_layout.setSpacing(6)

        self._format_combo = QComboBox()
        self._format_combo.addItems(
            ["保持原格式", "PNG", "JPG", "WebP", "GIF（静态单帧）", "TIFF（单页）"]
        )
        self._format_combo.setStyleSheet(self._combo_style())
        fmt_layout.addRow("输出格式:", self._format_combo)

        self._quality_w, self._quality_spin = self._make_spin(1, 100, 95, 70)
        fmt_layout.addRow("质量:", self._quality_w)

        self._max_w_w, self._max_w = self._make_spin(0, 99999, 0, 70)
        self._max_h_w, self._max_h = self._make_spin(0, 99999, 0, 70)
        max_row = QHBoxLayout()
        max_row.setSpacing(6)
        max_row.addWidget(self._max_w_w)
        max_row.addWidget(QLabel("×"))
        max_row.addWidget(self._max_h_w)
        max_row.addWidget(QLabel("(0 = 不限制)"))
        max_row.addStretch()
        fmt_layout.addRow("最大尺寸:", max_row)
        form.addRow(fmt_group)

        # ── 水印（多组管理，参考图片翻译页设计）──
        wm_group = QGroupBox("水印")
        wm_group.setStyleSheet(crop_group.styleSheet())
        wm_outer = QVBoxLayout(wm_group)
        wm_outer.setSpacing(4)

        # 水印列表
        self._wm_list = QListWidget()
        self._wm_list.setMaximumHeight(90)
        self._wm_list.setStyleSheet(
            "QListWidget { background: #e6e8ec; border: 1px solid #d5d9e0;"
            "  border-radius: 4px; color: #212733; }"
        )
        self._wm_list.currentRowChanged.connect(self._on_wm_selected)
        wm_outer.addWidget(self._wm_list)

        # 添加/删除按钮
        wm_btn_row = QHBoxLayout()
        wm_btn_row.setSpacing(6)
        add_wm_btn = QPushButton("+ 添加水印")
        add_wm_btn.setStyleSheet(self._btn_style())
        add_wm_btn.clicked.connect(self._on_add_watermark)
        del_wm_btn = QPushButton("删除")
        del_wm_btn.setStyleSheet(self._btn_style())
        del_wm_btn.clicked.connect(self._on_delete_watermark)
        wm_btn_row.addWidget(add_wm_btn)
        wm_btn_row.addWidget(del_wm_btn)
        wm_btn_row.addStretch()
        wm_outer.addLayout(wm_btn_row)

        # 编辑表单（跟随选中项）
        wm_edit = QFormLayout()
        wm_edit.setSpacing(4)

        self._wm_text = QLineEdit("水印")
        self._wm_text.setStyleSheet(self._line_style())
        self._wm_text.textChanged.connect(self._on_wm_field_changed)
        wm_edit.addRow("文字:", self._wm_text)

        self._wm_font = QFontComboBox()
        self._wm_font.setStyleSheet(self._combo_style())
        self._wm_font.currentFontChanged.connect(self._on_wm_field_changed)
        wm_edit.addRow("字体:", self._wm_font)

        self._wm_font_size_w, self._wm_font_size = self._make_spin(8, 360, 80, 70)
        self._wm_font_size.valueChanged.connect(self._on_wm_field_changed)
        wm_edit.addRow("字号:", self._wm_font_size_w)

        # 颜色自选按钮
        self._wm_color_btn = QPushButton("选择颜色")
        self._wm_color_btn.setFixedSize(90, 24)
        self._wm_color_btn.setStyleSheet(self._btn_style())
        self._wm_color_btn.clicked.connect(self._on_pick_color)
        self._wm_color_value = "#00FF00"
        self._wm_color_label = QLabel("■ #00FF00")
        self._wm_color_label.setStyleSheet("color: #212733;")
        color_row = QHBoxLayout()
        color_row.addWidget(self._wm_color_btn)
        color_row.addWidget(self._wm_color_label)
        color_row.addStretch()
        color_widget = QWidget()
        color_widget.setLayout(color_row)
        wm_edit.addRow("颜色:", color_widget)

        self._wm_opacity_w, self._wm_opacity_spin = self._make_spin(5, 100, 55, 70)
        self._wm_opacity_spin.valueChanged.connect(self._on_wm_field_changed)
        wm_edit.addRow("透明度:", self._wm_opacity_w)

        self._wm_tiled = QCheckBox("平铺水印")
        self._wm_tiled.setStyleSheet("color: #212733;")
        self._wm_tiled.toggled.connect(self._on_wm_field_changed)
        wm_edit.addRow("", self._wm_tiled)

        self._wm_position = QComboBox()
        for label, value in (
            ("左上", "top_left"), ("上中", "top_center"), ("右上", "top_right"),
            ("左中", "middle_left"), ("居中", "center"), ("右中", "middle_right"),
            ("左下", "bottom_left"), ("下中", "bottom_center"), ("右下", "bottom_right"),
        ):
            self._wm_position.addItem(label, value)
        self._wm_position.setCurrentIndex(8)
        self._wm_position.setStyleSheet(self._combo_style())
        self._wm_position.currentIndexChanged.connect(self._on_wm_field_changed)
        wm_edit.addRow("位置:", self._wm_position)

        self._wm_flip_h = QCheckBox("水平翻转")
        self._wm_flip_h.setStyleSheet("color: #212733;")
        self._wm_flip_h.toggled.connect(self._on_wm_field_changed)
        self._wm_flip_v = QCheckBox("垂直翻转")
        self._wm_flip_v.setStyleSheet("color: #212733;")
        self._wm_flip_v.toggled.connect(self._on_wm_field_changed)
        flip_row = QHBoxLayout()
        flip_row.addWidget(self._wm_flip_h)
        flip_row.addWidget(self._wm_flip_v)
        flip_row.addStretch()
        flip_widget = QWidget()
        flip_widget.setLayout(flip_row)
        wm_edit.addRow("翻转:", flip_widget)

        wm_outer.addLayout(wm_edit)

        self._wm_image_btn = QPushButton("选择本地图片水印…")
        self._wm_image_btn.setFixedSize(140, 24)
        self._wm_image_btn.setStyleSheet(self._btn_style())
        self._wm_image_btn.clicked.connect(self._on_select_watermark_image)
        self._wm_image_path: Path | None = None
        wm_outer.addWidget(self._wm_image_btn)
        form.addRow(wm_group)

        # 水印列表数据
        self._watermarks: list[WatermarkItem] = []
        self._wm_updating = False

        scroll.setWidget(scroll_widget)
        layout.addWidget(scroll, stretch=1)

        # 应用按钮
        apply_btn = QPushButton("⚡ 应用到选中图片")
        apply_btn.setObjectName("primaryButton")
        apply_btn.setStyleSheet(
            "QPushButton#primaryButton {"
            "  background: qlineargradient(x1:0, y1:0, x2:0, y2:1,"
            "  stop:0 #4a8af4, stop:1 #3973db);"
            "  color: #ffffff; border: 1px solid #5a9af4;"
            "  border-radius: 8px; padding: 10px 20px;"
            " font-weight: 600;"
            "}"
            "QPushButton#primaryButton:hover {"
            "  background: qlineargradient(x1:0, y1:0, x2:0, y2:1,"
            "  stop:0 #5a9af4, stop:1 #4a8af4);"
            "  border-color: #6aaaf4;"
            "}"
        )
        apply_btn.clicked.connect(self._on_apply)
        layout.addWidget(apply_btn)

        self._params = OperationParams()

    # —— 样式辅助 ——

    @staticmethod
    def _combo_style() -> str:
        return (
            "QComboBox { background: #ffffff; color: #212733; border: 1px solid #d5d9e0;"
            "  padding: 4px 8px; border-radius: 4px; }"
            "QComboBox:hover { border-color: #3973db; }"
        )

    @staticmethod
    def _line_style() -> str:
        return (
            "QLineEdit { background: #ffffff; color: #212733; border: 1px solid #d5d9e0;"
            "  padding: 4px 8px; border-radius: 4px; }"
        )

    @staticmethod
    def _btn_style() -> str:
        return (
            "QPushButton {"
            "  background: qlineargradient(x1:0, y1:0, x2:0, y2:1,"
            "    stop:0 #4a8af4, stop:1 #3973db);"
            "  color: #ffffff; border: 1px solid #5a9af4;"
            " border-radius: 4px; padding: 3px 8px;"
            "}"
            "QPushButton:hover {"
            "  background: qlineargradient(x1:0, y1:0, x2:0, y2:1,"
            "    stop:0 #5a9af4, stop:1 #4a8af4);"
            "  border-color: #7ab4ff;"
            "}"
            "QPushButton:pressed {"
            "  background: qlineargradient(x1:0, y1:0, x2:0, y2:1,"
            "    stop:0 #2a6ad4, stop:1 #1a5ac4);"
            "  border-color: #4a8af4;"
            "}"
            "QPushButton:disabled {"
            "  background: #46536f; color: #aeb9cc; border-color: #687895;"
            "}"
        )

    @staticmethod
    def _spin_no_buttons_style() -> str:
        return (
            "QSpinBox { background: #ffffff; color: #212733; border: 1px solid #d5d9e0;"
            "  padding: 4px 6px; border-radius: 4px; }"
        )

    @staticmethod
    def _make_spin(min_v: int, max_v: int, default: int, width: int = 80) -> tuple:
        """创建无按钮的 SpinBox + 外部 ± 按钮（图层状态样式），返回 (QWidget, QSpinBox)。"""
        container = QWidget()
        # 防止被 QFormLayout 拉伸导致按钮与输入框分离
        from PySide6.QtWidgets import QSizePolicy
        container.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        hbox = QHBoxLayout(container)
        hbox.setContentsMargins(0, 0, 0, 0)
        hbox.setSpacing(2)

        spin = QSpinBox()
        spin.setRange(min_v, max_v)
        spin.setValue(default)
        spin.setFixedWidth(width)
        spin.setButtonSymbols(QAbstractSpinBox.NoButtons)
        spin.setStyleSheet(OperationPanel._spin_no_buttons_style())
        hbox.addWidget(spin)

        btn_smaller = QToolButton()
        btn_smaller.setText("−")
        btn_smaller.setToolTip("减小")
        btn_smaller.setFixedSize(22, 16)
        btn_smaller.setStyleSheet(
            "QToolButton { background: #2a2a44; color: #212733;"
            "  border: 1px solid #d5d9e0; border-radius: 4px; }"
            "QToolButton:hover { background: #34345a; }"
            "QToolButton:pressed { background: #3a3a5e; }"
        )
        btn_smaller.clicked.connect(spin.stepDown)
        hbox.addWidget(btn_smaller)

        btn_larger = QToolButton()
        btn_larger.setText("+")
        btn_larger.setToolTip("增大")
        btn_larger.setFixedSize(22, 16)
        btn_larger.setStyleSheet(
            "QToolButton { background: #2a2a44; color: #212733;"
            "  border: 1px solid #d5d9e0; border-radius: 4px; }"
            "QToolButton:hover { background: #34345a; }"
            "QToolButton:pressed { background: #3a3a5e; }"
        )
        btn_larger.clicked.connect(spin.stepUp)
        hbox.addWidget(btn_larger)

        return container, spin

    # —— 交互 ——

    def _set_crop_mode_active(self, active: bool) -> None:
        """更新裁剪模式按钮状态。"""
        self._crop_mode_btn.setVisible(not active)
        self._crop_cancel_btn.setVisible(active)

    def _on_crop_mode_clicked(self) -> None:
        self._set_crop_mode_active(True)
        self.crop_mode_changed.emit(True)

    def _on_crop_cancel_clicked(self) -> None:
        self._set_crop_mode_active(False)
        self.crop_mode_changed.emit(False)

    def _on_crop_lock_toggled(self, locked: bool) -> None:
        """锁定切换：锁定时 W/H 归 0（不裁剪），解锁恢复默认。"""
        if locked:
            self._crop_x.setValue(0)
            self._crop_y.setValue(0)
            self._crop_w.setValue(0)
            self._crop_h.setValue(0)
            self._crop_lock_btn.setText("已锁定")
        else:
            self._crop_w.setValue(100)
            self._crop_h.setValue(100)
            self._crop_lock_btn.setText("锁定")

    def _clear_crop(self) -> None:
        """恢复裁剪默认值：X/Y=0，W/H=100。"""
        self._crop_lock_btn.setChecked(False)
        self._crop_x.setValue(0)
        self._crop_y.setValue(0)
        self._crop_w.setValue(100)
        self._crop_h.setValue(100)

    def enable_crop(self, x: int, y: int, w: int, h: int) -> None:
        """同步选区坐标到输入框（拖拽/双击都会调用）。"""
        self._crop_x.setValue(x)
        self._crop_y.setValue(y)
        self._crop_w.setValue(w)
        self._crop_h.setValue(h)

    def _on_select_watermark_image(self) -> None:
        from PySide6.QtWidgets import QFileDialog

        path, _ = QFileDialog.getOpenFileName(
            self, "选择水印图片", "",
            "图片文件 (*.png *.jpg *.jpeg *.webp)",
        )
        if path:
            self._wm_image_path = Path(path)
            self._wm_image_btn.setText(f"已选: {Path(path).name[:15]}...")

    def _build_params(self) -> OperationParams:
        # 裁剪（有坐标值时生效）
        crop_box: tuple[int, int, int, int] | None = None
        if self._crop_w.value() > 0 and self._crop_h.value() > 0:
            crop_box = (
                self._crop_x.value(), self._crop_y.value(),
                self._crop_w.value(), self._crop_h.value(),
            )

        # 旋转
        rotate_deg = [0, 90, 180, 270][self._rotate_combo.currentIndex()]

        # 翻转
        flip_idx = self._flip_combo.currentIndex()
        flip = [None, "horizontal", "vertical"][flip_idx]

        # 格式
        fmt_idx = self._format_combo.currentIndex()
        output_format = [None, "png", "jpg", "webp", "gif", "tiff"][fmt_idx]

        # 尺寸
        max_w = self._max_w.value()
        max_h = self._max_h.value()
        max_size: tuple[int, int] | None = None
        if max_w > 0 and max_h > 0:
            max_size = (max_w, max_h)

        return OperationParams(
            crop_box=crop_box,
            rotate_deg=rotate_deg,
            flip=flip,
            output_format=output_format,
            quality=self._quality_spin.value(),
            max_size=max_size,
            watermarks=list(self._watermarks),
            watermark_image_path=self._wm_image_path,
        )

    # —— 水印管理 ——

    def watermarks(self) -> list[WatermarkItem]:
        return list(self._watermarks)

    def set_watermarks(self, items: list[WatermarkItem]) -> None:
        """外部（预览交互）更新水印列表。"""
        self._watermarks = list(items)
        self._refresh_wm_list()
        self._load_wm_to_form()

    def _refresh_wm_list(self) -> None:
        self._wm_updating = True
        self._wm_list.clear()
        for wm in self._watermarks:
            self._wm_list.addItem(f"{wm.text}  ({wm.position})")
        self._wm_updating = False
        if self._watermarks:
            self._wm_list.setCurrentRow(0)

    def _current_wm(self) -> WatermarkItem | None:
        row = self._wm_list.currentRow()
        if 0 <= row < len(self._watermarks):
            return self._watermarks[row]
        return None

    def _on_add_watermark(self) -> None:
        wm = WatermarkItem(id=str(uuid.uuid4()))
        self._watermarks.append(wm)
        self._refresh_wm_list()
        self._wm_list.setCurrentRow(len(self._watermarks) - 1)
        self._load_wm_to_form()
        self.watermarks_changed.emit()

    def _on_delete_watermark(self) -> None:
        row = self._wm_list.currentRow()
        if 0 <= row < len(self._watermarks):
            self._watermarks.pop(row)
            self._refresh_wm_list()
            self._load_wm_to_form()
            self.watermarks_changed.emit()

    def _on_wm_selected(self, row: int) -> None:
        if not self._wm_updating:
            self._load_wm_to_form()

    def _load_wm_to_form(self) -> None:
        wm = self._current_wm()
        if wm is None:
            return
        self._wm_updating = True
        self._wm_text.setText(wm.text)
        from PySide6.QtGui import QFont
        font = QFont(wm.font_family)
        self._wm_font.setCurrentFont(font)
        self._wm_font_size.setValue(wm.font_size)
        self._wm_color_value = wm.color
        self._update_color_label()
        self._wm_opacity_spin.setValue(int(wm.opacity * 100))
        self._wm_tiled.setChecked(wm.tiled)
        pos_index = self._wm_position.findData(wm.position)
        if pos_index >= 0:
            self._wm_position.setCurrentIndex(pos_index)
        self._wm_flip_h.setChecked(wm.flip_h)
        self._wm_flip_v.setChecked(wm.flip_v)
        self._wm_updating = False

    def _on_wm_field_changed(self, *args) -> None:
        if self._wm_updating:
            return
        wm = self._current_wm()
        if wm is None:
            return
        wm.text = self._wm_text.text().strip() or "水印"
        wm.font_family = self._wm_font.currentFont().family()
        wm.font_size = self._wm_font_size.value()
        wm.color = self._wm_color_value
        wm.opacity = self._wm_opacity_spin.value() / 100.0
        wm.tiled = self._wm_tiled.isChecked()
        wm.position = self._wm_position.currentData() or "bottom_right"
        wm.flip_h = self._wm_flip_h.isChecked()
        wm.flip_v = self._wm_flip_v.isChecked()
        # 更新列表标题
        row = self._wm_list.currentRow()
        if 0 <= row < self._wm_list.count():
            self._wm_list.item(row).setText(f"{wm.text}  ({wm.position})")
        self.watermarks_changed.emit()

    def _on_pick_color(self) -> None:
        from PySide6.QtGui import QColor
        current = QColor(self._wm_color_value)
        color = QColorDialog.getColor(current, self, "选择水印颜色")
        if color.isValid():
            self._wm_color_value = color.name().upper()
            self._update_color_label()
            self._on_wm_field_changed()

    def _update_color_label(self) -> None:
        from PySide6.QtGui import QColor
        color = QColor(self._wm_color_value)
        rgb = color.getRgb()[:3]
        luminance = 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]
        text_color = "#000000" if luminance > 150 else "#ffffff"
        self._wm_color_label.setText(f"■ {self._wm_color_value}")
        self._wm_color_label.setStyleSheet(
            f"color: {text_color};"
            f"background: {self._wm_color_value}; padding: 2px 6px;"
            f"border-radius: 3px;"
        )

    def _on_apply(self) -> None:
        self._params = self._build_params()
        self.apply_requested.emit(self._params)

    @property
    def params(self) -> OperationParams:
        return self._params
