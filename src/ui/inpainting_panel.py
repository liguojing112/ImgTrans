from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from src.domain.inpainting import RepairOutcome


class InpaintingPanel(QFrame):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("inpaintingPanel")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 22, 22, 22)
        layout.setSpacing(12)
        title = QLabel("背景修复")
        title.setObjectName("panelTitle")
        hint = QLabel("仅擦除已翻译区域；LaMa 不可用时自动使用 OpenCV。")
        hint.setObjectName("panelHint")
        hint.setWordWrap(True)
        self.status_label = QLabel("完成模拟翻译后可生成蒙版并修复背景。")
        self.status_label.setObjectName("inpaintingStatusLabel")
        self.status_label.setWordWrap(True)
        self.show_mask = QCheckBox("显示擦除蒙版")
        self.show_mask.setChecked(True)
        self.repair_button = QPushButton("生成蒙版并修复")
        self.repair_button.setObjectName("repairButton")
        self.repair_button.setEnabled(False)
        actions = QHBoxLayout()
        self.toggle_button = QPushButton("查看原图")
        self.toggle_button.setObjectName("toggleOriginalButton")
        self.toggle_button.setEnabled(False)
        self.keep_original_button = QPushButton("撤销并保留原图")
        self.keep_original_button.setObjectName("keepOriginalButton")
        self.keep_original_button.setEnabled(False)
        actions.addWidget(self.toggle_button)
        actions.addWidget(self.keep_original_button)
        layout.addWidget(title)
        layout.addWidget(hint)
        layout.addWidget(self.status_label)
        layout.addWidget(self.show_mask)
        layout.addWidget(self.repair_button)
        layout.addLayout(actions)
        layout.addStretch()

    def set_result(self, outcome: RepairOutcome) -> None:
        result = outcome.result
        warning = f"\n{result.warning}" if result.warning else ""
        self.status_label.setText(
            f"修复完成 · {result.backend_id} · {result.elapsed_ms:.0f} ms{warning}"
        )
        self.repair_button.setText("重新修复")
        self.toggle_button.setEnabled(True)
        self.keep_original_button.setEnabled(True)

    def set_previewing_original(self, original: bool) -> None:
        self.toggle_button.setText("查看修复图" if original else "查看原图")

    def clear_result(self) -> None:
        self.status_label.setText("完成模拟翻译后可生成蒙版并修复背景。")
        self.repair_button.setText("生成蒙版并修复")
        self.toggle_button.setEnabled(False)
        self.keep_original_button.setEnabled(False)
        self.set_previewing_original(False)
