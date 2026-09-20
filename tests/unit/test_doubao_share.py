"""豆包分享链接解析 — 只取 image_raw（无水印）变体。"""

import pytest

from src.infrastructure.doubao_share import (
    DoubaoShareError,
    fetch_share_page,
    is_share_url,
    parse_share_images,
)

# 结构照搬真实分享页：JSON 嵌在脚本里，斜杠与 & 都是转义形式
_FIXTURE = (
    '{"data":{"creations":['
    '{"gen_detail":{"image":{'
    '"key":"tos-cn-i-a9rns2rl98\\/rc_gen_image\\/aaaa.jpeg",'
    '"image_thumb":{"url":"https:\\/\\/p26-flow-imagex-sign.byteimg.com\\/tos-cn-i-a9rns2rl98'
    '\\/rc_gen_image\\/aaaa.jpeg~tplv-a9rns2rl98-cthumb_wm1.png?lk3s=1&amp;x-signature=AAA%3D",'
    '"width":1536,"height":1536},'
    '"url_formats":{'
    '"png":"https:\\/\\/p3-flow-imagex-sign.byteimg.com\\/tos-cn-i-a9rns2rl98'
    '\\/rc_gen_image\\/aaaa.jpeg~tplv-a9rns2rl98-image_raw.png?lk3s=1&amp;x-signature=RAW1%3D",'
    '"heic":"https:\\/\\/p3-flow-imagex-sign.byteimg.com\\/tos-cn-i-a9rns2rl98'
    '\\/rc_gen_image\\/aaaa.jpeg~tplv-a9rns2rl98-image_raw.heic?lk3s=1&amp;x-signature=RAW2%3D"'
    '}}}},'
    '{"gen_detail":{"image":{'
    '"key":"tos-cn-i-a9rns2rl98\\/rc_gen_image\\/bbbb.jpeg",'
    '"image_thumb":{"url":"https:\\/\\/p26-flow-imagex-sign.byteimg.com\\/tos-cn-i-a9rns2rl98'
    '\\/rc_gen_image\\/bbbb.jpeg~tplv-a9rns2rl98-cdld_wm3.png?lk3s=1&amp;x-signature=WM%3D",'
    '"width":1024,"height":1024},'
    '"url_formats":{'
    '"png":"https:\\/\\/p3-flow-imagex-sign.byteimg.com\\/tos-cn-i-a9rns2rl98'
    '\\/rc_gen_image\\/bbbb.jpeg~tplv-a9rns2rl98-image_raw.png?lk3s=1&amp;x-signature=RAW3%3D"'
    '}}}}]}}'
)


def test_parse_returns_raw_variants_in_order() -> None:
    images = parse_share_images(_FIXTURE)

    assert [image.key.split("/")[-1] for image in images] == ["aaaa.jpeg", "bbbb.jpeg"]
    assert all("-image_raw." in image.url for image in images)
    assert images[0].width == 1536 and images[0].height == 1536
    assert images[1].width == 1024 and images[1].height == 1024


def test_parse_never_returns_watermarked_variant() -> None:
    """带水印的 cthumb_wm1 / cdld_wm3 变体不得出现在结果里。"""
    images = parse_share_images(_FIXTURE)

    urls = " ".join(image.url for image in images)
    assert "wm1" not in urls and "wm3" not in urls
    assert "x-signature=RAW" in urls


def test_parse_prefers_png_over_heic() -> None:
    images = parse_share_images(_FIXTURE)

    assert images[0].url.endswith("x-signature=RAW1%3D")
    assert images[0].url.split("~")[1].startswith("tplv-a9rns2rl98-image_raw.png")


def test_parse_returns_empty_without_raw_variant() -> None:
    assert parse_share_images("<html></html>") == ()


def test_share_url_detection() -> None:
    assert is_share_url("https://www.doubao.com/thread/xzPK9LN590IbmmB2w")
    assert is_share_url("https://doubao.com/thread/abc")
    assert not is_share_url("https://example.com/thread/abc")
    assert not is_share_url("not a url")


def test_non_share_url_is_rejected_before_network() -> None:
    with pytest.raises(DoubaoShareError):
        fetch_share_page("https://example.com/thread/abc")
