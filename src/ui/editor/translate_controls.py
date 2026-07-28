"""翻译控制区 — OCR 语言、目标语言、翻译按钮、阶段进度。"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from src.domain.job import ImageStage
from src.domain.language import SUPPORTED_LANGUAGE_CODES

_STAGE_LABELS = {
    ImageStage.OCR: "OCR 识别",
    ImageStage.TRANSLATION: "翻译",
    ImageStage.INPAINTING: "背景修复",
    ImageStage.LAYOUT: "排版",
    ImageStage.RENDERING: "渲染",
}

_LANGUAGE_DISPLAY = {
    "zh-Hans": "简体中文",
    "zh-Hant": "繁体中文",
    "en": "英语",
    "ja": "日语",
    "ko": "韩语",
    "fr": "法语",
    "de": "德语",
    "es": "西班牙语",
    "pt": "葡萄牙语",
    "it": "意大利语",
    "ru": "俄语",
    "ar": "阿拉伯语",
    "th": "泰语",
    "vi": "越南语",
    "id": "印尼语",
    "ms": "马来语",
    "hi": "印地语",
    "bn": "孟加拉语",
    "tr": "土耳其语",
    "nl": "荷兰语",
    "pl": "波兰语",
    "sv": "瑞典语",
    "da": "丹麦语",
    "fi": "芬兰语",
    "no": "挪威语",
    "cs": "捷克语",
}


class TranslateControls(QFrame):
    """翻译配置控件 — 语言选择 + 翻译按钮 + 进度。"""

    translate_requested = Signal(str, str)  # (ocr_language, target_language)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("translateControls")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        title = QLabel("图片翻译")
        title.setObjectName("propertyTitle")

        # OCR 语言
        ocr_row = QHBoxLayout()
        ocr_label = QLabel("OCR 语言")
        ocr_label.setObjectName("propertyFieldLabel")
        self.ocr_language = QComboBox()
        self.ocr_language.setMinimumWidth(140)
        for code in SUPPORTED_LANGUAGE_CODES:
            display = _LANGUAGE_DISPLAY.get(code, code)
            self.ocr_language.addItem(f"{display} ({code})", code)
        # 默认选中中文
        idx = self.ocr_language.findData("zh-Hans")
        if idx >= 0:
            self.ocr_language.setCurrentIndex(idx)
        ocr_row.addWidget(ocr_label)
        ocr_row.addWidget(self.ocr_language)

        # 目标语言
        target_row = QHBoxLayout()
        target_label = QLabel("目标语言")
        target_label.setObjectName("propertyFieldLabel")
        self.target_language = QComboBox()
        self.target_language.setMinimumWidth(140)
        for code in SUPPORTED_LANGUAGE_CODES:
            display = _LANGUAGE_DISPLAY.get(code, code)
            self.target_language.addItem(f"{display} ({code})", code)
        # 默认选中英语
        idx = self.target_language.findData("en")
        if idx >= 0:
            self.target_language.setCurrentIndex(idx)
        target_row.addWidget(target_label)
        target_row.addWidget(self.target_language)

        # 翻译按钮
        self.translate_button = QPushButton("开始翻译")
        self.translate_button.setObjectName("applyPropertyButton")
        self.translate_button.clicked.connect(self._on_translate)

        # 进度条
        self.progress = QProgressBar()
        self.progress.setRange(0, 5)
        self.progress.setValue(0)
        self.progress.setTextVisible(True)
        self.progress.setFormat("就绪")
        self.progress.setVisible(False)

        self.stage_label = QLabel("")
        self.stage_label.setObjectName("propertyFieldLabel")

        layout.addWidget(title)
        layout.addSpacing(4)
        layout.addLayout(ocr_row)
        layout.addLayout(target_row)
        layout.addWidget(self.translate_button)
        layout.addWidget(self.progress)
        layout.addWidget(self.stage_label)

    # —— 公开接口 ——

    @property
    def selected_ocr_language(self) -> str:
        return str(self.ocr_language.currentData())

    @property
    def selected_target_language(self) -> str:
        return str(self.target_language.currentData())

    def set_translating(self, translating: bool) -> None:
        self.translate_button.setEnabled(not translating)
        self.ocr_language.setEnabled(not translating)
        self.target_language.setEnabled(not translating)

    def set_stage(self, stage: object) -> None:
        if isinstance(stage, ImageStage):
            stage_order = {
                ImageStage.OCR: 1,
                ImageStage.TRANSLATION: 2,
                ImageStage.INPAINTING: 3,
                ImageStage.LAYOUT: 4,
                ImageStage.RENDERING: 5,
            }
            n = stage_order.get(stage, 0)
            self.progress.setVisible(True)
            self.progress.setValue(n)
            label = _STAGE_LABELS.get(stage, stage.value)
            self.progress.setFormat(f"{label}…")
            self.stage_label.setText(f"正在执行：{label}")

    def reset_progress(self) -> None:
        self.progress.setVisible(False)
        self.progress.setValue(0)
        self.progress.setFormat("就绪")
        self.stage_label.setText("")

    # —— 内部 ——

    def _on_translate(self) -> None:
        ocr = self.selected_ocr_language
        target = self.selected_target_language
        self.translate_requested.emit(ocr, target)
