from __future__ import annotations

from dataclasses import dataclass


class PortalError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class PortalModule:
    """客户端门户入口配置（如首页「万象笔记」卡片）。

    link_url 打开内嵌浏览器；image_url/title/description 用于首页卡片展示。
    """

    module_key: str
    title: str
    description: str
    image_url: str
    link_url: str
    enabled: bool = True

    def __post_init__(self) -> None:
        if not self.module_key.strip():
            raise PortalError("Module key cannot be empty")
        if not self.title.strip():
            raise PortalError("Module title cannot be empty")
        image = self.image_url.strip()
        if image and not image.startswith(("http://", "https://", "/")):
            raise PortalError("Module image URL must use HTTP, HTTPS or a site path")
        link = self.link_url.strip()
        if link and not link.startswith(("http://", "https://")):
            raise PortalError("Module link URL must use HTTP or HTTPS")
