from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from src.domain.batch import BatchItemSnapshot, BatchItemStatus, BatchSnapshot, BatchStatus
from src.domain.job import ImageStage


_STATUS_LABELS = {
    BatchItemStatus.QUEUED: "等待",
    BatchItemStatus.RUNNING: "处理中",
    BatchItemStatus.COMPLETED: "成功",
    BatchItemStatus.FAILED: "失败",
    BatchItemStatus.CANCELLED: "已取消",
}

_STAGE_LABELS = {
    ImageStage.OCR: "OCR",
    ImageStage.TRANSLATION: "翻译",
    ImageStage.INPAINTING: "修复",
    ImageStage.LAYOUT: "排版",
    ImageStage.RENDERING: "渲染",
}


class BatchPanel(QFrame):
    add_requested = Signal()
    clear_requested = Signal()
    start_requested = Signal()
    cancel_requested = Signal()
    export_requested = Signal()
    preview_requested = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("batchPanel")
        self._sources: list[Path] = []
        self._snapshot: BatchSnapshot | None = None
        self._known_completed: set[str] = set()
        self._interactive = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)
        title = QLabel("多图批量翻译")
        title.setObjectName("panelTitle")
        hint = QLabel(
            "使用 OCR/翻译页中的语言设置；图片按需加载，单张失败不停止批次。双击成功项可预览。"
        )
        hint.setObjectName("panelHint")
        hint.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(hint)

        source_actions = QHBoxLayout()
        self.add_button = QPushButton("添加图片")
        self.add_button.setObjectName("addBatchImagesButton")
        self.clear_button = QPushButton("清空")
        self.clear_button.setObjectName("clearBatchButton")
        self.add_button.clicked.connect(self.add_requested.emit)
        self.clear_button.clicked.connect(self.clear_requested.emit)
        source_actions.addWidget(self.add_button)
        source_actions.addWidget(self.clear_button)
        layout.addLayout(source_actions)

        self.items = QTreeWidget()
        self.items.setObjectName("batchItems")
        self.items.setColumnCount(4)
        self.items.setHeaderLabels(["导出 / 图片", "状态", "阶段", "错误"])
        self.items.setRootIsDecorated(False)
        self.items.setAlternatingRowColors(True)
        self.items.header().resizeSection(0, 170)
        self.items.header().resizeSection(1, 58)
        self.items.header().resizeSection(2, 54)
        self.items.itemDoubleClicked.connect(self._preview_item)
        self.items.itemChanged.connect(self._selection_changed)
        layout.addWidget(self.items, stretch=1)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        layout.addWidget(self.progress)
        self.status_label = QLabel("添加多张图片后开始批量翻译")
        self.status_label.setObjectName("batchStatusLabel")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        run_actions = QHBoxLayout()
        self.start_button = QPushButton("开始批量翻译")
        self.start_button.setObjectName("startBatchButton")
        self.cancel_button = QPushButton("取消批次")
        self.cancel_button.setObjectName("cancelBatchButton")
        self.start_button.clicked.connect(self.start_requested.emit)
        self.cancel_button.clicked.connect(self.cancel_requested.emit)
        self.cancel_button.setEnabled(False)
        run_actions.addWidget(self.start_button)
        run_actions.addWidget(self.cancel_button)
        layout.addLayout(run_actions)

        export_actions = QHBoxLayout()
        self.select_success_button = QPushButton("选择全部成功项")
        self.select_success_button.clicked.connect(self.select_all_successful)
        self.output_format = QComboBox()
        for label, suffix in (
            ("PNG", ".png"),
            ("JPG", ".jpg"),
            ("WebP", ".webp"),
            ("GIF（单帧）", ".gif"),
            ("TIFF（单页）", ".tiff"),
        ):
            self.output_format.addItem(label, suffix)
        self.export_button = QPushButton("导出勾选项")
        self.export_button.setObjectName("exportBatchButton")
        self.export_button.clicked.connect(self.export_requested.emit)
        export_actions.addWidget(self.select_success_button)
        export_actions.addWidget(self.output_format)
        export_actions.addWidget(self.export_button)
        layout.addLayout(export_actions)
        self.set_available(False, False)

    @property
    def sources(self) -> tuple[Path, ...]:
        return tuple(self._sources)

    @property
    def snapshot(self) -> BatchSnapshot | None:
        return self._snapshot

    @property
    def selected_result_ids(self) -> tuple[str, ...]:
        selected = []
        for index in range(self.items.topLevelItemCount()):
            item = self.items.topLevelItem(index)
            item_id = item.data(0, Qt.ItemDataRole.UserRole)
            if item_id and item.checkState(0) == Qt.CheckState.Checked:
                selected.append(str(item_id))
        return tuple(selected)

    @property
    def selected_output_suffix(self) -> str:
        return str(self.output_format.currentData())

    def add_sources(self, sources: tuple[Path, ...]) -> None:
        existing = {source.resolve() for source in self._sources}
        for source in sources:
            resolved = source.resolve()
            if resolved not in existing:
                self._sources.append(resolved)
                existing.add(resolved)
        self._snapshot = None
        self._known_completed.clear()
        self._render_sources()
        self.status_label.setText(f"已添加 {len(self._sources)} 张图片")

    def set_snapshot(self, snapshot: BatchSnapshot) -> None:
        checked = set(self.selected_result_ids)
        self._snapshot = snapshot
        self.items.clear()
        for batch_item in snapshot.items:
            row = self._snapshot_row(batch_item)
            self.items.addTopLevelItem(row)
            if batch_item.status is BatchItemStatus.COMPLETED:
                should_check = (
                    batch_item.item_id in checked
                    or batch_item.item_id not in self._known_completed
                )
                row.setCheckState(
                    0,
                    Qt.CheckState.Checked if should_check else Qt.CheckState.Unchecked,
                )
                self._known_completed.add(batch_item.item_id)
        self.progress.setValue(round(snapshot.progress * 100))
        self.status_label.setText(
            f"完成 {snapshot.completed_count} · 失败 {snapshot.failed_count} · "
            f"取消 {snapshot.cancelled_count} · 共 {len(snapshot.items)} 张"
        )

    def set_available(self, scheduler_available: bool, running: bool) -> None:
        self._interactive = scheduler_available and not running
        self.add_button.setEnabled(scheduler_available and not running)
        self.clear_button.setEnabled(bool(self._sources) and not running)
        self.start_button.setEnabled(
            scheduler_available and bool(self._sources) and not running
        )
        self.cancel_button.setEnabled(scheduler_available and running)
        has_success = self._snapshot is not None and self._snapshot.completed_count > 0
        self.select_success_button.setEnabled(has_success and not running)
        self.output_format.setEnabled(has_success and not running)
        self.export_button.setEnabled(
            scheduler_available
            and has_success
            and bool(self.selected_result_ids)
            and not running
        )

    def select_all_successful(self) -> None:
        if self._snapshot is None:
            return
        successful = {
            item.item_id
            for item in self._snapshot.items
            if item.status is BatchItemStatus.COMPLETED
        }
        for index in range(self.items.topLevelItemCount()):
            row = self.items.topLevelItem(index)
            if row.data(0, Qt.ItemDataRole.UserRole) in successful:
                row.setCheckState(0, Qt.CheckState.Checked)
        self.export_button.setEnabled(bool(successful))

    def clear_batch(self) -> None:
        self._sources.clear()
        self._snapshot = None
        self._known_completed.clear()
        self.items.clear()
        self.progress.setValue(0)
        self.status_label.setText("添加多张图片后开始批量翻译")

    def _render_sources(self) -> None:
        self.items.clear()
        for source in self._sources:
            self.items.addTopLevelItem(QTreeWidgetItem([source.name, "等待", "", ""]))
        self.progress.setValue(0)

    def _snapshot_row(self, item: BatchItemSnapshot) -> QTreeWidgetItem:
        row = QTreeWidgetItem(
            [
                item.source.name,
                _STATUS_LABELS[item.status],
                _STAGE_LABELS.get(item.current_stage, ""),
                item.error or "",
            ]
        )
        row.setData(0, Qt.ItemDataRole.UserRole, item.item_id)
        if item.status is BatchItemStatus.COMPLETED:
            row.setFlags(row.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            row.setCheckState(0, Qt.CheckState.Unchecked)
        return row

    def _preview_item(self, item: QTreeWidgetItem) -> None:
        item_id = item.data(0, Qt.ItemDataRole.UserRole)
        if not item_id or self._snapshot is None:
            return
        selected = next(
            (value for value in self._snapshot.items if value.item_id == item_id),
            None,
        )
        if selected is not None and selected.status is BatchItemStatus.COMPLETED:
            self.preview_requested.emit(str(item_id))

    def _selection_changed(self) -> None:
        finished = (
            self._snapshot is not None
            and self._snapshot.status is not BatchStatus.RUNNING
        )
        self.export_button.setEnabled(
            self._interactive and finished and bool(self.selected_result_ids)
        )
