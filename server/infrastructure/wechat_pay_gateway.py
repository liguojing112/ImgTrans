"""微信支付 API v3 网关 — 基于 wechatpayv3 SDK。

配置通过 provider 动态读取（优先数据库后台配置，其次环境变量），
支持运行期切换，无需重启服务。
"""

from __future__ import annotations

from typing import Callable

from server.domain.payment import PaymentConflict


class WechatPayV3Gateway:
    def __init__(
        self,
        config_provider: Callable[[], dict | None],
    ) -> None:
        self._provider = config_provider
        self._client = None

    def native_prepay(self, order_id: str, amount_minor: int, description: str) -> str:
        response = self._pay().pay(
            description=description,
            out_trade_no=order_id,
            amount={"total": amount_minor, "currency": "CNY"},
        )
        code_url = (response or {}).get("code_url", "")
        if not code_url:
            raise PaymentConflict("微信下单未返回付款二维码")
        return code_url

    def parse_notify(self, body: bytes, headers: dict[str, str]) -> dict:
        result = self._pay().callback(headers, body)
        return result if isinstance(result, dict) else {}

    def _pay(self):
        config = self._provider()
        if not config or not all(
            (
                config.get("appid"),
                config.get("mchid"),
                config.get("apiv3_key"),
                config.get("private_key"),
                config.get("serial_no"),
                config.get("platform_cert"),
                config.get("notify_url"),
            )
        ):
            raise PaymentConflict("微信支付未配置")
        # 配置变化时重建客户端（记录上次配置签名）
        signature = tuple(config[key] for key in ("mchid", "apiv3_key", "serial_no", "notify_url"))
        if self._client is None or getattr(self, "_signature", None) != signature:
            from wechatpayv3 import WeChatPay, WeChatPayType

            self._client = WeChatPay(
                wechatpay_type=WeChatPayType.NATIVE,
                mchid=config["mchid"],
                private_key=config["private_key"],
                cert_serial_no=config["serial_no"],
                apiv3_key=config["apiv3_key"],
                appid=config["appid"],
                notify_url=config["notify_url"],
                cert_dir=None,
            )
            self._signature = signature
        return self._client


class UnavailableWechatGateway:
    """微信支付未配置时的占位实现（兼容旧引用）。"""

    def native_prepay(self, order_id: str, amount_minor: int, description: str) -> str:
        raise PaymentConflict("微信支付未配置")

    def parse_notify(self, body: bytes, headers: dict[str, str]) -> dict:
        raise PaymentConflict("微信支付未配置")
