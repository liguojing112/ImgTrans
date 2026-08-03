"""图片翻译编辑器左侧工具栏。"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QButtonGroup, QFrame, QPushButton, QVBoxLayout


class EditorToolBar(QFrame):
    tool_changed = Signal(str)
    add_text_requested = Signal()
    feature_requested = Signal(str)

    _MODE_TOOLS = (
        ("select", "选择", "选择、移动和编辑文字图层"),
        ("text_regions", "文字区域", "显示并编辑识别到的文字区域"),
        ("manual_translate", "框选翻译", "框选漏翻区域并进行识别和翻译"),
        ("ai_erase", "AI消除", "查看或调整文字擦除区域"),
        ("crop", "裁剪", "裁剪图片"),
        ("layers", "图层", "查看文字图层状态"),
        ("watermark", "水印", "添加或管理水印"),
    )

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("editorToolBar")
        self.setFixedWidth(88)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 10, 8, 10)
        layout.setSpacing(5)

        self._button_group = QButtonGroup(self)
        self._button_group.setExclusive(True)
        self.buttons: dict[str, QPushButton] = {}

        for tool_id, label, tooltip in self._MODE_TOOLS[:2]:
            self._add_mode_button(layout, tool_id, label, tooltip)

        add_text = self._add_mode_button(
            layout,
            "add_text",
            "新增文字",
            "新增一个可编辑文字图层",
        )
        add_text.clicked.connect(self.add_text_requested.emit)

        for tool_id, label, tooltip in self._MODE_TOOLS[2:]:
            self._add_mode_button(layout, tool_id, label, tooltip)

        self.buttons["select"].setChecked(True)
        layout.addStretch()

    @property
    def active_tool(self) -> str:
        checked = self._button_group.checkedButton()
        return str(checked.property("toolId")) if checked is not None else "select"

    def set_active_tool(self, tool_id: str) -> None:
        button = self.buttons.get(tool_id)
        if button is not None and button.isCheckable():
            button.setChecked(True)

    def _add_mode_button(
        self,
        layout: QVBoxLayout,
        tool_id: str,
        label: str,
        tooltip: str,
    ) -> QPushButton:
        button = QPushButton(label)
        button.setObjectName("toolButton")
        button.setProperty("toolId", tool_id)
        button.setToolTip(tooltip)
        button.setCheckable(True)
        button.setFixedSize(72, 44)
        button.clicked.connect(
            lambda _checked=False, value=tool_id: self._activate(value)
        )
        self._button_group.addButton(button)
        layout.addWidget(button, alignment=Qt.AlignmentFlag.AlignTop)
        self.buttons[tool_id] = button
        return button

    def _activate(self, tool_id: str) -> None:
        if tool_id in {"crop", "watermark"}:
            self.feature_requested.emit(tool_id)
        self.tool_changed.emit(tool_id)
