"""HttpPortalConfigClient — 拉取服务端门户入口配置（/v1/portal-modules）。"""

from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from uuid import uuid4

from src.domain.portal import PortalModule

_MAX_CONFIG_BYTES = 64 * 1024


class PortalConfigError(RuntimeError):
    pass


class HttpPortalConfigClient:
    def __init__(self, base_url: str, timeout_seconds: float = 5.0) -> None:
        parsed = urlsplit(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Backend URL must use HTTP or HTTPS")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Backend URL cannot contain credentials, query or fragment")
        if timeout_seconds <= 0:
            raise ValueError("Portal config timeout must be positive")
        self._url = f"{base_url.rstrip('/')}/v1/portal-modules"
        self._timeout_seconds = timeout_seconds

    def fetch(self) -> tuple[PortalModule, ...]:
        request = Request(
            self._url,
            headers={
                "Accept": "application/json",
                "User-Agent": "ImgTrans/0.1",
                "X-Correlation-ID": uuid4().hex,
            },
            method="GET",
        )
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                content_length = response.headers.get("Content-Length")
                if content_length and int(content_length) > _MAX_CONFIG_BYTES:
                    raise PortalConfigError("门户配置响应过大")
                encoded = response.read(_MAX_CONFIG_BYTES + 1)
        except HTTPError as error:
            raise PortalConfigError(
                f"门户配置服务返回 HTTP {error.code}"
            ) from error
        except (URLError, OSError, ValueError) as error:
            raise PortalConfigError("无法连接门户配置服务") from error
        if len(encoded) > _MAX_CONFIG_BYTES:
            raise PortalConfigError("门户配置响应过大")
        return parse_portal_modules(encoded)


def parse_portal_modules(encoded: bytes) -> tuple[PortalModule, ...]:
    """解析 /v1/portal-modules 响应；字段缺失或类型错误时抛 PortalConfigError。"""
    try:
        payload = json.loads(encoded.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as error:
        raise PortalConfigError("门户配置响应无效") from error
    if not isinstance(payload, dict) or not isinstance(
        payload.get("modules"), list
    ):
        raise PortalConfigError("门户配置响应无效")
    modules: list[PortalModule] = []
    for item in payload["modules"]:
        if not isinstance(item, dict):
            raise PortalConfigError("门户配置响应无效")
        try:
            module = PortalModule(
                module_key=str(item["module_key"]),
                title=str(item["title"]),
                description=str(item.get("description") or ""),
                image_url=str(item.get("image_url") or ""),
                link_url=str(item.get("link_url") or ""),
            )
        except KeyError as error:
            raise PortalConfigError("门户配置响应无效") from error
        modules.append(module)
    return tuple(modules)
