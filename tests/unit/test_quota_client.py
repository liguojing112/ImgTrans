from __future__ import annotations

import json

import pytest

import src.infrastructure.quota_client as module
from src.infrastructure.quota_client import QuotaClient, QuotaError


class _Response:
    def __init__(self, payload: object) -> None:
        self._payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def read(self, size):
        return self._payload


def _client(monkeypatch, payload: object) -> tuple[QuotaClient, dict]:
    captured: dict = {}

    def open_request(request, timeout):
        captured["url"] = request.full_url
        captured["method"] = request.get_method()
        captured["body"] = request.data
        captured["auth"] = request.headers.get("Authorization")
        return _Response(payload)

    monkeypatch.setattr(module, "urlopen", open_request)
    return QuotaClient("https://api.example.test/root"), captured


def test_get_watermark_parses_usage(monkeypatch) -> None:
    client, captured = _client(
        monkeypatch,
        {
            "watermark_daily_limit": 5,
            "watermark_used_today": 2,
            "watermark_remaining": 3,
        },
    )
    info = client.get_watermark("itd_token")
    assert info == (
        module.WatermarkQuota(daily_limit=5, used_today=2, remaining=3)
    )
    assert captured["url"] == "https://api.example.test/root/v1/usage/watermark"
    assert captured["method"] == "GET"
    assert captured["auth"] == "Bearer itd_token"


def test_consume_watermark_sends_amount(monkeypatch) -> None:
    client, captured = _client(
        monkeypatch,
        {
            "consumed": True,
            "watermark_daily_limit": 5,
            "watermark_used_today": 4,
            "watermark_remaining": 1,
        },
    )
    info = client.consume_watermark("itd_token", amount=3)
    assert info.consumed is True
    assert info.remaining == 1
    assert captured["url"].endswith("/v1/usage/watermark/consume")
    assert captured["method"] == "POST"
    assert json.loads(captured["body"]) == {"amount": 3}


def test_consume_watermark_defaults_to_one(monkeypatch) -> None:
    client, captured = _client(
        monkeypatch,
        {
            "consumed": True,
            "watermark_daily_limit": 5,
            "watermark_used_today": 1,
            "watermark_remaining": 4,
        },
    )
    client.consume_watermark("itd_token")
    assert json.loads(captured["body"]) == {"amount": 1}


def test_watermark_invalid_payload_rejected(monkeypatch) -> None:
    client, _ = _client(monkeypatch, {"watermark_daily_limit": 5})
    with pytest.raises(QuotaError):
        client.get_watermark("itd_token")
