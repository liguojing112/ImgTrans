"""右侧属性编辑面板。

字段变更通过 300ms QTimer 防抖后发射 layer_property_changed 信号。
set_layer 时使用 blockSignals 避免循环同步。
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QColorDialog,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from src.domain.layout import TextLayer, TextBox

_DEBOUNCE_MS = 300


class PropertyPanel(QFrame):
    """文字图层属性编辑面板。无选中图层时显示占位提示。"""

    layer_property_changed = Signal(str, str, object)  # (region_id, field, value)
    apply_requested = Signal()
    add_layer_requested = Signal()
    delete_layer_requested = Signal()

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

        from PySide6.QtCore import QTimer
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.timeout.connect(self._flush_pending)

        # 滚动区域
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
        self.text_edit.setMaximumHeight(80)
        self.text_edit.textChanged.connect(lambda: self._on_field_changed("text", self.text_edit.toPlainText()))

        # X / Y
        self.x_spin = QDoubleSpinBox()
        self.x_spin.setRange(-99999, 99999)
        self.x_spin.setDecimals(1)
        self.x_spin.setSuffix(" px")
        self.x_spin.valueChanged.connect(lambda v: self._on_field_changed("center_x", v))

        self.y_spin = QDoubleSpinBox()
        self.y_spin.setRange(-99999, 99999)
        self.y_spin.setDecimals(1)
        self.y_spin.setSuffix(" px")
        self.y_spin.valueChanged.connect(lambda v: self._on_field_changed("center_y", v))

        # 宽 / 高
        self.width_spin = QDoubleSpinBox()
        self.width_spin.setRange(1, 99999)
        self.width_spin.setDecimals(1)
        self.width_spin.setSuffix(" px")
        self.width_spin.valueChanged.connect(lambda v: self._on_field_changed("width", v))

        self.height_spin = QDoubleSpinBox()
        self.height_spin.setRange(1, 99999)
        self.height_spin.setDecimals(1)
        self.height_spin.setSuffix(" px")
        self.height_spin.valueChanged.connect(lambda v: self._on_field_changed("height", v))

        # 旋转
        self.rotation_spin = QDoubleSpinBox()
        self.rotation_spin.setRange(-180, 180)
        self.rotation_spin.setDecimals(1)
        self.rotation_spin.setSuffix("°")
        self.rotation_spin.valueChanged.connect(lambda v: self._on_field_changed("rotation_degrees", v))

        # 字号
        self.font_size_spin = QDoubleSpinBox()
        self.font_size_spin.setRange(1, 500)
        self.font_size_spin.setDecimals(1)
        self.font_size_spin.setSuffix(" px")
        self.font_size_spin.valueChanged.connect(lambda v: self._on_field_changed("font_size", v))

        # 颜色
        self.color_button = QPushButton()
        self.color_button.setObjectName("colorButton")
        self.color_button.clicked.connect(self._choose_color)

        # 字重
        self.font_weight_combo = QComboBox()
        for label, value in (("正常 400", 400), ("半粗 600", 600), ("粗体 700", 700)):
            self.font_weight_combo.addItem(label, value)
        self.font_weight_combo.currentIndexChanged.connect(
            lambda: self._on_field_changed(
                "font_weight", self.font_weight_combo.currentData()
            )
        )

        form.addRow("文字内容", self.text_edit)
        form.addRow(_field_label("X"), self.x_spin)
        form.addRow(_field_label("Y"), self.y_spin)
        form.addRow(_field_label("宽度"), self.width_spin)
        form.addRow(_field_label("高度"), self.height_spin)
        form.addRow(_field_label("旋转"), self.rotation_spin)
        form.addRow(_field_label("字号"), self.font_size_spin)
        form.addRow(_field_label("颜色"), self.color_button)
        form.addRow(_field_label("字重"), self.font_weight_combo)

        layout.addWidget(title)
        layout.addWidget(self._no_selection_label)
        layout.addLayout(form)
        layout.addStretch()

        scroll.setWidget(content)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        self._set_fields_enabled(False)

    # —— 公开接口 ——

    @property
    def selected_region_id(self) -> str | None:
        return self._region_id

    def set_layer(self, layer: TextLayer | None) -> None:
        """加载图层数据到面板。blockSignals 防循环同步。"""
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
            self.font_size_spin.setValue(style.font_size)
            self._fill_rgb = style.fill_rgb
            self._update_color_button()
            idx = self.font_weight_combo.findData(style.font_weight)
            if idx >= 0:
                self.font_weight_combo.setCurrentIndex(idx)
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
        self.layer_property_changed.emit(
            self._region_id, self._pending_field, self._pending_value
        )

    def _choose_color(self) -> None:
        current = QColor(*self._fill_rgb)
        selected = QColorDialog.getColor(current, self, "选择文字颜色")
        if not selected.isValid():
            return
        self._fill_rgb = (selected.red(), selected.green(), selected.blue())
        self._update_color_button()
        self._on_field_changed("fill_rgb", self._fill_rgb)

    def _update_color_button(self) -> None:
        r, g, b = self._fill_rgb
        fg = "#ffffff" if (r + g + b) < 360 else "#172033"
        self.color_button.setStyleSheet(
            f"background: rgb({r},{g},{b}); color: {fg};"
            "border: 1px solid #3d3d5c; border-radius: 6px; padding: 5px;"
        )

    def _set_fields_enabled(self, enabled: bool) -> None:
        for widget in (
            self.text_edit,
            self.x_spin,
            self.y_spin,
            self.width_spin,
            self.height_spin,
            self.rotation_spin,
            self.font_size_spin,
            self.color_button,
            self.font_weight_combo,
        ):
            widget.setEnabled(enabled)

    def _clear_fields(self) -> None:
        self._suppress_signals = True
        try:
            self.text_edit.clear()
            self.x_spin.setValue(0)
            self.y_spin.setValue(0)
            self.width_spin.setValue(0)
            self.height_spin.setValue(0)
            self.rotation_spin.setValue(0)
            self.font_size_spin.setValue(0)
            self.font_weight_combo.setCurrentIndex(0)
        finally:
            self._suppress_signals = False


def _field_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("propertyFieldLabel")
    return label
