"""Desktop-to-backend translation adapter tests."""

import json

import src.infrastructure.server_translation_adapter as module
from src.application.translation import TranslateRegions
from src.domain.ocr import OcrResult, TextRegion, order_quad
from src.domain.protection import ProtectionEngine
from src.domain.translation import (
    TranslationMode,
    TranslationSelection,
    TranslationStatus,
)
from src.infrastructure.server_translation_adapter import ServerTranslationAdapter
import pytest
from src.domain.translation import TranslationError


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


def test_adapter_sends_only_text_contract_and_preserves_partial_failures(monkeypatch) -> None:
    captured = {}

    def open_request(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return _Response(
            {
                "correlation_id": "server-trace",
                "provider": "fixture",
                "items": [
                    {
                        "item_id": "item-0",
                        "status": "translated",
                        "translated_text": "促销",
                        "source_language": "en",
                        "error_code": None,
                        "error_message": None,
                    },
                    {
                        "item_id": "item-1",
                        "status": "failed",
                        "translated_text": None,
                        "error_code": "provider_rate_limited",
                        "error_message": "Rate limit reached",
                    },
                ],
            }
        )

    monkeypatch.setattr(module, "urlopen", open_request)
    adapter = ServerTranslationAdapter(
        "https://imgtrans.example.test",
        "fixture-client-token-123456",
    )
    result = adapter.translate(("SALE", "NEW"), "en", "zh-Hans")
    request = captured["request"]
    body = json.loads(request.data.decode("utf-8"))
    assert set(body) == {"source_language", "target_language", "items"}
    assert "image" not in request.data.decode("utf-8").lower()
    assert body["items"] == [
        {"item_id": "item-0", "text": "SALE"},
        {"item_id": "item-1", "text": "NEW"},
    ]
    headers = {key.lower(): value for key, value in request.header_items()}
    assert headers["authorization"] == "Bearer fixture-client-token-123456"
    assert result[0].translated_text == "促销"
    assert result[0].source_language == "en"
    assert result[1].error_code == "provider_rate_limited"


def test_failed_backend_item_remains_original_and_is_not_erased(monkeypatch) -> None:
    def open_request(request, timeout):
        del request, timeout
        return _Response(
            {
                "correlation_id": "server-trace",
                "provider": "fixture",
                "items": [
                    {
                        "item_id": "item-0",
                        "status": "failed",
                        "translated_text": None,
                        "error_code": "provider_unavailable",
                        "error_message": "Provider unavailable",
                    }
                ],
            }
        )

    monkeypatch.setattr(module, "urlopen", open_request)
    adapter = ServerTranslationAdapter(
        "https://imgtrans.example.test",
        "fixture-client-token-123456",
    )
    region = TextRegion(
        "r1",
        order_quad(((0, 0), (100, 0), (100, 30), (0, 30))),
        "SALE",
        1.0,
        "en",
        "fixture",
    )
    result = TranslateRegions(adapter, ProtectionEngine()).execute(
        OcrResult((region,), "en", "fixture", 0),
        TranslationSelection(TranslationMode.ALL, "zh-Hans"),
    )
    assert result.units[0].status is TranslationStatus.FAILED
    assert result.units[0].translated_text == "SALE"
    assert not result.units[0].should_erase_source


def test_adapter_resolves_updated_device_token_for_each_request(monkeypatch) -> None:
    token = {"value": None}
    adapter = ServerTranslationAdapter(
        "https://imgtrans.example.test",
        lambda: token["value"],
    )
    with pytest.raises(TranslationError) as captured:
        adapter.translate(("SALE",), "en", "zh-Hans")
    assert captured.value.code == "backend_authentication_required"

    seen = {}

    def open_request(request, timeout):
        del timeout
        seen["authorization"] = dict(request.header_items())["Authorization"]
        return _Response(
            {
                "items": [
                    {
                        "item_id": "item-0",
                        "status": "translated",
                        "translated_text": "促销",
                        "error_code": None,
                        "error_message": None,
                    }
                ]
            }
        )

    monkeypatch.setattr(module, "urlopen", open_request)
    token["value"] = "itd_live_device_token_123456"
    assert adapter.translate(("SALE",), "en", "zh-Hans")[0].translated_text == "促销"
    assert seen["authorization"] == "Bearer itd_live_device_token_123456"


def test_llm_parse_aligns_numbered_lines_and_ignores_preamble() -> None:
    raw = "Here are the translations:\n1. Soft & Smooth\n2. Ultra-thick\n3. Additive-free"
    assert module._parse_llm_translations(raw, 3, ["a", "b", "c"]) == [
        "Soft & Smooth",
        "Ultra-thick",
        "Additive-free",
    ]


def test_llm_parse_fills_missing_lines_with_source_text() -> None:
    raw = "1. Soft & Smooth\n2. Ultra-thick"
    assert module._parse_llm_translations(
        raw, 4, ["柔软细腻", "加厚", "零添加", "洗脸巾"]
    ) == [
        "Soft & Smooth",
        "Ultra-thick",
        "零添加",
        "洗脸巾",
    ]


def test_llm_parse_uses_plain_lines_when_no_numbering() -> None:
    raw = "Soft & Smooth\nUltra-thick"
    assert module._parse_llm_translations(raw, 2, ["a", "b"]) == [
        "Soft & Smooth",
        "Ultra-thick",
    ]


def test_llm_parse_raises_when_no_usable_output() -> None:
    with pytest.raises(RuntimeError):
        module._parse_llm_translations("", 2, ["a", "b"])


def test_ecommerce_translate_uses_dictionary_and_llm_numbered_output() -> None:
    class _LLM:
        def chat(self, messages, max_tokens=None):
            del messages, max_tokens
            return "1. New Arrival"

    adapter = ServerTranslationAdapter(
        "https://imgtrans.example.test",
        "fixture-client-token-123456",
        llm_adapter=_LLM(),
        ecommerce=True,
    )
    result = adapter.translate(("柔软细腻", "新品上市"), None, "en")
    assert [item.translated_text for item in result] == [
        "Soft & Smooth",
        "New Arrival",
    ]


def test_ecommerce_falls_back_to_azure_when_llm_output_unusable(monkeypatch) -> None:
    class _LLM:
        def chat(self, messages, max_tokens=None):
            del messages, max_tokens
            return ""

    captured = {}

    def open_request(request, timeout):
        del timeout
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return _Response(
            {
                "items": [
                    {
                        "item_id": "item-0",
                        "status": "translated",
                        "translated_text": "New arrival",
                        "source_language": "zh-Hans",
                    }
                ]
            }
        )

    monkeypatch.setattr(module, "urlopen", open_request)
    adapter = ServerTranslationAdapter(
        "https://imgtrans.example.test",
        "fixture-client-token-123456",
        llm_adapter=_LLM(),
        ecommerce=True,
    )
    result = adapter.translate(("新品上市",), None, "en")
    assert result[0].translated_text == "New arrival"
    assert captured["body"]["items"][0]["text"] == "新品上市"


def test_ecommerce_override_merges_over_builtin_dictionary() -> None:
    adapter = ServerTranslationAdapter(
        "https://imgtrans.example.test",
        "fixture-client-token-123456",
        llm_adapter=object(),
        ecommerce=True,
        ecommerce_terms={
            "零添加": "Free From Additives",
            "自定义短语": "Custom Phrase",
        },
    )
    result = adapter._ecommerce_translate(
        ("零添加", "自定义短语", "柔软细腻"),
        "en",
    )
    assert [item.translated_text for item in result] == [
        "Free From Additives",
        "Custom Phrase",
        "Soft & Smooth",
    ]


def test_ecommerce_prompt_override_is_used_for_llm() -> None:
    captured = {}

    class _LLM:
        def chat(self, messages, max_tokens=None):
            del max_tokens
            captured["prompt"] = messages[0]["content"]
            return "1. New Arrival"

    adapter = ServerTranslationAdapter(
        "https://imgtrans.example.test",
        "fixture-client-token-123456",
        llm_adapter=_LLM(),
        ecommerce=True,
        ecommerce_prompt="自定义要求：务必使用电商标题风格",
    )
    result = adapter.translate(("新品上市",), None, "en")
    assert result[0].translated_text == "New Arrival"
    assert captured["prompt"].startswith("自定义要求：务必使用电商标题风格")
    assert "待翻译：\n1. 新品上市" in captured["prompt"]


def test_ecommerce_override_can_be_updated_at_runtime() -> None:
    adapter = ServerTranslationAdapter(
        "https://imgtrans.example.test",
        "fixture-client-token-123456",
        llm_adapter=object(),
        ecommerce=True,
    )
    adapter.set_ecommerce_override({"新词": "New Word"}, "新提示词")
    result = adapter._ecommerce_translate(("新词",), "en")
    assert result[0].translated_text == "New Word"


def test_server_detection_filters_mixed_language_regions_after_ocr(monkeypatch) -> None:
    captured = {}

    def open_request(request, timeout):
        del timeout
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return _Response(
            {
                "items": [
                    {
                        "item_id": "item-0",
                        "status": "translated",
                        "translated_text": "Face towels",
                        "source_language": "zh-Hans",
                    },
                    {
                        "item_id": "item-1",
                        "status": "translated",
                        "translated_text": "Existing English",
                        "source_language": "en",
                    },
                ]
            }
        )

    monkeypatch.setattr(module, "urlopen", open_request)
    adapter = ServerTranslationAdapter(
        "https://imgtrans.example.test",
        "fixture-client-token-123456",
    )
    regions = (
        TextRegion(
            "r1",
            order_quad(((0, 0), (100, 0), (100, 30), (0, 30))),
            "洗脸巾",
            1.0,
            "zh-Hans",
            "fixture",
        ),
        TextRegion(
            "r2",
            order_quad(((0, 40), (160, 40), (160, 70), (0, 70))),
            "Existing English",
            1.0,
            "zh-Hans",
            "fixture",
        ),
    )
    result = TranslateRegions(adapter, ProtectionEngine()).execute(
        OcrResult(regions, "zh-Hans", "fixture", 0),
        TranslationSelection(TranslationMode.ALL, "en"),
    )

    assert captured["body"]["source_language"] is None
    assert result.units[0].status is TranslationStatus.TRANSLATED
    assert result.units[0].translated_text == "Face towels"
    assert result.units[1].status is TranslationStatus.SKIPPED_LANGUAGE
    assert result.units[1].translated_text == "Existing English"
    assert not result.units[1].should_erase_source
