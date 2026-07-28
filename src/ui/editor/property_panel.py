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
    QLineEdit,
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
    """文字图层属性编辑面板。"""

    layer_property_changed = Signal(str, str, object)
    delete_layer_requested = Signal(str)
    duplicate_layer_requested = Signal(str)
    restore_layout_requested = Signal(str)
    retranslate_requested = Signal(str)
    keep_original_requested = Signal(str)
    confirm_review_requested = Signal(str)

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
        self._image_w = 99999
        self._image_h = 99999

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
        layout.setSpacing(8)

        title = QLabel("属性")
        title.setObjectName("propertyTitle")
        self._no_selection_label = QLabel("请选择一个文字图层")
        self._no_selection_label.setObjectName("propertyNoSelection")
        self._no_selection_label.setWordWrap(True)

        form = QFormLayout()
        form.setSpacing(6)

        # ===== 基础信息（只读）=====
        info_title = QLabel("基础信息")
        info_title.setObjectName("propertyTitle")

        self.region_id_label = QLabel("")
        self.region_id_label.setObjectName("propertyFieldLabel")
        self.region_id_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        self.source_text_label = QLabel("")
        self.source_text_label.setObjectName("propertyFieldLabel")
        self.source_text_label.setWordWrap(True)
        self.source_text_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        self.status_label = QLabel("")
        self.status_label.setObjectName("propertyFieldLabel")

        self.confidence_label = QLabel("")
        self.confidence_label.setObjectName("propertyFieldLabel")

        self.review_label = QLabel("")
        self.review_label.setObjectName("propertyFieldLabel")

        self.overflow_label = QLabel("")
        self.overflow_label.setObjectName("propertyFieldLabel")

        # ===== 文字内容 =====
        self.text_edit = QPlainTextEdit()
        self.text_edit.setPlaceholderText("文字内容")
        self.text_edit.setMaximumHeight(60)
        self.text_edit.textChanged.connect(lambda: self._on_field_changed("text", self.text_edit.toPlainText()))

        # ===== 几何 =====
        self.x_spin = _dspin(0, 99999, " px")
        self.x_spin.valueChanged.connect(lambda v: self._on_field_changed("center_x", v))
        self.y_spin = _dspin(0, 99999, " px")
        self.y_spin.valueChanged.connect(lambda v: self._on_field_changed("center_y", v))
        self.width_spin = _dspin(1, 99999, " px")
        self.width_spin.valueChanged.connect(lambda v: self._on_field_changed("width", v))
        self.height_spin = _dspin(1, 99999, " px")
        self.height_spin.valueChanged.connect(lambda v: self._on_field_changed("height", v))
        self.rotation_spin = _dspin(-180, 180, " deg")
        self.rotation_spin.valueChanged.connect(lambda v: self._on_field_changed("rotation_degrees", v))

        # ===== 文字样式 =====
        self.font_family = QFontComboBox()
        self.font_family.currentFontChanged.connect(lambda f: self._on_field_changed("font_family", f.family()))
        self.font_size_spin = _dspin(1, 500, " px")
        self.font_size_spin.valueChanged.connect(lambda v: self._on_field_changed("font_size", v))
        self.font_weight_combo = QComboBox()
        for label, value in (("正常 400", 400), ("半粗 600", 600), ("粗体 700", 700)):
            self.font_weight_combo.addItem(label, value)
        self.font_weight_combo.currentIndexChanged.connect(
            lambda: self._on_field_changed("font_weight", self.font_weight_combo.currentData()))
        self.font_stretch_spin = QSpinBox()
        self.font_stretch_spin.setRange(50, 200)
        self.font_stretch_spin.setSuffix("%")
        self.font_stretch_spin.valueChanged.connect(lambda v: self._on_field_changed("font_stretch", v))

        self.wrap_check = QCheckBox("自动换行")
        self.wrap_check.toggled.connect(lambda v: self._on_field_changed("wrap", v))
        self.alignment_combo = QComboBox()
        for label, val in (("左对齐", TextAlignment.LEFT), ("居中", TextAlignment.CENTER), ("右对齐", TextAlignment.RIGHT)):
            self.alignment_combo.addItem(label, val)
        self.alignment_combo.currentIndexChanged.connect(
            lambda: self._on_field_changed("alignment", self.alignment_combo.currentData()))
        self.vertical_alignment_combo = QComboBox()
        for label, val in (("顶部", VerticalAlignment.TOP), ("居中", VerticalAlignment.CENTER), ("底部", VerticalAlignment.BOTTOM)):
            self.vertical_alignment_combo.addItem(label, val)
        self.vertical_alignment_combo.currentIndexChanged.connect(
            lambda: self._on_field_changed("vertical_alignment", self.vertical_alignment_combo.currentData()))

        self.color_button = QPushButton()
        self.color_button.setObjectName("colorButton")
        self.color_button.clicked.connect(lambda: self._choose_color("fill"))
        self.stroke_width_spin = _dspin(0, 12, " px")
        self.stroke_width_spin.valueChanged.connect(lambda v: self._on_field_changed("stroke_width", v))
        self.stroke_color_button = QPushButton()
        self.stroke_color_button.setObjectName("colorButton")
        self.stroke_color_button.clicked.connect(lambda: self._choose_color("stroke"))
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

        # ===== 表单 =====
        layout.addWidget(title)
        layout.addWidget(self._no_selection_label)

        layout.addWidget(info_title)
        layout.addLayout(form)
        form.addRow(_lbl("编号"), self.region_id_label)
        form.addRow(_lbl("OCR 原文"), self.source_text_label)
        form.addRow(_lbl("状态"), self.status_label)
        form.addRow(_lbl("置信度"), self.confidence_label)
        form.addRow(_lbl("待复核"), self.review_label)
        form.addRow(_lbl("溢出"), self.overflow_label)

        geo_title = QLabel("几何")
        geo_title.setObjectName("propertyTitle")
        layout.addWidget(geo_title)
        form.addRow(_lbl("X"), self.x_spin)
        form.addRow(_lbl("Y"), self.y_spin)
        form.addRow(_lbl("宽度"), self.width_spin)
        form.addRow(_lbl("高度"), self.height_spin)
        form.addRow(_lbl("旋转"), self.rotation_spin)

        style_title = QLabel("文字样式")
        style_title.setObjectName("propertyTitle")
        layout.addWidget(style_title)
        form.addRow("文字内容", self.text_edit)
        form.addRow(_lbl("字体"), self.font_family)
        form.addRow(_lbl("字号"), self.font_size_spin)
        form.addRow(_lbl("字重"), self.font_weight_combo)
        form.addRow(_lbl("拉伸"), self.font_stretch_spin)
        form.addRow("", self.wrap_check)
        form.addRow(_lbl("水平对齐"), self.alignment_combo)
        form.addRow(_lbl("垂直对齐"), self.vertical_alignment_combo)
        form.addRow(_lbl("填充色"), self.color_button)
        form.addRow(_lbl("描边宽度"), self.stroke_width_spin)
        form.addRow(_lbl("描边色"), self.stroke_color_button)
        form.addRow("", self.shadow_check)
        form.addRow(_lbl("阴影 X/Y"), self.shadow_x_spin)
        form.addRow("", self.shadow_y_spin)
        form.addRow(_lbl("阴影透明度"), self.shadow_opacity_spin)
        form.addRow(_lbl("阴影色"), self.shadow_color_button)

        # ===== 操作按钮 =====
        ops_title = QLabel("操作")
        ops_title.setObjectName("propertyTitle")
        layout.addWidget(ops_title)

        self.delete_btn = QPushButton("删除图层")
        self.delete_btn.setObjectName("deleteTextLayerButton")
        self.delete_btn.clicked.connect(self._on_delete)

        self.duplicate_btn = QPushButton("复制图层")
        self.duplicate_btn.setObjectName("applyPropertyButton")
        self.duplicate_btn.clicked.connect(self._on_duplicate)

        self.restore_layout_btn = QPushButton("恢复自动布局")
        self.restore_layout_btn.setObjectName("applyPropertyButton")
        self.restore_layout_btn.clicked.connect(self._on_restore_layout)

        self.retranslate_btn = QPushButton("重新翻译")
        self.retranslate_btn.setEnabled(False)
        self.retranslate_btn.setToolTip("尚未实现")
        self.retranslate_btn.clicked.connect(lambda: self.retranslate_requested.emit(self._region_id or ""))

        self.keep_original_btn = QPushButton("保留原文")
        self.keep_original_btn.setEnabled(False)
        self.keep_original_btn.setToolTip("尚未实现")
        self.keep_original_btn.clicked.connect(lambda: self.keep_original_requested.emit(self._region_id or ""))

        self.confirm_review_btn = QPushButton("确认待复核")
        self.confirm_review_btn.setEnabled(False)
        self.confirm_review_btn.setToolTip("尚未实现")
        self.confirm_review_btn.clicked.connect(lambda: self.confirm_review_requested.emit(self._region_id or ""))

        layout.addWidget(self.delete_btn)
        layout.addWidget(self.duplicate_btn)
        layout.addWidget(self.restore_layout_btn)
        layout.addWidget(self.retranslate_btn)
        layout.addWidget(self.keep_original_btn)
        layout.addWidget(self.confirm_review_btn)
        layout.addStretch()

        scroll.setWidget(content)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        self._set_fields_enabled(False)

    # —— 操作槽 ——

    def _on_delete(self) -> None:
        if self._region_id is not None:
            self.delete_layer_requested.emit(self._region_id)

    def _on_duplicate(self) -> None:
        if self._region_id is not None:
            self.duplicate_layer_requested.emit(self._region_id)

    def _on_restore_layout(self) -> None:
        if self._region_id is not None:
            self.restore_layout_requested.emit(self._region_id)

    # —— 公开接口 ——

    @property
    def selected_region_id(self) -> str | None:
        return self._region_id

    def set_image_bounds(self, width: int, height: int) -> None:
        self._image_w = max(1, width)
        self._image_h = max(1, height)
        self.x_spin.setRange(0, self._image_w)
        self.y_spin.setRange(0, self._image_h)
        self.width_spin.setRange(1, self._image_w)
        self.height_spin.setRange(1, self._image_h)

    def set_layer(
        self,
        layer: TextLayer | None,
        ocr_region: object = None,
        translation_unit: object = None,
    ) -> None:
        prev_id = self._region_id
        self._region_id = layer.region_id if layer is not None else None

        if layer is None:
            self._set_fields_enabled(False)
            self._no_selection_label.setVisible(True)
            self._no_selection_label.setText("请选择一个文字图层")
            if prev_id is not None:
                self._clear_fields()
                self._clear_info_labels()
            return

        self._no_selection_label.setVisible(False)
        self._set_fields_enabled(True)
        self._suppress_signals = True
        try:
            # 基础信息（只读）
            self.region_id_label.setText(layer.region_id)
            self.overflow_label.setText("是" if layer.overflow else "否")

            if ocr_region is not None:
                cr = ocr_region
                self.source_text_label.setText(cr.text)
                self.confidence_label.setText(f"{cr.confidence * 100:.1f}%")
            else:
                self.source_text_label.setText("—")
                self.confidence_label.setText("—")

            if translation_unit is not None:
                tu = translation_unit
                status_map = {
                    "translated": "已翻译",
                    "review_required": "待复核",
                    "skipped_language": "已跳过(语言)",
                    "skipped_protected": "已跳过(保护)",
                    "failed": "失败",
                }
                self.status_label.setText(status_map.get(str(tu.status.value), str(tu.status.value)))
                self.review_label.setText("是" if str(tu.status.value) == "review_required" else "否")
            else:
                self.status_label.setText("—")
                self.review_label.setText("—")

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
            self.font_stretch_spin.setValue(style.font_stretch)
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
            self.font_stretch_spin, self.wrap_check, self.alignment_combo, self.vertical_alignment_combo,
            self.color_button, self.stroke_width_spin, self.stroke_color_button,
            self.shadow_check, self.shadow_x_spin, self.shadow_y_spin,
            self.shadow_opacity_spin, self.shadow_color_button,
            self.delete_btn, self.duplicate_btn, self.restore_layout_btn,
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
            self.font_stretch_spin.setValue(100)
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

    def _clear_info_labels(self) -> None:
        for lbl in (self.region_id_label, self.source_text_label, self.status_label,
                     self.confidence_label, self.review_label, self.overflow_label):
            lbl.setText("")


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
