"""文案内容编辑器组件 — 标签、场景词、标题、卖点的可编辑列表。"""

from __future__ import annotations

import uuid

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.domain.copywriting import (
    ImageTag,
    LongTailKeyword,
    ProductTitle,
    SellingPoint,
)

_CATEGORY_LABELS = {
    "core": "核心", "function": "功能", "scene": "场景",
    "material": "材质", "packaging": "包装",
}


class TagEditor(QFrame):
    """图片标签编辑器 — 逐条编辑、删除、复制。"""

    item_edited = Signal(str, str)  # id, new_text
    item_deleted = Signal(str)
    item_copied = Signal(str)
    regenerate_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setProperty("editorStyle", True)
        self._items: dict[str, ImageTag] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        copy_all = QPushButton("复制全部")
        copy_all.setStyleSheet(
            "QPushButton { background: #eef0f4; color: #212733; border: 1px solid #d5d9e0; border-radius: 4px; padding: 3px 8px; }"
            "QPushButton:hover { background: #e0e4ec; }"
        )

        copy_all.clicked.connect(self._copy_all)
        regen = QPushButton("重新生成")
        regen.setStyleSheet(
            "QPushButton { background: #eef0f4; color: #212733; border: 1px solid #d5d9e0; border-radius: 4px; padding: 3px 8px; }"
            "QPushButton:hover { background: #e0e4ec; }"
        )

        regen.clicked.connect(self.regenerate_requested.emit)
        btn_row.addWidget(copy_all)
        btn_row.addWidget(regen)
        layout.addLayout(btn_row)

        hint = QLabel("尚未生成，请先生成文案")
        hint.setObjectName("emptyHint")
        hint.setStyleSheet("color: #98a0ad; padding: 8px;")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self._empty_hint = hint

        self._list = QListWidget()
        self._list.itemDoubleClicked.connect(self._on_double_click)
        layout.addWidget(self._list, stretch=1)
        self._update_empty_hint()  # 初始化时更新 hint 可见性

    def _update_empty_hint(self) -> None:
        if hasattr(self, '_empty_hint'):
            visible = self._list.count() == 0
            self._empty_hint.setVisible(visible)

    def set_tags(self, tags: list[ImageTag]) -> None:
        self._list.clear()
        self._items.clear()
        for tag in tags:
            self._items[tag.id] = tag
            self._add_row(tag)
        self._update_empty_hint()

    def _add_row(self, tag: ImageTag) -> None:
        widget = QWidget()
        row = QHBoxLayout(widget)
        row.setContentsMargins(4, 2, 4, 2)
        row.setSpacing(6)

        edit = QLineEdit(tag.tag)
        edit.setStyleSheet(
            "QLineEdit { background: transparent; border: 1px solid #d5d9e0;"
            "  color: #212733; padding: 2px 6px; border-radius: 4px; }"
        )
        edit.textChanged.connect(lambda t, tid=tag.id: self.item_edited.emit(tid, t))
        row.addWidget(edit, stretch=1)

        copy_btn = QPushButton("复制")
        copy_btn.setStyleSheet(
            "QPushButton { background: #eef0f4; color: #212733; border: 1px solid #d5d9e0; border-radius: 4px; padding: 3px 8px; }"
            "QPushButton:hover { background: #e0e4ec; }"
        )

        copy_btn.setFixedSize(48, 24)
        copy_btn.clicked.connect(lambda: self.item_copied.emit(tag.id))
        del_btn = QPushButton("×")
        del_btn.setStyleSheet(
            "QPushButton { background: #eef0f4; color: #212733; border: 1px solid #d5d9e0; border-radius: 4px; padding: 3px 8px; }"
            "QPushButton:hover { background: #e0e4ec; }"
        )

        del_btn.setFixedSize(24, 24)
        del_btn.clicked.connect(lambda: self._remove_tag(tag.id))
        row.addWidget(copy_btn)
        row.addWidget(del_btn)

        item = QListWidgetItem()
        item.setSizeHint(widget.sizeHint())
        item.setData(Qt.ItemDataRole.UserRole, tag.id)
        self._list.addItem(item)
        self._list.setItemWidget(item, widget)

    def _remove_tag(self, tag_id: str) -> None:
        self._items.pop(tag_id, None)
        self.item_deleted.emit(tag_id)
        self._refresh_from_items()

    def _on_double_click(self, item: QListWidgetItem) -> None:
        tag_id = item.data(Qt.ItemDataRole.UserRole)
        if tag_id:
            self.item_copied.emit(tag_id)

    def _copy_all(self) -> None:
        from PySide6.QtWidgets import QApplication
        texts = [t.tag for t in self._items.values()]
        QApplication.clipboard().setText("\n".join(texts))

    def _refresh_from_items(self) -> None:
        self._list.clear()
        for tag in self._items.values():
            self._add_row(tag)


class KeywordEditor(QFrame):
    """长尾场景词编辑器。"""

    item_edited = Signal(str, str, str)  # id, keyword, meaning
    item_deleted = Signal(str)
    regenerate_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setProperty("editorStyle", True)
        self._items: dict[str, LongTailKeyword] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        copy_all = QPushButton("复制全部")
        copy_all.setStyleSheet(
            "QPushButton { background: #eef0f4; color: #212733; border: 1px solid #d5d9e0; border-radius: 4px; padding: 3px 8px; }"
            "QPushButton:hover { background: #e0e4ec; }"
        )

        copy_all.clicked.connect(self._copy_all)
        regen = QPushButton("重新生成")
        regen.setStyleSheet(
            "QPushButton { background: #eef0f4; color: #212733; border: 1px solid #d5d9e0; border-radius: 4px; padding: 3px 8px; }"
            "QPushButton:hover { background: #e0e4ec; }"
        )

        regen.clicked.connect(self.regenerate_requested.emit)
        btn_row.addWidget(copy_all)
        btn_row.addWidget(regen)
        layout.addLayout(btn_row)

        self._list = QListWidget()
        layout.addWidget(self._list, stretch=1)

    def _update_empty_hint(self) -> None:
        pass  # KeywordEditor 不显示 hint (由 TagEditor 中的实现覆盖)

    def set_keywords(self, keywords: list[LongTailKeyword]) -> None:
        self._list.clear()
        self._items.clear()
        for kw in keywords:
            self._items[kw.id] = kw
            self._add_row(kw)
        self._update_empty_hint()

    def _add_row(self, kw: LongTailKeyword) -> None:
        widget = QWidget()
        row = QHBoxLayout(widget)
        row.setContentsMargins(4, 2, 4, 2)
        row.setSpacing(6)

        kw_edit = QLineEdit(kw.keyword)
        kw_edit.setStyleSheet(
            "QLineEdit { background: transparent; border: 1px solid #d5d9e0;"
            "  color: #212733; padding: 2px 6px; border-radius: 4px; }"
        )
        kw_edit.textChanged.connect(
            lambda t, kid=kw.id: self.item_edited.emit(
                kid, t, self._items.get(kid).original_meaning if self._items.get(kid) else ""
            )
        )
        row.addWidget(kw_edit, stretch=2)

        meaning_edit = QLineEdit(kw.original_meaning)
        meaning_edit.setPlaceholderText("中文含义")
        meaning_edit.setMaximumWidth(150)
        meaning_edit.setStyleSheet(
            "QLineEdit { background: transparent; border: 1px solid #d5d9e0;"
            "  color: #000000; padding: 2px 6px; border-radius: 4px; }"
        )
        meaning_edit.textChanged.connect(
            lambda t, kid=kw.id: self.item_edited.emit(
                kid, self._items.get(kid).keyword if self._items.get(kid) else "", t
            )
        )
        row.addWidget(meaning_edit)

        del_btn = QPushButton("×")
        del_btn.setStyleSheet(
            "QPushButton { background: #eef0f4; color: #212733; border: 1px solid #d5d9e0; border-radius: 4px; padding: 3px 8px; }"
            "QPushButton:hover { background: #e0e4ec; }"
        )

        del_btn.setFixedSize(24, 24)
        del_btn.clicked.connect(lambda: self._remove(kw.id))
        row.addWidget(del_btn)

        item = QListWidgetItem()
        item.setSizeHint(widget.sizeHint())
        item.setData(Qt.ItemDataRole.UserRole, kw.id)
        self._list.addItem(item)
        self._list.setItemWidget(item, widget)

    def _remove(self, kw_id: str) -> None:
        self._items.pop(kw_id, None)
        self.item_deleted.emit(kw_id)
        self._refresh()

    def _copy_all(self) -> None:
        from PySide6.QtWidgets import QApplication
        texts = [k.keyword for k in self._items.values()]
        QApplication.clipboard().setText("\n".join(texts))

    def _refresh(self) -> None:
        self._list.clear()
        for kw in self._items.values():
            self._add_row(kw)


class TitleEditor(QFrame):
    """产品标题编辑器 — 逐条编辑、选中、删除。"""

    item_edited = Signal(str, str)  # id, new_title
    item_deleted = Signal(str)
    item_selected = Signal(str)     # id
    regenerate_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setProperty("editorStyle", True)
        self._items: dict[str, ProductTitle] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        copy_all = QPushButton("复制全部")
        copy_all.setStyleSheet(
            "QPushButton { background: #eef0f4; color: #212733; border: 1px solid #d5d9e0; border-radius: 4px; padding: 3px 8px; }"
            "QPushButton:hover { background: #e0e4ec; }"
        )

        copy_all.clicked.connect(self._copy_all)
        regen = QPushButton("重新生成")
        regen.setStyleSheet(
            "QPushButton { background: #eef0f4; color: #212733; border: 1px solid #d5d9e0; border-radius: 4px; padding: 3px 8px; }"
            "QPushButton:hover { background: #e0e4ec; }"
        )

        regen.clicked.connect(self.regenerate_requested.emit)
        btn_row.addWidget(copy_all)
        btn_row.addWidget(regen)
        layout.addLayout(btn_row)

        self._list = QListWidget()
        layout.addWidget(self._list, stretch=1)

    def _update_empty_hint(self) -> None:
        pass  # TitleEditor 不显示 hint

    def set_titles(self, titles: list[ProductTitle]) -> None:
        self._list.clear()
        self._items.clear()
        for t in titles:
            self._items[t.id] = t
            self._add_row(t)
        self._update_empty_hint()

    def _on_star_clicked(self, tid: str) -> None:
        """星标互斥：选中一个标题，取消其他标题的星标。"""
        for t in self._items.values():
            t.is_selected = (t.id == tid)
        self._refresh()
        self.item_selected.emit(tid)

    def _add_row(self, title: ProductTitle) -> None:
        widget = QWidget()
        row = QHBoxLayout(widget)
        row.setContentsMargins(4, 2, 4, 2)
        row.setSpacing(6)

        # 选中标记
        star_btn = QPushButton("★" if title.is_selected else "☆")
        star_btn.setFixedSize(28, 28)
        star_btn.setStyleSheet(
            "QPushButton { border: none; color: #ca8a04; }"
            if title.is_selected
            else "QPushButton { border: none; color: #98a0ad; }"
        )
        star_btn.clicked.connect(lambda tid=title.id: self._on_star_clicked(tid))
        row.addWidget(star_btn)

        edit = QLineEdit(title.title)
        edit.setStyleSheet(
            "QLineEdit { background: transparent; border: 1px solid #d5d9e0;"
            "  color: #212733; padding: 2px 6px; border-radius: 4px; }"
        )
        edit.textChanged.connect(lambda t, tid=title.id: self.item_edited.emit(tid, t))
        row.addWidget(edit, stretch=1)

        count = QLabel(f"{len(title.title)}字")
        count.setStyleSheet("color: #000000;")
        count.setFixedWidth(40)
        edit.textChanged.connect(lambda t, lbl=count: lbl.setText(f"{len(t)}字"))
        row.addWidget(count)

        copy_btn = QPushButton("复制")
        copy_btn.setStyleSheet(
            "QPushButton { background: #eef0f4; color: #212733; border: 1px solid #d5d9e0; border-radius: 4px; padding: 3px 8px; }"
            "QPushButton:hover { background: #e0e4ec; }"
        )

        copy_btn.setFixedSize(48, 24)
        copy_btn.clicked.connect(lambda: self._copy_one(title))
        del_btn = QPushButton("×")
        del_btn.setStyleSheet(
            "QPushButton { background: #eef0f4; color: #212733; border: 1px solid #d5d9e0; border-radius: 4px; padding: 3px 8px; }"
            "QPushButton:hover { background: #e0e4ec; }"
        )

        del_btn.setFixedSize(24, 24)
        del_btn.clicked.connect(lambda: self._remove(title.id))
        row.addWidget(copy_btn)
        row.addWidget(del_btn)

        item = QListWidgetItem()
        item.setSizeHint(widget.sizeHint())
        item.setData(Qt.ItemDataRole.UserRole, title.id)
        self._list.addItem(item)
        self._list.setItemWidget(item, widget)

    def _remove(self, tid: str) -> None:
        self._items.pop(tid, None)
        self.item_deleted.emit(tid)
        self._refresh()

    def _copy_one(self, title: ProductTitle) -> None:
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(title.title)

    def _copy_all(self) -> None:
        from PySide6.QtWidgets import QApplication
        texts = [t.title for t in self._items.values()]
        QApplication.clipboard().setText("\n".join(texts))

    def _refresh(self) -> None:
        self._list.clear()
        for t in self._items.values():
            self._add_row(t)


class SellingPointEditor(QFrame):
    """商品卖点编辑器 — 分类、锁定、排序。"""

    item_edited = Signal(str, str)  # id, new_text
    item_deleted = Signal(str)
    item_locked = Signal(str)
    regenerate_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setProperty("editorStyle", True)
        self._items: dict[str, SellingPoint] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        move_up = QPushButton("↑")
        move_up.setStyleSheet(
            "QPushButton { background: #eef0f4; color: #212733; border: 1px solid #d5d9e0; border-radius: 4px; padding: 3px 8px; }"
            "QPushButton:hover { background: #e0e4ec; }"
        )

        move_up.clicked.connect(self._move_up)
        move_down = QPushButton("↓")
        move_down.setStyleSheet(
            "QPushButton { background: #eef0f4; color: #212733; border: 1px solid #d5d9e0; border-radius: 4px; padding: 3px 8px; }"
            "QPushButton:hover { background: #e0e4ec; }"
        )

        move_down.clicked.connect(self._move_down)
        regen = QPushButton("重新生成")
        regen.setStyleSheet(
            "QPushButton { background: #eef0f4; color: #212733; border: 1px solid #d5d9e0; border-radius: 4px; padding: 3px 8px; }"
            "QPushButton:hover { background: #e0e4ec; }"
        )

        regen.clicked.connect(self.regenerate_requested.emit)
        btn_row.addWidget(move_up)
        btn_row.addWidget(move_down)
        btn_row.addWidget(regen)
        layout.addLayout(btn_row)

        self._list = QListWidget()
        layout.addWidget(self._list, stretch=1)

    def _update_empty_hint(self) -> None:
        pass  # SellingPointEditor 不显示 hint

    def set_selling_points(self, points: list[SellingPoint]) -> None:
        self._list.clear()
        self._items.clear()
        for sp in sorted(points, key=lambda x: x.order):
            self._items[sp.id] = sp
            self._add_row(sp)
        self._update_empty_hint()

    def _add_row(self, sp: SellingPoint) -> None:
        widget = QWidget()
        row = QHBoxLayout(widget)
        row.setContentsMargins(4, 2, 4, 2)
        row.setSpacing(6)

        cat_label = QLabel(_CATEGORY_LABELS.get(sp.category, sp.category))
        cat_label.setFixedWidth(40)
        cat_label.setStyleSheet(
            "color: #3973db; font-weight: bold;"
        )
        row.addWidget(cat_label)

        edit = QLineEdit(sp.text)
        edit.setStyleSheet(
            "QLineEdit { background: transparent; border: 1px solid #d5d9e0;"
            "  color: #212733; padding: 2px 6px; border-radius: 4px; }"
        )
        if sp.locked:
            edit.setReadOnly(True)
            edit.setStyleSheet(
                "QLineEdit { background: #ffffff; border: 1px solid #d5d9e0;"
                "  color: #000000; padding: 2px 6px; border-radius: 4px; }"
            )
        edit.textChanged.connect(lambda t, sid=sp.id: self.item_edited.emit(sid, t))
        row.addWidget(edit, stretch=1)

        lock_btn = QPushButton("🔒" if sp.locked else "🔓")
        lock_btn.setFixedSize(28, 28)
        lock_btn.setStyleSheet("QPushButton { border: none; }")
        lock_btn.clicked.connect(lambda: self.item_locked.emit(sp.id))
        row.addWidget(lock_btn)

        del_btn = QPushButton("×")
        del_btn.setStyleSheet(
            "QPushButton { background: #eef0f4; color: #212733; border: 1px solid #d5d9e0; border-radius: 4px; padding: 3px 8px; }"
            "QPushButton:hover { background: #e0e4ec; }"
        )

        del_btn.setFixedSize(24, 24)
        del_btn.clicked.connect(lambda: self._remove(sp.id))
        row.addWidget(del_btn)

        item = QListWidgetItem()
        item.setSizeHint(widget.sizeHint())
        item.setData(Qt.ItemDataRole.UserRole, sp.id)
        self._list.addItem(item)
        self._list.setItemWidget(item, widget)

    def _remove(self, sp_id: str) -> None:
        self._items.pop(sp_id, None)
        self.item_deleted.emit(sp_id)
        self._refresh()

    def _move_up(self) -> None:
        row = self._list.currentRow()
        if row > 0:
            item = self._list.takeItem(row)
            self._list.insertItem(row - 1, item)
            self._list.setCurrentRow(row - 1)
            self._sync_order_from_list()

    def _move_down(self) -> None:
        row = self._list.currentRow()
        if row < self._list.count() - 1:
            item = self._list.takeItem(row)
            self._list.insertItem(row + 1, item)
            self._list.setCurrentRow(row + 1)
            self._sync_order_from_list()

    def _sync_order_from_list(self) -> None:
        """将列表顺序同步回 SellingPoint.order 字段。"""
        for i in range(self._list.count()):
            item = self._list.item(i)
            sp_id = item.data(Qt.ItemDataRole.UserRole)
            if sp_id and sp_id in self._items:
                self._items[sp_id].order = i

    def get_selling_points(self) -> list[SellingPoint]:
        """返回排序后的卖点列表（含同步的 order）。"""
        self._sync_order_from_list()
        return list(self._items.values())

    def _refresh(self) -> None:
        self._list.clear()
        for sp in sorted(self._items.values(), key=lambda x: x.order):
            self._add_row(sp)
