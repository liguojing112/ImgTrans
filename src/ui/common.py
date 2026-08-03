"""编辑器 UI 公共控件辅助。"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QHBoxLayout,
    QSizePolicy,
    QToolButton,
    QWidget,
)


def wrap_spin(
    spin: QAbstractSpinBox, width: int = 70, label: str = ""
) -> QWidget:
    """把 ± 按钮移到输入框右侧外部（与图层状态面板一致），返回容器。

    spin 引用保持不变，外部可通过 spin 读写值/信号。
    """
    spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
    spin.setFixedWidth(width)
    container = QWidget()
    container.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    hbox = QHBoxLayout(container)
    hbox.setContentsMargins(0, 0, 0, 0)
    hbox.setSpacing(2)
    hbox.addWidget(spin)
    smaller = QToolButton()
    smaller.setText("−")
    smaller.setToolTip(f"减小{label}" if label else "减小")
    smaller.clicked.connect(spin.stepDown)
    hbox.addWidget(smaller)
    larger = QToolButton()
    larger.setText("+")
    larger.setToolTip(f"增大{label}" if label else "增大")
    larger.clicked.connect(spin.stepUp)
    hbox.addWidget(larger)
    return container
