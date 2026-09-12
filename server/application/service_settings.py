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
                "wechat_public_key_id": "",
                "wechat_apiv3_key_configured": False,
                "wechat_private_key_configured": False,
                "wechat_platform_cert_configured": False,
                "wechat_pay_configured": False,
                "glm_configured": False,
                "glm_model": "",
                "glm_base_url": "",
            }
        return {
            "wechat_appid": row.wechat_appid or "",
            "wechat_mchid": row.wechat_mchid or "",
            "wechat_serial_no": row.wechat_serial_no or "",
            "wechat_notify_url": self._notify_url,
            "wechat_public_key_id": row.wechat_public_key_id or "",
            "wechat_apiv3_key_configured": bool(row.wechat_apiv3_key_cipher),
            "wechat_private_key_configured": bool(row.wechat_private_key_cipher),
            "wechat_platform_cert_configured": bool(row.wechat_platform_cert_cipher),
            "wechat_pay_configured": self._is_complete(row),
            "glm_configured": bool(row.glm_api_key_cipher),
            "glm_model": row.glm_model or "",
            "glm_base_url": row.glm_base_url or "",
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
            wechat_public_key_id=_strip(values.get("wechat_public_key_id", "")),
            # 回调 URL 固定写死，忽略表单提交值
            wechat_notify_url=self._notify_url,
            glm_api_key_cipher=current.glm_api_key_cipher if current else None,
            glm_model=current.glm_model if current else None,
            glm_base_url=current.glm_base_url if current else None,
        )
        self._repository.save(row)
        return self.get_public()

    def save_glm(self, values: dict) -> dict:
        """保存 GLM（商品详情生成）配置。API 密钥留空则保留原值；返回公开配置。"""
        current = self._repository.load()
        if current is None:
            current = ServiceSettingsRow()
        row = ServiceSettingsRow(
            wechat_appid=current.wechat_appid,
            wechat_mchid=current.wechat_mchid,
            wechat_apiv3_key_cipher=current.wechat_apiv3_key_cipher,
            wechat_private_key_cipher=current.wechat_private_key_cipher,
            wechat_serial_no=current.wechat_serial_no,
            wechat_platform_cert_cipher=current.wechat_platform_cert_cipher,
            wechat_public_key_id=current.wechat_public_key_id,
            wechat_notify_url=self._notify_url,
            glm_api_key_cipher=self._encrypt_or_keep(
                values.get("glm_api_key", ""),
                current.glm_api_key_cipher,
            ),
            glm_model=_strip(values.get("glm_model", "")),
            glm_base_url=_strip(values.get("glm_base_url", "")),
        )
        self._repository.save(row)
        return self.get_public()

    def load_glm_settings(self) -> dict | None:
        """解密出 GLM 配置供网关使用；未配置/解密失败返回 None。"""
        row = self._repository.load()
        if row is None or not row.glm_api_key_cipher:
            return None
        try:
            api_key = self._cipher.decrypt(row.glm_api_key_cipher)
        except ValueError:
            return None
        if not api_key:
            return None
        return {
            "api_key": api_key,
            "model": row.glm_model or "",
            "base_url": row.glm_base_url or "",
        }

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
                "private_key": _normalize_pem(
                    self._cipher.decrypt(row.wechat_private_key_cipher)
                ),
                "serial_no": row.wechat_serial_no,
                "platform_cert": _normalize_pem(
                    self._cipher.decrypt(row.wechat_platform_cert_cipher)
                ),
                "public_key_id": row.wechat_public_key_id or "",
                "notify_url": self._notify_url,
            }
        except ValueError:
            return None
        if not all(config.values()):
            return None
        return config

    def _encrypt_or_keep(self, raw: str, current_cipher: str | None) -> str | None:
        stripped = _normalize_pem(raw.strip())
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
            and row.wechat_public_key_id
        )


def _strip(value: str) -> str:
    return value.strip()


def _normalize_pem(value: str) -> str:
    """PEM 统一用 LF 行尾 — wechatpayv3 解析私钥不兼容 CRLF（`\r` 混入 base64 导致失败）。"""
    return value.replace("\r\n", "\n").replace("\r", "\n")
