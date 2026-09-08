from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QAbstractSpinBox,
)

from src.domain.batch import BatchItemSnapshot, BatchItemStatus, BatchSnapshot, BatchStatus
from src.domain.job import ImageStage
from src.domain.language import SUPPORTED_LANGUAGE_CODES
from src.domain.ocr import OcrMode
from src.ui.languages import LANGUAGE_LABELS


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


def _external_stepper(spin: QSpinBox) -> tuple[QHBoxLayout, QPushButton, QPushButton]:
    """Keep spinbox values editable while placing clear +/- controls outside."""
    spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
    spin.setMinimumWidth(120)
    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(6)
    minus = QPushButton("-")
    plus = QPushButton("+")
    for button in (minus, plus):
        button.setObjectName("batchStepperButton")
        button.setFixedSize(34, 30)
        button.setStyleSheet(
            "QPushButton { background: #eef0f4; color: #212733;"
            "  border: 1px solid #d5d9e0; border-radius: 4px; padding: 0; }"
            "QPushButton:hover { background: #e0e4ec; }"
            "QPushButton:pressed { background: #d5d9e0; }"
            "QPushButton:disabled { background: #eef0f4; color: #98a0ad;"
            "  border-color: #d5d9e0; }"
        )
    minus.clicked.connect(lambda: spin.setValue(spin.value() - spin.singleStep()))
    plus.clicked.connect(lambda: spin.setValue(spin.value() + spin.singleStep()))
    row.addWidget(spin, 1)
    row.addWidget(minus)
    row.addWidget(plus)
    return row, minus, plus


class BatchPanel(QFrame):
    add_requested = Signal()
    add_folder_requested = Signal()
    remove_requested = Signal()
    retry_failed_requested = Signal()
    clear_requested = Signal()
    start_requested = Signal()
    pause_requested = Signal()
    resume_requested = Signal()
    cancel_requested = Signal()
    export_requested = Signal()
    preview_requested = Signal(str)
    send_to_editor_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("batchPanel")
        self._sources: list[Path] = []
        self._snapshot: BatchSnapshot | None = None
        self._known_completed: set[str] = set()
        self._interactive = False
        self._scheduler_available = False
        self._running = False
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

        target_row = QHBoxLayout()
        target_row.addWidget(QLabel("目标语言"))
        self.target_language = QComboBox()
        self.target_language.setObjectName("batchTargetLanguage")
        self.target_language.setMinimumWidth(180)
        for code in SUPPORTED_LANGUAGE_CODES:
            self.target_language.addItem(
                f"{LANGUAGE_LABELS.get(code, code)} ({code})", code
            )
        target_index = self.target_language.findData("en")
        if target_index >= 0:
            self.target_language.setCurrentIndex(target_index)
        target_row.addWidget(self.target_language)
        target_row.addSpacing(18)
        target_row.addWidget(QLabel("OCR模式"))
        self.ocr_mode = QComboBox()
        self.ocr_mode.setObjectName("batchOcrMode")
        self.ocr_mode.addItem("标准 OCR", OcrMode.STANDARD.value)
        self.ocr_mode.addItem(
            "高召回 OCR（圆环/旋转文字）", OcrMode.HIGH_RECALL.value
        )
        target_row.addWidget(self.ocr_mode)
        target_row.addStretch(1)
        layout.addLayout(target_row)

        source_actions = QHBoxLayout()
        self.add_button = QPushButton("添加图片")
        self.add_button.setObjectName("addBatchImagesButton")
        self.add_folder_button = QPushButton("添加文件夹")
        self.remove_button = QPushButton("删除选中")
        self.clear_button = QPushButton("清空")
        self.clear_button.setObjectName("clearBatchButton")
        self.add_button.clicked.connect(self.add_requested.emit)
        self.add_folder_button.clicked.connect(self.add_folder_requested.emit)
        self.remove_button.clicked.connect(self.remove_requested.emit)
        self.clear_button.clicked.connect(self.clear_requested.emit)
        source_actions.addWidget(self.add_button)
        source_actions.addWidget(self.add_folder_button)
        source_actions.addWidget(self.remove_button)
        source_actions.addWidget(self.clear_button)
        layout.addLayout(source_actions)

        self.items = QTreeWidget()
        self.items.setObjectName("batchItems")
        self.items.setColumnCount(4)
        self.items.setHeaderLabels(["导出 / 图片", "状态", "阶段", "错误"])
        self.items.setRootIsDecorated(False)
        self.items.setAlternatingRowColors(True)
        self.items.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
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
        self.pause_button = QPushButton("暂停")
        self.pause_button.setObjectName("pauseBatchButton")
        self.pause_button.clicked.connect(self._toggle_pause)
        self.pause_button.setEnabled(False)
        self.retry_button = QPushButton("重试失败项")
        self.retry_button.clicked.connect(self.retry_failed_requested.emit)
        run_actions.addWidget(self.start_button)
        run_actions.addWidget(self.pause_button)
        run_actions.addWidget(self.cancel_button)
        run_actions.addWidget(self.retry_button)
        # 发送到工作台编辑
        self.send_to_editor_button = QPushButton("发送到工作台编辑")
        self.send_to_editor_button.setToolTip("将面板中的图片送入编辑器工作台，可逐张编辑（无需先翻译）")
        self.send_to_editor_button.clicked.connect(self.send_to_editor_requested.emit)
        run_actions.addWidget(self.send_to_editor_button)
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
            ("PDF", ".pdf"),
        ):
            self.output_format.addItem(label, suffix)
        self.export_button = QPushButton("导出勾选项")
        self.export_button.setObjectName("exportBatchButton")
        self.export_button.clicked.connect(self.export_requested.emit)
        self.export_now_button = QPushButton("导出")
        self.export_now_button.setObjectName("exportBatchNowButton")
        self.export_now_button.setToolTip("选择导出目录并导出当前勾选的成功图片")
        self.export_now_button.clicked.connect(self.export_requested.emit)
        export_actions.addWidget(self.select_success_button)
        export_actions.addWidget(self.output_format)
        export_actions.addWidget(self.export_button)
        export_actions.addWidget(self.export_now_button)
        layout.addLayout(export_actions)
        folder_options = QHBoxLayout()
        self.separate_subdirectory = QCheckBox("导出到独立子目录")
        self.separate_subdirectory.setChecked(True)
        self.subdirectory_name = QLineEdit()
        self.subdirectory_name.setPlaceholderText("留空则按当前批次自动命名")
        self.separate_subdirectory.toggled.connect(
            self.subdirectory_name.setEnabled
        )
        folder_options.addWidget(self.separate_subdirectory)
        folder_options.addWidget(self.subdirectory_name, stretch=1)
        layout.addLayout(folder_options)
        compression = QHBoxLayout()
        compression.addWidget(QLabel("压缩"))
        self.resize_mode = QComboBox()
        self.resize_mode.addItem("保持原尺寸", "original")
        self.resize_mode.addItem("按比例缩小", "percent")
        self.resize_mode.addItem("限制最长边", "max_edge")
        self.resize_value = QSpinBox()
        self.resize_value.setRange(10, 100)
        self.resize_value.setValue(100)
        self.resize_value.setSuffix("%")
        resize_stepper, self._resize_minus, self._resize_plus = _external_stepper(
            self.resize_value
        )
        self.resize_mode.currentIndexChanged.connect(
            self._sync_resize_control
        )
        self.quality = QSpinBox()
        self.quality.setRange(1, 100)
        self.quality.setValue(90)
        self.quality.setSuffix("%")
        quality_stepper, self._quality_minus, self._quality_plus = _external_stepper(
            self.quality
        )
        compression.addWidget(self.resize_mode)
        compression.addLayout(resize_stepper, 1)
        compression.addWidget(QLabel("质量"))
        compression.addLayout(quality_stepper, 1)
        layout.addLayout(compression)

        watermark = QHBoxLayout()
        self.watermark_enabled = QCheckBox("批量水印")
        self.watermark_kind = QComboBox()
        self.watermark_kind.addItem("文字", "text")
        self.watermark_kind.addItem("图片", "image")
        self.watermark_value = QLineEdit()
        self.watermark_value.setPlaceholderText("水印文字")
        self.watermark_image_button = QPushButton("选择图片")
        self.watermark_image_button.clicked.connect(
            self._choose_watermark_image
        )
        self.watermark_opacity = QSpinBox()
        self.watermark_opacity.setRange(1, 100)
        self.watermark_opacity.setValue(55)
        self.watermark_opacity.setSuffix("%")
        opacity_stepper, self._opacity_minus, self._opacity_plus = _external_stepper(
            self.watermark_opacity
        )
        self.watermark_tiled = QCheckBox("平铺")
        self.watermark_position = QComboBox()
        for label, value in (
            ("左上", "top_left"),
            ("上中", "top_center"),
            ("右上", "top_right"),
            ("左中", "middle_left"),
            ("居中", "center"),
            ("右中", "middle_right"),
            ("左下", "bottom_left"),
            ("下中", "bottom_center"),
            ("右下", "bottom_right"),
        ):
            self.watermark_position.addItem(label, value)
        self.watermark_position.setCurrentIndex(4)
        self.watermark_kind.currentIndexChanged.connect(
            self._sync_watermark_control
        )
        watermark.addWidget(self.watermark_enabled)
        watermark.addWidget(self.watermark_kind)
        watermark.addWidget(self.watermark_value, stretch=1)
        watermark.addWidget(self.watermark_image_button)
        watermark.addLayout(opacity_stepper)
        watermark.addWidget(self.watermark_tiled)
        watermark.addWidget(self.watermark_position)
        layout.addLayout(watermark)
        self._sync_resize_control()
        self._sync_watermark_control()
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

    @property
    def selected_target_language(self) -> str:
        return str(self.target_language.currentData() or "en")

    @property
    def selected_ocr_mode(self) -> OcrMode:
        return OcrMode(str(self.ocr_mode.currentData() or OcrMode.STANDARD.value))

    def set_target_language(self, language_code: str) -> None:
        index = self.target_language.findData(language_code)
        if index >= 0:
            self.target_language.setCurrentIndex(index)

    @property
    def batch_export_config(self) -> dict[str, object]:
        return {
            "quality": self.quality.value(),
            "resize_mode": str(self.resize_mode.currentData()),
            "resize_value": self.resize_value.value(),
            "watermark_enabled": self.watermark_enabled.isChecked(),
            "watermark_kind": str(self.watermark_kind.currentData()),
            "watermark_value": self.watermark_value.text().strip(),
            "watermark_opacity": self.watermark_opacity.value() / 100,
            "watermark_tiled": self.watermark_tiled.isChecked(),
            "watermark_position": str(self.watermark_position.currentData()),
            "separate_subdirectory": self.separate_subdirectory.isChecked(),
            "subdirectory_name": self.subdirectory_name.text().strip(),
        }

    @property
    def failed_sources(self) -> tuple[Path, ...]:
        if self._snapshot is None:
            return ()
        return tuple(
            item.source
            for item in self._snapshot.items
            if item.status is BatchItemStatus.FAILED
        )

    @property
    def succeeded_sources(self) -> tuple[Path, ...]:
        """返回勾选的成功项源文件（用于发送到工作台）。"""
        if self._snapshot is None:
            return ()
        selected = set(self.selected_result_ids)
        return tuple(
            item.source
            for item in self._snapshot.items
            if item.status is BatchItemStatus.COMPLETED
            and item.item_id in selected
        )

    @property
    def all_succeeded_sources(self) -> tuple[Path, ...]:
        """返回全部成功项源文件（不要求勾选）。"""
        if self._snapshot is None:
            return ()
        return tuple(
            item.source
            for item in self._snapshot.items
            if item.status is BatchItemStatus.COMPLETED
        )

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
        self.set_available(self._scheduler_available, self._running)

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
        paused = snapshot.status in {
            BatchStatus.PAUSING,
            BatchStatus.PAUSED,
        }
        self.pause_button.setText("恢复" if paused else "暂停")
        self.pause_button.setEnabled(
            snapshot.status
            in {BatchStatus.RUNNING, BatchStatus.PAUSING, BatchStatus.PAUSED}
        )
        self.status_label.setText(
            (
                "正在等待当前图片完成后暂停 · "
                if snapshot.status is BatchStatus.PAUSING
                else "批次已暂停 · "
                if snapshot.status is BatchStatus.PAUSED
                else ""
            )
            + f"完成 {snapshot.completed_count} · 失败 {snapshot.failed_count} · "
            + f"取消 {snapshot.cancelled_count} · 共 {len(snapshot.items)} 张"
        )

    def set_available(self, scheduler_available: bool, running: bool) -> None:
        self._scheduler_available = scheduler_available
        self._running = running
        self._interactive = scheduler_available and not running
        self.add_button.setEnabled(scheduler_available and not running)
        self.add_folder_button.setEnabled(scheduler_available and not running)
        self.remove_button.setEnabled(
            scheduler_available and bool(self._sources) and not running
        )
        self.clear_button.setEnabled(bool(self._sources) and not running)
        self.start_button.setEnabled(
            scheduler_available and bool(self._sources) and not running
        )
        self.cancel_button.setEnabled(scheduler_available and running)
        if not running:
            self.pause_button.setEnabled(False)
        self.retry_button.setEnabled(
            scheduler_available
            and not running
            and bool(self.failed_sources)
        )
        has_success = self._snapshot is not None and self._snapshot.completed_count > 0
        self.select_success_button.setEnabled(has_success and not running)
        self.output_format.setEnabled(has_success and not running)
        self.export_button.setEnabled(
            scheduler_available
            and has_success
            and bool(self.selected_result_ids)
            and not running
        )
        self.export_now_button.setEnabled(
            scheduler_available
            and has_success
            and bool(self.selected_result_ids)
            and not running
        )

    def set_error(self, message: str) -> None:
        self.pause_button.setEnabled(False)
        self.status_label.setText(f"批量处理未启动：{message}")

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
        self.export_now_button.setEnabled(bool(successful))

    def clear_batch(self) -> None:
        self._sources.clear()
        self._snapshot = None
        self._known_completed.clear()
        self.items.clear()
        self.progress.setValue(0)
        self.status_label.setText("添加多张图片后开始批量翻译")
        self.pause_button.setText("暂停")
        self.pause_button.setEnabled(False)
        self.set_available(self._scheduler_available, self._running)

    def _toggle_pause(self) -> None:
        if self._snapshot is not None and self._snapshot.status in {
            BatchStatus.PAUSING,
            BatchStatus.PAUSED,
        }:
            self.resume_requested.emit()
        else:
            self.pause_requested.emit()

    def _sync_resize_control(self) -> None:
        mode = str(self.resize_mode.currentData())
        self.resize_value.setEnabled(mode != "original")
        enabled = mode != "original"
        self._resize_minus.setEnabled(enabled)
        self._resize_plus.setEnabled(enabled)
        if mode == "percent":
            self.resize_value.setRange(10, 100)
            self.resize_value.setSuffix("%")
            self.resize_value.setValue(min(100, self.resize_value.value()))
        elif mode == "max_edge":
            previous_maximum = self.resize_value.maximum()
            self.resize_value.setRange(64, 16000)
            self.resize_value.setSuffix(" px")
            if previous_maximum <= 100 or self.resize_value.value() < 64:
                self.resize_value.setValue(1920)

    def _sync_watermark_control(self) -> None:
        is_image = str(self.watermark_kind.currentData()) == "image"
        self.watermark_image_button.setVisible(is_image)
        self.watermark_value.setPlaceholderText(
            "水印图片路径" if is_image else "水印文字"
        )

    def _choose_watermark_image(self) -> None:
        value, _ = QFileDialog.getOpenFileName(
            self,
            "选择水印图片",
            "",
            "图片 (*.png *.jpg *.jpeg *.webp *.bmp)",
        )
        if value:
            self.watermark_value.setText(value)

    def remove_selected_sources(self) -> None:
        if self._snapshot is not None:
            return
        selected = {
            Path(str(item.data(0, Qt.ItemDataRole.UserRole + 1))).resolve()
            for item in self.items.selectedItems()
            if item.data(0, Qt.ItemDataRole.UserRole + 1)
        }
        if not selected:
            return
        self._sources = [
            source for source in self._sources if source.resolve() not in selected
        ]
        self._render_sources()
        self.status_label.setText(f"已添加 {len(self._sources)} 张图片")
        self.set_available(self._scheduler_available, self._running)

    def replace_sources(self, sources: tuple[Path, ...]) -> None:
        self.clear_batch()
        self.add_sources(sources)

    def _render_sources(self) -> None:
        self.items.clear()
        for source in self._sources:
            item = QTreeWidgetItem([source.name, "等待", "", ""])
            item.setData(0, Qt.ItemDataRole.UserRole + 1, str(source))
            self.items.addTopLevelItem(item)
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
        self.export_now_button.setEnabled(
            self._interactive and finished and bool(self.selected_result_ids)
        )
