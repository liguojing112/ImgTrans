"""自定义取色对话框 — RGB 数值框外置 ± 按钮，替代系统 QColorDialog。

系统 QColorDialog 的色值调节依赖输入框内的原生上下箭头，和软件其它面板
「输入框 + 外置 −/+」的交互不一致；这里用同一套控件重做，并提供常用色板
和一键十六进制输入。
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from src.ui.common import wrap_spin

# 常用色板：黑、白、红、橙、黄、绿、蓝、紫
_PRESET_RGBS = (
    (0, 0, 0),
    (255, 255, 255),
    (220, 30, 30),
    (255, 140, 0),
    (255, 215, 0),
    (34, 139, 34),
    (0, 122, 204),
    (120, 60, 200),
)


class ColorPickerDialog(QDialog):
    """RGB 取色对话框：外置 ± 按钮调数值，色板快捷选色，支持十六进制输入。"""

    def __init__(
        self,
        current_rgb: tuple[int, int, int] = (0, 0, 0),
        title: str = "选择颜色",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(320)
        self._rgb = tuple(int(value) for value in current_rgb)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        self._preview = QLabel()
        self._preview.setFixedHeight(40)
        layout.addWidget(self._preview)

        swatch_row = QHBoxLayout()
        swatch_row.setSpacing(6)
        self._swatches: list[QPushButton] = []
        for rgb in _PRESET_RGBS:
            swatch = QPushButton()
            swatch.setFixedSize(24, 24)
            swatch.setCursor(Qt.CursorShape.PointingHandCursor)
            swatch.setToolTip("#{:02X}{:02X}{:02X}".format(*rgb))
            swatch.setStyleSheet(
                f"background: rgb{rgb};"
                "border: 1px solid #8a93a5; border-radius: 4px;"
            )
            swatch.clicked.connect(lambda _checked=False, value=rgb: self._set_rgb(value))
            swatch_row.addWidget(swatch)
            self._swatches.append(swatch)
        swatch_row.addStretch()
        layout.addLayout(swatch_row)

        self._spins: list[QSpinBox] = []
        for label, index in (("红 (R)", 0), ("绿 (G)", 1), ("蓝 (B)", 2)):
            name = QLabel(label)
            name.setMinimumWidth(52)
            spin = QSpinBox()
            spin.setRange(0, 255)
            spin.setValue(self._rgb[index])
            spin.valueChanged.connect(self._on_spin_changed)
            row = QHBoxLayout()
            row.setSpacing(8)
            row.addWidget(name)
            row.addWidget(wrap_spin(spin, width=88, label=label))
            row.addStretch()
            layout.addLayout(row)
            self._spins.append(spin)

        hex_name = QLabel("色值")
        hex_name.setMinimumWidth(52)
        self._hex_edit = QLineEdit()
        self._hex_edit.setPlaceholderText("#RRGGBB")
        self._hex_edit.setMaxLength(7)
        self._hex_edit.textEdited.connect(self._on_hex_edited)
        hex_row = QHBoxLayout()
        hex_row.setSpacing(8)
        hex_row.addWidget(hex_name)
        hex_row.addWidget(self._hex_edit, 1)
        layout.addLayout(hex_row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("确定")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._refresh_preview()

    def selected_rgb(self) -> tuple[int, int, int]:
        return self._rgb

    # —— 内部联动 ——

    def _set_rgb(self, rgb: tuple[int, int, int]) -> None:
        for spin, value in zip(self._spins, rgb):
            spin.blockSignals(True)
            spin.setValue(int(value))
            spin.blockSignals(False)
        self._rgb = tuple(int(value) for value in rgb)
        self._refresh_preview()

    def _on_spin_changed(self, _value: int) -> None:
        self._rgb = tuple(spin.value() for spin in self._spins)
        self._refresh_preview()

    def _on_hex_edited(self, text: str) -> None:
        value = text.strip()
        if len(value) == 6:
            value = "#" + value
        color = QColor(value)
        if not color.isValid():
            return
        self._set_rgb((color.red(), color.green(), color.blue()))

    def _refresh_preview(self) -> None:
        red, green, blue = self._rgb
        self._preview.setStyleSheet(
            f"background: rgb({red}, {green}, {blue});"
            "border: 1px solid #8a93a5; border-radius: 6px;"
        )
        hex_text = "#{:02X}{:02X}{:02X}".format(red, green, blue)
        if self._hex_edit.text().upper() != hex_text:
            self._hex_edit.setText(hex_text)


def pick_color(
    parent,
    current_rgb: tuple[int, int, int],
    title: str = "选择颜色",
) -> tuple[int, int, int] | None:
    """弹出取色对话框；取消时返回 None。"""
    dialog = ColorPickerDialog(tuple(current_rgb), title, parent)
    if dialog.exec() == QDialog.DialogCode.Accepted:
        return dialog.selected_rgb()
    return None
