"""左侧工具栏 — 竖直工具按钮组。"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QPushButton,
    QVBoxLayout,
)


class EditorToolBar(QFrame):
    """左侧窄工具栏，竖直排列工具按钮。"""

    import_requested = Signal()
    tool_changed = Signal(str)  # "select" | "text" | "layer"

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("editorToolBar")
        self.setFixedWidth(40)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 12, 4, 12)
        layout.setSpacing(4)

        self._button_group = QButtonGroup(self)
        self._button_group.setExclusive(True)

        buttons = [
            ("select", "▶", "选择"),
            ("text", "T", "文字"),
            ("layer", "⊞", "图层"),
        ]

        for tool_id, label, tip in buttons:
            btn = QPushButton(label)
            btn.setObjectName("toolButton")
            btn.setToolTip(tip)
            btn.setCheckable(True)
            btn.setFixedSize(32, 32)
            self._button_group.addButton(btn)
            layout.addWidget(btn, alignment=Qt.AlignmentFlag.AlignTop)

            if tool_id == "select":
                btn.setChecked(True)
                btn.clicked.connect(lambda: self.tool_changed.emit("select"))
            elif tool_id == "text":
                btn.clicked.connect(lambda: self.tool_changed.emit("text"))
            elif tool_id == "layer":
                btn.clicked.connect(lambda: self.tool_changed.emit("layer"))

        layout.addStretch()
