"""门户入口配置 — 客户端从服务端拉取的入口卡片信息（如「万象笔记」）。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PortalModule:
    module_key: str
    title: str
    description: str
    image_url: str
    link_url: str


# 服务端尚未配置时的内置默认：卡片照常显示（无图片、无链接），点击提示未配置
DEFAULT_WANXIANG_NOTE = PortalModule(
    module_key="wanxiang_note",
    title="万象笔记",
    description="记录图文灵感\n上传图文，一键生成分享内容",
    image_url="",
    link_url="",
)
