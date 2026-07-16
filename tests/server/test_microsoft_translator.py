"""Microsoft Translator v3 adapter tests without external requests."""

from email.message import Message
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit
import json

import pytest

import server.infrastructure.microsoft_translator as module
from server.domain.translation import TranslationProviderError
from server.infrastructure.microsoft_translator import MicrosoftTranslatorAdapter


class _Response:
    def __init__(self, payload) -> None:
        self.payload = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def read(self, size):
        assert size == 2 * 1024 * 1024 + 1
        return self.payload


def test_v3_request_maps_portuguese_and_keeps_key_out_of_url_and_body(monkeypatch) -> None:
    captured = {}

    def open_request(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return _Response(
            [
                {"translations": [{"text": "Olá", "to": "pt"}]},
                {"translations": [{"text": "Venda", "to": "pt"}]},
            ]
        )

    monkeypatch.setattr(module, "urlopen", open_request)
    adapter = MicrosoftTranslatorAdapter(
        "https://api.cognitive.microsofttranslator.com/translate",
        "fixture-subscription-key",
        "westus",
        3.0,
    )
    result = adapter.translate(
        ("Hello", "Sale"),
        "pt-PT",
        "pt-BR",
        "correlation-9",
    )
    request = captured["request"]
    query = parse_qs(urlsplit(request.full_url).query)
    headers = {key.lower(): value for key, value in request.header_items()}
    assert query == {"api-version": ["3.0"], "to": ["pt"], "from": ["pt-pt"]}
    assert headers["ocp-apim-subscription-key"] == "fixture-subscription-key"
    assert headers["ocp-apim-subscription-region"] == "westus"
    assert headers["x-clienttraceid"] == "correlation-9"
    assert "fixture-subscription-key" not in request.full_url
    assert b"fixture-subscription-key" not in request.data
    assert [item.translated_text for item in result] == ["Olá", "Venda"]


def test_retryable_rate_limit_retries_once_without_exposing_vendor_body(monkeypatch) -> None:
    calls = []
    sleeps = []

    def open_request(request, timeout):
        del request, timeout
        calls.append(1)
        if len(calls) == 1:
            headers = Message()
            headers["Retry-After"] = "0"
            raise HTTPError("https://provider", 429, "secret vendor detail", headers, None)
        return _Response([{"translations": [{"text": "你好", "to": "zh-Hans"}]}])

    monkeypatch.setattr(module, "urlopen", open_request)
    adapter = MicrosoftTranslatorAdapter(
        "https://api.cognitive.microsofttranslator.com/translate",
        "fixture-subscription-key",
        max_attempts=2,
        sleeper=sleeps.append,
    )
    result = adapter.translate(("hello",), None, "zh-Hans", "trace")
    assert result[0].translated_text == "你好"
    assert len(calls) == 2
    assert sleeps == [0.25]


def test_authentication_error_is_stable_and_not_retried(monkeypatch) -> None:
    calls = []

    def open_request(request, timeout):
        del request, timeout
        calls.append(1)
        raise HTTPError("https://provider", 401, "vendor secret", Message(), None)

    monkeypatch.setattr(module, "urlopen", open_request)
    adapter = MicrosoftTranslatorAdapter(
        "https://api.cognitive.microsofttranslator.com/translate",
        "fixture-subscription-key",
    )
    with pytest.raises(TranslationProviderError) as error:
        adapter.translate(("hello",), "en", "fr", "trace")
    assert error.value.code == "provider_authentication_failed"
    assert "vendor secret" not in str(error.value)
    assert len(calls) == 1
