"""步骤指示器组件。"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QPushButton


class StepIndicator(QFrame):
    """三步导航条。"""

    step_clicked = Signal(int)

    _STEP_LABELS = ["商品来源", "AI 商品分析", "文案生成"]

    def __init__(self) -> None:
        super().__init__()
        self.setProperty("editorStyle", True)
        self.setObjectName("stepIndicator")
        self._buttons: list[QPushButton] = []
        self._current = 0
        self._completed: set[int] = {0}

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        for i, label in enumerate(self._STEP_LABELS):
            btn = QPushButton(f"{i + 1}. {label}" if i == 0 else f"→ {label}")
            btn.setCheckable(True)
            btn.setObjectName("stepButton")
            btn.clicked.connect(lambda checked, idx=i: self._on_click(idx))
            self._buttons.append(btn)
            layout.addWidget(btn, stretch=1)

        layout.addStretch(1)
        self._update_styles()
        self.setFixedHeight(44)

    def set_active(self, step: int) -> None:
        self._current = step
        self._completed.add(step)
        self._update_styles()

    def set_completed(self, step: int) -> None:
        self._completed.add(step)
        self._update_styles()

    def _on_click(self, step: int) -> None:
        if step not in self._completed and step != self._current:
            return
        self.set_active(step)
        self.step_clicked.emit(step)

    def _update_styles(self) -> None:
        for i, btn in enumerate(self._buttons):
            if i == self._current:
                btn.setChecked(True)
                btn.setStyleSheet(
                    "QPushButton#stepButton {"
                    "  background: qlineargradient(x1:0, y1:0, x2:0, y2:1,"
                    "  stop:0 #4a8af4, stop:1 #3973db);"
                    "  color: #ffffff; border: 1px solid #5a9af4;"
                    " font-weight: 600;"
                    "  padding: 8px 16px; border-radius: 6px;"
                    "}"
                )
            elif i in self._completed:
                btn.setChecked(False)
                btn.setStyleSheet(
                    "QPushButton#stepButton {"
                    "  background: #ffffff; color: #626b7a;"
                    "  border: 1px solid #d5d9e0; padding: 8px 16px;"
                    "  border-radius: 4px;"
                    "}"
                    "QPushButton#stepButton:hover {"
                    "  border-color: #3973db; color: #212733;"
                    "}"
                )
            else:
                btn.setChecked(False)
                btn.setStyleSheet(
                    "QPushButton#stepButton {"
                    "  background: #f4f5f7; color: #98a0ad;"
                    "  border: 1px solid #2e2e48; padding: 8px 16px;"
                    "  border-radius: 4px;"
                    "}"
                )
