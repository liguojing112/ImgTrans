from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from src.domain.protection import ProtectionKind
from src.domain.translation import (
    TranslationMode,
    TranslationResult,
    TranslationSelection,
    TranslationStatus,
)
from src.ui.languages import LANGUAGE_LABELS


_STATUS_LABELS = {
    TranslationStatus.TRANSLATED: "已翻译",
    TranslationStatus.SKIPPED_LANGUAGE: "跳过：非指定语言",
    TranslationStatus.SKIPPED_PROTECTED: "跳过：全部受保护",
    TranslationStatus.FAILED: "失败：保留原文",
}

_PROTECTION_LABELS = {
    ProtectionKind.BRAND: "品牌",
    ProtectionKind.MODEL: "型号",
    ProtectionKind.SKU: "SKU",
    ProtectionKind.URL: "网址",
    ProtectionKind.NUMBER: "数字",
}


class TranslationPanel(QFrame):
    def __init__(
        self,
        language_codes: tuple[str, ...],
        provider_id: str = "mock-local",
    ) -> None:
        super().__init__()
        self.setObjectName("translationPanel")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(9)
        self._provider_label = "模拟翻译" if provider_id == "mock-local" else "服务端翻译"
        title = QLabel(self._provider_label)
        title.setObjectName("panelTitle")
        layout.addWidget(title)
        hint = QLabel(
            "本地开发服务，不使用网络或真实 API 密钥"
            if provider_id == "mock-local"
            else "仅向本项目后端发送受保护后的文字，不上传图片"
        )
        hint.setObjectName("panelHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.mode_combo = QComboBox()
        self.mode_combo.setObjectName("translationModeCombo")
        self.mode_combo.addItem("翻译全部识别区域", TranslationMode.ALL)
        self.mode_combo.addItem("仅翻译指定语言", TranslationMode.SPECIFIC_LANGUAGE)
        self.mode_combo.currentIndexChanged.connect(self._mode_changed)
        layout.addWidget(self.mode_combo)

        language_row = QHBoxLayout()
        self.source_combo = QComboBox()
        self.source_combo.setObjectName("sourceLanguageCombo")
        self.target_combo = QComboBox()
        self.target_combo.setObjectName("targetLanguageCombo")
        for code in language_codes:
            label = LANGUAGE_LABELS.get(code, code)
            self.source_combo.addItem(label, code)
            self.target_combo.addItem(label, code)
        self.source_combo.setEnabled(False)
        target_index = self.target_combo.findData("zh-Hans")
        self.target_combo.setCurrentIndex(max(0, target_index))
        language_row.addWidget(self.source_combo)
        language_row.addWidget(self.target_combo)
        layout.addLayout(language_row)

        self.brand_terms = QLineEdit()
        self.brand_terms.setObjectName("brandTerms")
        self.brand_terms.setPlaceholderText("品牌保护词，使用逗号分隔（可选）")
        layout.addWidget(self.brand_terms)
        self.translate_button = QPushButton(f"执行{self._provider_label}")
        self.translate_button.setObjectName("translateButton")
        self.translate_button.setEnabled(False)
        layout.addWidget(self.translate_button)
        self.status_label = QLabel("完成 OCR 后可以开始翻译")
        self.status_label.setObjectName("translationStatusLabel")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        self.protection_summary = QLabel("尚无保护片段")
        self.protection_summary.setObjectName("protectionSummary")
        self.protection_summary.setWordWrap(True)
        layout.addWidget(self.protection_summary)
        self.results = QTreeWidget()
        self.results.setObjectName("translationResults")
        self.results.setColumnCount(4)
        self.results.setHeaderLabels(["原文", "译文", "状态", "保护"])
        self.results.setRootIsDecorated(False)
        self.results.setAlternatingRowColors(True)
        self.results.header().setStretchLastSection(True)
        self.results.header().resizeSection(0, 85)
        self.results.header().resizeSection(1, 125)
        self.results.header().resizeSection(2, 90)
        layout.addWidget(self.results, stretch=1)

    @property
    def selection(self) -> TranslationSelection:
        mode = self.mode_combo.currentData()
        source = str(self.source_combo.currentData()) if mode is TranslationMode.SPECIFIC_LANGUAGE else None
        return TranslationSelection(
            mode=mode,
            source_language=source,
            target_language=str(self.target_combo.currentData()),
        )

    @property
    def configured_brand_terms(self) -> tuple[str, ...]:
        return tuple(
            value.strip()
            for value in self.brand_terms.text().replace("，", ",").split(",")
            if value.strip()
        )

    def set_source_language(self, language_code: str) -> None:
        index = self.source_combo.findData(language_code)
        if index >= 0:
            self.source_combo.setCurrentIndex(index)
        target = "en" if language_code.startswith("zh") else "zh-Hans"
        target_index = self.target_combo.findData(target)
        if target_index >= 0:
            self.target_combo.setCurrentIndex(target_index)

    def set_result(self, result: TranslationResult) -> None:
        self.results.clear()
        for unit in result.units:
            protections = "、".join(
                f"{_PROTECTION_LABELS[span.kind]}:{span.text}" for span in unit.protected_spans
            )
            item = QTreeWidgetItem(
                [
                    unit.source_text,
                    unit.translated_text,
                    _STATUS_LABELS[unit.status],
                    protections,
                ]
            )
            item.setToolTip(0, unit.source_text)
            item.setToolTip(1, unit.translated_text)
            item.setToolTip(2, unit.error_message or _STATUS_LABELS[unit.status])
            item.setToolTip(3, protections)
            self.results.addTopLevelItem(item)
        translated_count = sum(
            unit.status is TranslationStatus.TRANSLATED for unit in result.units
        )
        protected_values = [
            f"{_PROTECTION_LABELS[span.kind]} {span.text}"
            for unit in result.units
            for span in unit.protected_spans
        ]
        self.protection_summary.setText(
            "已保护：" + " · ".join(dict.fromkeys(protected_values))
            if protected_values
            else "没有匹配到保护词"
        )
        self.status_label.setText(
            f"{self._provider_label}完成：{translated_count}/{len(result.units)} 个区域进入译文 · {result.elapsed_ms:.1f} ms"
        )

    def clear_result(self) -> None:
        self.results.clear()
        self.status_label.setText("完成 OCR 后可以开始翻译")
        self.protection_summary.setText("尚无保护片段")

    def _mode_changed(self) -> None:
        self.source_combo.setEnabled(
            self.mode_combo.currentData() is TranslationMode.SPECIFIC_LANGUAGE
        )
