"""右侧属性编辑面板。

字段变更通过 300ms QTimer 防抖后发射 layer_property_changed 信号。
set_layer 时使用 blockSignals 避免循环同步。
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDoubleSpinBox,
    QFontComboBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from src.domain.layout import TextAlignment, TextLayer, TextBox, VerticalAlignment

_DEBOUNCE_MS = 300


class PropertyPanel(QFrame):
    """文字图层属性编辑面板。无选中图层时显示占位提示。"""

    layer_property_changed = Signal(str, str, object)  # (region_id, field, value)
    delete_layer_requested = Signal(str)  # region_id
    duplicate_layer_requested = Signal(str)  # region_id

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("propertyPanel")
        self.setMinimumWidth(240)
        self.setMaximumWidth(300)

        self._region_id: str | None = None
        self._suppress_signals = False
        self._pending_field: str | None = None
        self._pending_value: object = None
        self._fill_rgb = (24, 32, 51)
        self._stroke_rgb = (255, 255, 255)
        self._shadow_rgb = (0, 0, 0)

        from PySide6.QtCore import QTimer
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.timeout.connect(self._flush_pending)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        title = QLabel("属性")
        title.setObjectName("propertyTitle")
        self._no_selection_label = QLabel("点击画布中的文字框可查看属性")
        self._no_selection_label.setObjectName("propertyNoSelection")
        self._no_selection_label.setWordWrap(True)

        form = QFormLayout()
        form.setSpacing(8)

        # 文字内容
        self.text_edit = QPlainTextEdit()
        self.text_edit.setPlaceholderText("文字内容")
        self.text_edit.setMaximumHeight(60)
        self.text_edit.textChanged.connect(lambda: self._on_field_changed("text", self.text_edit.toPlainText()))

        # X / Y
        self.x_spin = _dspin(-99999, 99999, " px")
        self.x_spin.valueChanged.connect(lambda v: self._on_field_changed("center_x", v))
        self.y_spin = _dspin(-99999, 99999, " px")
        self.y_spin.valueChanged.connect(lambda v: self._on_field_changed("center_y", v))

        # 宽 / 高
        self.width_spin = _dspin(1, 99999, " px")
        self.width_spin.valueChanged.connect(lambda v: self._on_field_changed("width", v))
        self.height_spin = _dspin(1, 99999, " px")
        self.height_spin.valueChanged.connect(lambda v: self._on_field_changed("height", v))

        # 旋转
        self.rotation_spin = _dspin(-180, 180, " deg")
        self.rotation_spin.valueChanged.connect(lambda v: self._on_field_changed("rotation_degrees", v))

        # 字体族
        self.font_family = QFontComboBox()
        self.font_family.currentFontChanged.connect(
            lambda f: self._on_field_changed("font_family", f.family())
        )

        # 字号
        self.font_size_spin = _dspin(1, 500, " px")
        self.font_size_spin.valueChanged.connect(lambda v: self._on_field_changed("font_size", v))

        # 字重
        self.font_weight_combo = QComboBox()
        for label, value in (("正常 400", 400), ("半粗 600", 600), ("粗体 700", 700)):
            self.font_weight_combo.addItem(label, value)
        self.font_weight_combo.currentIndexChanged.connect(
            lambda: self._on_field_changed("font_weight", self.font_weight_combo.currentData())
        )

        # 自动换行
        self.wrap_check = QCheckBox("自动换行")
        self.wrap_check.toggled.connect(lambda v: self._on_field_changed("wrap", v))

        # 水平对齐
        self.alignment_combo = QComboBox()
        for label, val in (("左对齐", TextAlignment.LEFT), ("居中", TextAlignment.CENTER), ("右对齐", TextAlignment.RIGHT)):
            self.alignment_combo.addItem(label, val)
        self.alignment_combo.currentIndexChanged.connect(
            lambda: self._on_field_changed("alignment", self.alignment_combo.currentData())
        )

        # 垂直对齐
        self.vertical_alignment_combo = QComboBox()
        for label, val in (("顶部", VerticalAlignment.TOP), ("居中", VerticalAlignment.CENTER), ("底部", VerticalAlignment.BOTTOM)):
            self.vertical_alignment_combo.addItem(label, val)
        self.vertical_alignment_combo.currentIndexChanged.connect(
            lambda: self._on_field_changed("vertical_alignment", self.vertical_alignment_combo.currentData())
        )

        # 颜色
        self.color_button = QPushButton()
        self.color_button.setObjectName("colorButton")
        self.color_button.clicked.connect(lambda: self._choose_color("fill"))

        # 描边宽度
        self.stroke_width_spin = _dspin(0, 12, " px")
        self.stroke_width_spin.valueChanged.connect(lambda v: self._on_field_changed("stroke_width", v))

        # 描边颜色
        self.stroke_color_button = QPushButton()
        self.stroke_color_button.setObjectName("colorButton")
        self.stroke_color_button.clicked.connect(lambda: self._choose_color("stroke"))

        # 阴影
        self.shadow_check = QCheckBox("启用阴影")
        self.shadow_check.toggled.connect(lambda v: self._on_field_changed("shadow_enabled", v))

        self.shadow_x_spin = _dspin(-50, 50, " px")
        self.shadow_x_spin.valueChanged.connect(lambda v: self._on_field_changed("shadow_offset_x", v))
        self.shadow_y_spin = _dspin(-50, 50, " px")
        self.shadow_y_spin.valueChanged.connect(lambda v: self._on_field_changed("shadow_offset_y", v))

        self.shadow_opacity_spin = QSpinBox()
        self.shadow_opacity_spin.setRange(0, 100)
        self.shadow_opacity_spin.setSuffix("%")
        self.shadow_opacity_spin.valueChanged.connect(lambda v: self._on_field_changed("shadow_opacity", v))

        self.shadow_color_button = QPushButton()
        self.shadow_color_button.setObjectName("colorButton")
        self.shadow_color_button.clicked.connect(lambda: self._choose_color("shadow"))

        # 表单布局
        form.addRow("文字内容", self.text_edit)
        form.addRow(_lbl("X"), self.x_spin)
        form.addRow(_lbl("Y"), self.y_spin)
        form.addRow(_lbl("宽度"), self.width_spin)
        form.addRow(_lbl("高度"), self.height_spin)
        form.addRow(_lbl("旋转"), self.rotation_spin)
        form.addRow(_lbl("字体"), self.font_family)
        form.addRow(_lbl("字号"), self.font_size_spin)
        form.addRow(_lbl("字重"), self.font_weight_combo)
        form.addRow("", self.wrap_check)
        form.addRow(_lbl("水平对齐"), self.alignment_combo)
        form.addRow(_lbl("垂直对齐"), self.vertical_alignment_combo)
        form.addRow(_lbl("填充色"), self.color_button)
        form.addRow(_lbl("描边宽度"), self.stroke_width_spin)
        form.addRow(_lbl("描边色"), self.stroke_color_button)
        form.addRow("", self.shadow_check)
        form.addRow(_lbl("阴影X/Y"), self.shadow_x_spin)
        form.addRow("", self.shadow_y_spin)
        form.addRow(_lbl("阴影透明度"), self.shadow_opacity_spin)
        form.addRow(_lbl("阴影色"), self.shadow_color_button)

        layout.addWidget(title)
        layout.addWidget(self._no_selection_label)
        layout.addLayout(form)

        # 图层操作按钮
        layer_buttons = QHBoxLayout()
        self.delete_btn = QPushButton("删除图层")
        self.delete_btn.setObjectName("deleteTextLayerButton")
        self.delete_btn.clicked.connect(self._on_delete)
        self.duplicate_btn = QPushButton("复制图层")
        self.duplicate_btn.setObjectName("applyPropertyButton")
        self.duplicate_btn.clicked.connect(self._on_duplicate)
        layer_buttons.addWidget(self.delete_btn)
        layer_buttons.addWidget(self.duplicate_btn)
        layout.addLayout(layer_buttons)
        layout.addStretch()

        scroll.setWidget(content)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        self._set_fields_enabled(False)

    # —— 图层操作 ——

    def _on_delete(self) -> None:
        if self._region_id is not None:
            self.delete_layer_requested.emit(self._region_id)

    def _on_duplicate(self) -> None:
        if self._region_id is not None:
            self.duplicate_layer_requested.emit(self._region_id)

    # —— 公开接口 ——

    @property
    def selected_region_id(self) -> str | None:
        return self._region_id

    def set_layer(self, layer: TextLayer | None) -> None:
        prev_id = self._region_id
        self._region_id = layer.region_id if layer is not None else None

        if layer is None:
            self._set_fields_enabled(False)
            self._no_selection_label.setVisible(True)
            if prev_id is not None:
                self._clear_fields()
            return

        self._no_selection_label.setVisible(False)
        self._set_fields_enabled(True)
        self._suppress_signals = True
        try:
            if prev_id != layer.region_id:
                self.text_edit.setPlainText(layer.text)

            box = layer.box
            self.x_spin.setValue(box.center_x)
            self.y_spin.setValue(box.center_y)
            self.width_spin.setValue(box.width)
            self.height_spin.setValue(box.height)
            self.rotation_spin.setValue(box.rotation_degrees)

            style = layer.style
            self.font_family.setCurrentFont(QFont(style.font_family))
            self.font_size_spin.setValue(style.font_size)
            idx_w = self.font_weight_combo.findData(style.font_weight)
            if idx_w >= 0:
                self.font_weight_combo.setCurrentIndex(idx_w)
            self.wrap_check.setChecked(style.wrap)
            idx_a = self.alignment_combo.findData(style.alignment)
            if idx_a >= 0:
                self.alignment_combo.setCurrentIndex(idx_a)
            idx_v = self.vertical_alignment_combo.findData(style.vertical_alignment)
            if idx_v >= 0:
                self.vertical_alignment_combo.setCurrentIndex(idx_v)

            self._fill_rgb = style.fill_rgb
            self._stroke_rgb = style.stroke_rgb
            self._shadow_rgb = style.shadow_rgb
            self.stroke_width_spin.setValue(style.stroke_width)
            self.shadow_check.setChecked(style.shadow_opacity > 0)
            self.shadow_x_spin.setValue(style.shadow_offset_x)
            self.shadow_y_spin.setValue(style.shadow_offset_y)
            self.shadow_opacity_spin.setValue(round(style.shadow_opacity * 100))
            self._update_color_buttons()
        finally:
            self._suppress_signals = False

    # —— 内部方法 ——

    def _on_field_changed(self, field: str, value: object) -> None:
        if self._suppress_signals or self._region_id is None:
            return
        self._pending_field = field
        self._pending_value = value
        self._debounce.start(_DEBOUNCE_MS)

    def _flush_pending(self) -> None:
        if self._pending_field is None or self._region_id is None:
            return
        self.layer_property_changed.emit(self._region_id, self._pending_field, self._pending_value)

    def _choose_color(self, kind: str) -> None:
        current_rgb = {"fill": self._fill_rgb, "stroke": self._stroke_rgb, "shadow": self._shadow_rgb}[kind]
        selected = QColorDialog.getColor(QColor(*current_rgb), self, "选择颜色")
        if not selected.isValid():
            return
        rgb = (selected.red(), selected.green(), selected.blue())
        if kind == "fill":
            self._fill_rgb = rgb
            self._on_field_changed("fill_rgb", rgb)
        elif kind == "stroke":
            self._stroke_rgb = rgb
            self._on_field_changed("stroke_rgb", rgb)
        else:
            self._shadow_rgb = rgb
            self._on_field_changed("shadow_rgb", rgb)
        self._update_color_buttons()

    def _update_color_buttons(self) -> None:
        for btn, rgb in (
            (self.color_button, self._fill_rgb),
            (self.stroke_color_button, self._stroke_rgb),
            (self.shadow_color_button, self._shadow_rgb),
        ):
            fg = "#ffffff" if sum(rgb) < 360 else "#172033"
            btn.setStyleSheet(
                f"background: rgb{rgb}; color: {fg}; border: 1px solid #3d3d5c; border-radius: 6px; padding: 5px;"
            )

    def _set_fields_enabled(self, enabled: bool) -> None:
        for w in (
            self.text_edit, self.x_spin, self.y_spin, self.width_spin, self.height_spin,
            self.rotation_spin, self.font_family, self.font_size_spin, self.font_weight_combo,
            self.wrap_check, self.alignment_combo, self.vertical_alignment_combo,
            self.color_button, self.stroke_width_spin, self.stroke_color_button,
            self.shadow_check, self.shadow_x_spin, self.shadow_y_spin,
            self.shadow_opacity_spin, self.shadow_color_button,
        ):
            w.setEnabled(enabled)

    def _clear_fields(self) -> None:
        self._suppress_signals = True
        try:
            self.text_edit.clear()
            for s in (self.x_spin, self.y_spin, self.width_spin, self.height_spin):
                s.setValue(0)
            self.rotation_spin.setValue(0)
            self.font_size_spin.setValue(0)
            self.font_weight_combo.setCurrentIndex(0)
            self.wrap_check.setChecked(False)
            self.alignment_combo.setCurrentIndex(0)
            self.vertical_alignment_combo.setCurrentIndex(0)
            self.stroke_width_spin.setValue(0)
            self.shadow_check.setChecked(False)
            self.shadow_x_spin.setValue(0)
            self.shadow_y_spin.setValue(0)
            self.shadow_opacity_spin.setValue(0)
        finally:
            self._suppress_signals = False


def _lbl(text: str) -> QLabel:
    l = QLabel(text)
    l.setObjectName("propertyFieldLabel")
    return l


def _dspin(lo: float, hi: float, suffix: str) -> QDoubleSpinBox:
    s = QDoubleSpinBox()
    s.setRange(lo, hi)
    s.setDecimals(1)
    s.setSuffix(suffix)
    return s
