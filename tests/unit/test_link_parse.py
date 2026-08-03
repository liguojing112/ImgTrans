"""链接解析单元测试。"""

from __future__ import annotations

import urllib.error

import pytest

from src.application.link_parse import (
    LinkParseError,
    LinkParser,
    detect_platform,
    _extract_attributes,
    _MetaParser,
)


class TestDetectPlatform:
    def test_amazon(self):
        assert detect_platform("https://www.amazon.com/dp/B0XXXX") == "Amazon"

    def test_aliexpress(self):
        assert detect_platform("https://www.aliexpress.com/item/123.html") == "AliExpress"

    def test_taobao(self):
        assert detect_platform("https://item.taobao.com/item.htm?id=1") == "淘宝"

    def test_tmall(self):
        assert detect_platform("https://detail.tmall.com/item.htm?id=1") == "天猫"

    def test_jd(self):
        assert detect_platform("https://item.jd.com/1000123.html") == "京东"

    def test_unknown_platform(self):
        assert detect_platform("https://example.com/product/1") == ""


class TestMetaParser:
    def test_og_tags(self):
        html = """
        <html><head>
        <meta property="og:title" content="测试商品标题">
        <meta property="og:description" content="商品描述内容">
        <meta property="og:image" content="https://img.example.com/main.jpg">
        </head><body></body></html>
        """
        parser = _MetaParser()
        parser.feed(html)
        assert parser.og["title"] == "测试商品标题"
        assert parser.og["description"] == "商品描述内容"
        assert parser.og["image"] == "https://img.example.com/main.jpg"

    def test_title_and_images(self):
        html = """
        <html><head><title>页面标题</title></head>
        <body>
        <img src="https://img.example.com/a.jpg">
        <img data-src="https://img.example.com/b.jpg">
        </body></html>
        """
        parser = _MetaParser()
        parser.feed(html)
        assert parser.title == "页面标题"
        assert parser.images == [
            "https://img.example.com/a.jpg",
            "https://img.example.com/b.jpg",
        ]

    def test_meta_description_fallback(self):
        html = '<meta name="description" content="描述A">'
        parser = _MetaParser()
        parser.feed(html)
        assert parser.og["description"] == "描述A"


class TestExtractAttributes:
    def test_extract_brand_and_material(self):
        html = "品牌：ABC 材质:纯棉 规格：30片/包"
        attrs = _extract_attributes(html)
        assert attrs["品牌"] == "ABC"
        assert attrs["材质"] == "纯棉"
        assert attrs["规格"] == "30片/包"

    def test_no_match(self):
        assert _extract_attributes("<html>无属性</html>") == {}


class TestLinkParserValidation:
    def test_empty_url(self):
        with pytest.raises(LinkParseError, match="请输入商品链接"):
            LinkParser().parse("   ")

    def test_invalid_url(self):
        with pytest.raises(LinkParseError, match="链接格式不正确"):
            LinkParser().parse("not a url")

    def test_unsupported_scheme(self):
        with pytest.raises(LinkParseError, match="链接格式不正确"):
            LinkParser().parse("ftp://example.com/file")


class TestChallengeDetection:
    def test_x5sec_challenge(self):
        assert LinkParser._is_challenge_page(
            '<script>window._config_ = {"action":"captcha"...}</script>')
        assert LinkParser._is_challenge_page(
            '<html>x5secdata=xxxxx</html>')
        assert LinkParser._is_challenge_page(
            '<html>window.location.replace("/punish?x5step=1")</html>')

    def test_normal_page(self):
        assert not LinkParser._is_challenge_page(
            '<html><head><title>正常商品页</title></head></html>')


class TestBuildResult:
    def test_build_result_extracts_fields(self):
        html = """
        <html><head>
        <title>无线耳机 - Amazon</title>
        <meta property="og:title" content="无线降噪耳机">
        <meta property="og:description" content="高品质降噪">
        <meta property="og:image" content="https://img.example.com/a.jpg">
        </head><body>
        <img src="https://img.example.com/b.jpg">
        品牌：Sony
        </body></html>
        """
        result = LinkParser()._build_result(
            "https://www.amazon.com/dp/B0TEST", html, "Amazon")
        assert result.title == "无线降噪耳机"
        assert result.description == "高品质降噪"
        assert result.images[0] == "https://img.example.com/a.jpg"
        assert result.attributes["品牌"] == "Sony"

    def test_build_result_strips_platform_suffix(self):
        html = '<title>商品标题 - 拼多多</title>'
        result = LinkParser()._build_result(
            "https://mobile.yangkeduo.com/goods.html", html, "拼多多")
        assert result.title == "商品标题"


class TestBrowserExtractDom:
    def test_extract_title_and_images(self):
        html = """
        <html><head><title>加厚洗脸巾 30片 - 拼多多</title></head>
        <body>
        <img src="https://t00img.yangkeduo.com/goods1.jpg">
        <div style="background-image:url('https://t00img.yangkeduo.com/goods2.jpg')">
        </div></body></html>
        """
        result = LinkParser._browser_extract_dom(
            "https://mobile.yangkeduo.com/goods.html", "拼多多", html)
        assert "加厚洗脸巾" in result.title
        assert "https://t00img.yangkeduo.com/goods1.jpg" in result.images
        assert "https://t00img.yangkeduo.com/goods2.jpg" in result.images


class TestImageUrlDetection:
    def test_detect_direct_image_links(self):
        assert LinkParser().parse(
            "https://cbu01.alicdn.com/img/ibank/O1CN01QjsaBx2KwTaEelKJt.jpg").images == [
            "https://cbu01.alicdn.com/img/ibank/O1CN01QjsaBx2KwTaEelKJt.jpg"]
        assert LinkParser().parse(
            "https://img.example.com/product.png").images == [
            "https://img.example.com/product.png"]

    def test_image_url_skips_http_fetch(self, monkeypatch):
        import src.application.link_parse as lp
        fetched = []

        def fake_urlopen(req, timeout=None):
            fetched.append(req.full_url)
            return _FakeResponse(b"should not be called")

        monkeypatch.setattr(lp.urllib.request, "urlopen", fake_urlopen)

        result = LinkParser().parse(
            "https://img.example.com/photo.webp")
        assert result.images == ["https://img.example.com/photo.webp"]
        assert len(fetched) == 0  # 不应触发 HTTP 请求


class TestPlatformBrowserRouting:
    """平台白名单强制走浏览器渲染。"""

    def test_pinduoduo_skips_http_goes_to_browser(self, monkeypatch):
        import src.application.link_parse as lp
        calls = []

        def fake_browser_parse(self, url, platform, headless=False):
            calls.append((url, platform))
            return lp.LinkParseResult(url=url, platform=platform,
                                      title="浏览器解析的标题")

        monkeypatch.setattr(lp.LinkParser, "_parse_with_browser",
                            fake_browser_parse)

        result = LinkParser().parse(
            "https://mobile.yangkeduo.com/goods.html?goods_id=123")
        assert result.title == "浏览器解析的标题"
        # 拼多多应跳过 HTTP 直接走浏览器
        assert len(calls) == 1

    def test_1688_skips_http_goes_to_browser(self, monkeypatch):
        import src.application.link_parse as lp

        def fake_browser_parse(self, url, platform, headless=False):
            return lp.LinkParseResult(url=url, platform=platform,
                                      title="1688商品")

        monkeypatch.setattr(lp.LinkParser, "_parse_with_browser",
                            fake_browser_parse)

        result = LinkParser().parse(
            "https://detail.1688.com/offer/1068864463531.html")
        assert result.title == "1688商品"

    def test_amazon_uses_http_path(self, monkeypatch):
        """Amazon 等平台走 HTTP 快速通道。"""
        import src.application.link_parse as lp

        def fake_urlopen(req, timeout=None):
            return _FakeResponse(
                '<html><head><meta property="og:title" content="Amazon商品">'
                '</head><body></body></html>'.encode())

        monkeypatch.setattr(lp.urllib.request, "urlopen", fake_urlopen)

        result = LinkParser().parse("https://www.amazon.com/dp/B0TEST")
        assert result.title == "Amazon商品"


class TestLinkParserFetch:
    """mock 网络请求验证解析流程。"""

    def test_parse_success(self, monkeypatch):
        html = """
        <html><head>
        <title>无线耳机 - Amazon</title>
        <meta property="og:title" content="无线降噪耳机">
        <meta property="og:description" content="高品质无线耳机，降噪功能">
        <meta property="og:image" content="https://img.example.com/headphone.jpg">
        </head><body>
        <img src="//img.example.com/detail1.jpg">
        品牌：Sony 材质：塑料
        </body></html>
        """
        captured = {}

        def fake_urlopen(req, timeout=None):
            captured["url"] = req.full_url
            captured["headers"] = req.headers
            return _FakeResponse(html.encode("utf-8"))

        import src.application.link_parse as lp
        monkeypatch.setattr(lp.urllib.request, "urlopen", fake_urlopen)

        result = LinkParser().parse("https://www.amazon.com/dp/B0TEST")
        assert result.platform == "Amazon"
        assert result.title == "无线降噪耳机"
        assert result.description == "高品质无线耳机，降噪功能"
        assert result.images[0] == "https://img.example.com/headphone.jpg"
        assert result.images[1] == "https://img.example.com/detail1.jpg"
        assert result.attributes["品牌"] == "Sony"
        assert captured["url"] == "https://www.amazon.com/dp/B0TEST"
        assert "Mozilla" in captured["headers"]["User-agent"]

    def test_parse_http_403_falls_back_to_browser(self, monkeypatch):
        """403 反爬 → 自动降级到浏览器渲染。"""
        def fake_urlopen(req, timeout=None):
            raise urllib.error.HTTPError(req.full_url, 403, "Forbidden",
                                         {}, None)

        import src.application.link_parse as lp
        monkeypatch.setattr(lp.urllib.request, "urlopen", fake_urlopen)

        calls = []

        def fake_browser_parse(self, url, platform, headless=False):
            calls.append((url, platform, headless))
            return lp.LinkParseResult(url=url, platform=platform,
                                      title="浏览器解析的标题")

        monkeypatch.setattr(lp.LinkParser, "_parse_with_browser",
                            fake_browser_parse)

        result = LinkParser().parse("https://www.amazon.com/dp/B0TEST")
        assert result.title == "浏览器解析的标题"
        assert len(calls) == 1

    def test_parse_http_403_browser_also_fails(self, monkeypatch):
        def fake_urlopen(req, timeout=None):
            raise urllib.error.HTTPError(req.full_url, 403, "Forbidden",
                                         {}, None)

        import src.application.link_parse as lp
        monkeypatch.setattr(lp.urllib.request, "urlopen", fake_urlopen)

        def fake_browser_parse(self, url, platform, headless=False):
            raise lp.LinkParseError("浏览器也无法访问")

        monkeypatch.setattr(lp.LinkParser, "_parse_with_browser",
                            fake_browser_parse)

        with pytest.raises(LinkParseError):
            LinkParser().parse("https://www.amazon.com/dp/B0TEST")

    def test_parse_http_404(self, monkeypatch):
        def fake_urlopen(req, timeout=None):
            raise urllib.error.HTTPError(req.full_url, 404, "Not Found",
                                         {}, None)

        import src.application.link_parse as lp
        monkeypatch.setattr(lp.urllib.request, "urlopen", fake_urlopen)

        with pytest.raises(LinkParseError, match="404"):
            LinkParser().parse("https://www.amazon.com/dp/B0MISSING")

    def test_parse_network_error(self, monkeypatch):
        def fake_urlopen(req, timeout=None):
            raise urllib.error.URLError("Connection refused")

        import src.application.link_parse as lp
        monkeypatch.setattr(lp.urllib.request, "urlopen", fake_urlopen)

        with pytest.raises(LinkParseError, match="链接无法访问"):
            LinkParser().parse("https://example.com/product/1")


class _FakeResponse:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def read(self, n: int = -1) -> bytes:
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False
