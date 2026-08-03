"""商品链接解析用例 — 提取商品标题、描述、主图等信息。

第一版使用标准库（urllib + html.parser）实现，不引入新依赖。
支持平台白名单：Amazon / AliExpress / Shopee / Lazada / 淘宝 / 天猫 / 京东 / 1688。
原理：读取页面 HTML 中的 Open Graph (og:) 元标签和 img 标签，
无法解析动态渲染（JS）内容的平台会返回基础信息。
"""

from __future__ import annotations

import html as html_lib
import re
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

# 支持平台白名单（域名关键词 → 平台名）
_SUPPORTED_PLATFORMS: dict[str, str] = {
    "amazon": "Amazon",
    "aliexpress": "AliExpress",
    "shopee": "Shopee",
    "lazada": "Lazada",
    "taobao": "淘宝",
    "tmall": "天猫",
    "jd.com": "京东",
    "1688.com": "1688",
    "yangkeduo.com": "拼多多",
    "pinduoduo.com": "拼多多",
    "pddpic.com": "拼多多",
}

_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".svg"}

_HTTP_TIMEOUT = 15  # 秒
_MAX_HTML_BYTES = 2 * 1024 * 1024  # 最多读取 2MB HTML

# 以下平台 HTTP 抓取无法拿到商品数据（JS 渲染/登录墙/验证码），强制走浏览器
_NEEDS_BROWSER_PLATFORMS = {"拼多多", "淘宝", "天猫", "1688", "京东"}

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


class LinkParseError(Exception):
    """链接解析错误。"""


@dataclass
class LinkParseResult:
    """链接解析结果。"""

    url: str
    platform: str = ""  # 平台名称
    title: str = ""  # 商品标题
    description: str = ""  # 商品描述
    images: list[str] = field(default_factory=list)  # 图片 URL 列表
    attributes: dict[str, str] = field(default_factory=dict)  # 属性/规格


def _is_image_url(url: str) -> bool:
    """检测是否为直接图片链接。"""
    path = urlparse(url).path.lower()
    for ext in _IMAGE_EXTENSIONS:
        if path.endswith(ext):
            return True
    return False


class _MetaParser(HTMLParser):
    """提取 og: 元标签、title、img 的 HTML 解析器。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.og: dict[str, str] = {}
        self.title: str = ""
        self.images: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        attr_dict = dict(attrs)
        if tag == "meta":
            prop = attr_dict.get("property") or attr_dict.get("name") or ""
            content = attr_dict.get("content", "")
            if prop.lower().startswith("og:"):
                key = prop.lower()[3:]
                self.og[key] = content.strip()
            elif prop.lower() == "description" and content.strip():
                self.og.setdefault("description", content.strip())
        elif tag == "img":
            src = attr_dict.get("src") or attr_dict.get("data-src") or ""
            if src:
                self.images.append(src)

    def handle_data(self, data: str) -> None:
        if not self.title:
            self.title = data.strip()[:200]


def detect_platform(url: str) -> str:
    """根据 URL 域名识别平台。未知平台返回空字符串。"""
    host = (urlparse(url).netloc or "").lower()
    for keyword, name in _SUPPORTED_PLATFORMS.items():
        if keyword in host:
            return name
    return ""


def _fetch_html(url: str) -> str:
    """抓取页面 HTML。"""
    req = urllib.request.Request(url, headers={
        "User-Agent": _USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    })
    try:
        with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as resp:
            raw = resp.read(_MAX_HTML_BYTES)
            return raw.decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        if e.code in (403, 429):
            raise LinkParseError("登录或反爬限制：该页面拒绝了访问请求") from e
        if e.code == 404:
            raise LinkParseError("链接无法访问：页面不存在 (404)") from e
        raise LinkParseError(f"链接无法访问：HTTP {e.code}") from e
    except urllib.error.URLError as e:
        reason = getattr(e, "reason", e)
        raise LinkParseError(f"链接无法访问：{reason}") from e


def _absolute_url(base: str, src: str) -> str:
    if src.startswith("//"):
        return "https:" + src
    if src.startswith("data:"):
        return src
    return urljoin(base, src)


def _extract_attributes(html_text: str) -> dict[str, str]:
    """从 HTML 中提取常见商品属性（品牌/材质/规格等）。"""
    attrs: dict[str, str] = {}
    patterns = [
        ("品牌", r"品牌[^<]{0,20}?[:：]\s*([^<\n]{1,40}?)(?=\s*(?:材质|规格|型号|颜色|品牌)[:：]|\s*<|$)"),
        ("材质", r"材质[^<]{0,20}?[:：]\s*([^<\n]{1,40}?)(?=\s*(?:品牌|规格|型号|颜色|材质)[:：]|\s*<|$)"),
        ("规格", r"规格[^<]{0,20}?[:：]\s*([^<\n]{1,40}?)(?=\s*(?:品牌|材质|型号|颜色|规格)[:：]|\s*<|$)"),
        ("型号", r"型号[^<]{0,20}?[:：]\s*([^<\n]{1,40}?)(?=\s*(?:品牌|材质|规格|颜色|型号)[:：]|\s*<|$)"),
        ("颜色", r"颜色[^<]{0,20}?[:：]\s*([^<\n]{1,40}?)(?=\s*(?:品牌|材质|规格|型号|颜色)[:：]|\s*<|$)"),
    ]
    for key, pattern in patterns:
        match = re.search(pattern, html_text)
        if match:
            value = html_lib.unescape(match.group(1)).strip()
            if value:
                attrs[key] = value
    return attrs


class LinkParser:
    """商品链接解析器。

    流程：纯 HTTP 抓取 → 提取失败或遇到反爬验证页时，
    自动降级到 Playwright 真实浏览器渲染。
    1688 等平台的验证码无法自动通过时，弹出有头浏览器让用户手动验证。
    """

    def __init__(self, on_challenge: Callable[[str], None] | None = None) -> None:
        """on_challenge: 检测到验证码/登录墙、需要用户人工操作时回调
        （在后台线程中调用，回调需自行处理线程安全）。"""
        self._on_challenge = on_challenge

    def parse(self, url: str) -> LinkParseResult:
        url = url.strip()
        if not url:
            raise LinkParseError("请输入商品链接")
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise LinkParseError("链接格式不正确，请检查 URL")

        platform = detect_platform(url)

        # 图片链接直接返回 URL 用于下载，不走 HTML 解析
        if _is_image_url(url):
            return LinkParseResult(url=url, platform=platform, images=[url])

        # 1) 纯 HTTP 抓取（平台需浏览器渲染的跳过，HTTP 永远拿不到商品数据）
        if platform not in _NEEDS_BROWSER_PLATFORMS:
            try:
                html_text = _fetch_html(url)
                if not self._is_challenge_page(html_text):
                    result = self._build_result(url, html_text, platform)
                    if result.title or result.images or result.description:
                        return result
            except LinkParseError as e:
                challenge_hint = "反爬" in str(e)
                if not challenge_hint:
                    raise
                # 反爬限制 → 降级到浏览器

        # 2) Playwright 渲染（无头）
        try:
            return self._parse_with_browser(url, platform)
        except LinkParseError:
            raise
        except Exception as e:
            raise LinkParseError(f"浏览器解析失败: {e}") from e

    @staticmethod
    def _is_challenge_page(html_text: str) -> bool:
        """检测是否为反爬验证页（1688 x5sec / 通用 captcha）。"""
        low = html_text.lower()
        markers = ["x5sec", "punish", "captcha", "verify",
                   "window._config_", "slide verify", "geetest"]
        return any(m in low for m in markers)

    @staticmethod
    def _is_login_page(page) -> bool:
        """检测是否为登录墙（拼多多强制手机登录）。"""
        try:
            title = page.title() or ""
            if "登录" in title and len(title) < 10:
                return True
            # 拼多多登录页特征
            body = page.evaluate("document.body ? document.body.innerText.slice(0, 200) : ''")
            if "打开拼多多APP" in body and "手机登录" in body:
                return True
        except Exception:
            return False
        return False

    def _build_result(self, url: str, html_text: str,
                      platform: str) -> LinkParseResult:
        parser = _MetaParser()
        parser.feed(html_text)

        # 标题：og:title > 页面 title
        title = parser.og.get("title", "") or parser.title
        title = html_lib.unescape(title).strip()
        # 清理平台后缀（如 "- Amazon.cn"）
        title = re.sub(
            r"\s*[-–—|]\s*(Amazon|AliExpress|淘宝网|京东|Shopee|Lazada|拼多多)\s*$",
            "", title, flags=re.IGNORECASE).strip()

        description = parser.og.get("description", "")
        description = html_lib.unescape(description).strip()

        # 图片：og:image > 页面 img 标签
        images: list[str] = []
        og_image = parser.og.get("image", "")
        if og_image:
            images.append(_absolute_url(url, og_image))
        for src in parser.images:
            abs_url = _absolute_url(url, src)
            if abs_url not in images and abs_url.startswith("http"):
                images.append(abs_url)
            if len(images) >= 8:
                break

        attributes = _extract_attributes(html_text)

        return LinkParseResult(
            url=url,
            platform=platform,
            title=title,
            description=description,
            images=images,
            attributes=attributes,
        )

    def _parse_with_browser(self, url: str, platform: str) -> LinkParseResult:
        """Playwright 渲染页面。无头模式；若页面仍在验证态则转有头人工验证。"""
        try:
            return self._browser_parse(url, platform, headless=True)
        except _ChallengePending:
            return self._browser_parse(url, platform, headless=False)

    def _browser_parse(self, url: str, platform: str,
                       headless: bool) -> LinkParseResult:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=headless)
            try:
                context = browser.new_context(
                    user_agent=_USER_AGENT,
                    locale="zh-CN",
                    viewport={"width": 1280, "height": 900},
                )
                page = context.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=45_000)
                try:
                    page.wait_for_load_state("networkidle", timeout=10_000)
                except Exception:
                    pass  # 网络空闲等待超时不影响继续

                # 等待页面内容稳定（最多 12s）
                for _ in range(24):
                    try:
                        html_text = page.content()
                    except Exception:
                        page.wait_for_timeout(500)
                        continue
                    blocked = (self._is_challenge_page(html_text)
                               or self._is_login_page(page))
                    if blocked and not headless:
                        # 有头模式下等待用户手动完成验证/登录，最长 120s
                        print("[LinkParser] 检测到验证码或登录墙，"
                              "请在弹出的浏览器中完成验证/登录...")
                        if self._on_challenge:
                            self._on_challenge(
                                "检测到验证码或登录墙：请在浏览器窗口中"
                                "完成验证/登录，完成后自动继续解析")
                        waited = 0
                        while waited < 120:
                            page.wait_for_timeout(3000)
                            waited += 3
                            try:
                                cur = page.content()
                            except Exception:
                                continue
                            if not (self._is_challenge_page(cur)
                                    or self._is_login_page(page)):
                                # 验证完成后等待商品数据加载
                                try:
                                    page.wait_for_load_state(
                                        "networkidle", timeout=10_000)
                                except Exception:
                                    pass
                                page.wait_for_timeout(2000)
                                try:
                                    html_text = page.content()
                                except Exception:
                                    continue
                                break
                        else:
                            raise LinkParseError(
                                "验证/登录超时：未能在 120 秒内完成")
                        break
                    if not blocked:
                        # 无头模式或阻塞解除：等待页面导航完成再提取内容
                        try:
                            page.wait_for_load_state("networkidle", timeout=8_000)
                        except Exception:
                            pass
                        if platform in _NEEDS_BROWSER_PLATFORMS:
                            page.wait_for_timeout(60_000)  # 1 分钟
                        else:
                            page.wait_for_timeout(3_000)
                        # 页面可能还在跳转，重试提取内容
                        html_text = ""
                        for _ in range(10):
                            try:
                                html_text = page.content()
                                break
                            except Exception:
                                page.wait_for_timeout(2000)
                        if not html_text:
                            raise LinkParseError("页面内容提取失败：页面持续导航中")
                        break
                    page.wait_for_timeout(500)
                else:
                    if headless:
                        raise _ChallengePending()
                    raise LinkParseError("页面持续处于验证状态，无法解析")

                browser.close()

                result = self._build_result(url, html_text, platform)
                # 无头渲染后如果仍是站点通用页（拼多多），提取动态 DOM 信息
                if not result.title or not result.images:
                    result = self._browser_extract_dom(url, platform, html_text)
                return result
            finally:
                browser.close()

    @staticmethod
    def _browser_extract_dom(url: str, platform: str,
                             html_text: str) -> LinkParseResult:
        """从渲染后的 DOM 中提取商品信息（拼多多等 SPA 页面）。"""
        result = LinkParseResult(url=url, platform=platform)
        title_match = re.search(
            r'<title[^>]*>([^<]{1,300})</title>', html_text, re.IGNORECASE)
        if title_match:
            result.title = html_lib.unescape(title_match.group(1)).strip()
        desc_match = re.search(
            r'<meta[^>]*name="description"[^>]*content="([^"]*)"',
            html_text, re.IGNORECASE)
        if desc_match:
            result.description = html_lib.unescape(desc_match.group(1)).strip()

        # 图片：img src + background-image
        images = re.findall(r'<img[^>]*src="(https?[^"]+)"', html_text)
        images += re.findall(
            r'background-image:\s*url\(["\']?(https?[^"\'()]+)', html_text)
        seen = set()
        for src in images:
            if src in seen:
                continue
            seen.add(src)
            result.images.append(src)
            if len(result.images) >= 8:
                break
        return result


class _ChallengePending(Exception):
    """无头模式下遇到验证页，需要转有头模式人工验证。"""
