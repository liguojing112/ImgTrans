from __future__ import annotations

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
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from src.domain.layout import (
    ArtisticPreset,
    FontStyleHint,
    TextAlignment,
    TextLayer,
    TextStyle,
    VerticalAlignment,
)
from src.platform.font_candidates import recommend_system_fonts


class LayerStylePanel(QFrame):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("layerStylePanel")
        self._region_id: str | None = None
        self._selected_text = ""
        self._fill_rgb = (24, 32, 51)
        self._stroke_rgb = (255, 255, 255)
        self._shadow_rgb = (0, 0, 0)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)
        title = QLabel("文字样式与图层")
        title.setObjectName("panelTitle")
        self.selected_label = QLabel("尚未选择文字图层")
        self.selected_label.setObjectName("styleSelectedLabel")
        form = QFormLayout()
        form.setSpacing(6)
        self.font_family = QFontComboBox()
        self.font_family.setObjectName("styleFontFamily")
        font_recommendation = QHBoxLayout()
        self.font_hint = QComboBox()
        for label, value in (
            ("无衬线", FontStyleHint.SANS.value),
            ("衬线", FontStyleHint.SERIF.value),
            ("展示/粗体", FontStyleHint.DISPLAY.value),
            ("手写风格", FontStyleHint.HANDWRITTEN.value),
        ):
            self.font_hint.addItem(label, value)
        self.recommend_font_button = QPushButton("推荐已安装字体")
        self.recommend_font_button.clicked.connect(self._recommend_font)
        font_recommendation.addWidget(self.font_hint)
        font_recommendation.addWidget(self.recommend_font_button)
        self.font_size = QDoubleSpinBox()
        self.font_size.setRange(1, 500)
        self.font_size.setDecimals(1)
        self.font_size.setSuffix(" px")
        self.auto_fit = QCheckBox("自动适配字号")
        self.wrap = QCheckBox("自动换行")
        self.horizontal = QComboBox()
        for label, value in (
            ("左对齐", TextAlignment.LEFT),
            ("居中", TextAlignment.CENTER),
            ("右对齐", TextAlignment.RIGHT),
        ):
            self.horizontal.addItem(label, value)
        self.vertical = QComboBox()
        for label, value in (
            ("顶部", VerticalAlignment.TOP),
            ("垂直居中", VerticalAlignment.CENTER),
            ("底部", VerticalAlignment.BOTTOM),
        ):
            self.vertical.addItem(label, value)
        self.rotation = QDoubleSpinBox()
        self.rotation.setRange(-180, 180)
        self.rotation.setSuffix("°")
        self.fill_button = QPushButton("文字颜色")
        self.fill_button.clicked.connect(lambda: self._choose_color("fill"))
        self.stroke_width = QDoubleSpinBox()
        self.stroke_width.setRange(0, 12)
        self.stroke_width.setDecimals(1)
        self.stroke_width.setSuffix(" px")
        self.stroke_button = QPushButton("描边颜色")
        self.stroke_button.clicked.connect(lambda: self._choose_color("stroke"))
        self.shadow_enabled = QCheckBox("启用阴影")
        shadow_offsets = QHBoxLayout()
        self.shadow_x = QDoubleSpinBox()
        self.shadow_y = QDoubleSpinBox()
        for spin in (self.shadow_x, self.shadow_y):
            spin.setRange(-50, 50)
            spin.setSuffix(" px")
        shadow_offsets.addWidget(self.shadow_x)
        shadow_offsets.addWidget(self.shadow_y)
        self.shadow_opacity = QSpinBox()
        self.shadow_opacity.setRange(0, 100)
        self.shadow_opacity.setSuffix("%")
        self.shadow_button = QPushButton("阴影颜色")
        self.shadow_button.clicked.connect(lambda: self._choose_color("shadow"))
        artistic_row = QHBoxLayout()
        self.effect_preset = QComboBox()
        for label, value in (
            ("自定义", ArtisticPreset.CUSTOM.value),
            ("清晰描边", ArtisticPreset.OUTLINE.value),
            ("电商海报", ArtisticPreset.POSTER.value),
            ("立体阴影", ArtisticPreset.SHADOW.value),
        ):
            self.effect_preset.addItem(label, value)
        self.apply_preset_button = QPushButton("载入近似预设")
        self.apply_preset_button.clicked.connect(self._apply_effect_preset)
        artistic_row.addWidget(self.effect_preset)
        artistic_row.addWidget(self.apply_preset_button)
        form.addRow("字体", self.font_family)
        form.addRow("字体候选", font_recommendation)
        form.addRow("字号", self.font_size)
        form.addRow("", self.auto_fit)
        form.addRow("", self.wrap)
        form.addRow("水平对齐", self.horizontal)
        form.addRow("垂直对齐", self.vertical)
        form.addRow("旋转", self.rotation)
        form.addRow("填充", self.fill_button)
        form.addRow("描边宽度", self.stroke_width)
        form.addRow("描边", self.stroke_button)
        form.addRow("", self.shadow_enabled)
        form.addRow("阴影偏移 X/Y", shadow_offsets)
        form.addRow("阴影透明度", self.shadow_opacity)
        form.addRow("阴影", self.shadow_button)
        form.addRow("艺术效果", artistic_row)
        self.apply_button = QPushButton("应用样式")
        self.apply_button.setObjectName("applyLayerStyleButton")
        layer_actions = QHBoxLayout()
        self.add_button = QPushButton("新增文字框")
        self.add_button.setObjectName("addTextLayerButton")
        self.delete_button = QPushButton("删除文字框")
        self.delete_button.setObjectName("deleteTextLayerButton")
        layer_actions.addWidget(self.add_button)
        layer_actions.addWidget(self.delete_button)
        layout.addWidget(title)
        layout.addWidget(self.selected_label)
        layout.addLayout(form)
        layout.addWidget(self.apply_button)
        layout.addLayout(layer_actions)
        layout.addStretch()
        self.set_layer(None)

    @property
    def selected_region_id(self) -> str | None:
        return self._region_id

    def set_layer(self, layer: TextLayer | None) -> None:
        self._region_id = layer.region_id if layer else None
        self._selected_text = layer.text if layer else ""
        self.selected_label.setText(
            f"当前图层：{layer.text or '（空文本）'}" if layer else "尚未选择文字图层"
        )
        if layer is not None:
            style = layer.style
            self.font_family.setCurrentFont(QFont(style.font_family))
            self.font_size.setValue(style.font_size)
            self.auto_fit.setChecked(style.auto_fit)
            self.wrap.setChecked(style.wrap)
            self.horizontal.setCurrentIndex(self.horizontal.findData(style.alignment))
            self.vertical.setCurrentIndex(
                self.vertical.findData(style.vertical_alignment)
            )
            self.rotation.setValue(layer.box.rotation_degrees)
            self.stroke_width.setValue(style.stroke_width)
            self.shadow_enabled.setChecked(style.shadow_opacity > 0)
            self.shadow_x.setValue(style.shadow_offset_x)
            self.shadow_y.setValue(style.shadow_offset_y)
            self.shadow_opacity.setValue(round(style.shadow_opacity * 100))
            preset_index = self.effect_preset.findData(style.effect_preset.value)
            self.effect_preset.setCurrentIndex(max(0, preset_index))
            self._fill_rgb = style.fill_rgb
            self._stroke_rgb = style.stroke_rgb
            self._shadow_rgb = style.shadow_rgb
            self._update_color_buttons()
        self.apply_button.setEnabled(layer is not None)
        self.delete_button.setEnabled(layer is not None)
        self.recommend_font_button.setEnabled(layer is not None)
        self.apply_preset_button.setEnabled(layer is not None)

    def edited_style(self) -> tuple[TextStyle, float]:
        shadow_opacity = (
            self.shadow_opacity.value() / 100 if self.shadow_enabled.isChecked() else 0
        )
        return (
            TextStyle(
                self.font_family.currentFont().family(),
                self.font_size.value(),
                self._fill_rgb,
                self.horizontal.currentData(),
                self.vertical.currentData(),
                self.wrap.isChecked(),
                self.auto_fit.isChecked(),
                self._stroke_rgb,
                self.stroke_width.value(),
                self._shadow_rgb,
                shadow_opacity,
                self.shadow_x.value(),
                self.shadow_y.value(),
                ArtisticPreset(self.effect_preset.currentData()),
            ),
            self.rotation.value(),
        )

    def set_editor_available(self, available: bool, busy: bool) -> None:
        self.add_button.setEnabled(available and not busy)
        selected = available and self._region_id is not None and not busy
        self.apply_button.setEnabled(selected)
        self.delete_button.setEnabled(selected)
        self.recommend_font_button.setEnabled(selected)
        self.apply_preset_button.setEnabled(selected)

    def _choose_color(self, kind: str) -> None:
        current = {
            "fill": self._fill_rgb,
            "stroke": self._stroke_rgb,
            "shadow": self._shadow_rgb,
        }[kind]
        selected = QColorDialog.getColor(QColor(*current), self, "选择颜色")
        if not selected.isValid():
            return
        value = (selected.red(), selected.green(), selected.blue())
        if kind == "fill":
            self._fill_rgb = value
        elif kind == "stroke":
            self._stroke_rgb = value
        else:
            self._shadow_rgb = value
        self._update_color_buttons()

    def _update_color_buttons(self) -> None:
        for button, color in (
            (self.fill_button, self._fill_rgb),
            (self.stroke_button, self._stroke_rgb),
            (self.shadow_button, self._shadow_rgb),
        ):
            foreground = "#ffffff" if sum(color) < 360 else "#172033"
            button.setStyleSheet(
                f"background: rgb{color}; color: {foreground}; border: 1px solid #aeb8c8; padding: 5px;"
            )

    def _recommend_font(self) -> None:
        hint = FontStyleHint(self.font_hint.currentData())
        candidates = recommend_system_fonts(self._selected_text, hint)
        if candidates:
            self.font_family.setCurrentFont(QFont(candidates[0]))

    def _apply_effect_preset(self) -> None:
        preset = ArtisticPreset(self.effect_preset.currentData())
        if preset is ArtisticPreset.CUSTOM:
            return
        if preset is ArtisticPreset.OUTLINE:
            self.stroke_width.setValue(max(2, self.stroke_width.value()))
            self._stroke_rgb = (255, 255, 255)
            self.shadow_enabled.setChecked(False)
        elif preset is ArtisticPreset.POSTER:
            self.stroke_width.setValue(max(3, self.stroke_width.value()))
            self._stroke_rgb = (24, 32, 51)
            self.shadow_enabled.setChecked(True)
            self.shadow_opacity.setValue(55)
            self.shadow_x.setValue(4)
            self.shadow_y.setValue(4)
        else:
            self.stroke_width.setValue(max(1, self.stroke_width.value()))
            self.shadow_enabled.setChecked(True)
            self.shadow_opacity.setValue(70)
            self.shadow_x.setValue(6)
            self.shadow_y.setValue(6)
        self._update_color_buttons()
