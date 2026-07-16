from __future__ import annotations

from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

from src.domain.job import ImageStage


_STAGE_LABELS = {
    ImageStage.OCR: "OCR 文字识别",
    ImageStage.TRANSLATION: "语言筛选、保护词和翻译",
    ImageStage.INPAINTING: "擦除蒙版和背景修复",
    ImageStage.LAYOUT: "译文布局和字号拟合",
    ImageStage.RENDERING: "译文渲染与合成",
}


class PipelinePanel(QFrame):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("pipelinePanel")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 22, 22, 22)
        layout.setSpacing(12)
        title = QLabel("单图自动翻译")
        title.setObjectName("panelTitle")
        hint = QLabel("使用 OCR 页的识别语言，以及翻译页的语言和保护词设置。")
        hint.setObjectName("panelHint")
        hint.setWordWrap(True)
        self.status_label = QLabel("导入图片后可以执行完整处理。")
        self.status_label.setObjectName("pipelineStatusLabel")
        self.status_label.setWordWrap(True)
        self.stages = QListWidget()
        self.stages.setObjectName("pipelineStages")
        for stage in ImageStage:
            item = QListWidgetItem(f"○  {_STAGE_LABELS[stage]}")
            item.setData(256, stage)
            self.stages.addItem(item)
        actions = QHBoxLayout()
        self.start_button = QPushButton("一键完成图片翻译")
        self.start_button.setObjectName("startWorkflowButton")
        self.start_button.setEnabled(False)
        self.cancel_button = QPushButton("取消")
        self.cancel_button.setObjectName("cancelWorkflowButton")
        self.cancel_button.setEnabled(False)
        actions.addWidget(self.start_button, stretch=1)
        actions.addWidget(self.cancel_button)
        layout.addWidget(title)
        layout.addWidget(hint)
        layout.addWidget(self.status_label)
        layout.addWidget(self.stages)
        layout.addLayout(actions)

    def reset(self) -> None:
        for index, stage in enumerate(ImageStage):
            self.stages.item(index).setText(f"○  {_STAGE_LABELS[stage]}")
        self.status_label.setText("图片已就绪，可以执行完整处理。")

    def set_stage(self, active: ImageStage) -> None:
        stages = tuple(ImageStage)
        active_index = stages.index(active)
        for index, stage in enumerate(stages):
            marker = "✓" if index < active_index else "▶" if stage is active else "○"
            self.stages.item(index).setText(f"{marker}  {_STAGE_LABELS[stage]}")
        self.status_label.setText(f"正在执行：{_STAGE_LABELS[active]}")

    def set_completed(self, warning: str | None, overflow_count: int) -> None:
        for index, stage in enumerate(ImageStage):
            self.stages.item(index).setText(f"✓  {_STAGE_LABELS[stage]}")
        details = []
        if warning:
            details.append("背景修复使用了降级方案")
        if overflow_count:
            details.append(f"{overflow_count} 个长译文已使用最小字号，请在 M2 编辑器中调整")
        self.status_label.setText("单图翻译完成" + ("；" + "；".join(details) if details else ""))

    def set_cancelled(self) -> None:
        self.status_label.setText("任务已取消，原图保持不变。")
