"""工作台左侧图片列表面板 — 显示已加入工作台的图片，点击切换。"""

from __future__ import annotations

import time

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

# 同一张图的激活信号合并窗口：一次点击在部分平台上会连发 currentItemChanged
# 与 itemClicked（日志实测间隔约 190ms），强化翻译会当成两轮各传一次图。
_ACTIVATE_DEBOUNCE_S = 0.45


class ImageListPanel(QFrame):
    """左侧图片列表 — 工作台多文档切换。"""

    document_activated = Signal(str)  # doc_id
    remove_requested = Signal(str)  # doc_id

    def __init__(self) -> None:
        super().__init__()
        self.setProperty("editorStyle", True)
        self.setObjectName("imageListPanel")
        self.setMinimumWidth(150)
        self.setMaximumWidth(220)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        title = QLabel("图片列表")
        title.setStyleSheet("color: #212733; font-weight: 650;")
        layout.addWidget(title)

        self._remove_btn = QPushButton("删除选中")
        self._remove_btn.setEnabled(False)
        self._remove_btn.setToolTip("从工作台移除选中图片（不影响磁盘文件）")
        self._remove_btn.setStyleSheet(
            "QPushButton { background: #eef0f4; color: #212733;"
            "  border: 1px solid #d5d9e0; border-radius: 6px;"
            "  padding: 4px 10px; }"
            "QPushButton:disabled { color: #98a0ad; }"
            "QPushButton:hover { background: #e0e4ec; }"
        )
        self._remove_btn.clicked.connect(self._on_remove_clicked)
        layout.addWidget(self._remove_btn)

        self._list = QListWidget()
        self._list.setStyleSheet(
            "QListWidget { background: #e6e8ec; border: 1px solid #d5d9e0;"
            "  border-radius: 6px; color: #212733; }"
        )
        self._list.currentItemChanged.connect(self._on_current_changed)
        # 重复点击当前项不触发 currentItemChanged，单独补发（强化翻译需重传）
        self._list.itemPressed.connect(self._on_item_pressed)
        self._list.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self._list, stretch=1)

        self._count_label = QLabel("0 张图片")
        self._count_label.setStyleSheet("color: #98a0ad;")
        layout.addWidget(self._count_label)

        self._items: dict[str, QListWidgetItem] = {}
        self._doc_ids: list[str] = []
        self._current_doc_id: str | None = None
        self._pressed_was_current = False
        self._suppress_activation = False
        self._last_emit_doc_id: str | None = None
        self._last_emit_at = 0.0

    # —— 数据 ——

    def set_documents(self, documents: list) -> None:
        """documents: list[EditorDocumentRef]"""
        self._list.clear()
        self._items.clear()
        self._doc_ids = [d.doc_id for d in documents]
        for doc in documents:
            item = QListWidgetItem()
            item.setText(doc.name)
            item.setData(Qt.ItemDataRole.UserRole, doc.doc_id)
            item.setToolTip(str(doc.source_path))
            self._list.addItem(item)
            self._items[doc.doc_id] = item
        self._count_label.setText(f"{len(documents)} 张图片")
        self._remove_btn.setEnabled(False)
        self._last_emit_doc_id = None
        self._last_emit_at = 0.0

    def set_active(self, doc_id: str | None) -> None:
        """程序化同步高亮项，不发 document_activated。

        只更新选中外观：导入解析结果等非用户操作也会走到这里，若照常发信号，
        会被当成「点了左侧图片」而把刚导入的图重新上传给AI。
        """
        self._suppress_activation = True
        try:
            if doc_id is None:
                self._list.setCurrentRow(-1)
                return
            item = self._items.get(doc_id)
            if item is not None:
                self._list.setCurrentItem(item)
        finally:
            self._suppress_activation = False

    def set_active_name(self, name: str) -> None:
        """同步当前活动文档的显示名（如批量预览·xx）。"""
        item = self._list.currentItem()
        if item is not None:
            item.setText(name)

    # —— 槽 ——

    def _emit_activated(self, doc_id: str) -> None:
        """合并同文档的连发激活：窗口期内的第二次只保留第一次。"""
        now = time.monotonic()
        if doc_id == self._last_emit_doc_id and now - self._last_emit_at < _ACTIVATE_DEBOUNCE_S:
            return
        self._last_emit_doc_id = doc_id
        self._last_emit_at = now
        self.document_activated.emit(doc_id)

    def _on_current_changed(self, current, _previous) -> None:
        self._remove_btn.setEnabled(current is not None)
        if current is None:
            self._current_doc_id = None
            return
        doc_id = current.data(Qt.ItemDataRole.UserRole)
        if doc_id:
            self._current_doc_id = doc_id
            if not self._suppress_activation:
                self._emit_activated(doc_id)

    def _on_item_pressed(self, item) -> None:
        """记录按下前该项是否已是当前项，供点击时判断是否需要补发。"""
        self._pressed_was_current = (
            item.data(Qt.ItemDataRole.UserRole) == self._current_doc_id
        )

    def _on_item_clicked(self, item) -> None:
        """点击已激活项时 currentItemChanged 不触发，这里补发一次。"""
        if not self._pressed_was_current:
            return
        doc_id = item.data(Qt.ItemDataRole.UserRole)
        if doc_id:
            self._emit_activated(doc_id)

    def _on_remove_clicked(self) -> None:
        item = self._list.currentItem()
        if item is None:
            return
        doc_id = item.data(Qt.ItemDataRole.UserRole)
        if doc_id:
            self.remove_requested.emit(doc_id)
