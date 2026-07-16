from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from src.domain.layout import TextLayout


class TextEditPanel(QFrame):
    layer_selected = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("textEditPanel")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(9)
        title = QLabel("译文编辑")
        title.setObjectName("panelTitle")
        hint = QLabel("滚轮缩放，中键拖动画布；拖动文字框、右下手柄或顶部手柄可移动、缩放和旋转。")
        hint.setObjectName("panelHint")
        hint.setWordWrap(True)
        self.layers = QListWidget()
        self.layers.setObjectName("editableLayers")
        self.layers.currentRowChanged.connect(self._selection_changed)
        self.text = QPlainTextEdit()
        self.text.setObjectName("translatedTextEditor")
        self.text.setPlaceholderText("选择一个译文图层")
        self.text.setMaximumHeight(100)
        self.text.setEnabled(False)
        self.status_label = QLabel("完成一键翻译后可以编辑译文。")
        self.status_label.setObjectName("editStatusLabel")
        self.status_label.setWordWrap(True)
        self.apply_button = QPushButton("应用译文修改")
        self.apply_button.setObjectName("applyTextEditButton")
        self.apply_button.setEnabled(False)
        self.fit_view_button = QPushButton("适应画布")
        self.fit_view_button.setObjectName("fitCanvasButton")
        history = QHBoxLayout()
        self.undo_button = QPushButton("撤销")
        self.undo_button.setObjectName("undoEditButton")
        self.redo_button = QPushButton("重做")
        self.redo_button.setObjectName("redoEditButton")
        self.undo_button.setEnabled(False)
        self.redo_button.setEnabled(False)
        history.addWidget(self.undo_button)
        history.addWidget(self.redo_button)
        layout.addWidget(title)
        layout.addWidget(hint)
        layout.addWidget(self.layers, stretch=1)
        layout.addWidget(self.text)
        layout.addWidget(self.status_label)
        layout.addWidget(self.apply_button)
        layout.addWidget(self.fit_view_button)
        layout.addLayout(history)

    @property
    def selected_region_id(self) -> str | None:
        item = self.layers.currentItem()
        return str(item.data(Qt.ItemDataRole.UserRole)) if item is not None else None

    def set_layout(
        self,
        text_layout: TextLayout,
        can_undo: bool = False,
        can_redo: bool = False,
        selected_region_id: str | None = None,
    ) -> None:
        selected_region_id = selected_region_id or self.selected_region_id
        self.layers.clear()
        selected_row = 0
        for index, layer in enumerate(text_layout.layers):
            marker = " ⚠ 溢出" if layer.overflow else ""
            item = QListWidgetItem(f"{index + 1}. {layer.text}{marker}")
            item.setData(Qt.ItemDataRole.UserRole, layer.region_id)
            item.setData(Qt.ItemDataRole.UserRole + 1, layer.text)
            item.setToolTip(layer.text)
            self.layers.addItem(item)
            if layer.region_id == selected_region_id:
                selected_row = index
        if text_layout.layers:
            self.layers.setCurrentRow(selected_row)
        else:
            self.text.clear()
            self.text.setEnabled(False)
        self.set_history(can_undo, can_redo)

    def set_history(self, can_undo: bool, can_redo: bool) -> None:
        self.undo_button.setEnabled(can_undo)
        self.redo_button.setEnabled(can_redo)

    def set_edit_completed(self, overflow: bool) -> None:
        self.status_label.setText(
            "译文已修改，但当前文字框无法容纳全部内容。"
            if overflow
            else "译文已重新排版并渲染。"
        )

    def select_region(self, region_id: str) -> None:
        for row in range(self.layers.count()):
            item = self.layers.item(row)
            if str(item.data(Qt.ItemDataRole.UserRole)) == region_id:
                if self.layers.currentRow() != row:
                    self.layers.setCurrentRow(row)
                return

    def clear_result(self) -> None:
        self.layers.clear()
        self.text.clear()
        self.text.setEnabled(False)
        self.apply_button.setEnabled(False)
        self.set_history(False, False)
        self.status_label.setText("完成一键翻译后可以编辑译文。")

    def _selection_changed(self) -> None:
        item = self.layers.currentItem()
        if item is None:
            self.text.clear()
            self.text.setEnabled(False)
            self.apply_button.setEnabled(False)
            return
        self.text.setPlainText(str(item.data(Qt.ItemDataRole.UserRole + 1)))
        self.text.setEnabled(True)
        self.apply_button.setEnabled(True)
        self.layer_selected.emit(str(item.data(Qt.ItemDataRole.UserRole)))
