"""OCR 结果信息面板 — QTreeWidget 显示识别到的文字区域详情。

列：原文 | 置信度 | region_id | 状态
低置信区域以淡黄色背景标记。
点击行 → 发射 region_selected 信号同步画布。
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from src.domain.ocr import OcrMode, OcrResult, TextRegionStatus


class OcrResultPanel(QFrame):
    """OCR 结果列表面板。"""

    region_selected = Signal(str)  # region_id

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("ocrResultPanel")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        title = QLabel("OCR 结果")
        title.setObjectName("propertyTitle")

        self.tree = QTreeWidget()
        self.tree.setObjectName("ocrResultTree")
        self.tree.setHeaderLabels(["原文", "置信度", "区域", "状态"])
        self.tree.setColumnWidth(0, 100)
        self.tree.setColumnWidth(1, 60)
        self.tree.setColumnWidth(2, 80)
        self.tree.setColumnWidth(3, 80)
        self.tree.setAlternatingRowColors(False)
        self.tree.setRootIsDecorated(False)
        self.tree.currentItemChanged.connect(self._on_selection)
        self.tree.setStyleSheet(
            "QTreeWidget#ocrResultTree {"
            "  background: #2a2a3e; color: #e0e0f0;"
            "  border: 1px solid #3d3d5c; border-radius: 6px;"
            "}"
            "QTreeWidget#ocrResultTree::item { padding: 3px; }"
            "QTreeWidget#ocrResultTree::item:selected {"
            "  background: #3973db;"
            "}"
            "QHeaderView::section {"
            "  background: #232336; color: #9898b0;"
            "  border: none; padding: 4px; font-size: 11px;"
            "}"
        )

        self._empty_label = QLabel("尚未执行 OCR 识别")
        self._empty_label.setObjectName("propertyNoSelection")

        layout.addWidget(title)
        layout.addWidget(self.tree, stretch=1)
        layout.addWidget(self._empty_label)

        self._empty_label.setVisible(True)
        self.tree.setVisible(False)

    def set_result(self, result: OcrResult) -> None:
        """填充 OCR 结果列表。"""
        self.tree.clear()
        high_recall = result.mode is OcrMode.HIGH_RECALL
        for region in result.regions:
            confidence_text = f"{region.confidence * 100:.1f}%"
            short_id = region.region_id[-6:] if len(region.region_id) > 6 else region.region_id

            if high_recall and region.enhanced_only and not region.auto_process_eligible:
                status_text = "待确认"
                status_fg = QColor("#e5b83c")
            elif region.enhanced_only:
                status_text = "增强已确认"
                status_fg = QColor("#20a464")
            elif region.status is TextRegionStatus.LOW_CONFIDENCE:
                status_text = "低置信"
                status_fg = QColor("#e55353")
            else:
                status_text = "标准"
                status_fg = QColor("#9898b0")

            item = QTreeWidgetItem([region.text, confidence_text, short_id, status_text])
            item.setData(0, Qt.ItemDataRole.UserRole, region.region_id)
            item.setToolTip(0, region.text)
            item.setToolTip(2, region.region_id)
            item.setForeground(3, QBrush(status_fg))

            if region.status is TextRegionStatus.LOW_CONFIDENCE:
                item.setBackground(0, QBrush(QColor(61, 61, 32)))
                item.setBackground(1, QBrush(QColor(61, 61, 32)))
                item.setBackground(2, QBrush(QColor(61, 61, 32)))
                item.setBackground(3, QBrush(QColor(61, 61, 32)))

            self.tree.addTopLevelItem(item)

        self._empty_label.setVisible(False)
        self.tree.setVisible(True)

    def clear_result(self) -> None:
        self.tree.clear()
        self._empty_label.setVisible(True)
        self.tree.setVisible(False)

    def _on_selection(self, current: QTreeWidgetItem, previous: QTreeWidgetItem) -> None:
        if current is not None:
            region_id = str(current.data(0, Qt.ItemDataRole.UserRole))
            self.region_selected.emit(region_id)
