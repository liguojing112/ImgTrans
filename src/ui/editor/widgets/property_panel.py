"""右侧属性编辑面板。

字段变更通过 300ms QTimer 防抖后发射 layer_property_changed 信号。
set_layer 时使用 blockSignals 避免循环同步。
"""

from __future__ import annotations

from math import cos, radians, sin

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QApplication,
    QAbstractSpinBox,
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
    QSizePolicy,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from src.domain.layout import (
    ArcTextPath,
    ArtisticPreset,
    CircularTextPath,
    TextAlignment,
    TextLayer,
    TextBox,
    VerticalAlignment,
)
from src.domain.language import SUPPORTED_LANGUAGE_CODES
from src.ui.languages import LANGUAGE_LABELS

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
    source_text_changed = Signal(str, str)
    translated_text_changed = Signal(str, str)
    manual_translate_requested = Signal(str, str, str, str)
    # OCR 尚未生成文字图层时，仍允许编辑几何和文字样式；由 EditorPage 暂存，
    # 后续翻译生成图层时应用这些设置。
    ocr_property_changed = Signal(str, str, object)
    # 格式刷：(目标 region_id, 来源 region_id, 样式快照 dict)
    style_brush_applied = Signal(str, str, dict)

    add_layer_requested = Signal(str)  # default text

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("propertyPanel")
        self.setMinimumWidth(300)
        # 字段行最小宽约 580px；上限放至面板允许的 540 以减少横向截断
        self.setMaximumWidth(540)

        self._region_id: str | None = None
        self._ocr_editing = False
        self._suppress_signals = False
        self._pending_field: str | None = None
        self._pending_value: object = None
        self._fill_rgb = (24, 32, 51)
        self._stroke_rgb = (255, 255, 255)
        self._shadow_rgb = (0, 0, 0)
        self._background_rgb = (255, 255, 255)
        self._image_w = 99999
        self._image_h = 99999
        self._current_box: TextBox | None = None
        self._last_path_mode = "straight"
        self._brush_armed = False
        self._brush_source_id: str | None = None
        self._brush_snapshot: dict[str, object] = {}

        from PySide6.QtCore import QTimer
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.timeout.connect(self._flush_pending)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        # 面板窄于表单最小宽时显示横向滚动条，避免右侧内容被无声截断
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

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

        self.source_text_edit = QPlainTextEdit()
        self.source_text_edit.setPlaceholderText("OCR 原文")
        self.source_text_edit.setMaximumHeight(56)
        self.apply_source_text_btn = QPushButton("更新 OCR 原文")
        self.apply_source_text_btn.clicked.connect(self._on_source_text_changed)
        source_text_widget = QWidget()
        source_text_layout = QVBoxLayout(source_text_widget)
        source_text_layout.setContentsMargins(0, 0, 0, 0)
        source_text_layout.setSpacing(4)
        source_text_layout.addWidget(self.source_text_edit)
        source_text_layout.addWidget(self.apply_source_text_btn)

        self.translated_text_edit = QPlainTextEdit()
        self.translated_text_edit.setPlaceholderText("译文（编辑后点击应用）")
        self.translated_text_edit.setMaximumHeight(56)
        self.apply_translated_text_btn = QPushButton("应用译文")
        self.apply_translated_text_btn.clicked.connect(self._on_translated_text_changed)
        translated_text_widget = QWidget()
        translated_text_layout = QVBoxLayout(translated_text_widget)
        translated_text_layout.setContentsMargins(0, 0, 0, 0)
        translated_text_layout.setSpacing(4)
        translated_text_layout.addWidget(self.translated_text_edit)
        translated_text_layout.addWidget(self.apply_translated_text_btn)

        self.manual_source_language = QComboBox()
        self.manual_target_language = QComboBox()
        language_names = {
            "zh-Hans": "简体中文", "zh-Hant": "繁体中文", "en": "英语",
            "ja": "日语", "ko": "韩语", "ru": "俄语", "ar": "阿拉伯语",
            "th": "泰语", "vi": "越南语", "de": "德语", "fr": "法语",
            "es": "西班牙语", "pt": "葡萄牙语", "pt-PT": "葡萄牙语（葡萄牙）",
            "pt-BR": "葡萄牙语（巴西）", "it": "意大利语", "id": "印尼语",
            "ms": "马来语", "hi": "印地语", "bn": "孟加拉语", "fil": "菲律宾语",
            "ur": "乌尔都语", "fa": "波斯语", "sw": "斯瓦希里语", "tr": "土耳其语",
            "pl": "波兰语", "nl": "荷兰语", "sv": "瑞典语", "da": "丹麦语",
            "fi": "芬兰语", "no": "挪威语", "cs": "捷克语",
        }
        self.manual_source_language.addItem("自动识别", None)
        for code in SUPPORTED_LANGUAGE_CODES:
            label = language_names.get(code, code)
            self.manual_source_language.addItem(f"{label} ({code})", code)
            self.manual_target_language.addItem(f"{label} ({code})", code)
        self.manual_target_language.setCurrentIndex(
            max(0, self.manual_target_language.findData("en"))
        )
        manual_language_row = QWidget()
        manual_language_layout = QHBoxLayout(manual_language_row)
        manual_language_layout.setContentsMargins(0, 0, 0, 0)
        manual_language_layout.setSpacing(4)
        manual_language_layout.addWidget(self.manual_source_language)
        manual_language_layout.addWidget(self.manual_target_language)
        # 手动新增文字图层的翻译行：源/目标语言 + 「新增文字翻译」按钮
        self._manual_language_widget = QWidget()
        manual_language_form = QVBoxLayout(self._manual_language_widget)
        manual_language_form.setContentsMargins(0, 0, 0, 0)
        manual_language_form.setSpacing(4)
        manual_language_form.addWidget(manual_language_row)
        self.manual_translate_btn = QPushButton("新增文字翻译")
        self.manual_translate_btn.clicked.connect(self._on_manual_translate)
        manual_language_form.addWidget(self.manual_translate_btn)

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

        self.path_mode = QComboBox()
        self.path_mode.addItem("直线", "straight")
        self.path_mode.addItem("弧线", "arc")
        self.path_mode.addItem("圆环", "circle")
        self.path_mode.currentIndexChanged.connect(self._on_path_changed)
        self.arc_bend = _dspin(-1, 1, "")
        self.arc_bend.setDecimals(2)
        self.arc_bend.setSingleStep(0.05)
        self.arc_bend.setValue(0.35)
        self.arc_bend.valueChanged.connect(self._on_path_changed)
        self.arc_bend.editingFinished.connect(self._commit_arc_bend)
        self.path_reverse = QCheckBox("反向排列")
        self.path_reverse.toggled.connect(self._on_path_changed)
        self.circle_center_x = _dspin(0, 99999, " px")
        self.circle_center_y = _dspin(0, 99999, " px")
        self.circle_radius = _dspin(1, 99999, " px")
        self.circle_start = _dspin(-360, 360, "°")
        self.circle_end = _dspin(-360, 360, "°")
        for widget in (
            self.circle_center_x,
            self.circle_center_y,
            self.circle_radius,
            self.circle_start,
            self.circle_end,
        ):
            widget.valueChanged.connect(self._on_path_changed)

        # ===== 文字样式 =====
        self.font_family = QFontComboBox()
        self.font_family.currentFontChanged.connect(lambda f: self._on_field_changed("font_family", f.family()))
        self.font_size_spin = _dspin(1, 500, " px")
        self.font_size_spin.valueChanged.connect(self._on_font_size_changed)
        self.auto_fit_check = QCheckBox("自动适配字号")
        self.auto_fit_check.toggled.connect(
            lambda value: self._on_field_changed("auto_fit", value)
        )
        self.font_weight_combo = QComboBox()
        for label, value in (("正常 400", 400), ("半粗 600", 600), ("粗体 700", 700)):
            self.font_weight_combo.addItem(label, value)
        self.font_weight_combo.currentIndexChanged.connect(
            lambda: self._on_field_changed("font_weight", self.font_weight_combo.currentData()))
        self.artistic_preset = QComboBox()
        for label, value in (
            ("自定义", ArtisticPreset.CUSTOM),
            ("描边", ArtisticPreset.OUTLINE),
            ("海报", ArtisticPreset.POSTER),
            ("阴影", ArtisticPreset.SHADOW),
        ):
            self.artistic_preset.addItem(label, value)
        self.artistic_preset.currentIndexChanged.connect(
            lambda: self._on_field_changed(
                "effect_preset", self.artistic_preset.currentData()
            )
        )
        self.font_stretch_spin = QSpinBox()
        self.font_stretch_spin.setRange(50, 200)
        self.font_stretch_spin.setSuffix("%")
        self.font_stretch_spin.valueChanged.connect(lambda v: self._on_field_changed("font_stretch", v))
        self.line_height_spin = _dspin(0.7, 3.0, "×")
        self.line_height_spin.setSingleStep(0.1)
        self.line_height_spin.valueChanged.connect(
            lambda v: self._on_field_changed("line_height", v)
        )
        self.letter_spacing_spin = _dspin(-10, 50, " px")
        self.letter_spacing_spin.valueChanged.connect(
            lambda v: self._on_field_changed("letter_spacing", v)
        )
        self.box_padding_spin = _dspin(0, 200, " px")
        self.box_padding_spin.setSingleStep(1)
        self.box_padding_spin.valueChanged.connect(
            lambda v: self._on_field_changed("box_padding", v)
        )
        self.text_opacity_spin = QSpinBox()
        self.text_opacity_spin.setRange(0, 100)
        self.text_opacity_spin.setSuffix("%")
        self.text_opacity_spin.valueChanged.connect(
            lambda v: self._on_field_changed("text_opacity", v)
        )
        self.background_color_button = QPushButton()
        self.background_color_button.setObjectName("colorButton")
        self.background_color_button.clicked.connect(
            lambda: self._choose_color("background")
        )
        self.background_opacity_spin = QSpinBox()
        self.background_opacity_spin.setRange(0, 100)
        self.background_opacity_spin.setSuffix("%")
        self.background_opacity_spin.valueChanged.connect(
            lambda v: self._on_field_changed("background_opacity", v)
        )

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
        self.color_button.setToolTip("选择当前文字图层的文字颜色")
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
        form.addRow(_lbl("原文"), source_text_widget)
        form.addRow(_lbl("翻译"), self._manual_language_widget)
        form.addRow(_lbl("译文"), translated_text_widget)
        form.addRow(_lbl("状态"), self.status_label)
        form.addRow(_lbl("置信度"), self.confidence_label)
        form.addRow(_lbl("待复核"), self.review_label)
        form.addRow(_lbl("溢出"), self.overflow_label)

        geo_title = QLabel("几何")
        geo_title.setObjectName("propertyTitle")
        layout.addWidget(geo_title)
        form.addRow(_lbl("X"), _wrap_spin(self.x_spin, label="X"))
        form.addRow(_lbl("Y"), _wrap_spin(self.y_spin, label="Y"))
        form.addRow(_lbl("宽度"), _wrap_spin(self.width_spin, label="宽度"))
        form.addRow(_lbl("高度"), _wrap_spin(self.height_spin, label="高度"))
        form.addRow(_lbl("旋转"), _wrap_spin(self.rotation_spin, label="旋转"))
        form.addRow(_lbl("文字路径"), self.path_mode)
        self.arc_bend_label = _lbl("弧线弯曲度")
        self.arc_bend_row = _wrap_spin(self.arc_bend, label="弧线弯曲度")
        form.addRow(self.arc_bend_label, self.arc_bend_row)
        self.path_reverse_label = _lbl("排列方向")
        form.addRow(self.path_reverse_label, self.path_reverse)
        self.circle_center_x_label = _lbl("圆心 X")
        self.circle_center_x_row = _wrap_spin(self.circle_center_x, label="圆心 X")
        form.addRow(self.circle_center_x_label, self.circle_center_x_row)
        self.circle_center_y_label = _lbl("圆心 Y")
        self.circle_center_y_row = _wrap_spin(self.circle_center_y, label="圆心 Y")
        form.addRow(self.circle_center_y_label, self.circle_center_y_row)
        self.circle_radius_label = _lbl("圆环半径")
        self.circle_radius_row = _wrap_spin(self.circle_radius, label="圆环半径")
        form.addRow(self.circle_radius_label, self.circle_radius_row)
        self.circle_start_label = _lbl("起始角度")
        self.circle_start_row = _wrap_spin(self.circle_start, label="起始角度")
        form.addRow(self.circle_start_label, self.circle_start_row)
        self.circle_end_label = _lbl("结束角度")
        self.circle_end_row = _wrap_spin(self.circle_end, label="结束角度")
        form.addRow(self.circle_end_label, self.circle_end_row)

        style_title = QLabel("文字样式")
        style_title.setObjectName("propertyTitle")
        layout.addWidget(style_title)
        form.addRow("文字内容", self.text_edit)
        form.addRow(_lbl("字体"), self.font_family)
        self.format_brush_btn = QToolButton()
        self.format_brush_btn.setObjectName("formatBrushButton")
        self.format_brush_btn.setCheckable(True)
        self.format_brush_btn.setText("格式刷")
        self.format_brush_btn.setToolTip(
            "捕获当前图层的文字样式；之后选中其他文字图层自动应用。"
            "按 Esc 或再次点击取消"
        )
        self.format_brush_btn.toggled.connect(self._on_format_brush_toggled)
        font_size_container = QWidget()
        font_size_row = QHBoxLayout(font_size_container)
        font_size_row.setContentsMargins(0, 0, 0, 0)
        font_size_row.setSpacing(4)
        font_size_row.addWidget(_wrap_spin(self.font_size_spin, label="字号"))
        font_size_row.addSpacing(24)
        font_size_row.addWidget(self.format_brush_btn)
        font_size_row.addStretch()
        form.addRow(_lbl("字号"), font_size_container)
        form.addRow("", self.auto_fit_check)
        form.addRow(_lbl("字重"), self.font_weight_combo)
        form.addRow(_lbl("艺术字"), self.artistic_preset)
        form.addRow(_lbl("拉伸"), _wrap_spin(self.font_stretch_spin, label="拉伸"))
        form.addRow(_lbl("行高"), _wrap_spin(self.line_height_spin, label="行高"))
        form.addRow(_lbl("字间距"), _wrap_spin(self.letter_spacing_spin, label="字间距"))
        form.addRow(_lbl("框内边距"), _wrap_spin(self.box_padding_spin, label="框内边距"))
        form.addRow(_lbl("文字透明度"), _wrap_spin(self.text_opacity_spin, label="文字透明度"))
        form.addRow(_lbl("背景色"), self.background_color_button)
        form.addRow(_lbl("背景透明度"), _wrap_spin(self.background_opacity_spin, label="背景透明度"))
        form.addRow("", self.wrap_check)
        form.addRow(_lbl("水平对齐"), self.alignment_combo)
        form.addRow(_lbl("垂直对齐"), self.vertical_alignment_combo)
        form.addRow(_lbl("文字颜色"), self.color_button)
        form.addRow(_lbl("描边宽度"), _wrap_spin(self.stroke_width_spin, label="描边宽度"))
        form.addRow(_lbl("描边色"), self.stroke_color_button)
        form.addRow("", self.shadow_check)
        form.addRow(_lbl("阴影 X/Y"), _wrap_spin(self.shadow_x_spin, label="阴影 X"))
        form.addRow("", _wrap_spin(self.shadow_y_spin, label="阴影 Y"))
        form.addRow(_lbl("阴影透明度"), _wrap_spin(self.shadow_opacity_spin, label="阴影透明度"))
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

        self.add_btn = QPushButton("新增文字图层")
        self.add_btn.setObjectName("applyPropertyButton")
        self.add_btn.clicked.connect(lambda: self.add_layer_requested.emit("新文本"))

        self.restore_layout_btn = QPushButton("恢复自动布局")
        self.restore_layout_btn.setObjectName("applyPropertyButton")
        self.restore_layout_btn.clicked.connect(self._on_restore_layout)

        # 二次翻译（普通区域）：目标语言 + 「二次翻译」按钮
        self.retranslate_target = QComboBox()
        self.retranslate_target.setObjectName("retranslateTargetLanguage")
        for code in SUPPORTED_LANGUAGE_CODES:
            self.retranslate_target.addItem(
                f"{LANGUAGE_LABELS.get(code, code)} ({code})", code
            )
        self.retranslate_target.setCurrentIndex(
            max(0, self.retranslate_target.findData("en"))
        )
        self.retranslate_btn = QPushButton("二次翻译")
        self.retranslate_btn.setEnabled(False)
        self.retranslate_btn.clicked.connect(
            lambda: self.retranslate_requested.emit(self._region_id or "")
        )
        self._retranslate_widget = QWidget()
        retranslate_inner = QHBoxLayout(self._retranslate_widget)
        retranslate_inner.setContentsMargins(0, 0, 0, 0)
        retranslate_inner.addWidget(self.retranslate_target, stretch=1)
        retranslate_inner.addWidget(self.retranslate_btn)

        self.keep_original_btn = QPushButton("保留原文")
        self.keep_original_btn.setEnabled(False)
        self.keep_original_btn.setToolTip("恢复该区域原图像素，不再显示译文")
        self.keep_original_btn.clicked.connect(lambda: self.keep_original_requested.emit(self._region_id or ""))

        self.confirm_review_btn = QPushButton("确认待复核")
        self.confirm_review_btn.setEnabled(False)
        self.confirm_review_btn.setToolTip("确认低置信 OCR 原文并翻译该区域")
        self.confirm_review_btn.clicked.connect(lambda: self.confirm_review_requested.emit(self._region_id or ""))

        layout.addWidget(self.delete_btn)
        layout.addWidget(self.duplicate_btn)
        layout.addWidget(self.add_btn)
        layout.addWidget(self.restore_layout_btn)
        layout.addWidget(self._retranslate_widget)
        layout.addWidget(self.keep_original_btn)
        layout.addWidget(self.confirm_review_btn)
        layout.addStretch()

        scroll.setWidget(content)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        self._set_fields_enabled(False)
        self._update_path_control_visibility("straight")

    # —— 格式刷 ——

    def _on_format_brush_toggled(self, checked: bool) -> None:
        if checked:
            if self._region_id is None or self._ocr_editing:
                # 没有可捕获的文字图层 → 回弹取消
                self.format_brush_btn.blockSignals(True)
                self.format_brush_btn.setChecked(False)
                self.format_brush_btn.blockSignals(False)
                return
            self._brush_armed = True
            self._brush_source_id = self._region_id
            self._brush_snapshot = self._capture_brush_snapshot()
            self._set_app_event_filter(True)
        else:
            self._brush_armed = False
            self._brush_source_id = None
            self._brush_snapshot = {}
            self._set_app_event_filter(False)

    def _set_app_event_filter(self, enabled: bool) -> None:
        """armed 期间挂应用级事件过滤器：点选画布后焦点不在面板上，
        只有应用级过滤器才能在任何焦点位置捕获 Esc。"""
        app = QApplication.instance()
        if app is None:
            return
        if enabled:
            app.installEventFilter(self)
        else:
            app.removeEventFilter(self)

    def _capture_brush_snapshot(self) -> dict[str, object]:
        """抓取当前图层的全部文字样式（不含位置/旋转/文字内容/路径）。

        应用顺序有讲究：effect_preset 会联动改描边/阴影，先应用；
        auto_fit 最后应用，覆盖 font_size 的 auto_fit=False 副作用。
        """
        return {
            "effect_preset": self.artistic_preset.currentData(),
            "font_family": self.font_family.currentFont().family(),
            "font_size": self.font_size_spin.value(),
            "font_weight": self.font_weight_combo.currentData(),
            "font_stretch": self.font_stretch_spin.value(),
            "line_height": self.line_height_spin.value(),
            "letter_spacing": self.letter_spacing_spin.value(),
            "box_padding": self.box_padding_spin.value(),
            "wrap": self.wrap_check.isChecked(),
            "alignment": self.alignment_combo.currentData(),
            "vertical_alignment": self.vertical_alignment_combo.currentData(),
            "fill_rgb": self._fill_rgb,
            "text_opacity": self.text_opacity_spin.value(),
            "background_rgb": self._background_rgb,
            "background_opacity": self.background_opacity_spin.value(),
            "stroke_width": self.stroke_width_spin.value(),
            "stroke_rgb": self._stroke_rgb,
            "shadow_enabled": self.shadow_check.isChecked(),
            "shadow_offset_x": self.shadow_x_spin.value(),
            "shadow_offset_y": self.shadow_y_spin.value(),
            "shadow_opacity": self.shadow_opacity_spin.value(),
            "auto_fit": self.auto_fit_check.isChecked(),
        }

    def _maybe_apply_brush_to(self, region_id: str) -> None:
        if (
            self._brush_armed
            and region_id != self._brush_source_id
            and self._brush_snapshot
        ):
            self.style_brush_applied.emit(
                region_id,
                self._brush_source_id or "",
                dict(self._brush_snapshot),
            )

    def eventFilter(self, obj: object, event: object) -> bool:
        if (
            self._brush_armed
            and event is not None
            and event.type() == QEvent.Type.KeyPress
            and event.key() == Qt.Key.Key_Escape  # type: ignore[union-attr]
        ):
            # 有模态对话框（如颜色选择器）打开时不拦截，Esc 仍用于关对话框
            app = QApplication.instance()
            if app is None or app.activeModalWidget() is None:
                self.format_brush_btn.setChecked(False)
                return True
        return super().eventFilter(obj, event)

    # —— 操作槽 ——

    def selected_retranslate_target(self) -> str:
        """属性面板中二次翻译的目标语言。"""
        return str(self.retranslate_target.currentData())

    def set_retranslate_target(self, code: str) -> None:
        """同步主翻译设置的目标语言到面板下拉。"""
        index = self.retranslate_target.findData(code)
        if index >= 0:
            self.retranslate_target.setCurrentIndex(index)

    def _on_delete(self) -> None:
        if self._region_id is not None:
            self.delete_layer_requested.emit(self._region_id)

    def _on_duplicate(self) -> None:
        if self._region_id is not None:
            self.duplicate_layer_requested.emit(self._region_id)

    def _on_restore_layout(self) -> None:
        if self._region_id is not None:
            self.restore_layout_requested.emit(self._region_id)

    def _on_source_text_changed(self) -> None:
        if self._region_id is None:
            return
        text = self.source_text_edit.toPlainText().strip()
        if text:
            self.source_text_changed.emit(self._region_id, text)

    def _on_translated_text_changed(self) -> None:
        if self._region_id is None:
            return
        text = self.translated_text_edit.toPlainText().strip()
        if text:
            self.translated_text_changed.emit(self._region_id, text)

    def _on_manual_translate(self) -> None:
        if self._region_id is None:
            return
        if not self._region_id.startswith("manual-"):
            # 普通 OCR 区域：二次翻译，与「重新翻译」一致
            # （用区域原文 + 「目标语言」下拉所选语言）
            self.retranslate_requested.emit(self._region_id)
            return
        # 手动新增文字图层：手动输入原文，用手动行语言
        text = self.source_text_edit.toPlainText().strip()
        target = self.manual_target_language.currentData()
        if not text or not isinstance(target, str):
            return
        source = self.manual_source_language.currentData()
        self.manual_translate_requested.emit(
            self._region_id,
            text,
            source if isinstance(source, str) else "",
            target,
        )

    def _on_path_changed(self, *_args) -> None:
        mode = str(self.path_mode.currentData())
        if self._suppress_signals:
            self._last_path_mode = mode
            self._update_path_control_visibility(mode)
            return
        if mode == "circle" and self._last_path_mode != "circle":
            self._initialize_circle_controls()
        self._last_path_mode = mode
        self._update_path_control_visibility(mode)
        self._on_field_changed(
            "text_path",
            {
                "mode": mode,
                "bend": self.arc_bend.value(),
                "reverse": self.path_reverse.isChecked(),
                "center_x": self.circle_center_x.value(),
                "center_y": self.circle_center_y.value(),
                "radius": self.circle_radius.value(),
                "start": self.circle_start.value(),
                "end": self.circle_end.value(),
            },
        )

    def _commit_arc_bend(self) -> None:
        if self._suppress_signals or self.path_mode.currentData() != "arc":
            return
        self._on_path_changed()
        self._flush_pending()

    def _on_font_size_changed(self, value: float) -> None:
        if not self._suppress_signals and self.auto_fit_check.isChecked():
            self.auto_fit_check.blockSignals(True)
            self.auto_fit_check.setChecked(False)
            self.auto_fit_check.blockSignals(False)
        self._on_field_changed("font_size", value)

    def _initialize_circle_controls(self) -> None:
        box = self._current_box
        if box is None:
            return
        previous = self._suppress_signals
        self._suppress_signals = True
        try:
            self.circle_center_x.setValue(box.center_x)
            self.circle_center_y.setValue(box.center_y)
            self.circle_radius.setValue(max(1.0, max(box.width, box.height) / 2))
            self.circle_start.setValue(180)
            self.circle_end.setValue(360)
        finally:
            self._suppress_signals = previous

    def _update_path_control_visibility(self, mode: str) -> None:
        arc = mode == "arc"
        circle = mode == "circle"
        self.arc_bend_label.setVisible(arc)
        self.arc_bend_row.setVisible(arc)
        self.path_reverse_label.setVisible(arc or circle)
        self.path_reverse.setVisible(arc or circle)
        for label, row in (
            (self.circle_center_x_label, self.circle_center_x_row),
            (self.circle_center_y_label, self.circle_center_y_row),
            (self.circle_radius_label, self.circle_radius_row),
            (self.circle_start_label, self.circle_start_row),
            (self.circle_end_label, self.circle_end_row),
        ):
            label.setVisible(circle)
            row.setVisible(circle)

    @staticmethod
    def _arc_bend_for_layer(layer: TextLayer) -> float:
        if not isinstance(layer.path, ArcTextPath):
            return 0.35
        angle = radians(layer.box.rotation_degrees)
        dx = layer.path.control.x - layer.box.center_x
        dy = layer.path.control.y - layer.box.center_y
        local_y = -dx * sin(angle) + dy * cos(angle)
        return max(-1.0, min(1.0, -local_y / max(1.0, layer.box.height)))

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
        self.circle_center_x.setRange(0, self._image_w)
        self.circle_center_y.setRange(0, self._image_h)
        self.circle_radius.setRange(1, max(self._image_w, self._image_h) * 2)

    def set_layer(
        self,
        layer: TextLayer | None,
        ocr_region: object = None,
        translation_unit: object = None,
    ) -> None:
        self._ocr_editing = False
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

            is_manual = layer.region_id.startswith("manual-") and ocr_region is None
            # 手动新增文字图层：显示「新增文字翻译」行；普通区域：显示「二次翻译」行
            self._manual_language_widget.setVisible(is_manual)
            self._retranslate_widget.setVisible(not is_manual)
            if ocr_region is not None:
                cr = ocr_region
                self.source_text_edit.setPlainText(cr.text)
                self.confidence_label.setText(f"{cr.confidence * 100:.1f}%")
            elif is_manual:
                self.source_text_edit.setPlainText(layer.text)
                self.confidence_label.setText("—")
            else:
                self.source_text_edit.clear()
                self.confidence_label.setText("—")

            if translation_unit is not None:
                tu = translation_unit
                status_map = {
                    "translated": "已翻译",
                    "review_required": "待复核",
                    "skipped_language": "已跳过(语言)",
                    "skipped_protected": "已跳过(保护)",
                    "skipped_user": "用户保留原文",
                    "failed": "失败",
                }
                self.status_label.setText(status_map.get(str(tu.status.value), str(tu.status.value)))
                self.review_label.setText("是" if str(tu.status.value) == "review_required" else "否")
                status = str(tu.status.value)
                self.keep_original_btn.setEnabled(status in {"translated", "review_required", "failed"})
                self.confirm_review_btn.setEnabled(status == "review_required")
            else:
                self.status_label.setText("—")
                self.review_label.setText("—")
                self.keep_original_btn.setEnabled(False)
                self.confirm_review_btn.setEnabled(False)
            self.restore_layout_btn.setEnabled(
                translation_unit is not None and not is_manual
            )

            if prev_id != layer.region_id:
                self.text_edit.setPlainText(layer.text)

            if prev_id != layer.region_id or not self.translated_text_edit.hasFocus():
                # 译文框仅对翻译区域显示/编辑；自建文字图层（无翻译单元）不显示译文
                if is_manual:
                    self.translated_text_edit.setPlainText(layer.text)
                    self.apply_translated_text_btn.setEnabled(True)
                elif translation_unit is not None and translation_unit.translated_text:
                    self.translated_text_edit.setPlainText(
                        translation_unit.translated_text
                    )
                    self.apply_translated_text_btn.setEnabled(True)
                else:
                    self.translated_text_edit.clear()
                    self.apply_translated_text_btn.setEnabled(False)
            # 「二次翻译」按钮（普通区域）：有可翻译原文即可用，保护区域除外
            protected = (
                translation_unit is not None
                and str(translation_unit.status.value) == "skipped_protected"
            )
            self.retranslate_btn.setEnabled(
                bool(self.source_text_edit.toPlainText().strip())
                and not protected
            )
            # 「新增文字翻译」按钮（手动新增文字图层）
            self.manual_translate_btn.setEnabled(is_manual)

            box = layer.box
            self._current_box = box
            self.x_spin.setValue(box.center_x)
            self.y_spin.setValue(box.center_y)
            self.width_spin.setValue(box.width)
            self.height_spin.setValue(box.height)
            self.rotation_spin.setValue(box.rotation_degrees)
            if isinstance(layer.path, CircularTextPath):
                path_mode = "circle"
                self.circle_center_x.setValue(layer.path.center.x)
                self.circle_center_y.setValue(layer.path.center.y)
                self.circle_radius.setValue(layer.path.radius)
                self.circle_start.setValue(layer.path.start_angle_degrees)
                self.circle_end.setValue(layer.path.end_angle_degrees)
                self.path_reverse.setChecked(layer.path.reverse)
            elif isinstance(layer.path, ArcTextPath):
                path_mode = "arc"
                self.arc_bend.setValue(self._arc_bend_for_layer(layer))
                self.path_reverse.setChecked(layer.path.reverse)
            else:
                path_mode = "straight"
                self.circle_center_x.setValue(box.center_x)
                self.circle_center_y.setValue(box.center_y)
                self.circle_radius.setValue(max(1.0, box.width / 2))
                self.circle_start.setValue(180)
                self.circle_end.setValue(360)
                self.path_reverse.setChecked(False)
            path_index = self.path_mode.findData(path_mode)
            self.path_mode.setCurrentIndex(max(0, path_index))
            self._last_path_mode = path_mode
            self._update_path_control_visibility(path_mode)

            style = layer.style
            self.font_family.setCurrentFont(QFont(style.font_family))
            self.font_size_spin.setValue(style.font_size)
            self.auto_fit_check.setChecked(style.auto_fit)
            idx_w = self.font_weight_combo.findData(style.font_weight)
            if idx_w >= 0:
                self.font_weight_combo.setCurrentIndex(idx_w)
            preset_index = self.artistic_preset.findData(style.effect_preset)
            self.artistic_preset.setCurrentIndex(max(0, preset_index))
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
            self._background_rgb = style.background_rgb or (255, 255, 255)
            self.stroke_width_spin.setValue(style.stroke_width)
            self.shadow_check.setChecked(style.shadow_opacity > 0)
            self.shadow_x_spin.setValue(style.shadow_offset_x)
            self.shadow_y_spin.setValue(style.shadow_offset_y)
            self.shadow_opacity_spin.setValue(round(style.shadow_opacity * 100))
            self.line_height_spin.setValue(style.line_height)
            self.letter_spacing_spin.setValue(style.letter_spacing)
            self.box_padding_spin.setValue(style.box_padding)
            self.text_opacity_spin.setValue(round(style.text_opacity * 100))
            self.background_opacity_spin.setValue(
                round(style.background_opacity * 100)
            )
            self._update_color_buttons()
        finally:
            self._suppress_signals = False

        # 格式刷：选中新的图层时自动应用已捕获的样式（同一图层重入不重复刷）
        if prev_id != layer.region_id:
            self._maybe_apply_brush_to(layer.region_id)

    def set_ocr_region(
        self,
        ocr_region: object,
        translation_unit: object | None = None,
        property_overrides: dict[str, object] | None = None,
    ) -> None:
        # Loading a row into the editor must not be treated as a user edit.
        # In particular, QPlainTextEdit emits textChanged from setPlainText;
        # forwarding that signal here would create a duplicate preview layer
        # over the untouched OCR pixels every time a row is selected.
        previous_suppression = self._suppress_signals
        self._suppress_signals = True
        try:
            self._set_ocr_region_contents(
                ocr_region, translation_unit, property_overrides
            )
        finally:
            self._suppress_signals = previous_suppression

    def _set_ocr_region_contents(
        self,
        ocr_region: object,
        translation_unit: object | None,
        property_overrides: dict[str, object] | None,
    ) -> None:
        self._region_id = str(ocr_region.region_id)
        self._ocr_editing = True
        self._no_selection_label.setVisible(False)
        self._set_fields_enabled(False)
        self.source_text_edit.setEnabled(True)
        self.apply_source_text_btn.setEnabled(True)
        self.translated_text_edit.setEnabled(True)
        if translation_unit is not None and translation_unit.translated_text:
            self.translated_text_edit.setPlainText(
                str(translation_unit.translated_text)
            )
            self.apply_translated_text_btn.setEnabled(True)
        else:
            self.translated_text_edit.clear()
            self.apply_translated_text_btn.setEnabled(False)
        self.region_id_label.setText(self._region_id)
        self.source_text_edit.setPlainText(str(ocr_region.text))
        self.text_edit.setPlainText(str(ocr_region.text))
        self.confidence_label.setText(f"{ocr_region.confidence * 100:.1f}%")
        self.overflow_label.setText("—")
        status = (
            str(translation_unit.status.value)
            if translation_unit is not None
            else "unprocessed"
        )
        labels = {
            "translated": "已翻译",
            "review_required": "待复核",
            "skipped_language": "已跳过(语言)",
            "skipped_protected": "已跳过(保护)",
            "skipped_user": "用户保留原文",
            "failed": "失败",
            "unprocessed": "未处理",
        }
        self.status_label.setText(labels.get(status, status))
        self.review_label.setText("是" if status == "review_required" else "否")
        self.keep_original_btn.setEnabled(status in {"translated", "review_required", "failed"})
        self.confirm_review_btn.setEnabled(status == "review_required")
        # 「二次翻译」按钮：有可翻译原文即可用（OCR-only 普通区域）
        self.retranslate_btn.setEnabled(
            bool(self.source_text_edit.toPlainText().strip())
            and status != "skipped_protected"
        )

        # OCR-only 阶段没有 TextLayer，但属性编辑仍应可用。初始几何取 OCR
        # polygon 的包围盒，后续改动通过 ocr_property_changed 暂存。
        points = tuple(getattr(ocr_region, "polygon", ()))
        if len(points) == 4:
            xs = [float(point.x) for point in points]
            ys = [float(point.y) for point in points]
            self._suppress_signals = True
            try:
                self.x_spin.setValue((min(xs) + max(xs)) / 2)
                self.y_spin.setValue((min(ys) + max(ys)) / 2)
                self.width_spin.setValue(max(1.0, max(xs) - min(xs)))
                self.height_spin.setValue(max(1.0, max(ys) - min(ys)))
                self.rotation_spin.setValue(0)
                self._current_box = TextBox(
                    (min(xs) + max(xs)) / 2,
                    (min(ys) + max(ys)) / 2,
                    max(1.0, max(xs) - min(xs)),
                    max(1.0, max(ys) - min(ys)),
                )
                self.font_size_spin.setValue(
                    max(1.0, min(96.0, max(10.0, max(ys) - min(ys))))
                )
                self.font_weight_combo.setCurrentIndex(
                    max(0, self.font_weight_combo.findData(400))
                )
                self.auto_fit_check.setChecked(True)
                self.path_mode.setCurrentIndex(0)
                self._last_path_mode = "straight"
                self._update_path_control_visibility("straight")
                self._fill_rgb = (0, 0, 0)
                self._update_color_buttons()
            finally:
                self._suppress_signals = False
        self._suppress_signals = True
        try:
            for field, value in (property_overrides or {}).items():
                self._set_ocr_control_value(field, value)
        finally:
            self._suppress_signals = False
        if translation_unit is None:
            self._set_ocr_editable_fields(True)

    def _set_ocr_editable_fields(self, enabled: bool) -> None:
        """启用 OCR-only 可编辑字段，禁用必须依赖文字图层的操作。"""
        for widget in (
            self.text_edit, self.x_spin, self.y_spin, self.width_spin,
            self.height_spin, self.rotation_spin, self.font_family,
            self.font_size_spin, self.auto_fit_check, self.font_weight_combo, self.path_mode,
            self.arc_bend, self.path_reverse, self.circle_center_x,
            self.circle_center_y, self.circle_radius, self.circle_start,
            self.circle_end, self.artistic_preset, self.font_stretch_spin,
            self.wrap_check, self.alignment_combo, self.vertical_alignment_combo,
            self.line_height_spin, self.letter_spacing_spin, self.box_padding_spin,
            self.text_opacity_spin, self.background_color_button,
            self.background_opacity_spin,
            self.color_button, self.stroke_width_spin, self.stroke_color_button,
            self.shadow_check, self.shadow_x_spin, self.shadow_y_spin,
            self.shadow_opacity_spin, self.shadow_color_button,
        ):
            widget.setEnabled(enabled)
        for widget in (
            self.delete_btn, self.duplicate_btn, self.add_btn,
            self.restore_layout_btn,
            self.keep_original_btn, self.confirm_review_btn,
        ):
            widget.setEnabled(False)

    def _set_ocr_control_value(self, field: str, value: object) -> None:
        """将暂存的 OCR-only 属性回显到对应控件。"""
        controls = {
            "center_x": self.x_spin, "center_y": self.y_spin,
            "width": self.width_spin, "height": self.height_spin,
            "rotation_degrees": self.rotation_spin, "font_size": self.font_size_spin,
            "font_stretch": self.font_stretch_spin, "line_height": self.line_height_spin,
            "letter_spacing": self.letter_spacing_spin,
            "box_padding": self.box_padding_spin,
            "text_opacity": self.text_opacity_spin,
            "background_opacity": self.background_opacity_spin,
            "stroke_width": self.stroke_width_spin,
            "shadow_x": self.shadow_x_spin, "shadow_y": self.shadow_y_spin,
            "shadow_opacity": self.shadow_opacity_spin,
        }
        control = controls.get(field)
        if control is not None:
            control.setValue(float(value))
        elif field == "font_weight":
            index = self.font_weight_combo.findData(int(value))
            if index >= 0:
                self.font_weight_combo.setCurrentIndex(index)
        elif field == "font_family":
            self.font_family.setCurrentFont(QFont(str(value)))
        elif field == "auto_fit":
            self.auto_fit_check.setChecked(bool(value))
        elif field == "text":
            self.text_edit.setPlainText(str(value))
        elif field == "wrap":
            self.wrap_check.setChecked(bool(value))
        elif field == "alignment":
            index = self.alignment_combo.findData(value)
            if index >= 0:
                self.alignment_combo.setCurrentIndex(index)
        elif field == "vertical_alignment":
            index = self.vertical_alignment_combo.findData(value)
            if index >= 0:
                self.vertical_alignment_combo.setCurrentIndex(index)
        elif field == "text_opacity":
            self.text_opacity_spin.setValue(float(value) * 100 if float(value) <= 1 else float(value))
        elif field == "background_rgb":
            self._background_rgb = tuple(value)  # type: ignore[arg-type]
            self._update_color_buttons()
        elif field == "background_opacity":
            self.background_opacity_spin.setValue(float(value) * 100 if float(value) <= 1 else float(value))
        elif field == "fill_rgb":
            self._fill_rgb = tuple(value)  # type: ignore[arg-type]
            self._update_color_buttons()
        elif field == "stroke_rgb":
            self._stroke_rgb = tuple(value)  # type: ignore[arg-type]
            self._update_color_buttons()
        elif field == "shadow_rgb":
            self._shadow_rgb = tuple(value)  # type: ignore[arg-type]
            self._update_color_buttons()
        elif field == "shadow_offset_x":
            self.shadow_x_spin.setValue(float(value))
        elif field == "shadow_offset_y":
            self.shadow_y_spin.setValue(float(value))
        elif field == "shadow_opacity":
            self.shadow_opacity_spin.setValue(float(value) * 100 if float(value) <= 1 else float(value))
        elif field == "shadow_enabled":
            self.shadow_check.setChecked(bool(value))

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
        field = self._pending_field
        value = self._pending_value
        self._pending_field = None
        self._pending_value = None
        signal = self.ocr_property_changed if self._ocr_editing else self.layer_property_changed
        signal.emit(self._region_id, field, value)

    def _choose_color(self, kind: str) -> None:
        current_rgb = {
            "fill": self._fill_rgb,
            "stroke": self._stroke_rgb,
            "shadow": self._shadow_rgb,
            "background": self._background_rgb,
        }[kind]
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
        elif kind == "shadow":
            self._shadow_rgb = rgb
            self._on_field_changed("shadow_rgb", rgb)
        else:
            self._background_rgb = rgb
            self._on_field_changed("background_rgb", rgb)
        self._update_color_buttons()

    def _update_color_buttons(self) -> None:
        for btn, rgb in (
            (self.color_button, self._fill_rgb),
            (self.stroke_color_button, self._stroke_rgb),
            (self.shadow_color_button, self._shadow_rgb),
            (self.background_color_button, self._background_rgb),
        ):
            btn.setText("#{:02X}{:02X}{:02X}".format(*rgb))
            fg = "#ffffff" if sum(rgb) < 360 else "#172033"
            btn.setStyleSheet(
                f"background: rgb{rgb}; color: {fg}; border: 1px solid #d5d9e0; border-radius: 6px; padding: 5px;"
            )

    def _set_fields_enabled(self, enabled: bool) -> None:
        for w in (
            self.text_edit, self.x_spin, self.y_spin, self.width_spin, self.height_spin,
            self.rotation_spin, self.font_family, self.font_size_spin, self.font_weight_combo,
            self.auto_fit_check, self.format_brush_btn,
            self.path_mode, self.arc_bend, self.path_reverse, self.circle_center_x,
            self.circle_center_y, self.circle_radius, self.circle_start, self.circle_end,
            self.artistic_preset,
            self.font_stretch_spin, self.wrap_check, self.alignment_combo, self.vertical_alignment_combo,
            self.line_height_spin, self.letter_spacing_spin, self.box_padding_spin,
            self.text_opacity_spin, self.background_color_button,
            self.background_opacity_spin,
            self.color_button, self.stroke_width_spin, self.stroke_color_button,
            self.shadow_check, self.shadow_x_spin, self.shadow_y_spin,
            self.shadow_opacity_spin, self.shadow_color_button,
            self.delete_btn, self.duplicate_btn, self.add_btn, self.restore_layout_btn,
            self.source_text_edit, self.apply_source_text_btn,
            self.translated_text_edit, self.apply_translated_text_btn,
            self.manual_source_language, self.manual_target_language,
            self.manual_translate_btn, self.retranslate_btn,
            self.keep_original_btn, self.confirm_review_btn,
        ):
            w.setEnabled(enabled)

    def _clear_fields(self) -> None:
        self._suppress_signals = True
        try:
            self.text_edit.clear()
            for s in (self.x_spin, self.y_spin, self.width_spin, self.height_spin):
                s.setValue(0)
            self.rotation_spin.setValue(0)
            self.path_mode.setCurrentIndex(0)
            self.font_size_spin.setValue(0)
            self.auto_fit_check.setChecked(True)
            self.font_weight_combo.setCurrentIndex(0)
            self.artistic_preset.setCurrentIndex(0)
            self.font_stretch_spin.setValue(100)
            self.line_height_spin.setValue(1)
            self.letter_spacing_spin.setValue(0)
            self.box_padding_spin.setValue(0)
            self.text_opacity_spin.setValue(100)
            self.background_opacity_spin.setValue(0)
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
        self.source_text_edit.clear()
        self.translated_text_edit.clear()
        for lbl in (self.region_id_label, self.status_label,
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


def _wrap_spin(
    spin: QAbstractSpinBox, width: int = 70, label: str = ""
) -> QWidget:
    """把 ± 按钮移到输入框右侧外部（与图层状态面板一致），返回容器。"""
    spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
    spin.setFixedWidth(width)
    container = QWidget()
    container.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    hbox = QHBoxLayout(container)
    hbox.setContentsMargins(0, 0, 0, 0)
    hbox.setSpacing(2)
    hbox.addWidget(spin)
    smaller = QToolButton()
    smaller.setText("−")
    smaller.setToolTip(f"减小{label}")
    smaller.clicked.connect(spin.stepDown)
    hbox.addWidget(smaller)
    larger = QToolButton()
    larger.setText("+")
    larger.setToolTip(f"增大{label}")
    larger.clicked.connect(spin.stepUp)
    hbox.addWidget(larger)
    return container
