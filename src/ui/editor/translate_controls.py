"""翻译控制区 — 翻译偏好设置 + 进度 + 摘要。"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from src.domain.job import ImageStage
from src.domain.language import SUPPORTED_LANGUAGE_CODES
from src.domain.protection import normalize_brand_terms
from src.domain.translation import TranslationMode

_STAGE_LABELS = {
    ImageStage.OCR: "OCR 识别",
    ImageStage.TRANSLATION: "翻译",
    ImageStage.INPAINTING: "背景修复",
    ImageStage.LAYOUT: "排版",
    ImageStage.RENDERING: "渲染",
}

_LANGUAGE_DISPLAY = {
    "zh-Hans": "简体中文", "zh-Hant": "繁体中文", "en": "英语",
    "ja": "日语", "ko": "韩语", "fr": "法语", "de": "德语",
    "es": "西班牙语", "pt": "葡萄牙语", "it": "意大利语",
    "ru": "俄语", "ar": "阿拉伯语", "th": "泰语", "vi": "越南语",
    "id": "印尼语", "ms": "马来语", "hi": "印地语", "bn": "孟加拉语",
    "tr": "土耳其语", "nl": "荷兰语", "pl": "波兰语", "sv": "瑞典语",
    "da": "丹麦语", "fi": "芬兰语", "no": "挪威语", "cs": "捷克语",
}


class TranslateControls(QFrame):
    """翻译配置控件 — 语言选择 + 品牌词 + 翻译按钮 + 进度 + 摘要。"""

    translate_requested = Signal(str, str)  # (ocr_language, target_language)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("translateControls")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        title = QLabel("图片翻译")
        title.setObjectName("propertyTitle")

        # OCR 语言
        ocr_row = QHBoxLayout()
        ocr_label = QLabel("OCR 语言")
        ocr_label.setObjectName("propertyFieldLabel")
        self.ocr_language = QComboBox()
        self.ocr_language.setMinimumWidth(140)
        for code in SUPPORTED_LANGUAGE_CODES:
            self.ocr_language.addItem(f"{_LANGUAGE_DISPLAY.get(code, code)} ({code})", code)
        idx = self.ocr_language.findData("zh-Hans")
        if idx >= 0:
            self.ocr_language.setCurrentIndex(idx)
        ocr_row.addWidget(ocr_label)
        ocr_row.addWidget(self.ocr_language)

        # 翻译模式
        mode_row = QHBoxLayout()
        mode_label = QLabel("翻译模式")
        mode_label.setObjectName("propertyFieldLabel")
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("翻译全部区域", TranslationMode.ALL.value)
        self.mode_combo.addItem("仅翻译指定语言", TranslationMode.SPECIFIC_LANGUAGE.value)
        self.mode_combo.currentIndexChanged.connect(self._mode_changed)
        mode_row.addWidget(mode_label)
        mode_row.addWidget(self.mode_combo)

        # 源语言（SPECIFIC_LANGUAGE 模式时可用）
        src_row = QHBoxLayout()
        src_label = QLabel("源语言")
        src_label.setObjectName("propertyFieldLabel")
        self.source_language = QComboBox()
        self.source_language.setMinimumWidth(140)
        self.source_language.addItem("自动识别", None)
        for code in SUPPORTED_LANGUAGE_CODES:
            self.source_language.addItem(f"{_LANGUAGE_DISPLAY.get(code, code)} ({code})", code)
        self.source_language.setEnabled(False)
        src_row.addWidget(src_label)
        src_row.addWidget(self.source_language)

        # 目标语言
        tgt_row = QHBoxLayout()
        tgt_label = QLabel("目标语言")
        tgt_label.setObjectName("propertyFieldLabel")
        self.target_language = QComboBox()
        self.target_language.setMinimumWidth(140)
        for code in SUPPORTED_LANGUAGE_CODES:
            self.target_language.addItem(f"{_LANGUAGE_DISPLAY.get(code, code)} ({code})", code)
        idx = self.target_language.findData("en")
        if idx >= 0:
            self.target_language.setCurrentIndex(idx)
        tgt_row.addWidget(tgt_label)
        tgt_row.addWidget(self.target_language)

        # 品牌词
        brand_row = QHBoxLayout()
        brand_label = QLabel("品牌词")
        brand_label.setObjectName("propertyFieldLabel")
        self.brand_terms = QLineEdit()
        self.brand_terms.setPlaceholderText("逗号分隔，可选")
        brand_row.addWidget(brand_label)
        brand_row.addWidget(self.brand_terms)

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

        # 翻译摘要
        self.summary_label = QLabel("")
        self.summary_label.setObjectName("propertyFieldLabel")
        self.summary_label.setWordWrap(True)
        self.summary_label.setVisible(False)

        layout.addWidget(title)
        layout.addSpacing(4)
        layout.addLayout(ocr_row)
        layout.addLayout(mode_row)
        layout.addLayout(src_row)
        layout.addLayout(tgt_row)
        layout.addLayout(brand_row)
        layout.addWidget(self.translate_button)
        layout.addWidget(self.progress)
        layout.addWidget(self.stage_label)
        layout.addWidget(self.summary_label)

    # —— 公开接口 ——

    @property
    def selected_ocr_language(self) -> str:
        return str(self.ocr_language.currentData())

    @property
    def selected_target_language(self) -> str:
        return str(self.target_language.currentData())

    @property
    def selected_source_language(self) -> str | None:
        return self.source_language.currentData()

    @property
    def selected_mode(self) -> str:
        return str(self.mode_combo.currentData())

    @property
    def configured_brand_terms(self) -> tuple[str, ...]:
        return normalize_brand_terms(self.brand_terms.text())

    def set_translating(self, translating: bool) -> None:
        self.translate_button.setEnabled(not translating)
        self.ocr_language.setEnabled(not translating)
        self.target_language.setEnabled(not translating)
        self.mode_combo.setEnabled(not translating)
        self.source_language.setEnabled(
            not translating and self.mode_combo.currentData() == TranslationMode.SPECIFIC_LANGUAGE.value
        )
        self.brand_terms.setEnabled(not translating)

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

    def set_summary(self, ocr_count: int, translated: int, review: int,
                    skipped: int, failed: int, overflow: int) -> None:
        """显示翻译完成后的统计摘要。"""
        parts = [f"识别区域：{ocr_count}"]
        if translated:
            parts.append(f"翻译：{translated}")
        if review:
            parts.append(f"待复核：{review}")
        if skipped:
            parts.append(f"跳过：{skipped}")
        if failed:
            parts.append(f"失败：{failed}")
        if overflow:
            parts.append(f"溢出：{overflow}")
        self.summary_label.setText("  ·  ".join(parts))
        self.summary_label.setVisible(True)

    # —— 内部 ——

    def _on_translate(self) -> None:
        self.summary_label.setVisible(False)
        ocr = self.selected_ocr_language
        target = self.selected_target_language
        self.translate_requested.emit(ocr, target)

    def _mode_changed(self) -> None:
        specific = self.mode_combo.currentData() == TranslationMode.SPECIFIC_LANGUAGE.value
        self.source_language.setEnabled(specific)
