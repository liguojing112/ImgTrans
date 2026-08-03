from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from src.domain.image import ExportOptions


def _wrap_spin(spin: QSpinBox, width: int = 70, label: str = "") -> QWidget:
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


class ExportSettingsPanel(QFrame):
    export_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("exportSettingsPanel")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        title = QLabel("导出设置")
        title.setObjectName("propertyTitle")
        form = QFormLayout()
        self.format_combo = QComboBox()
        self.format_combo.addItem("PNG（推荐，保留透明通道）", ".png")
        self.format_combo.addItem("JPG", ".jpg")
        self.format_combo.addItem("WebP", ".webp")
        self.format_combo.addItem("GIF（静态单帧）", ".gif")
        self.format_combo.addItem("TIFF（单页）", ".tiff")
        self.format_combo.currentIndexChanged.connect(self._update_estimate)
        form.addRow("输出格式", self.format_combo)
        self.quality = QSpinBox()
        self.quality.setRange(1, 100)
        self.quality.setValue(95)
        self.quality.setSuffix("%")
        form.addRow("JPEG/WebP 质量", _wrap_spin(self.quality, label="质量"))
        self.preserve_alpha = QCheckBox("PNG/WebP 保留透明通道")
        self.preserve_alpha.setChecked(True)
        form.addRow("", self.preserve_alpha)
        self.background = QLineEdit("#FFFFFF")
        self.background.setMaxLength(7)
        form.addRow("非透明格式背景", self.background)
        self.output_width = QSpinBox()
        self.output_width.setRange(0, 30000)
        self.output_width.setSpecialValueText("原始")
        self.output_width.setSuffix(" px")
        self.output_height = QSpinBox()
        self.output_height.setRange(0, 30000)
        self.output_height.setSpecialValueText("原始")
        self.output_height.setSuffix(" px")
        form.addRow("输出宽度", _wrap_spin(self.output_width, width=90, label="输出宽度"))
        form.addRow("输出高度", _wrap_spin(self.output_height, width=90, label="输出高度"))
        self.estimated_size = QLabel("预计大小：导出时计算")
        self.estimated_size.setObjectName("propertyFieldLabel")
        self.quality.valueChanged.connect(self._update_estimate)
        self.output_width.valueChanged.connect(
            lambda value: self._sync_dimensions("width", value)
        )
        self.output_height.valueChanged.connect(
            lambda value: self._sync_dimensions("height", value)
        )

        note = QLabel("方向会自动校正；PNG、WebP 将尽量保留透明通道。")
        note.setObjectName("propertyFieldLabel")
        note.setWordWrap(True)

        self.export_button = QPushButton("导出图片")
        self.export_button.setObjectName("applyPropertyButton")
        self.export_button.setEnabled(False)
        self.export_button.clicked.connect(self.export_requested.emit)

        layout.addWidget(title)
        layout.addLayout(form)
        layout.addWidget(note)
        layout.addWidget(self.estimated_size)
        layout.addStretch()
        layout.addWidget(self.export_button)

    @property
    def selected_suffix(self) -> str:
        return str(self.format_combo.currentData())

    @property
    def options(self) -> ExportOptions:
        value = self.background.text().strip().lstrip("#")
        if len(value) != 6:
            value = "FFFFFF"
        try:
            background = tuple(
                int(value[index : index + 2], 16)
                for index in (0, 2, 4)
            )
        except ValueError:
            background = (255, 255, 255)
        return ExportOptions(
            self.quality.value(),
            self.preserve_alpha.isChecked(),
            background,
            self.output_width.value() or None,
            self.output_height.value() or None,
        )

    def set_export_enabled(self, enabled: bool) -> None:
        self.export_button.setEnabled(enabled)

    def set_source_size(self, width: int, height: int, has_alpha: bool) -> None:
        self._source_width = width
        self._source_height = height
        self._has_alpha = has_alpha
        self._update_estimate()

    def _update_estimate(self, *_: object) -> None:
        width = self.output_width.value() or getattr(self, "_source_width", 0)
        height = self.output_height.value() or getattr(self, "_source_height", 0)
        if not width or not height:
            self.estimated_size.setText("预计大小：导出时计算")
            return
        suffix = self.selected_suffix
        channels = 4 if getattr(self, "_has_alpha", False) else 3
        raw = width * height * channels
        ratio = {
            ".jpg": max(0.04, (105 - self.quality.value()) / 220),
            ".webp": max(0.03, (105 - self.quality.value()) / 260),
            ".png": 0.45,
            ".gif": 0.35,
            ".tiff": 0.55,
        }.get(suffix, 0.5)
        estimated = max(1024, round(raw * ratio))
        unit = (
            f"{estimated / 1024 / 1024:.1f} MiB"
            if estimated >= 1024 * 1024
            else f"{estimated / 1024:.0f} KiB"
        )
        self.estimated_size.setText(f"预计文件大小：约 {unit}（实际以导出为准）")

    def _sync_dimensions(self, changed: str, value: int) -> None:
        source_width = getattr(self, "_source_width", 0)
        source_height = getattr(self, "_source_height", 0)
        if not source_width or not source_height:
            self._update_estimate()
            return
        other = self.output_height if changed == "width" else self.output_width
        other.blockSignals(True)
        try:
            if value == 0:
                other.setValue(0)
            elif changed == "width":
                other.setValue(max(1, round(value * source_height / source_width)))
            else:
                other.setValue(max(1, round(value * source_width / source_height)))
        finally:
            other.blockSignals(False)
        self._update_estimate()
