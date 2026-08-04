"""微信支付 API v3 网关 — 基于 wechatpayv3 SDK。

SDK 懒加载：仅在真实配置并首次调用时导入，避免未安装时影响启动。
业务层通过 application.payment 的 WechatPayGateway Protocol 依赖倒置。
"""

from __future__ import annotations

from server.domain.payment import PaymentConflict


class WechatPayV3Gateway:
    def __init__(self, settings) -> None:
        self._settings = settings
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
        if self._client is None:
            from wechatpayv3 import WeChatPay, WeChatPayType

            self._client = WeChatPay(
                wechatpay_type=WeChatPayType.NATIVE,
                mchid=self._settings.wechat_mchid,
                private_key=self._settings.wechat_private_key,
                cert_serial_no=self._settings.wechat_serial_no,
                apiv3_key=self._settings.wechat_apiv3_key,
                appid=self._settings.wechat_appid,
                notify_url=self._settings.wechat_notify_url,
                cert_dir=None,
            )
        return self._client


class UnavailableWechatGateway:
    """微信支付未配置时的占位实现。"""

    def native_prepay(self, order_id: str, amount_minor: int, description: str) -> str:
        raise PaymentConflict("微信支付未配置")

    def parse_notify(self, body: bytes, headers: dict[str, str]) -> dict:
        raise PaymentConflict("微信支付未配置")
