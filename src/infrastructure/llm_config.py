"""LLM 配置持久化 — JSON 文件存储。

存储路径: {data_dir}/config/llm-config.json
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class LLMConfig:
    """LLM 配置"""

    provider: str = "openai"  # openai / anthropic / ollama / custom
    api_key: str = ""
    base_url: str = ""
    model: str = "gpt-4o"
    max_tokens: int = 4096
    temperature: float = 0.7


# 提供商预设
_PROVIDER_PRESETS = {
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o",
    },
    "anthropic": {
        "base_url": "https://api.anthropic.com/v1",
        "model": "claude-sonnet-4-20250514",
    },
    "glm": {
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "model": "glm-4v-flash",
    },
    "ollama": {
        "base_url": "http://localhost:11434/v1",
        "model": "",
    },
}


def provider_preset(provider: str) -> dict[str, str]:
    """返回提供商的预设 base_url 和推荐模型。"""
    return dict(_PROVIDER_PRESETS.get(provider, {}))


class JsonLLMConfigStore:
    """LLM 配置 JSON 持久化存储。"""

    def __init__(self, config_path: Path) -> None:
        self._path = config_path

    def load(self) -> LLMConfig:
        if not self._path.exists():
            return LLMConfig()
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            return LLMConfig(
                provider=data.get("provider", "openai"),
                api_key=data.get("api_key", ""),
                base_url=data.get("base_url", ""),
                model=data.get("model", "gpt-4o"),
                max_tokens=data.get("max_tokens", 4096),
                temperature=data.get("temperature", 0.7),
            )
        except (json.JSONDecodeError, OSError):
            return LLMConfig()

    def save(self, config: LLMConfig) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "provider": config.provider,
            "api_key": config.api_key,
            "base_url": config.base_url,
            "model": config.model,
            "max_tokens": config.max_tokens,
            "temperature": config.temperature,
        }
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self._path)
