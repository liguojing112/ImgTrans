"""左侧工具栏 — 竖直图标按钮组。"""

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
        self.setFixedWidth(48)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 12, 6, 12)
        layout.setSpacing(4)

        self._button_group = QButtonGroup(self)
        self._button_group.setExclusive(True)

        buttons = [
            ("import", "📥", "导入图片"),
            ("select", "🖱", "选择"),
            ("text", "T", "文字"),
            ("layer", "📑", "图层"),
        ]

        for tool_id, icon, tip in buttons:
            btn = QPushButton(icon)
            btn.setObjectName("toolButton")
            btn.setToolTip(tip)
            btn.setCheckable(True)
            btn.setFixedSize(36, 36)
            self._button_group.addButton(btn)
            layout.addWidget(btn, alignment=Qt.AlignmentFlag.AlignTop)

            if tool_id == "import":
                btn.clicked.connect(self.import_requested.emit)
            elif tool_id == "select":
                btn.setChecked(True)
                btn.clicked.connect(lambda: self.tool_changed.emit("select"))
            elif tool_id == "text":
                btn.clicked.connect(lambda: self.tool_changed.emit("text"))
            elif tool_id == "layer":
                btn.clicked.connect(lambda: self.tool_changed.emit("layer"))

        layout.addStretch()
