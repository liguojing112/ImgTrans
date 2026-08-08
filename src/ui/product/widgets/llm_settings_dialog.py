"""LLM API 配置对话框。"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from src.infrastructure.llm_config import LLMConfig, provider_preset


class LlmSettingsDialog(QDialog):
    """LLM API 配置对话框。"""

    def __init__(self, config: LLMConfig) -> None:
        super().__init__()
        self.setProperty("editorStyle", True)
        self.setWindowTitle("LLM API 设置")
        self.setMinimumWidth(420)
        self._config = config
        self._result: LLMConfig | None = None

        layout = QVBoxLayout(self)
        layout.setSpacing(16)

        form = QFormLayout()
        form.setSpacing(10)

        # 提供商
        self._provider = QComboBox()
        self._provider.addItems(["openai", "anthropic", "glm", "ollama", "custom"])
        self._provider.setCurrentText(config.provider)
        self._provider.currentTextChanged.connect(self._on_provider_changed)
        form.addRow("提供商:", self._provider)

        # API Key
        self._api_key = QLineEdit(config.api_key)
        self._api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._api_key.setPlaceholderText("输入 API Key")
        form.addRow("API Key:", self._api_key)

        # Base URL
        self._base_url = QLineEdit(config.base_url)
        self._base_url.setPlaceholderText("留空使用默认地址")
        self._base_url.setPlaceholderText("留空使用默认地址")
        form.addRow("Base URL:", self._base_url)

        # 模型
        self._model = QComboBox()
        self._model.setEditable(True)
        self._model.setCurrentText(config.model)
        form.addRow("模型:", self._model)

        # Max Tokens
        self._max_tokens = QSpinBox()
        self._max_tokens.setRange(256, 131072)
        self._max_tokens.setValue(config.max_tokens)
        self._max_tokens.setSingleStep(512)
        form.addRow("Max Tokens:", self._max_tokens)

        # Temperature
        self._temperature = QDoubleSpinBox()
        self._temperature.setRange(0.0, 2.0)
        self._temperature.setSingleStep(0.1)
        self._temperature.setValue(config.temperature)
        form.addRow("Temperature:", self._temperature)

        layout.addLayout(form)

        # 状态提示
        self._status = QLabel("")
        self._status.setStyleSheet("color: #000000;")
        layout.addWidget(self._status)

        # 按钮
        btn_layout = QVBoxLayout()
        self._test_btn = QPushButton("测试连接")
        self._test_btn.clicked.connect(self._on_test)
        btn_layout.addWidget(self._test_btn)

        btn_row = QHBoxLayout()
        save_btn = QPushButton("保存")
        save_btn.clicked.connect(self._on_save)
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(save_btn)
        btn_row.addWidget(cancel_btn)
        btn_layout.addLayout(btn_row)

        layout.addLayout(btn_layout)

        self._on_provider_changed(config.provider)

    def result(self) -> LLMConfig | None:
        return self._result

    def _on_provider_changed(self, provider: str) -> None:
        preset = provider_preset(provider)
        if preset.get("base_url"):
            self._base_url.setText(preset["base_url"])
            self._base_url.setPlaceholderText(preset["base_url"])
        else:
            self._base_url.setPlaceholderText("输入 API 地址")
        if preset.get("model"):
            current = self._model.currentText()
            self._model.clear()
            self._model.addItem(preset["model"])
            self._model.setCurrentText(current or preset["model"])
        # 预填常用模型
        if provider == "openai":
            models = ["gpt-4o", "gpt-4o-mini", "gpt-4.1"]
        elif provider == "anthropic":
            models = ["claude-sonnet-4-20250514", "claude-opus-4-20250514"]
        elif provider == "glm":
            models = ["glm-4v-flash", "glm-5v-turbo"]
        else:
            models = []
        if models:
            current = self._model.currentText()
            self._model.clear()
            self._model.addItems(models)
            if current in models:
                self._model.setCurrentText(current)

    def _on_test(self) -> None:
        config = self._build_config()
        from src.infrastructure.llm_adapter import LLMAdapter, LLMError
        adapter = LLMAdapter(config)
        try:
            ok = adapter.test_connection()
            if ok:
                self._status.setText("✓ 连接成功")
                self._status.setStyleSheet("color: #16a34a;")
            else:
                self._status.setText("✗ 连接失败")
                self._status.setStyleSheet("color: #dc2626;")
        except LLMError as e:
            self._status.setText(f"✗ 错误: {e}")
            self._status.setStyleSheet("color: #dc2626;")

    def _on_save(self) -> None:
        self._result = self._build_config()
        self.accept()

    def _build_config(self) -> LLMConfig:
        return LLMConfig(
            provider=self._provider.currentText(),
            api_key=self._api_key.text().strip(),
            base_url=self._base_url.text().strip(),
            model=self._model.currentText().strip(),
            max_tokens=self._max_tokens.value(),
            temperature=self._temperature.value(),
        )
