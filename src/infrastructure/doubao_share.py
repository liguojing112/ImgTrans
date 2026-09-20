"""豆包分享链接取原图 — 解析分享页数据里的无水印地址。

豆包的水印加在 CDN 的**交付模板**上：APP「下载」走 `cdld_wm3`（带水印），
而分享页数据里同时给出了 `image_raw` 模板的原图地址，取它即可得到无水印原图，
不需要任何图像处理。

两个限制：链接带签名且会过期（解析后应尽快下载）；模板名由平台维护，
平台调整后需要跟着改（解析失败会明确报错，不会静默返回带水印的图）。
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

_MAX_PAGE_BYTES = 8 * 1024 * 1024
_MAX_IMAGE_BYTES = 32 * 1024 * 1024
_TIMEOUT_SECONDS = 30.0
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
_SHARE_HOSTS = ("doubao.com",)
_RAW_URL = re.compile(r"https://[^\"'<>\s\\]*-image_raw\.(?:png|heic)[^\"'<>\s\\]*")
_KEY_IN_JSON = re.compile(r'"key"\s*:\s*"([^"]+)"')
_SIZE_AFTER = re.compile(r'"width"\s*:\s*(\d+)\s*,\s*"height"\s*:\s*(\d+)')
_ESCAPE_PAIRS = (
    ("\\u002F", "/"),
    ("\\u0026", "&"),
    ("\\/", "/"),
    ("&amp;", "&"),
    ('\\"', '"'),
    ("\\&quot;", '"'),
)


class DoubaoShareError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ShareImage:
    url: str
    key: str
    width: int | None = None
    height: int | None = None
    order: int = 0


def is_share_url(value: str) -> bool:
    """是否是受支持的分享链接（目前支持豆包分享页）。"""
    try:
        host = urlsplit(value.strip()).hostname or ""
    except ValueError:
        return False
    return any(host == item or host.endswith("." + item) for item in _SHARE_HOSTS)


def _is_png(url: str) -> bool:
    """PNG 比 HEIC 通用，同一对象的多种格式优先取 PNG。"""
    return urlsplit(url).path.endswith(".png")


def unescape_share_text(html: str) -> str:
    """分享页把 JSON 嵌在脚本里且是**多层转义**，要反复反转义才能看到原始 URL。

    只做一层时 `\\\\"key\\\\":` 会残留成 `\\"key\\":`，字段名匹配不上（尺寸就取不到）。
    """
    text = html
    for _ in range(4):
        before = text
        for source, target in _ESCAPE_PAIRS:
            text = text.replace(source, target)
        if text == before:
            break
    return text


def parse_share_images(html: str) -> tuple[ShareImage, ...]:
    """返回分享页里的无水印原图，按出现顺序；同一对象只保留一张。"""
    text = unescape_share_text(html)
    keys = [match.group(1) for match in _KEY_IN_JSON.finditer(text)]
    images: dict[str, ShareImage] = {}
    for order, match in enumerate(_RAW_URL.finditer(text)):
        url = match.group(0)
        key = urlsplit(url).path.split("~", 1)[0].lstrip("/")
        if not key:
            continue
        existing = images.get(key)
        if existing is not None and (_is_png(existing.url) or not _is_png(url)):
            continue
        width = height = None
        for candidate in keys:
            if not key.endswith(candidate.split("/")[-1]):
                continue
            start = text.find(candidate)
            size = _SIZE_AFTER.search(text, start, start + 2000)
            if size is not None:
                width, height = int(size.group(1)), int(size.group(2))
            break
        images[key] = ShareImage(
            url=url,
            key=key,
            width=width,
            height=height,
            order=order,
        )
    return tuple(sorted(images.values(), key=lambda item: item.order))


def fetch_share_page(url: str, timeout: float = _TIMEOUT_SECONDS) -> str:
    if not is_share_url(url):
        raise DoubaoShareError("请粘贴豆包分享链接（含 doubao.com 的地址）")
    request = Request(url.strip(), headers={"User-Agent": _USER_AGENT})
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = response.read(_MAX_PAGE_BYTES + 1)
    except HTTPError as error:
        raise DoubaoShareError(f"分享页打不开（HTTP {error.code}），请确认链接未过期") from error
    except (URLError, TimeoutError, OSError) as error:
        raise DoubaoShareError(f"无法访问分享页：{error}") from error
    if len(payload) > _MAX_PAGE_BYTES:
        raise DoubaoShareError("分享页内容过大，无法解析")
    return payload.decode("utf-8", errors="ignore")


def fetch_share_images(url: str, timeout: float = _TIMEOUT_SECONDS) -> tuple[ShareImage, ...]:
    images = parse_share_images(fetch_share_page(url, timeout))
    if not images:
        raise DoubaoShareError("这个链接里没有解析到无水印原图（可能是链接已过期或平台调整了地址）")
    return images


def download_image(url: str, timeout: float = _TIMEOUT_SECONDS) -> bytes:
    request = Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = response.read(_MAX_IMAGE_BYTES + 1)
    except HTTPError as error:
        raise DoubaoShareError(f"图片下载失败（HTTP {error.code}），链接可能已过期") from error
    except (URLError, TimeoutError, OSError) as error:
        raise DoubaoShareError(f"图片下载失败：{error}") from error
    if len(payload) > _MAX_IMAGE_BYTES:
        raise DoubaoShareError("图片体积过大，已跳过")
    if not payload:
        raise DoubaoShareError("图片内容为空")
    return payload
