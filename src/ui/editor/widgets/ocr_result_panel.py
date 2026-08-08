"""左侧文字区域面板 — 显示 OCR 原文、译文与处理状态。

列：原文 | 译文 | 置信度 | 状态
低置信区域以淡黄色背景标记，待确认区域以琥珀色前景标记。
点击行 → 发射 region_selected 信号同步画布。
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from src.domain.ocr import OcrMode, OcrResult, TextRegion


class OcrResultPanel(QFrame):
    """文字识别结果列表面板。"""

    region_selected = Signal(str)  # region_id
    edit_region_requested = Signal(str)
    retranslate_requested = Signal(str)
    show_regions_changed = Signal(bool)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("ocrResultPanel")
        self.setMinimumWidth(256)
        self._rows: list[tuple[TextRegion, object | None]] = []
        self._result: OcrResult | None = None
        self._translation_result: object | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        title = QLabel("文字区域")
        title.setObjectName("propertyTitle")

        filters = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("搜索原文或译文")
        self.status_filter = QComboBox()
        self.status_filter.addItem("全部状态", "")
        for label, value in (
            ("已翻译", "translated"),
            ("待复核", "review_required"),
            ("已保护", "skipped_protected"),
            ("用户保留", "skipped_user"),
            ("保留原文", "skipped_language"),
            ("失败", "failed"),
            ("未处理", "unprocessed"),
        ):
            self.status_filter.addItem(label, value)
        self.search_edit.textChanged.connect(self._apply_filter)
        self.status_filter.currentIndexChanged.connect(self._apply_filter)
        filters.addWidget(self.search_edit, stretch=1)
        filters.addWidget(self.status_filter)
        self.show_regions = QCheckBox("显示区域框")
        self.show_regions.setChecked(True)
        self.show_regions.toggled.connect(self.show_regions_changed.emit)

        self.tree = QTreeWidget()
        self.tree.setObjectName("ocrResultTree")
        self.tree.setHeaderLabels(["原文", "译文", "置信度", "状态"])
        self.tree.setColumnWidth(0, 92)
        self.tree.setColumnWidth(1, 112)
        self.tree.setColumnWidth(2, 58)
        self.tree.setColumnWidth(3, 64)
        self.tree.setAlternatingRowColors(False)
        self.tree.setRootIsDecorated(False)
        self.tree.currentItemChanged.connect(self._on_selection)
        self.tree.setStyleSheet(
            "QTreeWidget#ocrResultTree {"
            "  background: #ffffff; color: #212733;"
            "  border: 1px solid #d5d9e0; border-radius: 6px;"
            "}"
            "QTreeWidget#ocrResultTree::item { padding: 2px; }"
            "QTreeWidget#ocrResultTree::item:selected {"
            "  background: #4a8af4;"
            "}"
            "QHeaderView::section {"
            "  background: #ffffff; color: #626b7a;"
            "  border: none; padding: 4px; font-size: 11px;"
            "}"
        )
        action_row = QHBoxLayout()
        self.edit_source_button = QPushButton("编辑 OCR 原文")
        self.edit_source_button.setEnabled(False)
        self.edit_source_button.clicked.connect(
            lambda: self._emit_selected(self.edit_region_requested)
        )
        self.retranslate_button = QPushButton("重新翻译选中区域")
        self.retranslate_button.setEnabled(False)
        self.retranslate_button.setToolTip(
            "仅重新翻译当前区域，不重新处理整张图片"
        )
        self.retranslate_button.clicked.connect(
            lambda: self._emit_selected(self.retranslate_requested)
        )
        action_row.addWidget(self.edit_source_button)
        action_row.addWidget(self.retranslate_button)

        self._empty_label = QLabel("尚未执行 OCR 识别")
        self._empty_label.setObjectName("propertyNoSelection")

        layout.addWidget(title)
        layout.addLayout(filters)
        layout.addWidget(self.show_regions)
        layout.addWidget(self.tree, stretch=1)
        layout.addLayout(action_row)
        layout.addWidget(self._empty_label)

        self._empty_label.setVisible(True)
        self.tree.setVisible(False)
        self.edit_source_button.setEnabled(False)
        self.retranslate_button.setEnabled(False)

    def set_result(
        self,
        result: OcrResult,
        translation_result: object | None = None,
    ) -> None:
        """填充文字识别结果列表。"""
        current = self.tree.currentItem()
        selected_region_id = (
            str(current.data(0, Qt.ItemDataRole.UserRole))
            if current is not None
            else None
        )
        self._result = result
        self._translation_result = translation_result
        units = {
            unit.region_id: unit
            for unit in getattr(translation_result, "units", ())
        }
        self._rows = [(region, units.get(region.region_id)) for region in result.regions]
        # QTreeWidget may implicitly select the first row while rebuilding.
        # Preserve the row being edited so OCR updates cannot jump the
        # property panel back to the first region.
        self.tree.blockSignals(True)
        try:
            self._rebuild_tree()
            selected_item = None
            if selected_region_id:
                for index in range(self.tree.topLevelItemCount()):
                    item = self.tree.topLevelItem(index)
                    if item.data(0, Qt.ItemDataRole.UserRole) == selected_region_id:
                        selected_item = item
                        break
            self.tree.setCurrentItem(selected_item)
        finally:
            self.tree.blockSignals(False)
        if selected_item is not None:
            self._on_selection(selected_item, None)

    def _rebuild_tree(self) -> None:
        self.tree.clear()
        if self._result is None:
            return
        query = self.search_edit.text().strip().casefold()
        wanted_status = str(self.status_filter.currentData() or "")
        result = self._result
        high_recall = result.mode is OcrMode.HIGH_RECALL
        for region, unit in self._rows:
            confidence_text = f"{region.confidence * 100:.1f}%"

            if unit is not None:
                translated_text = (
                    unit.translated_text
                    if unit.translated_text != region.text
                    else "—"
                )
                status_text, status_fg = _translation_status(unit.status.value)
            elif high_recall and region.enhanced_only and not region.auto_process_eligible:
                translated_text = "—"
                status_text = "待确认"
                status_fg = QColor("#e5b83c")
            elif region.enhanced_only:
                translated_text = "—"
                status_text = "增强已确认"
                status_fg = QColor("#15803d")
            elif region.status.value == "low_confidence":
                translated_text = "—"
                status_text = "低置信"
                status_fg = QColor("#dc2626")
            else:
                translated_text = "—"
                status_text = "标准"
                status_fg = QColor("#626b7a")
            status_value = (
                str(unit.status.value)
                if unit is not None
                else "unprocessed"
            )
            if wanted_status and status_value != wanted_status:
                continue
            if query and query not in region.text.casefold() and query not in translated_text.casefold():
                continue

            item = QTreeWidgetItem([
                region.text,
                translated_text,
                confidence_text,
                status_text,
            ])
            item.setData(0, Qt.ItemDataRole.UserRole, region.region_id)
            item.setToolTip(0, region.text)
            item.setToolTip(1, translated_text)
            item.setToolTip(2, f"{region.region_id}\n{_polygon_tooltip(region)}")
            item.setToolTip(
                3,
                _status_tooltip(
                    getattr(getattr(unit, "status", None), "value", ""),
                    region,
                ),
            )
            item.setForeground(3, QBrush(status_fg))

            if region.status.value == "low_confidence":
                low_bg = QBrush(QColor(61, 61, 32))
                for col in range(4):
                    item.setBackground(col, low_bg)

            self.tree.addTopLevelItem(item)

        visible_rows = self.tree.topLevelItemCount()
        self._empty_label.setText(
            "没有符合筛选条件的文字区域"
            if self._rows and not visible_rows
            else "尚未执行 OCR 识别"
        )
        self._empty_label.setVisible(not visible_rows)
        self.tree.setVisible(bool(visible_rows))

    def clear_result(self) -> None:
        self.tree.clear()
        self._rows.clear()
        self._result = None
        self._translation_result = None
        self.search_edit.clear()
        self.status_filter.setCurrentIndex(0)
        self._empty_label.setVisible(True)
        self.tree.setVisible(False)

    def _apply_filter(self, *_: object) -> None:
        if self._result is not None:
            self._rebuild_tree()

    def _on_selection(self, current: QTreeWidgetItem, previous: QTreeWidgetItem) -> None:
        del previous
        region_id = (
            str(current.data(0, Qt.ItemDataRole.UserRole))
            if current is not None
            else ""
        )
        self.edit_source_button.setEnabled(bool(region_id))
        status = self._status_for_region(region_id)
        self.retranslate_button.setEnabled(
            bool(region_id) and status != "skipped_protected"
        )
        if region_id:
            self.region_selected.emit(region_id)

    def select_region(self, region_id: str) -> None:
        """画布选中文字时，列表滚动定位并选中对应行（同步联动）。"""
        for index in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(index)
            if item.data(0, Qt.ItemDataRole.UserRole) == region_id:
                self.tree.setCurrentItem(item)
                self.tree.scrollToItem(
                    item, QAbstractItemView.ScrollHint.EnsureVisible
                )
                return

    def _emit_selected(self, signal: object) -> None:
        current = self.tree.currentItem()
        if current is None:
            return
        region_id = str(current.data(0, Qt.ItemDataRole.UserRole))
        if region_id:
            signal.emit(region_id)

    def _status_for_region(self, region_id: str) -> str:
        for region, unit in self._rows:
            if region.region_id == region_id and unit is not None:
                return str(unit.status.value)
        return ""


def _polygon_tooltip(region: TextRegion) -> str:
    pts = region.polygon
    return (
        f"左上 ({pts[0].x:.1f}, {pts[0].y:.1f})\n"
        f"右上 ({pts[1].x:.1f}, {pts[1].y:.1f})\n"
        f"右下 ({pts[2].x:.1f}, {pts[2].y:.1f})\n"
        f"左下 ({pts[3].x:.1f}, {pts[3].y:.1f})"
    )


def _translation_status(status: str) -> tuple[str, QColor]:
    return {
        "translated": ("已翻译", QColor("#15803d")),
        "review_required": ("待复核", QColor("#e5b83c")),
        "skipped_protected": ("已保护", QColor("#626b7a")),
        "skipped_user": ("用户保留", QColor("#626b7a")),
        "skipped_language": ("保留", QColor("#626b7a")),
        "failed": ("失败", QColor("#dc2626")),
    }.get(status, (status, QColor("#626b7a")))


def _status_tooltip(status: str, region: TextRegion) -> str:
    if status == "review_required":
        return (
            f"待复核：OCR 置信度 {region.confidence:.1%} 低于自动处理门槛，"
            "未自动翻译、擦除或渲染。"
        )
    if status == "skipped_protected":
        return "已按品牌、型号、SKU、网址或数字保护规则保留原图。"
    if status == "skipped_language":
        return "该区域不属于当前指定的源语言，已保留原图。"
    if status == "skipped_user":
        return "用户已确认保留原文，未擦除或渲染译文。"
    if status == "failed":
        return "处理失败，原图区域已安全保留。"
    if status == "translated":
        return "已完成翻译、背景修复和译文渲染。"
    return f"OCR 置信度：{region.confidence:.1%}"
