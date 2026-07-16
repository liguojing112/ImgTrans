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
