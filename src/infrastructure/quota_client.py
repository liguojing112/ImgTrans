from __future__ import annotations

from dataclasses import dataclass
import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


_MAX_RESPONSE_BYTES = 64 * 1024


class QuotaError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class QuotaInfo:
    quota_total: int
    quota_remaining: int
    consumed: bool = False


class QuotaClient:
    """商品详情次数额度客户端 — 查询/扣减/解绑。"""

    def __init__(self, base_url: str, timeout_seconds: float = 15.0) -> None:
        parsed = urlsplit(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Backend URL must use HTTP or HTTPS")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Backend URL cannot contain credentials, query or fragment")
        if timeout_seconds <= 0:
            raise ValueError("Quota timeout must be positive")
        self._base = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds

    def get_usage(self, token: str) -> QuotaInfo:
        payload = self._request("/v1/usage", token, None, "GET")
        return _parse_quota(payload)

    def consume(self, token: str) -> QuotaInfo:
        payload = self._request("/v1/usage/consume", token, None, "POST")
        return _parse_quota(payload)

    def unbind(self, activation_code: str) -> bool:
        encoded = json.dumps(
            {"activation_code": activation_code}, separators=(",", ":")
        ).encode("utf-8")
        payload = self._request("/v1/activations/unbind", None, encoded, "POST")
        return bool(isinstance(payload, dict) and payload.get("unbound"))

    def _request(
        self, path: str, token: str | None, data: bytes | None, method: str
    ) -> object:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json; charset=UTF-8",
            "User-Agent": "ImgTrans/0.1",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = Request(self._base + path, data=data, headers=headers, method=method)
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                encoded = response.read(_MAX_RESPONSE_BYTES + 1)
        except HTTPError as error:
            raise QuotaError(_http_code(error.code), _http_message(error.code)) from error
        except (URLError, TimeoutError, OSError) as error:
            raise QuotaError(
                "quota_service_unavailable", "无法连接用量服务，请检查网络后重试"
            ) from error
        if len(encoded) > _MAX_RESPONSE_BYTES:
            raise QuotaError("invalid_quota_response", "用量服务响应无效")
        try:
            return json.loads(encoded.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise QuotaError("invalid_quota_response", "用量服务响应无效") from error


def _parse_quota(payload: object) -> QuotaInfo:
    if not isinstance(payload, dict):
        raise QuotaError("invalid_quota_response", "用量服务响应无效")
    try:
        return QuotaInfo(
            quota_total=int(payload["quota_total"]),
            quota_remaining=int(payload["quota_remaining"]),
            consumed=bool(payload.get("consumed", False)),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise QuotaError("invalid_quota_response", "用量服务响应无效") from error


def _http_code(status: int) -> str:
    if status in {408, 500, 502, 503, 504}:
        return "quota_service_unavailable"
    return "quota_failed"


def _http_message(status: int) -> str:
    if status == 401:
        return "激活码已停用或授权已失效，请重新激活或续费"
    if status in {408, 500, 502, 503, 504}:
        return "用量服务暂时不可用"
    return "用量操作失败，请稍后重试"
