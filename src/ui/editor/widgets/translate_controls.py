"""翻译控制区 — 翻译偏好设置 + 进度 + 摘要 + 取消 + 耗时。"""

from __future__ import annotations

from PySide6.QtCore import QElapsedTimer, QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPlainTextEdit,
    QDoubleSpinBox,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
)

from src.domain.job import ImageStage
from src.domain.language import SUPPORTED_LANGUAGE_CODES
from src.domain.ocr import HighRecallOcrOptions, OcrMode, Point, RingBand
from src.domain.protection import normalize_brand_terms
from src.domain.translation import TranslationMode
from src.domain.terminology import TerminologyEntry
from src.ui.common import wrap_spin

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


def _group_title(text: str) -> QLabel:
    """功能分组标题（H3）。"""
    label = QLabel(text)
    label.setObjectName("groupTitle")
    return label


class TranslateControls(QFrame):
    """翻译配置控件 — 语言选择 + 品牌词 + 翻译按钮 + 进度 + 摘要 + 取消。"""

    translate_requested = Signal(str, str)
    ocr_only_requested = Signal()
    cancel_requested = Signal()
    activity_changed = Signal(bool)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("translateControls")
        self._activity_step = 0
        self._activity_name = ""
        self._activity_elapsed = QElapsedTimer()
        self._activity_timer = QTimer(self)
        self._activity_timer.setInterval(1000)
        self._activity_timer.timeout.connect(self._update_activity_label)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)

        title = QLabel("图片翻译")
        title.setObjectName("pageTitle")

        # OCR 语言
        ocr_row = QHBoxLayout()
        ocr_label = QLabel("原图文字语言（OCR）")
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

        ocr_mode_row = QHBoxLayout()
        ocr_mode_label = QLabel("OCR 模式")
        ocr_mode_label.setObjectName("propertyFieldLabel")
        self.ocr_mode = QComboBox()
        self.ocr_mode.addItem("标准 OCR", OcrMode.STANDARD.value)
        self.ocr_mode.addItem(
            "高召回 OCR（圆环/旋转文字）",
            OcrMode.HIGH_RECALL.value,
        )
        self.ocr_mode.currentIndexChanged.connect(
            self._ocr_mode_changed
        )
        ocr_mode_row.addWidget(ocr_mode_label)
        ocr_mode_row.addWidget(self.ocr_mode)
        self.ocr_mode_hint = QLabel()
        self.ocr_mode_hint.setObjectName("captionLabel")
        self.ocr_mode_hint.setWordWrap(True)

        self.high_recall_controls = QFrame()
        self.high_recall_controls.setMinimumHeight(118)
        high_recall_layout = QVBoxLayout(self.high_recall_controls)
        high_recall_layout.setContentsMargins(0, 0, 0, 0)
        high_recall_layout.setSpacing(4)
        high_recall_hint = QLabel(
            "自动检测圆心和文字环带；需要时可填写圆心及内外半径。"
        )
        high_recall_hint.setObjectName("captionLabel")
        high_recall_hint.setWordWrap(True)
        high_recall_layout.addWidget(high_recall_hint)
        center_row = QHBoxLayout()
        center_label = QLabel("圆心 X / Y")
        center_label.setMinimumHeight(32)
        center_row.addWidget(center_label)
        self.high_recall_center_x = _coordinate_spinbox()
        self.high_recall_center_y = _coordinate_spinbox()
        center_row.addWidget(wrap_spin(self.high_recall_center_x, width=90, label="圆心 X"))
        center_row.addWidget(wrap_spin(self.high_recall_center_y, width=90, label="圆心 Y"))
        high_recall_layout.addLayout(center_row)
        radius_row = QHBoxLayout()
        radius_label = QLabel("内 / 外半径")
        radius_label.setMinimumHeight(32)
        radius_row.addWidget(radius_label)
        self.high_recall_inner_radius = _radius_spinbox()
        self.high_recall_outer_radius = _radius_spinbox()
        radius_row.addWidget(wrap_spin(self.high_recall_inner_radius, width=90, label="内半径"))
        radius_row.addWidget(wrap_spin(self.high_recall_outer_radius, width=90, label="外半径"))
        high_recall_layout.addLayout(radius_row)

        # 翻译模式
        mode_label = QLabel("翻译模式")
        mode_label.setObjectName("propertyFieldLabel")
        self.all_mode_radio = QRadioButton("翻译全部区域")
        self.specific_mode_radio = QRadioButton("只翻译指定语言")
        for radio in (self.all_mode_radio, self.specific_mode_radio):
            radio.setStyleSheet(
                "QRadioButton { color: #212733; spacing: 6px; }"
            )
        self._mode_group = QButtonGroup(self)
        self._mode_group.addButton(self.all_mode_radio)
        self._mode_group.addButton(self.specific_mode_radio)
        self.all_mode_radio.setChecked(True)
        self.all_mode_radio.toggled.connect(self._mode_changed)
        self.specific_mode_radio.toggled.connect(self._mode_changed)

        # 源语言（仅「只翻译指定语言」时参与）
        src_row = QHBoxLayout()
        src_label = QLabel("指定源语言")
        src_label.setObjectName("propertyFieldLabel")
        self.source_language = QComboBox()
        self.source_language.setMinimumWidth(140)
        for code in SUPPORTED_LANGUAGE_CODES:
            self.source_language.addItem(f"{_LANGUAGE_DISPLAY.get(code, code)} ({code})", code)
        idx = self.source_language.findData("zh-Hans")
        if idx >= 0:
            self.source_language.setCurrentIndex(idx)
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
        self.ocr_language.currentIndexChanged.connect(
            self._update_ocr_mode_hint
        )
        self.target_language.currentIndexChanged.connect(
            self._update_ocr_mode_hint
        )

        # 品牌词
        brand_row = QHBoxLayout()
        brand_label = QLabel("品牌词")
        brand_label.setObjectName("propertyFieldLabel")
        self.brand_terms = QLineEdit()
        self.brand_terms.setPlaceholderText("逗号分隔，可选")
        brand_row.addWidget(brand_label)
        brand_row.addWidget(self.brand_terms)

        model_row = QHBoxLayout()
        model_label = QLabel("型号保护词")
        model_label.setObjectName("propertyFieldLabel")
        self.model_terms = QLineEdit()
        self.model_terms.setPlaceholderText("商品型号、SKU，逗号分隔")
        model_row.addWidget(model_label)
        model_row.addWidget(self.model_terms)

        self.preserve_numbers = QCheckBox("保留数字与单位")
        self.preserve_numbers.setChecked(True)
        self.preserve_numbers.setToolTip(
            "默认启用；关闭后允许翻译纯数字和单位。网址、品牌、型号和 SKU 始终保护"
        )

        confidence_row = QHBoxLayout()
        confidence_label = QLabel("自动处理阈值")
        confidence_label.setObjectName("propertyFieldLabel")
        self.confidence_threshold = QDoubleSpinBox()
        self.confidence_threshold.setRange(0.50, 0.99)
        self.confidence_threshold.setSingleStep(0.05)
        self.confidence_threshold.setDecimals(2)
        self.confidence_threshold.setValue(0.75)
        self.allow_low_confidence = QCheckBox("自动处理低于阈值区域")
        self.allow_low_confidence.setChecked(False)
        self.allow_low_confidence.setToolTip(
            "开启后可能误擦除低可靠文字；建议仅在人工核对后使用"
        )
        confidence_row.addWidget(confidence_label)
        confidence_row.addWidget(
            wrap_spin(self.confidence_threshold, width=80, label="自动处理阈值")
        )

        self.service_status = QLabel("翻译服务：启动时检测")
        self.service_status.setObjectName("captionLabel")

        terminology_label = QLabel("精确术语表（源词 => 目标词）")
        terminology_label.setObjectName("propertyFieldLabel")
        self.terminology_editor = QPlainTextEdit()
        self.terminology_editor.setPlaceholderText("每行一条，例如：卡箍 => Clamp")
        self.terminology_editor.setMaximumHeight(92)
        self.terminology_status = QLabel("")
        self.terminology_status.setObjectName("captionLabel")

        # 翻译按钮
        self.translate_button = QPushButton("开始翻译")
        self.translate_button.setObjectName("applyPropertyButton")
        self.translate_button.clicked.connect(self._on_translate)

        self.ocr_only_button = QPushButton("仅 OCR 识别")
        self.ocr_only_button.setObjectName("applyPropertyButton")
        self.ocr_only_button.setToolTip(
            "只识别图片中的文字，不翻译；结果在右侧「OCR 结果」列表"
        )
        self.ocr_only_button.clicked.connect(self.ocr_only_requested.emit)

        action_row = QHBoxLayout()
        action_row.setSpacing(6)
        action_row.addWidget(self.translate_button)
        action_row.addWidget(self.ocr_only_button)

        # 翻译提示（翻译开始后无法取消）
        self.translate_hint = QLabel("翻译开始后无法取消，请耐心等待完成")
        self.translate_hint.setObjectName("captionLabel")
        self.translate_hint.setWordWrap(True)
        self.translate_hint.setVisible(False)

        # 进度条
        self.progress = QProgressBar()
        self.progress.setRange(0, 5)
        self.progress.setValue(0)
        self.progress.setTextVisible(True)
        self.progress.setFormat("就绪")
        self.progress.setVisible(False)

        self.stage_label = QLabel("")
        self.stage_label.setObjectName("captionLabel")

        # 翻译摘要 + 耗时
        self.summary_label = QLabel("")
        self.summary_label.setObjectName("captionLabel")
        self.summary_label.setWordWrap(True)
        self.summary_label.setVisible(False)

        layout.addWidget(title)
        layout.addSpacing(4)

        # —— 语言设置 ——
        layout.addWidget(_group_title("语言设置"))
        layout.addLayout(ocr_row)
        layout.addLayout(ocr_mode_row)
        layout.addWidget(self.ocr_mode_hint)
        layout.addWidget(self.high_recall_controls)

        # —— 翻译范围 ——
        layout.addWidget(_group_title("翻译范围"))
        layout.addWidget(mode_label)
        layout.addWidget(self.all_mode_radio)
        layout.addWidget(self.specific_mode_radio)
        layout.addSpacing(2)
        layout.addLayout(src_row)
        layout.addLayout(tgt_row)

        # —— 保护规则 ——
        layout.addWidget(_group_title("保护规则"))
        layout.addLayout(brand_row)
        layout.addLayout(model_row)
        layout.addWidget(self.preserve_numbers)

        # —— 识别与复核 ——
        layout.addWidget(_group_title("识别与复核"))
        layout.addLayout(confidence_row)
        layout.addWidget(self.allow_low_confidence)
        layout.addWidget(self.service_status)

        # —— 精准术语表 ——
        layout.addWidget(_group_title("精准术语表"))
        layout.addWidget(terminology_label)
        layout.addWidget(self.terminology_editor)
        layout.addWidget(self.terminology_status)

        layout.addLayout(action_row)
        layout.addWidget(self.translate_hint)
        layout.addWidget(self.progress)
        layout.addWidget(self.stage_label)
        layout.addWidget(self.summary_label)
        self._ocr_mode_changed()

    # —— 公开接口 ——

    @property
    def selected_ocr_language(self) -> str:
        return str(self.ocr_language.currentData())

    @property
    def selected_ocr_mode(self) -> OcrMode:
        return OcrMode(str(self.ocr_mode.currentData()))

    @property
    def configured_high_recall_options(self) -> HighRecallOcrOptions:
        center = (
            Point(
                self.high_recall_center_x.value(),
                self.high_recall_center_y.value(),
            )
            if self.high_recall_center_x.value() >= 0
            and self.high_recall_center_y.value() >= 0
            else None
        )
        inner = self.high_recall_inner_radius.value()
        outer = self.high_recall_outer_radius.value()
        bands = (RingBand(inner, outer),) if outer > inner else ()
        return HighRecallOcrOptions(center=center, ring_bands=bands)

    @property
    def selected_target_language(self) -> str:
        return str(self.target_language.currentData())

    @property
    def selected_source_language(self) -> str | None:
        return self.source_language.currentData()

    @property
    def selected_mode(self) -> str:
        return (
            TranslationMode.SPECIFIC_LANGUAGE.value
            if self.specific_mode_radio.isChecked()
            else TranslationMode.ALL.value
        )

    @property
    def configured_brand_terms(self) -> tuple[str, ...]:
        return normalize_brand_terms(self.brand_terms.text())

    @property
    def configured_model_terms(self) -> tuple[str, ...]:
        return normalize_brand_terms(self.model_terms.text())

    @property
    def configured_protection_terms(self) -> tuple[str, ...]:
        return normalize_brand_terms(
            (*self.configured_brand_terms, *self.configured_model_terms)
        )

    @property
    def automatic_confidence_threshold(self) -> float:
        return float(self.confidence_threshold.value())

    @property
    def should_process_low_confidence(self) -> bool:
        return self.allow_low_confidence.isChecked()

    @property
    def should_preserve_numbers(self) -> bool:
        return self.preserve_numbers.isChecked()

    def set_configured_brand_terms(self, terms: tuple[str, ...]) -> None:
        self.brand_terms.setText(", ".join(normalize_brand_terms(terms)))

    def set_configured_model_terms(self, terms: tuple[str, ...]) -> None:
        self.model_terms.setText(", ".join(normalize_brand_terms(terms)))

    def set_service_status(self, text: str, available: bool) -> None:
        color = "#15803d" if available else "#dc2626"
        self.service_status.setText(text)
        self.service_status.setStyleSheet(f"color: {color};")

    def configured_terminology_entries(
        self,
        source_language: str,
        target_language: str,
    ) -> tuple[TerminologyEntry, ...]:
        entries: list[TerminologyEntry] = []
        for line_number, raw in enumerate(
            self.terminology_editor.toPlainText().splitlines(), start=1
        ):
            line = raw.strip()
            if not line:
                continue
            if "=>" not in line:
                raise ValueError(f"术语表第 {line_number} 行缺少 =>")
            source_text, target_text = (part.strip() for part in line.split("=>", 1))
            entries.append(
                TerminologyEntry(
                    source_language,
                    target_language,
                    source_text,
                    target_text,
                )
            )
        return tuple(entries)

    def set_terminology_entries(
        self,
        source_language: str,
        target_language: str,
        entries: tuple[TerminologyEntry, ...],
    ) -> None:
        values = [
            f"{entry.source_text} => {entry.target_text}"
            for entry in entries
            if entry.enabled
            and entry.source_language == source_language
            and entry.target_language == target_language
        ]
        self.terminology_editor.setPlainText("\n".join(values))
        self.terminology_status.setText(
            f"当前语言对：{source_language} → {target_language} · {len(values)} 条"
        )

    def set_translating(self, translating: bool) -> None:
        self.translate_button.setEnabled(not translating)
        self.ocr_only_button.setEnabled(not translating)
        self.translate_hint.setVisible(translating)
        self.ocr_language.setEnabled(not translating)
        self.ocr_mode.setEnabled(not translating)
        self.high_recall_controls.setEnabled(not translating)
        self.target_language.setEnabled(not translating)
        self.all_mode_radio.setEnabled(not translating)
        self.specific_mode_radio.setEnabled(not translating)
        self.source_language.setEnabled(
            not translating
            and self.selected_mode == TranslationMode.SPECIFIC_LANGUAGE.value
        )
        self.brand_terms.setEnabled(not translating)
        self.model_terms.setEnabled(not translating)
        self.preserve_numbers.setEnabled(not translating)
        self.terminology_editor.setEnabled(not translating)
        self.confidence_threshold.setEnabled(not translating)
        self.allow_low_confidence.setEnabled(not translating)
        if translating:
            self._activity_elapsed.start()
            self._activity_timer.start()
            self.activity_changed.emit(True)
        else:
            self._activity_timer.stop()

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
            self._activity_step = n
            self._activity_name = label
            self.progress.setFormat(f"步骤 {n}/5 · {label}…")
            self._update_activity_label()
            self.activity_changed.emit(True)

    def set_preparing(self) -> None:
        self.progress.setVisible(True)
        self.progress.setValue(0)
        self.progress.setFormat("正在准备…")
        self._activity_step = 0
        self._activity_name = "准备图片、语言设置和保护规则"
        self._update_activity_label()
        self.activity_changed.emit(True)

    def reset_progress(self) -> None:
        self._activity_timer.stop()
        self.progress.setVisible(False)
        self.progress.setValue(0)
        self.progress.setFormat("就绪")
        self.stage_label.setText("")
        self._activity_step = 0
        self._activity_name = ""
        self.activity_changed.emit(False)

    def set_summary(self, ocr_count: int, translated: int, review: int,
                    skipped: int, failed: int, overflow: int,
                    ocr_ms: float = 0, total_ms: float = 0) -> None:
        """显示翻译完成后的统计摘要和耗时。"""
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
        if ocr_ms > 0:
            parts.append(f"OCR：{ocr_ms:.0f}ms")
        if total_ms > 0:
            parts.append(f"总计：{total_ms:.0f}ms")
        self.summary_label.setText("  ·  ".join(parts))
        self.summary_label.setVisible(True)

    # —— 内部 ——

    def _on_translate(self) -> None:
        self.summary_label.setVisible(False)
        ocr = self.selected_ocr_language
        target = self.selected_target_language
        self.translate_requested.emit(ocr, target)

    def _update_activity_label(self) -> None:
        if not self._activity_name:
            return
        elapsed_seconds = (
            max(0, self._activity_elapsed.elapsed() // 1000)
            if self._activity_elapsed.isValid()
            else 0
        )
        slow_stage_hint = (
            "；高召回 OCR 通常需要 1～4 分钟，请勿重复点击"
            if self._activity_step == 1
            and self.selected_ocr_mode is OcrMode.HIGH_RECALL
            else ""
        )
        self.stage_label.setText(
            f"正在执行：{self._activity_name} · 已用时 {elapsed_seconds}s"
            f"{slow_stage_hint}"
        )

    def _mode_changed(self, _checked: bool = False) -> None:
        self.source_language.setEnabled(
            self.selected_mode == TranslationMode.SPECIFIC_LANGUAGE.value
        )

    def _ocr_mode_changed(self) -> None:
        self.high_recall_controls.setVisible(
            self.selected_ocr_mode is OcrMode.HIGH_RECALL
        )
        self._update_ocr_mode_hint()

    def _update_ocr_mode_hint(self) -> None:
        source_code = self.selected_ocr_language
        target_code = self.selected_target_language
        source_name = _LANGUAGE_DISPLAY.get(source_code, source_code)
        target_name = _LANGUAGE_DISPLAY.get(target_code, target_code)
        direction = f"当前方向：{source_name}原文 → {target_name}译文。"
        if self.selected_ocr_mode is OcrMode.STANDARD:
            self.ocr_mode_hint.setText(
                direction
                + "圆环、倾斜或任意角度文字必须切换为“高召回 OCR”。"
            )
            self.ocr_mode_hint.setStyleSheet("color: #b45309;")
            return
        if source_code == target_code:
            correction = (
                "英译汉请把“原图文字语言（OCR）”设为英语（en），"
                "“译文语言”设为简体中文（zh-Hans）。"
                if target_code == "zh-Hans"
                else "请把“原图文字语言（OCR）”改为原图实际语言。"
            )
            self.ocr_mode_hint.setText(
                direction + "原文与译文语言相同，无法执行有效翻译。" + correction
            )
            self.ocr_mode_hint.setStyleSheet("color: #dc2626;")
            return
        self.ocr_mode_hint.setText(
            direction
            + "高召回模式已启用；未确认候选会保留原图并标记为待复核。"
        )
        self.ocr_mode_hint.setStyleSheet("color: #15803d;")


def _coordinate_spinbox() -> QDoubleSpinBox:
    spinbox = QDoubleSpinBox()
    spinbox.setMinimumHeight(32)
    spinbox.setRange(-1, 100000)
    spinbox.setDecimals(1)
    spinbox.setValue(-1)
    spinbox.setSpecialValueText("自动")
    return spinbox


def _radius_spinbox() -> QDoubleSpinBox:
    spinbox = QDoubleSpinBox()
    spinbox.setMinimumHeight(32)
    spinbox.setRange(0, 100000)
    spinbox.setDecimals(1)
    spinbox.setValue(0)
    spinbox.setSpecialValueText("自动")
    return spinbox
