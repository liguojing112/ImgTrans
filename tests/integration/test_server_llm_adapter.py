"""服务端代理大模型适配器 — 按用途分流到不同端点（商品详情 / 图片翻译）。"""

import json

import pytest

import src.infrastructure.server_llm_adapter as module
from src.infrastructure.server_llm_adapter import ServerLLMAdapter

_TOKEN = "device-token-for-tests-123456"


class _Response:
    def __init__(self, payload) -> None:
        self.payload = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def read(self, size):
        return self.payload


def _capture(monkeypatch) -> dict:
    captured: dict = {}

    def open_request(request, timeout):
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return _Response({"text": "ok"})

    monkeypatch.setattr(module, "urlopen", open_request)
    return captured


def test_default_purpose_posts_to_product_endpoint(monkeypatch) -> None:
    captured = _capture(monkeypatch)
    adapter = ServerLLMAdapter("https://backend.test", _TOKEN)

    assert adapter.chat([{"role": "user", "content": "hi"}]) == "ok"
    assert captured["url"] == "https://backend.test/v1/llm/chat"


def test_translation_purpose_posts_to_translation_endpoint(monkeypatch) -> None:
    """图片翻译走独立端点，服务端据此使用「图片翻译」那组大模型配置。"""
    captured = _capture(monkeypatch)
    adapter = ServerLLMAdapter(
        "https://backend.test", _TOKEN, purpose="translation"
    )

    assert adapter.chat([{"role": "user", "content": "hi"}]) == "ok"
    assert captured["url"] == "https://backend.test/v1/llm/translation"


def test_unknown_purpose_is_rejected() -> None:
    with pytest.raises(ValueError):
        ServerLLMAdapter("https://backend.test", _TOKEN, purpose="unknown")
