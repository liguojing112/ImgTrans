from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QLabel,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from src.domain.ocr import OcrResult, TextRegionStatus
from src.ui.languages import LANGUAGE_LABELS


class OcrPanel(QFrame):
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
        self.language_combo = QComboBox()
        self.language_combo.setObjectName("ocrLanguageCombo")
        for code in language_codes:
            label = LANGUAGE_LABELS.get(code, code)
            if code == "bn":
                label += "（模型待接入）"
            self.language_combo.addItem(label, code)
        layout.addWidget(self.language_combo)
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
        self.results.setColumnCount(3)
        self.results.setHeaderLabels(["原文", "置信度", "语言"])
        self.results.setRootIsDecorated(False)
        self.results.setAlternatingRowColors(True)
        self.results.header().setStretchLastSection(False)
        self.results.header().resizeSection(0, 150)
        self.results.header().resizeSection(1, 70)
        self.results.header().resizeSection(2, 65)
        layout.addWidget(self.results, stretch=1)

    @property
    def selected_language_code(self) -> str:
        return str(self.language_combo.currentData())

    def set_result(self, result: OcrResult) -> None:
        self.results.clear()
        for region in result.regions:
            confidence = f"{region.confidence * 100:.1f}%"
            item = QTreeWidgetItem([region.text, confidence, region.language_code])
            if region.status is TextRegionStatus.LOW_CONFIDENCE:
                item.setToolTip(0, "低置信度结果，请人工检查")
                item.setForeground(1, Qt.GlobalColor.darkYellow)
            self.results.addTopLevelItem(item)
        if result.regions:
            self.status_label.setText(
                f"识别到 {len(result.regions)} 个区域 · {result.elapsed_ms / 1000:.2f} 秒"
            )
        else:
            self.status_label.setText("没有识别到文字，可更换识别语言后重试")

    def clear_result(self) -> None:
        self.results.clear()
        self.status_label.setText("点击“识别文字”开始")
