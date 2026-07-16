from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json

import pytest

import src.infrastructure.activation_client as module
from src.domain.activation import ActivationError
from src.infrastructure.activation_client import HttpActivationClient


class _Response:
    def __init__(self, payload: object) -> None:
        self._encoded = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def read(self, size: int) -> bytes:
        assert size == 64 * 1024 + 1
        return self._encoded


def test_http_activation_client_sends_only_code_and_device_and_parses_grant(monkeypatch) -> None:
    captured = {}
    now = datetime.now(timezone.utc)

    def open_request(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return _Response(
            {
                "status": "active",
                "plan_id": 9,
                "activated_at": now.isoformat(),
                "expires_at": (now + timedelta(days=30)).isoformat(),
                "access_token": "itd_new_device_token_123456",
                "token_type": "Bearer",
            }
        )

    monkeypatch.setattr(module, "urlopen", open_request)
    client = HttpActivationClient("https://api.example.test")
    session = client.activate("IT-ABCD", "imgtrans-device-123456")

    request = captured["request"]
    assert request.full_url == "https://api.example.test/v1/activations/validate"
    assert json.loads(request.data) == {
        "activation_code": "IT-ABCD",
        "device_id": "imgtrans-device-123456",
    }
    assert "Authorization" not in dict(request.header_items())
    assert session.plan_id == 9
    assert session.access_token == "itd_new_device_token_123456"


def test_http_activation_client_rejects_unexpected_response(monkeypatch) -> None:
    monkeypatch.setattr(module, "urlopen", lambda request, timeout: _Response({"status": "active"}))
    with pytest.raises(ActivationError) as captured:
        HttpActivationClient("https://api.example.test").activate(
            "IT-ABCD", "imgtrans-device-123456"
        )
    assert captured.value.code == "invalid_activation_response"

