"""第三方服务配置管理用例 — 微信支付密钥加密存储、不回显。"""

from __future__ import annotations

from server.infrastructure.secrets_cipher import SecretsCipher
from server.infrastructure.service_settings_repository import (
    ServiceSettingsRow,
    SqlAlchemyServiceSettingsRepository,
)

# 支付回调 URL 固定写死，不允许在后台修改
DEFAULT_WECHAT_NOTIFY_URL = "https://imgtrans.rchtop.top/v1/payments/notify"


class ManageServiceSettings:
    def __init__(
        self,
        cipher: SecretsCipher,
        repository: SqlAlchemyServiceSettingsRepository,
        notify_url: str = DEFAULT_WECHAT_NOTIFY_URL,
    ) -> None:
        self._cipher = cipher
        self._repository = repository
        self._notify_url = notify_url

    def get_public(self) -> dict:
        """后台/客户端可见的公开配置 — 敏感字段只返回是否已配置。"""
        row = self._repository.load()
        if row is None:
            return {
                "wechat_appid": "",
                "wechat_mchid": "",
                "wechat_serial_no": "",
                "wechat_notify_url": self._notify_url,
                "wechat_apiv3_key_configured": False,
                "wechat_private_key_configured": False,
                "wechat_platform_cert_configured": False,
                "wechat_pay_configured": False,
            }
        return {
            "wechat_appid": row.wechat_appid or "",
            "wechat_mchid": row.wechat_mchid or "",
            "wechat_serial_no": row.wechat_serial_no or "",
            "wechat_notify_url": self._notify_url,
            "wechat_apiv3_key_configured": bool(row.wechat_apiv3_key_cipher),
            "wechat_private_key_configured": bool(row.wechat_private_key_cipher),
            "wechat_platform_cert_configured": bool(row.wechat_platform_cert_cipher),
            "wechat_pay_configured": self._is_complete(row),
        }

    def save_wechat(self, values: dict) -> dict:
        """保存微信配置。敏感字段提交为空字符串则保留原值；返回公开配置。"""
        current = self._repository.load()
        row = ServiceSettingsRow(
            wechat_appid=_strip(values.get("wechat_appid", "")),
            wechat_mchid=_strip(values.get("wechat_mchid", "")),
            wechat_apiv3_key_cipher=self._encrypt_or_keep(
                values.get("wechat_apiv3_key", ""),
                current.wechat_apiv3_key_cipher if current else None,
            ),
            wechat_private_key_cipher=self._encrypt_or_keep(
                values.get("wechat_private_key", ""),
                current.wechat_private_key_cipher if current else None,
            ),
            wechat_serial_no=_strip(values.get("wechat_serial_no", "")),
            wechat_platform_cert_cipher=self._encrypt_or_keep(
                values.get("wechat_platform_cert", ""),
                current.wechat_platform_cert_cipher if current else None,
            ),
            # 回调 URL 固定写死，忽略表单提交值
            wechat_notify_url=self._notify_url,
        )
        self._repository.save(row)
        return self.get_public()

    def load_wechat_settings(self) -> dict | None:
        """解密出完整微信配置，供支付网关使用；未配置/解密失败返回 None。"""
        row = self._repository.load()
        if row is None or not row.wechat_apiv3_key_cipher:
            return None
        try:
            config = {
                "appid": row.wechat_appid,
                "mchid": row.wechat_mchid,
                "apiv3_key": self._cipher.decrypt(row.wechat_apiv3_key_cipher),
                "private_key": self._cipher.decrypt(row.wechat_private_key_cipher),
                "serial_no": row.wechat_serial_no,
                "platform_cert": self._cipher.decrypt(row.wechat_platform_cert_cipher),
                "notify_url": self._notify_url,
            }
        except ValueError:
            return None
        if not all(config.values()):
            return None
        return config

    def _encrypt_or_keep(self, raw: str, current_cipher: str | None) -> str | None:
        stripped = raw.strip()
        if stripped:
            return self._cipher.encrypt(stripped)
        return current_cipher

    @staticmethod
    def _is_complete(row: ServiceSettingsRow) -> bool:
        return bool(
            row.wechat_appid
            and row.wechat_mchid
            and row.wechat_apiv3_key_cipher
            and row.wechat_private_key_cipher
            and row.wechat_serial_no
            and row.wechat_platform_cert_cipher
        )


def _strip(value: str) -> str:
    return value.strip()
