from __future__ import annotations

from datetime import datetime
import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from src.domain.activation import ActivationError, ActivationSession


_MAX_RESPONSE_BYTES = 64 * 1024


class HttpActivationClient:
    def __init__(self, base_url: str, timeout_seconds: float = 15.0) -> None:
        parsed = urlsplit(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Backend URL must use HTTP or HTTPS")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Backend URL cannot contain credentials, query or fragment")
        if timeout_seconds <= 0:
            raise ValueError("Activation timeout must be positive")
        self._url = f"{base_url.rstrip('/')}/v1/activations/validate"
        self._timeout_seconds = timeout_seconds

    def activate(self, activation_code: str, device_id: str) -> ActivationSession:
        encoded = json.dumps(
            {"activation_code": activation_code, "device_id": device_id},
            separators=(",", ":"),
        ).encode("utf-8")
        request = Request(
            self._url,
            data=encoded,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json; charset=UTF-8",
                "User-Agent": "ImgTrans/0.1",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                payload = response.read(_MAX_RESPONSE_BYTES + 1)
        except HTTPError as error:
            raise ActivationError(
                _http_error_code(error.code),
                _http_error_message(error.code),
            ) from error
        except (URLError, TimeoutError, OSError) as error:
            raise ActivationError(
                "activation_service_unavailable",
                "无法连接激活服务，请检查网络后重试",
            ) from error
        if len(payload) > _MAX_RESPONSE_BYTES:
            raise ActivationError(
                "invalid_activation_response",
                "激活服务响应无效",
            )
        return _parse_response(payload)


def _parse_response(encoded: bytes) -> ActivationSession:
    try:
        payload = json.loads(encoded.decode("utf-8"))
        if not isinstance(payload, dict) or set(payload) != {
            "status",
            "plan_id",
            "activated_at",
            "expires_at",
            "access_token",
            "token_type",
        }:
            raise ValueError
        if payload["status"] != "active" or payload["token_type"] != "Bearer":
            raise ValueError
        return ActivationSession(
            plan_id=payload["plan_id"],
            activated_at=datetime.fromisoformat(payload["activated_at"].replace("Z", "+00:00")),
            expires_at=datetime.fromisoformat(payload["expires_at"].replace("Z", "+00:00")),
            access_token=payload["access_token"],
        )
    except (UnicodeDecodeError, ValueError, TypeError, KeyError, json.JSONDecodeError) as error:
        raise ActivationError(
            "invalid_activation_response",
            "激活服务响应无效",
        ) from error


def _http_error_code(status: int) -> str:
    if status in {403, 409, 422}:
        return "activation_denied"
    if status == 429:
        return "activation_rate_limited"
    if status in {408, 500, 502, 503, 504}:
        return "activation_service_unavailable"
    return "activation_failed"


def _http_error_message(status: int) -> str:
    if status in {403, 409, 422}:
        return "激活码无效、已停用或已绑定其他设备"
    if status == 429:
        return "激活尝试过于频繁，请稍后重试"
    return "激活服务暂时不可用"

