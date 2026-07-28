from __future__ import annotations

from math import atan2, degrees, hypot

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.domain.layout import (
    CircularTextPath,
    PathPoint,
    TextBox,
    ensure_bottom_inward_circular_path,
)
from src.domain.manual_region import ManualInputMode, ManualRegionSpec


class ManualRegionPanel(QFrame):
    select_requested = Signal()
    process_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("manualRegionPanel")
        self._selection_box: TextBox | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)

        title = QLabel("手动补充翻译")
        title.setObjectName("panelTitle")
        hint = QLabel("在画布框选漏翻区域；擦除区域和译文区域可以独立调整。")
        hint.setObjectName("panelHint")
        hint.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(hint)

        self.mode_combo = QComboBox()
        self.mode_combo.setObjectName("manualInputMode")
        self.mode_combo.addItem("自动 OCR → 翻译", ManualInputMode.AUTO.value)
        self.mode_combo.addItem("直接输入原文并翻译", ManualInputMode.SOURCE_TEXT.value)
        self.mode_combo.addItem("直接输入最终译文", ManualInputMode.TRANSLATED_TEXT.value)
        self.mode_combo.currentIndexChanged.connect(self._mode_changed)
        layout.addWidget(self.mode_combo)

        self.select_button = QPushButton("在画布框选区域")
        self.select_button.setObjectName("selectManualRegionButton")
        self.select_button.clicked.connect(self.select_requested.emit)
        self.selection_label = QLabel("尚未框选")
        self.selection_label.setObjectName("manualSelectionLabel")
        layout.addWidget(self.select_button)
        layout.addWidget(self.selection_label)

        self.source_text = QPlainTextEdit()
        self.source_text.setObjectName("manualSourceText")
        self.source_text.setPlaceholderText("输入原文")
        self.source_text.setMaximumHeight(68)
        self.translated_text = QPlainTextEdit()
        self.translated_text.setObjectName("manualTranslatedText")
        self.translated_text.setPlaceholderText("输入最终译文")
        self.translated_text.setMaximumHeight(68)
        layout.addWidget(self.source_text)
        layout.addWidget(self.translated_text)

        self.erase_fields = _BoxFields(False)
        self.text_fields = _BoxFields(True)
        erase_form = QFormLayout()
        erase_form.addRow("擦除区域", self.erase_fields)
        text_form = QFormLayout()
        text_form.addRow("译文区域", self.text_fields)
        layout.addLayout(erase_form)
        layout.addLayout(text_form)

        self.circular_enabled = QCheckBox("沿圆环逐字排版")
        self.circular_enabled.setObjectName("manualCircularTextEnabled")
        self.circular_enabled.toggled.connect(self._circular_mode_changed)
        layout.addWidget(self.circular_enabled)
        self.circular_fields = QWidget()
        circular_form = QFormLayout(self.circular_fields)
        circular_form.setContentsMargins(0, 0, 0, 0)
        self.circle_center_x = _coordinate_spin("CircleCenterX")
        self.circle_center_y = _coordinate_spin("CircleCenterY")
        center_row = QWidget()
        center_layout = QGridLayout(center_row)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.addWidget(self.circle_center_x, 0, 0)
        center_layout.addWidget(self.circle_center_y, 0, 1)
        self.circle_radius = _coordinate_spin("CircleRadius")
        self.circle_start_angle = _angle_spin("manualCircleStartAngle")
        self.circle_end_angle = _angle_spin("manualCircleEndAngle")
        angles_row = QWidget()
        angles_layout = QGridLayout(angles_row)
        angles_layout.setContentsMargins(0, 0, 0, 0)
        angles_layout.addWidget(self.circle_start_angle, 0, 0)
        angles_layout.addWidget(self.circle_end_angle, 0, 1)
        self.circle_reverse = QCheckBox("反向排列")
        circular_form.addRow("圆心 X / Y", center_row)
        circular_form.addRow("半径", self.circle_radius)
        circular_form.addRow("起止角度", angles_row)
        circular_form.addRow("", self.circle_reverse)
        layout.addWidget(self.circular_fields)

        self.process_button = QPushButton("处理手动区域")
        self.process_button.setObjectName("processManualRegionButton")
        self.process_button.setEnabled(False)
        self.process_button.clicked.connect(self.process_requested.emit)
        self.status_label = QLabel("导入图片后可以框选漏翻区域")
        self.status_label.setObjectName("manualRegionStatus")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.process_button)
        layout.addWidget(self.status_label)
        layout.addStretch(1)
        self._mode_changed()
        self._circular_mode_changed(False)

    @property
    def has_selection(self) -> bool:
        return self._selection_box is not None

    @property
    def spec(self) -> ManualRegionSpec:
        if self._selection_box is None:
            raise ValueError("请先在画布框选区域")
        circular_path = (
            ensure_bottom_inward_circular_path(
                CircularTextPath(
                    PathPoint(
                        self.circle_center_x.value(),
                        self.circle_center_y.value(),
                    ),
                    self.circle_radius.value(),
                    self.circle_start_angle.value(),
                    self.circle_end_angle.value(),
                    self.circle_reverse.isChecked(),
                ),
            )
            if self.circular_enabled.isChecked()
            else None
        )
        return ManualRegionSpec(
            mode=ManualInputMode(self.mode_combo.currentData()),
            selection_box=self._selection_box,
            erase_box=self.erase_fields.box,
            text_box=self.text_fields.box,
            source_text=self.source_text.toPlainText(),
            translated_text=self.translated_text.toPlainText(),
            circular_path=circular_path,
        )

    def set_selection(self, box: TextBox) -> None:
        self._selection_box = box
        self.erase_fields.set_box(box)
        self.text_fields.set_box(box)
        self.selection_label.setText(
            f"已框选：{box.width:.0f} × {box.height:.0f} px"
        )
        self.status_label.setText("可调整擦除区域和译文区域，然后开始处理")

        if self.circle_radius.value() <= 0.01:
            self.set_circle_center(
                box.center_x,
                box.center_y + max(box.width, box.height),
            )
        else:
            self._fit_circle_angles(box)

    def set_circle_center(self, center_x: float, center_y: float) -> None:
        self.circle_center_x.setValue(center_x)
        self.circle_center_y.setValue(center_y)
        if self._selection_box is not None:
            self._fit_circle_angles(self._selection_box)

    def clear_selection(self) -> None:
        self._selection_box = None
        self.selection_label.setText("尚未框选")
        self.status_label.setText("导入图片后可以框选漏翻区域")

    def set_available(self, available: bool, busy: bool = False) -> None:
        self.select_button.setEnabled(available and not busy)
        self.process_button.setEnabled(
            available and not busy and self._selection_box is not None
        )

    def _mode_changed(self) -> None:
        mode = ManualInputMode(self.mode_combo.currentData())
        self.source_text.setVisible(mode is ManualInputMode.SOURCE_TEXT)
        self.translated_text.setVisible(mode is ManualInputMode.TRANSLATED_TEXT)

    def _circular_mode_changed(self, enabled: bool) -> None:
        self.circular_fields.setVisible(enabled)

    def _fit_circle_angles(self, box: TextBox) -> None:
        dx = box.center_x - self.circle_center_x.value()
        dy = box.center_y - self.circle_center_y.value()
        radius = hypot(dx, dy)
        if radius <= 0.01:
            return
        midpoint = degrees(atan2(dy, dx))
        half_span = min(75.0, max(1.0, degrees(box.width / (2 * radius))))
        self.circle_radius.setValue(radius)
        self.circle_start_angle.setValue(midpoint - half_span)
        self.circle_end_angle.setValue(midpoint + half_span)


class _BoxFields(QWidget):
    def __init__(self, allow_rotation: bool) -> None:
        super().__init__()
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(4)
        grid.setVerticalSpacing(3)
        self.center_x = _coordinate_spin("X")
        self.center_y = _coordinate_spin("Y")
        self.width = _coordinate_spin("宽")
        self.height = _coordinate_spin("高")
        self.rotation = QDoubleSpinBox()
        self.rotation.setRange(-180, 180)
        self.rotation.setSuffix("°")
        controls = (
            ("X", self.center_x),
            ("Y", self.center_y),
            ("宽", self.width),
            ("高", self.height),
        )
        for index, (label, control) in enumerate(controls):
            grid.addWidget(QLabel(label), index // 2, (index % 2) * 2)
            grid.addWidget(control, index // 2, (index % 2) * 2 + 1)
        if allow_rotation:
            grid.addWidget(QLabel("旋转"), 2, 0)
            grid.addWidget(self.rotation, 2, 1)
        else:
            self.rotation.hide()

    @property
    def box(self) -> TextBox:
        return TextBox(
            self.center_x.value(),
            self.center_y.value(),
            self.width.value(),
            self.height.value(),
            self.rotation.value(),
        )

    def set_box(self, box: TextBox) -> None:
        self.center_x.setValue(box.center_x)
        self.center_y.setValue(box.center_y)
        self.width.setValue(box.width)
        self.height.setValue(box.height)
        self.rotation.setValue(box.rotation_degrees)


def _coordinate_spin(name: str) -> QDoubleSpinBox:
    control = QDoubleSpinBox()
    control.setObjectName(f"manualBox{name}")
    control.setRange(0.01, 100000)
    control.setDecimals(1)
    control.setSuffix(" px")
    return control


def _angle_spin(name: str) -> QDoubleSpinBox:
    control = QDoubleSpinBox()
    control.setObjectName(name)
    control.setRange(-720, 720)
    control.setDecimals(1)
    control.setSuffix("°")
    return control
