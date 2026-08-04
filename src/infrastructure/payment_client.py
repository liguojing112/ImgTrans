from __future__ import annotations

from dataclasses import dataclass
import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


_MAX_RESPONSE_BYTES = 64 * 1024


class PaymentError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class PayablePlan:
    plan_id: int
    name: str
    amount_minor: int
    currency: str
    duration_days: int
    plan_type: str = "duration"
    quota: int = 0
    sale_amount_minor: int | None = None
    sale_ends_at: str | None = None
    benefits: str = ""
    is_on_sale: bool = False


@dataclass(frozen=True, slots=True)
class PaymentOrderInfo:
    order_id: str
    code_url: str
    amount_minor: int
    currency: str
    status: str
    activation_code: str | None = None


class PaymentClient:
    def __init__(self, base_url: str, timeout_seconds: float = 15.0) -> None:
        parsed = urlsplit(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Backend URL must use HTTP or HTTPS")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Backend URL cannot contain credentials, query or fragment")
        if timeout_seconds <= 0:
            raise ValueError("Payment timeout must be positive")
        self._base = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds

    def list_plans(self) -> list[PayablePlan]:
        payload = self._get("/v1/payments/plans")
        if not isinstance(payload, list):
            raise PaymentError("invalid_payment_response", "套餐服务响应无效")
        return [
            PayablePlan(
                plan_id=item["plan_id"],
                name=item["name"],
                amount_minor=item["amount_minor"],
                currency=item["currency"],
                duration_days=item["duration_days"],
                plan_type=item.get("plan_type", "duration"),
                quota=item.get("quota", 0),
                sale_amount_minor=item.get("sale_amount_minor"),
                sale_ends_at=item.get("sale_ends_at"),
                benefits=item.get("benefits", ""),
                is_on_sale=item.get("is_on_sale", False),
            )
            for item in payload
        ]

    def create_order(self, plan_id: int) -> PaymentOrderInfo:
        payload = self._post("/v1/payments/orders", {"plan_id": plan_id})
        return _parse_order(payload)

    def poll_order(self, order_id: str) -> PaymentOrderInfo:
        payload = self._get(f"/v1/payments/orders/{order_id}")
        return _parse_order(payload)

    def _get(self, path: str) -> object:
        return self._request(path, None, "GET")

    def _post(self, path: str, body: dict) -> object:
        encoded = json.dumps(body, separators=(",", ":")).encode("utf-8")
        return self._request(path, encoded, "POST")

    def _request(self, path: str, data: bytes | None, method: str) -> object:
        request = Request(
            self._base + path,
            data=data,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json; charset=UTF-8",
                "User-Agent": "ImgTrans/0.1",
            },
            method=method,
        )
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                encoded = response.read(_MAX_RESPONSE_BYTES + 1)
        except HTTPError as error:
            raise PaymentError(_http_code(error.code), _http_message(error.code)) from error
        except (URLError, TimeoutError, OSError) as error:
            raise PaymentError(
                "payment_service_unavailable", "无法连接支付服务，请检查网络后重试"
            ) from error
        if len(encoded) > _MAX_RESPONSE_BYTES:
            raise PaymentError("invalid_payment_response", "支付服务响应无效")
        try:
            return json.loads(encoded.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise PaymentError("invalid_payment_response", "支付服务响应无效") from error


def _parse_order(payload: object) -> PaymentOrderInfo:
    if not isinstance(payload, dict):
        raise PaymentError("invalid_payment_response", "支付服务响应无效")
    try:
        return PaymentOrderInfo(
            order_id=payload["order_id"],
            code_url=payload.get("code_url", ""),
            amount_minor=payload["amount_minor"],
            currency=payload["currency"],
            status=payload["status"],
            activation_code=payload.get("activation_code"),
        )
    except (KeyError, TypeError) as error:
        raise PaymentError("invalid_payment_response", "支付服务响应无效") from error


def _http_code(status: int) -> str:
    if status in {408, 500, 502, 503, 504}:
        return "payment_service_unavailable"
    return "payment_failed"


def _http_message(status: int) -> str:
    if status in {408, 500, 502, 503, 504}:
        return "支付服务暂时不可用"
    return "支付操作失败，请稍后重试"
