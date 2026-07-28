from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFrame,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.domain.ocr import (
    HighRecallOcrOptions,
    OcrMode,
    OcrResult,
    Point,
    RingBand,
    TextRegionStatus,
)
from src.ui.languages import LANGUAGE_LABELS


class OcrPanel(QFrame):
    center_pick_requested = Signal()
    region_confirmation_requested = Signal(str, str)

    def __init__(self, language_codes: tuple[str, ...]) -> None:
        super().__init__()
        self.setObjectName("ocrPanel")
        self.setMinimumWidth(300)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        title = QLabel("文字识别")
        title.setObjectName("panelTitle")
        layout.addWidget(title)
        hint = QLabel("选择与图片主要文字匹配的识别模型")
        hint.setObjectName("panelHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.mode_combo = QComboBox()
        self.mode_combo.setObjectName("ocrModeCombo")
        self.mode_combo.addItem("标准 OCR", OcrMode.STANDARD.value)
        self.mode_combo.addItem("高召回 OCR（圆环/旋转文字）", OcrMode.HIGH_RECALL.value)
        layout.addWidget(self.mode_combo)
        self.language_combo = QComboBox()
        self.language_combo.setObjectName("ocrLanguageCombo")
        for code in language_codes:
            label = LANGUAGE_LABELS.get(code, code)
            if code == "bn":
                label += "（模型待接入）"
            self.language_combo.addItem(label, code)
        layout.addWidget(self.language_combo)
        self.high_recall_controls = QFrame()
        controls = QFormLayout(self.high_recall_controls)
        controls.setContentsMargins(0, 0, 0, 0)
        center_row = QWidget()
        center_layout = QHBoxLayout(center_row)
        center_layout.setContentsMargins(0, 0, 0, 0)
        self.center_x = _coordinate_spinbox("ocrCenterX")
        self.center_y = _coordinate_spinbox("ocrCenterY")
        self.pick_center_button = QPushButton("在画布点击圆心")
        self.pick_center_button.setObjectName("pickOcrCenterButton")
        self.pick_center_button.clicked.connect(self.center_pick_requested)
        center_layout.addWidget(self.center_x)
        center_layout.addWidget(self.center_y)
        center_layout.addWidget(self.pick_center_button)
        controls.addRow("圆心 X / Y", center_row)
        radius_row = QWidget()
        radius_layout = QHBoxLayout(radius_row)
        radius_layout.setContentsMargins(0, 0, 0, 0)
        self.inner_radius = _radius_spinbox("ocrInnerRadius")
        self.outer_radius = _radius_spinbox("ocrOuterRadius")
        radius_layout.addWidget(self.inner_radius)
        radius_layout.addWidget(self.outer_radius)
        controls.addRow("内 / 外半径", radius_row)
        self.preview_strips_button = QPushButton("查看展开环带")
        self.preview_strips_button.setObjectName("previewOcrStripsButton")
        self.preview_strips_button.setEnabled(False)
        self.preview_strips_button.clicked.connect(
            lambda _checked=False: self.show_preview_strips()
        )
        controls.addRow(self.preview_strips_button)
        layout.addWidget(self.high_recall_controls)
        self.mode_combo.currentIndexChanged.connect(self._mode_changed)
        self._mode_changed()
        self.recognize_button = QPushButton("识别文字")
        self.recognize_button.setObjectName("recognizeButton")
        self.recognize_button.setEnabled(False)
        layout.addWidget(self.recognize_button)
        self.status_label = QLabel("导入图片后可以开始识别")
        self.status_label.setObjectName("ocrStatusLabel")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        self.results = QTreeWidget()
        self.results.setObjectName("ocrResults")
        self.results.setColumnCount(4)
        self.results.setHeaderLabels(["原文", "置信度", "语言", "状态"])
        self.results.setRootIsDecorated(False)
        self.results.setAlternatingRowColors(True)
        self.results.header().setStretchLastSection(False)
        self.results.header().resizeSection(0, 150)
        self.results.header().resizeSection(1, 70)
        self.results.header().resizeSection(2, 65)
        self.results.header().resizeSection(3, 80)
        layout.addWidget(self.results, stretch=1)
        self.confirm_button = QPushButton("确认选中识别结果")
        self.confirm_button.setObjectName("confirmOcrRegionButton")
        self.confirm_button.setEnabled(False)
        self.confirm_button.clicked.connect(self._confirm_selected_region)
        self.results.itemSelectionChanged.connect(
            lambda: self.confirm_button.setEnabled(
                bool(self.results.selectedItems())
                and bool(
                    self.results.selectedItems()[0].data(
                        0,
                        Qt.ItemDataRole.UserRole,
                    )
                )
            )
        )
        layout.addWidget(self.confirm_button)
        self._result: OcrResult | None = None

    @property
    def selected_language_code(self) -> str:
        return str(self.language_combo.currentData())

    @property
    def selected_mode(self) -> OcrMode:
        return OcrMode(str(self.mode_combo.currentData()))

    @property
    def high_recall_options(self) -> HighRecallOcrOptions:
        center = (
            Point(self.center_x.value(), self.center_y.value())
            if self.center_x.value() >= 0 and self.center_y.value() >= 0
            else None
        )
        bands = (
            (RingBand(self.inner_radius.value(), self.outer_radius.value()),)
            if self.outer_radius.value() > self.inner_radius.value()
            else ()
        )
        return HighRecallOcrOptions(center=center, ring_bands=bands)

    def set_image_geometry(self, width: int, height: int) -> None:
        self.center_x.setMaximum(float(width))
        self.center_y.setMaximum(float(height))
        maximum_radius = float(max(width, height))
        self.inner_radius.setMaximum(maximum_radius)
        self.outer_radius.setMaximum(maximum_radius)

    def set_center(self, point: Point) -> None:
        self.center_x.setValue(point.x)
        self.center_y.setValue(point.y)

    def set_result(self, result: OcrResult) -> None:
        self._result = result
        self.results.clear()
        for region in result.regions:
            confidence = f"{region.confidence * 100:.1f}%"
            requires_review = (
                result.mode is OcrMode.HIGH_RECALL
                and region.enhanced_only
                and not region.auto_process_eligible
            )
            state = (
                "待确认"
                if requires_review
                else ("增强已确认" if region.enhanced_only else "标准")
            )
            item = QTreeWidgetItem(
                [region.text, confidence, region.language_code, state]
            )
            if result.mode is OcrMode.HIGH_RECALL:
                item.setData(0, Qt.ItemDataRole.UserRole, region.region_id)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
                item.setToolTip(
                    0,
                    "高召回 OCR 候选；修改文字后点击“确认选中识别结果”才允许后续自动处理。",
                )
            if region.status is TextRegionStatus.LOW_CONFIDENCE:
                item.setToolTip(0, "低置信度结果，请人工检查")
                item.setForeground(1, Qt.GlobalColor.darkYellow)
            if requires_review:
                item.setForeground(3, Qt.GlobalColor.darkYellow)
            self.results.addTopLevelItem(item)
        self.preview_strips_button.setEnabled(bool(result.preview_strips))
        if result.regions:
            self.status_label.setText(
                f"识别到 {len(result.regions)} 个区域 · {result.elapsed_ms / 1000:.2f} 秒"
            )
        else:
            self.status_label.setText("没有识别到文字，可更换识别语言后重试")

    def clear_result(self) -> None:
        self._result = None
        self.results.clear()
        self.preview_strips_button.setEnabled(False)
        self.confirm_button.setEnabled(False)
        self.status_label.setText("点击“识别文字”开始")

    def show_preview_strips(self, result: OcrResult | None = None) -> None:
        value = result or self._result
        if value is None or not value.preview_strips:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("高召回 OCR 环带展开预览")
        dialog.resize(900, 500)
        tabs = QTabWidget(dialog)
        for strip in value.preview_strips:
            image = QImage(
                strip.pixels,
                strip.width,
                strip.height,
                strip.width * 3,
                QImage.Format.Format_RGB888,
            ).copy()
            label = QLabel()
            label.setPixmap(QPixmap.fromImage(image))
            scroll = QScrollArea()
            scroll.setWidget(label)
            scroll.setWidgetResizable(False)
            tabs.addTab(scroll, strip.name)
        dialog_layout = QVBoxLayout(dialog)
        dialog_layout.addWidget(tabs)
        dialog.exec()

    def _mode_changed(self) -> None:
        self.high_recall_controls.setVisible(
            self.selected_mode is OcrMode.HIGH_RECALL
        )

    def _confirm_selected_region(self) -> None:
        selected = self.results.selectedItems()
        if not selected:
            return
        item = selected[0]
        region_id = item.data(0, Qt.ItemDataRole.UserRole)
        text = item.text(0).strip()
        if region_id and text:
            self.region_confirmation_requested.emit(str(region_id), text)


def _coordinate_spinbox(name: str) -> QDoubleSpinBox:
    spinbox = QDoubleSpinBox()
    spinbox.setObjectName(name)
    spinbox.setRange(-1, 100000)
    spinbox.setDecimals(1)
    spinbox.setValue(-1)
    spinbox.setSpecialValueText("自动")
    return spinbox


def _radius_spinbox(name: str) -> QDoubleSpinBox:
    spinbox = QDoubleSpinBox()
    spinbox.setObjectName(name)
    spinbox.setRange(0, 100000)
    spinbox.setDecimals(1)
    spinbox.setValue(0)
    spinbox.setSpecialValueText("自动")
    return spinbox
