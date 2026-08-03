"""文案生成设置面板 — 右侧设置区域。"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QCheckBox,
    QComboBox,
    QFrame,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from src.domain.copywriting import CopywritingSettings
from src.domain.language import SUPPORTED_LANGUAGE_CODES

_LANGUAGE_DISPLAY = {
    "zh-Hans": "简体中文", "zh-Hant": "繁体中文", "en": "英语",
    "ja": "日语", "ko": "韩语", "fr": "法语", "de": "德语",
    "es": "西班牙语", "pt": "葡萄牙语", "pt-PT": "葡萄牙语(葡)", "pt-BR": "葡萄牙语(巴)",
    "it": "意大利语", "ru": "俄语", "ar": "阿拉伯语", "th": "泰语",
    "vi": "越南语", "id": "印尼语", "ms": "马来语", "hi": "印地语",
    "bn": "孟加拉语", "tr": "土耳其语", "pl": "波兰语", "fil": "菲律宾语",
    "ur": "乌尔都语", "fa": "波斯语", "sw": "斯瓦希里语",
}

_PLATFORM_OPTIONS = [
    ("通用电商", "general"),
    ("Amazon", "amazon"),
    ("AliExpress", "aliexpress"),
    ("Shopee", "shopee"),
    ("Lazada", "lazada"),
    ("独立站", "standalone"),
]

_STYLE_OPTIONS = [
    ("专业", "professional"),
    ("休闲", "casual"),
    ("热情", "enthusiastic"),
    ("简约", "minimal"),
]

_TONE_OPTIONS = [
    ("中性", "neutral"),
    ("亲切", "warm"),
    ("权威", "authoritative"),
]


class CopywritingSettingsPanel(QFrame):
    """文案生成设置面板。"""

    settings_changed = Signal(object)  # CopywritingSettings

    def __init__(self) -> None:
        super().__init__()
        self.setProperty("editorStyle", True)
        self.setObjectName("copywritingSettings")
        self.setMinimumWidth(220)
        self.setMaximumWidth(320)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_widget = QWidget()
        form = QFormLayout(scroll_widget)
        form.setSpacing(8)
        form.setContentsMargins(12, 12, 12, 12)

        # 目标语言
        self._lang_combo = QComboBox()
        for code in sorted(SUPPORTED_LANGUAGE_CODES):
            self._lang_combo.addItem(
                _LANGUAGE_DISPLAY.get(code, code), code
            )
        self._lang_combo.setCurrentIndex(
            max(0, self._lang_combo.findData("en"))
        )
        form.addRow("目标语言:", self._lang_combo)

        # 目标国家
        self._country_edit = QLineEdit()
        self._country_edit.setPlaceholderText("如 US, UK, JP")
        form.addRow("目标国家:", self._country_edit)

        # 电商平台
        self._platform_combo = QComboBox()
        for label, value in _PLATFORM_OPTIONS:
            self._platform_combo.addItem(label, value)
        form.addRow("平台:", self._platform_combo)

        # 文案风格
        self._style_combo = QComboBox()
        for label, value in _STYLE_OPTIONS:
            self._style_combo.addItem(label, value)
        form.addRow("风格:", self._style_combo)

        # 语气
        self._tone_combo = QComboBox()
        for label, value in _TONE_OPTIONS:
            self._tone_combo.addItem(label, value)
        form.addRow("语气:", self._tone_combo)

        form.addRow(QLabel(""))  # 分隔

        # 标签数量
        self._tag_count = self._create_spin_box(1, 50, 10)
        form.addRow("标签数量:", self._tag_count)

        # 场景词数量
        self._kw_count = self._create_spin_box(1, 50, 10)
        form.addRow("场景词数量:", self._kw_count)

        # 标题数量
        self._title_count = self._create_spin_box(1, 20, 5)
        form.addRow("标题数量:", self._title_count)

        # 标题字符上限
        self._title_max_chars = self._create_spin_box(50, 500, 200, step=10)
        form.addRow("标题上限:", self._title_max_chars)

        form.addRow(QLabel(""))  # 分隔

        # 保留品牌
        self._keep_brand = QCheckBox("保留品牌名")
        self._keep_brand.setChecked(True)
        form.addRow("", self._keep_brand)

        # 保留型号
        self._keep_model = QCheckBox("保留型号")
        self._keep_model.setChecked(True)
        form.addRow("", self._keep_model)

        # 禁用词
        self._banned_words = QLineEdit()
        self._banned_words.setPlaceholderText("逗号分隔")
        form.addRow("禁用词:", self._banned_words)

        # 关键词
        self._custom_keywords = QLineEdit()
        self._custom_keywords.setPlaceholderText("逗号分隔")
        form.addRow("关键词:", self._custom_keywords)

        # 自定义要求
        self._custom_requirements = QLineEdit()
        self._custom_requirements.setPlaceholderText("补充生成要求")
        form.addRow("自定义要求:", self._custom_requirements)

        scroll.setWidget(scroll_widget)
        layout.addWidget(scroll)

        # 信号连接 — 任何变更都发射
        for w in (
            self._lang_combo, self._platform_combo,
            self._style_combo, self._tone_combo,
            self._tag_count, self._kw_count, self._title_count,
            self._title_max_chars,
        ):
            if isinstance(w, QComboBox):
                w.currentIndexChanged.connect(self._emit_settings)
            elif isinstance(w, QWidget) and w.property("spin_box"):
                self._get_spin(w).valueChanged.connect(self._emit_settings)

        self._country_edit.textChanged.connect(self._emit_settings)
        self._keep_brand.toggled.connect(self._emit_settings)
        self._keep_model.toggled.connect(self._emit_settings)
        self._banned_words.textChanged.connect(self._emit_settings)
        self._custom_keywords.textChanged.connect(self._emit_settings)
        self._custom_requirements.textChanged.connect(self._emit_settings)

    def _get_spin(self, widget: QWidget) -> QSpinBox:
        """从组合控件中提取 QSpinBox。"""
        return widget.property("spin_box")

    def get_settings(self) -> CopywritingSettings:
        return CopywritingSettings(
            target_language=self._lang_combo.currentData(),
            target_country=self._country_edit.text().strip(),
            platform=self._platform_combo.currentData(),
            style=self._style_combo.currentData(),
            tone=self._tone_combo.currentData(),
            tag_count=self._get_spin(self._tag_count).value(),
            keyword_count=self._get_spin(self._kw_count).value(),
            title_count=self._get_spin(self._title_count).value(),
            title_max_chars=self._get_spin(self._title_max_chars).value(),
            keep_brand=self._keep_brand.isChecked(),
            keep_model=self._keep_model.isChecked(),
            banned_words=[
                w.strip()
                for w in self._banned_words.text().split(",")
                if w.strip()
            ],
            custom_keywords=[
                w.strip()
                for w in self._custom_keywords.text().split(",")
                if w.strip()
            ],
            custom_requirements=self._custom_requirements.text().strip(),
        )

    def set_target_language(self, language: str) -> None:
        """Restore a saved language without changing the language contract."""
        index = self._lang_combo.findData(language)
        if index >= 0:
            self._lang_combo.setCurrentIndex(index)

    def _emit_settings(self) -> None:
        self.settings_changed.emit(self.get_settings())

    def _create_spin_box(
        self, min_val: int, max_val: int, default: int, step: int = 1
    ) -> QWidget:
        """创建数字输入框 + 外部 ± 按钮的组合控件（图层状态样式）。"""
        container = QWidget()
        hbox = QHBoxLayout(container)
        hbox.setContentsMargins(0, 0, 0, 0)
        hbox.setSpacing(2)

        spin = QSpinBox()
        spin.setRange(min_val, max_val)
        spin.setValue(default)
        spin.setSingleStep(step)
        spin.setButtonSymbols(QAbstractSpinBox.NoButtons)
        hbox.addWidget(spin, stretch=1)

        btn_smaller = QToolButton()
        btn_smaller.setText("−")
        btn_smaller.setToolTip("减小")
        btn_smaller.setFixedSize(24, 18)
        btn_smaller.setStyleSheet(
            "QToolButton { background: #2a2a44; color: #e0e0f0;"
            "  border: 1px solid #3d3d5c; border-radius: 4px; font-size: 11px; }"
            "QToolButton:hover { background: #34345a; }"
            "QToolButton:pressed { background: #3a3a5e; }"
        )
        btn_smaller.clicked.connect(spin.stepDown)
        hbox.addWidget(btn_smaller)

        btn_larger = QToolButton()
        btn_larger.setText("+")
        btn_larger.setToolTip("增大")
        btn_larger.setFixedSize(24, 18)
        btn_larger.setStyleSheet(
            "QToolButton { background: #2a2a44; color: #e0e0f0;"
            "  border: 1px solid #3d3d5c; border-radius: 4px; font-size: 11px; }"
            "QToolButton:hover { background: #34345a; }"
            "QToolButton:pressed { background: #3a3a5e; }"
        )
        btn_larger.clicked.connect(spin.stepUp)
        hbox.addWidget(btn_larger)

        # 保存 spin 引用以便后续访问
        container.setProperty("spin_box", spin)
        return container
