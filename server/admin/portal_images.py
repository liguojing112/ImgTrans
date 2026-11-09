"""门户入口图片 — 后台上传图片的保存与公开访问。

图片以 base64 data URL 随表单提交（不引入 multipart 依赖），解码校验后
存到 data/portal-images/，通过 /portal-assets/<name> 静态挂载公开访问。
"""

from __future__ import annotations

import base64
import binascii
import re
from pathlib import Path
from uuid import uuid4

PORTAL_IMAGE_URL_PREFIX = "/portal-assets"
_MAX_BYTES = 2 * 1024 * 1024
_NAME_PATTERN = re.compile(r"^[a-z0-9-]+\.(png|jpg|webp|gif)$")

_IMAGE_DIR = Path(__file__).resolve().parents[2] / "data" / "portal-images"


class PortalImageError(ValueError):
    pass


def portal_images_dir() -> Path:
    _IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    return _IMAGE_DIR


def save_portal_image(data_url: str) -> str:
    """保存 base64 data URL 图片，返回相对访问路径（/portal-assets/xxx）。"""
    header, _, payload = data_url.partition(",")
    encoded = payload.strip() if header.startswith("data:") else data_url.strip()
    if not encoded:
        raise PortalImageError("图片内容为空")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as error:
        raise PortalImageError("图片数据无效") from error
    if not raw:
        raise PortalImageError("图片内容为空")
    if len(raw) > _MAX_BYTES:
        raise PortalImageError("图片不能超过 2 MB")
    extension = _sniff_extension(raw)
    if extension is None:
        raise PortalImageError("仅支持 PNG / JPEG / WebP / GIF 图片")
    filename = f"portal-{uuid4().hex[:12]}{extension}"
    target = portal_images_dir() / filename
    try:
        target.write_bytes(raw)
    except OSError as error:
        raise PortalImageError("图片保存失败") from error
    return f"{PORTAL_IMAGE_URL_PREFIX}/{filename}"


def delete_portal_image(image_url: str) -> None:
    """删除此前上传的图片文件；仅处理本模块生成的相对路径。"""
    if not image_url.startswith(f"{PORTAL_IMAGE_URL_PREFIX}/"):
        return
    name = image_url.rsplit("/", 1)[-1]
    if not _NAME_PATTERN.match(name):
        return
    try:
        (_IMAGE_DIR / name).unlink(missing_ok=True)
    except OSError:
        pass


def _sniff_extension(raw: bytes) -> str | None:
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if raw.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if raw.startswith((b"GIF87a", b"GIF89a")):
        return ".gif"
    if len(raw) > 12 and raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return ".webp"
    return None
