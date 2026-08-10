from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QFrame,
    QCheckBox,
    QColorDialog,
    QDoubleSpinBox,
    QFontComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from src.domain.composition import WatermarkLayer
from src.domain.layout import TextLayout


class LayerStatePanel(QFrame):
    layer_selected = Signal(str)
    layer_visibility_changed = Signal(str, bool)
    layer_lock_changed = Signal(str, bool)
    watermark_visibility_changed = Signal(str, bool)
    watermark_lock_changed = Signal(str, bool)
    watermark_selected = Signal(str)
    watermark_delete_requested = Signal(str)
    watermark_duplicate_requested = Signal(str)
    watermark_property_changed = Signal(str, str, object)
    watermark_preview_changed = Signal(object)
    layer_move_requested = Signal(str, str, int)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("layerStatePanel")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        title = QLabel("图层状态")
        title.setObjectName("propertyTitle")
        self.tree = QTreeWidget()
        self.tree.setObjectName("layerStateTree")
        self.tree.setHeaderLabels(("图层", "状态", "锁定"))
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        self.tree.itemSelectionChanged.connect(self._emit_selection)
        self.tree.itemChanged.connect(self._emit_visibility)

        self.empty_label = QLabel("翻译完成后将在这里显示文字图层")
        self.empty_label.setObjectName("propertyNoSelection")
        self.empty_label.setWordWrap(True)

        layout.addWidget(title)
        layout.addWidget(self.tree, stretch=1)

        self.watermark_editor = QFrame()
        editor_form = QFormLayout(self.watermark_editor)
        editor_form.setContentsMargins(0, 0, 0, 0)
        self.watermark_text = QLineEdit()
        self.watermark_text.setPlaceholderText("选择文字水印后可编辑")
        self.watermark_font = QFontComboBox()
        self.watermark_font_size = QDoubleSpinBox()
        self.watermark_font_size.setRange(4, 1000)
        self.watermark_font_size.setDecimals(1)
        self.watermark_font_size.setSuffix(" px")
        (
            font_size_row,
            self.watermark_font_smaller,
            self.watermark_font_larger,
        ) = _stepper_row(self.watermark_font_size, "字号")
        self.watermark_color = QLineEdit()
        self.watermark_color.setPlaceholderText("#FFFFFF")
        self.watermark_color.setReadOnly(True)
        self.watermark_color_button = QPushButton("选择颜色")
        color_row = QHBoxLayout()
        color_row.setContentsMargins(0, 0, 0, 0)
        color_row.addWidget(self.watermark_color)
        color_row.addWidget(self.watermark_color_button)
        self.watermark_rotation = QDoubleSpinBox()
        self.watermark_rotation.setRange(-360, 360)
        self.watermark_rotation.setDecimals(1)
        self.watermark_rotation.setSuffix("°")
        (
            rotation_row,
            self.watermark_rotation_smaller,
            self.watermark_rotation_larger,
        ) = _stepper_row(self.watermark_rotation, "旋转角度")
        size_row = QHBoxLayout()
        size_row.setContentsMargins(0, 0, 0, 0)
        self.watermark_width = QDoubleSpinBox()
        self.watermark_width.setRange(10, 100000)
        self.watermark_width.setDecimals(1)
        self.watermark_width.setSuffix(" px")
        (
            width_row,
            self.watermark_width_smaller,
            self.watermark_width_larger,
        ) = _stepper_row(self.watermark_width, "宽度", 94)
        self.watermark_height = QDoubleSpinBox()
        self.watermark_height.setRange(10, 100000)
        self.watermark_height.setDecimals(1)
        self.watermark_height.setSuffix(" px")
        (
            height_row,
            self.watermark_height_smaller,
            self.watermark_height_larger,
        ) = _stepper_row(self.watermark_height, "高度", 94)
        size_row.addLayout(width_row)
        size_row.addLayout(height_row)
        editor_form.addRow("水印文字", self.watermark_text)
        editor_form.addRow("字体", self.watermark_font)
        editor_form.addRow("字号", font_size_row)
        editor_form.addRow("颜色", color_row)
        editor_form.addRow("旋转", rotation_row)
        editor_form.addRow("宽度 / 高度", size_row)
        layout.addWidget(self.watermark_editor)

        self.watermark_text.editingFinished.connect(
            self._emit_watermark_text
        )
        self.watermark_font.currentFontChanged.connect(
            lambda font: self._emit_watermark_style(
                font_family=font.family()
            )
        )
        self.watermark_font_size.editingFinished.connect(
            lambda: self._emit_watermark_style(
                font_size=self.watermark_font_size.value()
            )
        )
        self.watermark_font_size.valueChanged.connect(
            self._preview_watermark_font_size
        )
        self.watermark_font_smaller.clicked.connect(
            lambda: self._adjust_watermark_font_size(-1)
        )
        self.watermark_font_larger.clicked.connect(
            lambda: self._adjust_watermark_font_size(1)
        )
        self.watermark_color_button.clicked.connect(self._choose_watermark_color)
        self.watermark_rotation.valueChanged.connect(
            self._preview_watermark_rotation
        )
        self.watermark_rotation.editingFinished.connect(
            lambda: self._emit_watermark_property(
                "rotation_degrees",
                self.watermark_rotation.value(),
            )
        )
        self.watermark_rotation_smaller.clicked.connect(
            lambda: self._adjust_watermark_rotation(-1)
        )
        self.watermark_rotation_larger.clicked.connect(
            lambda: self._adjust_watermark_rotation(1)
        )
        self.watermark_width.valueChanged.connect(self._preview_watermark_size)
        self.watermark_height.valueChanged.connect(self._preview_watermark_size)
        self.watermark_width.editingFinished.connect(
            self._emit_watermark_size
        )
        self.watermark_height.editingFinished.connect(self._emit_watermark_size)
        self.watermark_width_smaller.clicked.connect(
            lambda: self._adjust_watermark_size(self.watermark_width, -1)
        )
        self.watermark_width_larger.clicked.connect(
            lambda: self._adjust_watermark_size(self.watermark_width, 1)
        )
        self.watermark_height_smaller.clicked.connect(
            lambda: self._adjust_watermark_size(self.watermark_height, -1)
        )
        self.watermark_height_larger.clicked.connect(
            lambda: self._adjust_watermark_size(self.watermark_height, 1)
        )

        watermark_form = QHBoxLayout()
        self.watermark_opacity = QSpinBox()
        self.watermark_opacity.setRange(0, 100)
        self.watermark_opacity.setSuffix("%")
        (
            opacity_row,
            self.watermark_opacity_smaller,
            self.watermark_opacity_larger,
        ) = _stepper_row(self.watermark_opacity, "透明度", 94)
        self.watermark_tiled = QCheckBox("平铺")
        watermark_form.addWidget(QLabel("水印透明度"))
        watermark_form.addLayout(opacity_row)
        watermark_form.addWidget(self.watermark_tiled)
        layout.addLayout(watermark_form)
        self.watermark_opacity.editingFinished.connect(
            lambda: self._emit_watermark_property(
                "opacity", self.watermark_opacity.value() / 100
            )
        )
        self.watermark_opacity_smaller.clicked.connect(
            lambda: self._adjust_watermark_opacity(-1)
        )
        self.watermark_opacity_larger.clicked.connect(
            lambda: self._adjust_watermark_opacity(1)
        )
        self.watermark_tiled.toggled.connect(
            lambda value: self._emit_watermark_property("tiled", value)
        )
        actions = QHBoxLayout()
        self.move_up = QPushButton("上移")
        self.move_down = QPushButton("下移")
        self.duplicate_watermark = QPushButton("复制水印")
        self.delete_watermark = QPushButton("删除水印")
        self.move_up.clicked.connect(lambda: self._emit_move(-1))
        self.move_down.clicked.connect(lambda: self._emit_move(1))
        self.duplicate_watermark.clicked.connect(
            lambda: self._emit_watermark_action(False)
        )
        self.delete_watermark.clicked.connect(
            lambda: self._emit_watermark_action(True)
        )
        actions.addWidget(self.move_up)
        actions.addWidget(self.move_down)
        actions.addWidget(self.duplicate_watermark)
        actions.addWidget(self.delete_watermark)
        layout.addLayout(actions)
        layout.addWidget(self.empty_label)
        self._watermarks: dict[str, WatermarkLayer] = {}
        self._selected_watermark_id: str | None = None
        self._set_watermark_editor_enabled(False)
        self.set_layout(TextLayout(()))

    def set_layout(self, text_layout: TextLayout) -> None:
        self.set_composition(text_layout, (), 0)

    def set_composition(
        self,
        text_layout: TextLayout,
        watermarks: tuple[WatermarkLayer, ...],
        patch_count: int,
    ) -> None:
        self._watermarks = {
            item.watermark_id: item for item in watermarks
        }
        visibility = {
            str(self.tree.topLevelItem(index).data(0, Qt.ItemDataRole.UserRole)):
            self.tree.topLevelItem(index).checkState(0)
            for index in range(self.tree.topLevelItemCount())
        }
        self.tree.blockSignals(True)
        self.tree.clear()
        background = QTreeWidgetItem(("背景", "原图", "锁定"))
        background.setData(0, Qt.ItemDataRole.UserRole, "background")
        self.tree.addTopLevelItem(background)
        if patch_count:
            patch = QTreeWidgetItem(("修复补丁", f"{patch_count} 个", "锁定"))
            patch.setData(0, Qt.ItemDataRole.UserRole, "patches")
            self.tree.addTopLevelItem(patch)
        for layer in text_layout.layers:
            status = "溢出·保留原图" if layer.overflow else "正常"
            item = QTreeWidgetItem((layer.text, status))
            item.setData(0, Qt.ItemDataRole.UserRole, f"text:{layer.region_id}")
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                0,
                visibility.get(
                    f"text:{layer.region_id}",
                    Qt.CheckState.Checked if layer.visible else Qt.CheckState.Unchecked,
                ),
            )
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                2,
                Qt.CheckState.Checked if layer.locked else Qt.CheckState.Unchecked,
            )
            item.setToolTip(0, f"{layer.region_id}\n{layer.text}")
            self.tree.addTopLevelItem(item)
        for watermark in watermarks:
            label = watermark.text if watermark.kind == "text" else "图片水印"
            item = QTreeWidgetItem((label, "平铺" if watermark.tiled else "水印", ""))
            item.setData(
                0,
                Qt.ItemDataRole.UserRole,
                f"watermark:{watermark.watermark_id}",
            )
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                0,
                Qt.CheckState.Checked
                if watermark.visible
                else Qt.CheckState.Unchecked,
            )
            item.setCheckState(
                2,
                Qt.CheckState.Checked
                if watermark.locked
                else Qt.CheckState.Unchecked,
            )
            self.tree.addTopLevelItem(item)
        self.tree.blockSignals(False)
        has_layers = bool(text_layout.layers or watermarks or patch_count)
        self.tree.setVisible(True)
        self.empty_label.setVisible(not has_layers)
        if (
            self._selected_watermark_id is not None
            and self._selected_watermark_id in self._watermarks
        ):
            self.select_watermark(self._selected_watermark_id)
        elif self._selected_watermark_id is not None:
            self._selected_watermark_id = None
            self._set_watermark_editor_enabled(False)

    def select_region(self, region_id: str | None) -> None:
        self.tree.blockSignals(True)
        self.tree.clearSelection()
        if region_id:
            for index in range(self.tree.topLevelItemCount()):
                item = self.tree.topLevelItem(index)
                if item.data(0, Qt.ItemDataRole.UserRole) == f"text:{region_id}":
                    item.setSelected(True)
                    self.tree.scrollToItem(item)
                    break
        self.tree.blockSignals(False)

    def select_watermark(self, watermark_id: str) -> None:
        self.tree.blockSignals(True)
        self.tree.clearSelection()
        for index in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(index)
            if (
                item.data(0, Qt.ItemDataRole.UserRole)
                == f"watermark:{watermark_id}"
            ):
                item.setSelected(True)
                self.tree.scrollToItem(item)
                self._select_watermark(watermark_id)
                break
        self.tree.blockSignals(False)

    def is_layer_visible(self, region_id: str) -> bool:
        for index in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(index)
            if item.data(0, Qt.ItemDataRole.UserRole) == f"text:{region_id}":
                return item.checkState(0) is Qt.CheckState.Checked
        return True

    def _emit_selection(self) -> None:
        selected = self.tree.selectedItems()
        if selected:
            value = str(selected[0].data(0, Qt.ItemDataRole.UserRole))
            if value.startswith("text:"):
                self.layer_selected.emit(value.split(":", 1)[1])
            elif value.startswith("watermark:"):
                watermark_id = value.split(":", 1)[1]
                self._select_watermark(watermark_id)
                self.watermark_selected.emit(watermark_id)
            else:
                self._selected_watermark_id = None
                self._set_watermark_editor_enabled(False)

    def _emit_visibility(self, item: QTreeWidgetItem, column: int) -> None:
        value = str(item.data(0, Qt.ItemDataRole.UserRole))
        if ":" not in value:
            return
        kind, layer_id = value.split(":", 1)
        if column == 0:
            visible = item.checkState(0) is Qt.CheckState.Checked
            if kind == "text":
                self.layer_visibility_changed.emit(layer_id, visible)
            elif kind == "watermark":
                self.watermark_visibility_changed.emit(layer_id, visible)
        elif column == 2:
            locked = item.checkState(2) is Qt.CheckState.Checked
            if kind == "text":
                self.layer_lock_changed.emit(layer_id, locked)
            elif kind == "watermark":
                self.watermark_lock_changed.emit(layer_id, locked)

    def _emit_watermark_action(self, delete: bool) -> None:
        selected = self.tree.selectedItems()
        if not selected:
            return
        value = str(selected[0].data(0, Qt.ItemDataRole.UserRole))
        if not value.startswith("watermark:"):
            return
        watermark_id = value.split(":", 1)[1]
        if delete:
            self.watermark_delete_requested.emit(watermark_id)
        else:
            self.watermark_duplicate_requested.emit(watermark_id)

    def _emit_watermark_property(self, field: str, value: object) -> None:
        watermark_id = self._selected_watermark_id
        if watermark_id is None:
            return
        self.watermark_property_changed.emit(
            watermark_id,
            field,
            value,
        )

    def _select_watermark(self, watermark_id: str) -> None:
        self._selected_watermark_id = watermark_id
        watermark = self._watermarks.get(watermark_id)
        if watermark is None:
            self._set_watermark_editor_enabled(False)
            return
        controls = (
            self.watermark_text,
            self.watermark_font,
            self.watermark_font_size,
            self.watermark_font_smaller,
            self.watermark_font_larger,
            self.watermark_color,
            self.watermark_color_button,
            self.watermark_rotation,
            self.watermark_rotation_smaller,
            self.watermark_rotation_larger,
            self.watermark_width,
            self.watermark_width_smaller,
            self.watermark_width_larger,
            self.watermark_height,
            self.watermark_height_smaller,
            self.watermark_height_larger,
            self.watermark_opacity,
            self.watermark_opacity_smaller,
            self.watermark_opacity_larger,
            self.watermark_tiled,
        )
        for control in controls:
            control.blockSignals(True)
        self.watermark_text.setText(watermark.text)
        if watermark.style is not None:
            self.watermark_font.setCurrentFont(
                QFont(watermark.style.font_family)
            )
            self.watermark_font_size.setValue(watermark.style.font_size)
            self.watermark_color.setText(
                "#{:02X}{:02X}{:02X}".format(*watermark.style.fill_rgb)
            )
            self.watermark_color.setStyleSheet(
                f"border-left: 18px solid {self.watermark_color.text()};"
            )
        else:
            self.watermark_font_size.setValue(12)
            self.watermark_color.clear()
            self.watermark_color.setStyleSheet("")
        self.watermark_rotation.setValue(watermark.rotation_degrees)
        self.watermark_width.setValue(watermark.width)
        self.watermark_height.setValue(watermark.height)
        self.watermark_opacity.setValue(round(watermark.opacity * 100))
        self.watermark_tiled.setChecked(watermark.tiled)
        for control in controls:
            control.blockSignals(False)
        self._set_watermark_editor_enabled(True, watermark.kind == "text")

    def _set_watermark_editor_enabled(
        self,
        enabled: bool,
        text_watermark: bool = False,
    ) -> None:
        self.watermark_editor.setEnabled(enabled)
        for control in (
            self.watermark_text,
            self.watermark_font,
            self.watermark_font_size,
            self.watermark_font_smaller,
            self.watermark_font_larger,
            self.watermark_color,
            self.watermark_color_button,
        ):
            control.setEnabled(enabled and text_watermark)

    def _emit_watermark_text(self) -> None:
        watermark_id = self._selected_watermark_id
        text = self.watermark_text.text().strip()
        if watermark_id is None or not text:
            return
        self.watermark_property_changed.emit(
            watermark_id,
            "text",
            text,
        )

    def _emit_watermark_style(self, **changes: object) -> None:
        watermark_id = self._selected_watermark_id
        watermark = self._watermarks.get(watermark_id or "")
        if watermark_id is None or watermark is None or watermark.style is None:
            return
        self.watermark_property_changed.emit(
            watermark_id,
            "style",
            replace(watermark.style, **changes),
        )

    def _adjust_watermark_font_size(self, direction: int) -> None:
        value = max(
            self.watermark_font_size.minimum(),
            min(
                self.watermark_font_size.maximum(),
                self.watermark_font_size.value() + direction,
            ),
        )
        self.watermark_font_size.setValue(value)
        self._emit_watermark_style(font_size=value)

    def _adjust_watermark_rotation(self, direction: int) -> None:
        self.watermark_rotation.setValue(
            self.watermark_rotation.value() + direction
        )
        self._emit_watermark_property(
            "rotation_degrees", self.watermark_rotation.value()
        )

    def _adjust_watermark_size(
        self,
        control: QDoubleSpinBox,
        direction: int,
    ) -> None:
        control.setValue(control.value() + direction)
        self._emit_watermark_size()

    def _adjust_watermark_opacity(self, direction: int) -> None:
        self.watermark_opacity.setValue(
            self.watermark_opacity.value() + direction
        )
        self._emit_watermark_property(
            "opacity", self.watermark_opacity.value() / 100
        )

    def _preview_watermark_rotation(self) -> None:
        watermark_id = self._selected_watermark_id or ""
        watermark = self._watermarks.get(watermark_id)
        if watermark is None:
            return
        preview = replace(
            watermark,
            rotation_degrees=self.watermark_rotation.value(),
        )
        self._watermarks[watermark_id] = preview
        self.watermark_preview_changed.emit(preview)

    def _preview_watermark_size(self) -> None:
        watermark_id = self._selected_watermark_id or ""
        watermark = self._watermarks.get(watermark_id)
        if watermark is None:
            return
        preview = replace(
            watermark,
            width=self.watermark_width.value(),
            height=self.watermark_height.value(),
        )
        self._watermarks[watermark_id] = preview
        self.watermark_preview_changed.emit(preview)

    def _preview_watermark_font_size(self, font_size: float) -> None:
        watermark_id = self._selected_watermark_id or ""
        watermark = self._watermarks.get(watermark_id)
        if watermark is None or watermark.style is None:
            return
        scale = font_size / watermark.style.font_size
        preview = replace(
            watermark,
            width=watermark.width * scale,
            height=watermark.height * scale,
            style=replace(watermark.style, font_size=font_size),
        )
        self._watermarks[watermark_id] = preview
        self.watermark_preview_changed.emit(preview)

    def _emit_watermark_size(self) -> None:
        self._emit_watermark_property(
            "size",
            (self.watermark_width.value(), self.watermark_height.value()),
        )

    def _emit_watermark_color(self) -> None:
        value = QColor(self.watermark_color.text().strip())
        if not value.isValid():
            watermark = self._watermarks.get(
                self._selected_watermark_id or ""
            )
            if watermark is not None and watermark.style is not None:
                self.watermark_color.setText(
                    "#{:02X}{:02X}{:02X}".format(
                        *watermark.style.fill_rgb
                    )
                )
            return
        self._emit_watermark_style(
            fill_rgb=(value.red(), value.green(), value.blue())
        )

    def _choose_watermark_color(self) -> None:
        current = QColor(self.watermark_color.text().strip())
        if not current.isValid():
            current = QColor("#FFFFFF")
        selected = QColorDialog.getColor(current, self, "选择水印颜色")
        if not selected.isValid():
            return
        self.watermark_color.setText(selected.name(QColor.NameFormat.HexRgb).upper())
        self.watermark_color.setStyleSheet(
            f"border-left: 18px solid {selected.name()};"
        )
        self._emit_watermark_color()

    def _emit_move(self, offset: int) -> None:
        selected = self.tree.selectedItems()
        if not selected:
            return
        value = str(selected[0].data(0, Qt.ItemDataRole.UserRole))
        if ":" not in value:
            return
        kind, layer_id = value.split(":", 1)
        if kind in {"text", "watermark"}:
            self.layer_move_requested.emit(kind, layer_id, offset)


def _stepper_row(
    control: QDoubleSpinBox | QSpinBox,
    label: str,
    input_width: int = 112,
) -> tuple[QHBoxLayout, QToolButton, QToolButton]:
    control.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
    control.setMaximumWidth(input_width)
    smaller = QToolButton()
    smaller.setText("−")
    smaller.setToolTip(f"减小{label}")
    larger = QToolButton()
    larger.setText("+")
    larger.setToolTip(f"增大{label}")
    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(6)
    row.addWidget(control)
    row.addWidget(smaller)
    row.addWidget(larger)
    row.addStretch(1)
    return row, smaller, larger
