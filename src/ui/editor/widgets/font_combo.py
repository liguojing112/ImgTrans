"""字体选择器 — 带搜索框的字体下拉，各处字体选项统一用它。

展开后的弹层顶部固定一个搜索框，下面列出全部字体；输入字体名、中文名、
风格说明的任意片段都能筛选。外观与交互对齐常见办公软件的字体选择器。

对外保持 QComboBox 风格的最小接口（`currentData()` / `setCurrentIndex()` /
`findData()` 等），替换现有下拉时调用方无需改逻辑。
"""

from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import QEvent, QPoint, QSize, Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QStyledItemDelegate,
    QVBoxLayout,
)


class _FontPopup(QFrame):
    """字体弹层：搜索框 + 字体列表。"""

    picked = Signal(object)

    def __init__(self, parent=None) -> None:
        # Qt.Tool 而不是 Qt.Popup：Popup 窗口不接管输入法上下文，
        # 客户机器上中文输入法候选框弹不出来，只能打英文。
        super().__init__(parent, Qt.WindowType.Tool)
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, False)
        # 顶层窗口默认不带输入法上下文，窗口级也要显式打开，
        # 否则搜索框拿不到 IME 组词，只能敲英文字母
        self.setAttribute(Qt.WidgetAttribute.WA_InputMethodEnabled, True)
        # 原生 StyledPanel 在 Windows 深色系统主题下用调色板画一圈近黑色描边，
        # 与样式表里的浅色边框叠成双层深框，必须关掉由样式表独占绘制
        self.setFrameShape(QFrame.Shape.NoFrame)
        # 弹层是独立顶层窗口，不会自动继承主窗口样式；显式给浅色配色。
        # 圆角放在 objectName 选择器上：QFrame 的泛匹配会被子控件继承，
        # 列表/滚动条边上会多出一圈深色描边。
        self.setObjectName("fontPopup")
        self.setStyleSheet(
            """
            QFrame#fontPopup {
                background: #ffffff;
                border: 1px solid #d5d9e0;
                border-radius: 8px;
            }
            QLineEdit {
                background: #f4f6f9; border: 1px solid #c8cdd6;
                border-radius: 4px; padding: 5px 8px; color: #1f2430;
                selection-background-color: #cfe8c8;
            }
            QLineEdit:focus { border-color: #3973db; }
            QListWidget {
                background: #ffffff; border: none; color: #1f2430;
                outline: none;
            }
            QListWidget::item { padding: 5px 6px; border: none; }
            QListWidget::item:selected {
                background: #e6f2e0; color: #1f2430;
            }
            QListWidget::item:hover { background: #f0f4ec; }
            QScrollBar:vertical {
                background: #ffffff; width: 8px; border: none;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical {
                background: #d5d9e0; border-radius: 4px; min-height: 30px;
            }
            QScrollBar::handle:vertical:hover { background: #5085e8; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0;
            }
            """
        )
        self._search = QLineEdit(self)
        # 关掉原生输入框边框：深色系统主题下它会画一圈近黑描边
        self._search.setFrame(False)
        self._search.setPlaceholderText("输入字体的首字母或全拼")
        self._search.setClearButtonEnabled(True)
        # 顶层窗口不参与主窗口的输入法上下文，必须显式打开：
        # 否则客户机上中文输入法候选框不出现，只能敲英文字母。
        self._search.setAttribute(
            Qt.WidgetAttribute.WA_InputMethodEnabled, True
        )
        # ImhNone = 不对输入类型做强限制，中文/日文输入法都能正常组词
        self._search.setInputMethodHints(Qt.InputMethodHint.ImhNone)
        self._search.textChanged.connect(self._apply_filter)
        self._list = QListWidget(self)
        # 列表自带原生边框，深色系统主题下会画成深色内框，关掉由样式表绘制
        self._list.setFrameShape(QFrame.Shape.NoFrame)
        # 焦点始终留在搜索框：列表一旦拿到焦点，输入法上下文会跟着走，
        # 中文打不进去；点列表项照样能选中（不需要焦点）
        self._list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._list.setUniformItemSizes(True)
        self._list.setAlternatingRowColors(False)
        self._list.itemActivated.connect(self._on_activated)
        self._list.itemClicked.connect(self._on_activated)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)
        layout.addWidget(self._search)
        layout.addWidget(self._list)

    def set_items(self, entries: list[tuple[str, object]]) -> None:
        self._list.clear()
        for display, data in entries:
            item = QListWidgetItem(display)
            item.setData(Qt.ItemDataRole.UserRole, data)
            self._list.addItem(item)
        self._apply_filter(self._search.text())

    def sync_current(self, index: int) -> None:
        if 0 <= index < self._list.count():
            self._list.setCurrentRow(index)
            self._list.scrollToItem(self._list.item(index))

    def _apply_filter(self, text: str) -> None:
        needle = text.strip().casefold()
        for row in range(self._list.count()):
            item = self._list.item(row)
            item.setHidden(bool(needle) and needle not in item.text().casefold())
        # 有命中时自动选中第一条，回车即可确认
        for row in range(self._list.count()):
            if not self._list.item(row).isHidden():
                self._list.setCurrentRow(row)
                break

    def _on_activated(self, item: QListWidgetItem) -> None:
        self.picked.emit(item.data(Qt.ItemDataRole.UserRole))
        self.close()

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            item = self._list.currentItem()
            if item is not None and not item.isHidden():
                self._on_activated(item)
                return
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            return
        super().keyPressEvent(event)

    def eventFilter(self, watched, event) -> bool:
        # Qt.Tool 窗口不像 Qt.Popup 会自动关闭：点窗口外或应用失焦时收起
        if event.type() == QEvent.Type.ApplicationDeactivate:
            self.close()
        elif event.type() == QEvent.Type.MouseButtonPress:
            if not self.geometry().contains(event.globalPosition().toPoint()):
                self.close()
        return super().eventFilter(watched, event)

    def focus_search(self) -> None:
        self._search.setFocus()
        self._search.selectAll()


class _ComboDelegate(QStyledItemDelegate):
    """把下拉项按选项文字绘制（而不是渲染字体本身），长列表更整齐。"""

    def paint(self, painter, option, index) -> None:
        option.text = index.data(Qt.ItemDataRole.DisplayRole) or ""
        super().paint(painter, option, index)

    def sizeHint(self, option, index) -> QSize:
        option.text = index.data(Qt.ItemDataRole.DisplayRole) or ""
        return super().sizeHint(option, index)


class SearchableFontComboBox(QComboBox):
    """带搜索框的字体下拉框，接口与 QComboBox 用法一致。"""

    currentFontChanged = Signal(QFont)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setToolTip("点击后可直接输入字体名搜索")
        self.setMinimumWidth(180)
        self.setEditable(False)
        self.setItemDelegate(_ComboDelegate(self))
        self._popup = _FontPopup(self)
        self._popup.picked.connect(self._on_picked)
        self._filter_installed = False
        self.currentIndexChanged.connect(self._remember_index)
        self.currentIndexChanged.connect(
            lambda _index: self.currentFontChanged.emit(self.currentFont())
        )

    def populate(
        self,
        families: Iterable[str] | None = None,
        placeholder: str | None = None,
    ) -> None:
        """按系统字体重建选项；placeholder 用于「自动匹配字体」这类空值项。"""
        # 延迟导入：translate_controls 也依赖本模块，顶层导入会形成循环
        from src.ui.editor.widgets.translate_controls import translation_font_choices

        previous = self.currentData()
        blocked = self.blockSignals(True)
        try:
            self.clear()
            if placeholder is not None:
                self.addItem(placeholder, None)
            for display, family in translation_font_choices(families):
                self.addItem(display, family)
            index = self.findData(previous) if previous is not None else 0
            self.setCurrentIndex(max(0, index))
        finally:
            self.blockSignals(blocked)

    def _remember_index(self, _index: int) -> None:
        self._popup.sync_current(self.currentIndex())

    # —— QFontComboBox 兼容接口 ——
    # 水印字体等处沿用 setCurrentFont / currentFont，保持调用方无需改动。

    def currentFont(self) -> QFont:
        return QFont(self.currentData() or self.currentText())

    def setCurrentFont(self, font: QFont) -> None:
        family = font.family()
        index = self.findData(family)
        if index < 0:
            index = self.findText(family)
        if index >= 0:
            self.setCurrentIndex(index)

    def showPopup(self) -> None:
        entries = [
            (self.itemText(index), self.itemData(index))
            for index in range(self.count())
        ]
        self._popup.set_items(entries)
        self._popup.sync_current(self.currentIndex())
        self._popup.resize(max(self.width(), 320), 420)
        origin = self.mapToGlobal(QPoint(0, self.height()))
        self._popup.move(origin)
        app = QApplication.instance()
        if app is not None and not self._filter_installed:
            app.installEventFilter(self._popup)
            self._filter_installed = True
        self._popup.show()
        self._popup.raise_()
        self._popup.activateWindow()
        self._popup.focus_search()

    def hidePopup(self) -> None:
        self._popup.hide()
        super().hidePopup()

    def _on_picked(self, data: object) -> None:
        index = self.findData(data)
        if index >= 0:
            self.setCurrentIndex(index)
        self._popup.close()


__all__ = ["SearchableFontComboBox"]
