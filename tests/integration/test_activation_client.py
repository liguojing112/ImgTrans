from __future__ import annotations

from datetime import datetime, timedelta, timezone
import io
import json
from urllib.error import HTTPError

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
                "quota_total": 100,
                "quota_remaining": 100,
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
    assert session.quota_total == 100
    assert session.quota_remaining == 100


def test_http_activation_client_status_parses_active(monkeypatch) -> None:
    captured = {}

    def open_request(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return _Response({"active": True})

    monkeypatch.setattr(module, "urlopen", open_request)
    client = HttpActivationClient("https://api.example.test")
    assert client.status("IT-ABCD", "imgtrans-device-123456") is True

    request = captured["request"]
    assert request.full_url == "https://api.example.test/v1/activations/status"
    assert json.loads(request.data) == {
        "activation_code": "IT-ABCD",
        "device_id": "imgtrans-device-123456",
    }


def test_http_activation_client_status_rejects_invalid_payload(monkeypatch) -> None:
    monkeypatch.setattr(
        module, "urlopen", lambda request, timeout: _Response({"active": "yes"})
    )
    with pytest.raises(ActivationError) as captured:
        HttpActivationClient("https://api.example.test").status(
            "IT-ABCD", "imgtrans-device-123456"
        )
    assert captured.value.code == "invalid_activation_response"


def test_http_activation_client_rejects_unexpected_response(monkeypatch) -> None:
    monkeypatch.setattr(module, "urlopen", lambda request, timeout: _Response({"status": "active"}))
    with pytest.raises(ActivationError) as captured:
        HttpActivationClient("https://api.example.test").activate(
            "IT-ABCD", "imgtrans-device-123456"
        )
    assert captured.value.code == "invalid_activation_response"


def _http_error(monkeypatch, status: int, detail: object) -> None:
    def open_request(request, timeout):
        body = json.dumps({"detail": detail}).encode("utf-8")
        raise HTTPError(request.full_url, status, "error", {}, io.BytesIO(body))

    monkeypatch.setattr(module, "urlopen", open_request)


def test_http_activation_client_maps_expired_detail_to_chinese(monkeypatch) -> None:
    _http_error(monkeypatch, 422, "Activation code has expired")
    with pytest.raises(ActivationError) as captured:
        HttpActivationClient("https://api.example.test").activate(
            "IT-ABCD", "imgtrans-device-123456"
        )
    assert captured.value.code == "activation_denied"
    assert str(captured.value) == "激活码已到期，请续期或更换激活码"


def test_http_activation_client_maps_mismatch_detail_to_chinese(monkeypatch) -> None:
    _http_error(
        monkeypatch, 422, "Activation code is already bound to another device"
    )
    with pytest.raises(ActivationError) as captured:
        HttpActivationClient("https://api.example.test").activate(
            "IT-ABCD", "imgtrans-device-123456"
        )
    assert str(captured.value) == "激活码已绑定其他设备，请先解绑再激活"


def test_http_activation_client_keeps_generic_message_for_unknown_detail(monkeypatch) -> None:
    _http_error(monkeypatch, 422, "Something unexpected")
    with pytest.raises(ActivationError) as captured:
        HttpActivationClient("https://api.example.test").activate(
            "IT-ABCD", "imgtrans-device-123456"
        )
    assert str(captured.value) == "激活码无效、已停用或已绑定其他设备"


def test_http_activation_client_ignores_non_json_error_body(monkeypatch) -> None:
    def open_request(request, timeout):
        raise HTTPError(
            request.full_url, 500, "error", {}, io.BytesIO(b"<html>oops</html>")
        )

    monkeypatch.setattr(module, "urlopen", open_request)
    with pytest.raises(ActivationError) as captured:
        HttpActivationClient("https://api.example.test").activate(
            "IT-ABCD", "imgtrans-device-123456"
        )
    assert captured.value.code == "activation_service_unavailable"
    assert str(captured.value) == "激活服务暂时不可用"

