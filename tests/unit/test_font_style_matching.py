"""按原图匹配字体风格（衬线 / 无衬线）测试。"""

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont
from PySide6.QtWidgets import QApplication

from src.domain.image import ImageAsset, ImageDocument, ImageFileFormat
from src.domain.ocr import OcrResult, TextRegion, order_quad
from src.domain.translation import (
    TranslationMode,
    TranslationResult,
    TranslationSelection,
    TranslationStatus,
    TranslationUnit,
)
from src.infrastructure.text_renderer import QtBasicTextLayoutAdapter, _estimate_serif
from src.platform.fonts import FontResolution, _select_style_font

_SIMSUN = "C:/Windows/Fonts/simsun.ttc"
_SIMHEI = "C:/Windows/Fonts/simhei.ttf"


def _text_document(font_path: str | None = None) -> ImageDocument:
    if font_path is None:
        pixels = np.full((90, 420, 3), 245, dtype=np.uint8)
    else:
        image = Image.new("L", (420, 90), 245)
        draw = ImageDraw.Draw(image)
        draw.text((10, 10), "食品工厂", font=ImageFont.truetype(font_path, 44), fill=0)
        pixels = np.stack([np.array(image)] * 3, axis=-1)
    asset = ImageAsset(
        Path("style.png"), 420, 90, 1, ImageFileFormat.PNG, False, False
    )
    return ImageDocument(asset, "RGB", pixels.tobytes())


def _region() -> TextRegion:
    return TextRegion(
        "r1",
        order_quad(((8, 6), (400, 6), (400, 80), (8, 80))),
        "食品工厂",
        0.95,
        "zh-Hans",
        "fixture",
    )


def _ocr(region: TextRegion) -> OcrResult:
    return OcrResult((region,), "zh-Hans", "fixture", 1)


def _translation(text: str = "FOOD FACTORY") -> TranslationResult:
    return TranslationResult(
        (
            TranslationUnit(
                "r1",
                "食品工厂",
                "zh-Hans",
                "en",
                text,
                TranslationStatus.TRANSLATED,
            ),
        ),
        TranslationSelection(TranslationMode.ALL, "en"),
        "fixture",
        1,
    )


@pytest.mark.skipif(
    not Path(_SIMSUN).is_file() or not Path(_SIMHEI).is_file(),
    reason="需要 Windows 中文字体做合成测试",
)
def test_estimate_serif_distinguishes_songti_from_heiti() -> None:
    """宋体（横细竖粗）判为衬线；黑体判为无衬线。"""
    QApplication.instance() or QApplication(["font-style-test"])
    assert _estimate_serif(_text_document(_SIMSUN), _region()) is True
    assert _estimate_serif(_text_document(_SIMHEI), _region()) is False


def test_estimate_serif_rejects_tiny_regions() -> None:
    """小字号区域噪声大，保守判为无衬线。"""
    QApplication.instance() or QApplication(["font-style-test"])
    image = Image.new("L", (420, 90), 245)
    draw = ImageDraw.Draw(image)
    if not Path(_SIMSUN).is_file():
        pytest.skip("需要 Windows 中文字体")
    draw.text((10, 30), "食品工厂", font=ImageFont.truetype(_SIMSUN, 14), fill=0)
    pixels = np.stack([np.array(image)] * 3, axis=-1)
    asset = ImageAsset(
        Path("tiny.png"), 420, 90, 1, ImageFileFormat.PNG, False, False
    )
    document = ImageDocument(asset, "RGB", pixels.tobytes())
    tiny_region = TextRegion(
        "r1",
        order_quad(((8, 30), (80, 30), (80, 48), (8, 48))),
        "食品工厂",
        0.95,
        "zh-Hans",
        "fixture",
    )
    assert _estimate_serif(document, tiny_region) is False


def test_select_style_font_prefers_serif_and_falls_back() -> None:
    resolution = _select_style_font(
        "zh-Hans", "Windows", ("Microsoft YaHei UI", "SimSun")
    )
    assert resolution.family == "SimSun"
    assert not resolution.degraded

    fallback = _select_style_font("zh-Hans", "Windows", ("Microsoft YaHei UI",))
    assert fallback.family == "Microsoft YaHei UI"

    english = _select_style_font("en", "Windows", ("Segoe UI", "Times New Roman"))
    assert english.family == "Times New Roman"


def test_adapter_uses_serif_family_when_classifier_says_serif(monkeypatch) -> None:
    import src.infrastructure.text_renderer as renderer_module

    QApplication.instance() or QApplication(["font-style-test"])
    calls: list = []
    monkeypatch.setattr(
        renderer_module, "_estimate_font_style", lambda document, region: "serif"
    )
    monkeypatch.setattr(
        renderer_module,
        "resolve_style_font_details",
        lambda language, serif: calls.append((language, serif))
        or FontResolution(language, "SerifFixture", False, None),
    )
    adapter = QtBasicTextLayoutAdapter()
    layout = adapter.layout(_text_document(), _ocr(_region()), _translation())

    assert calls == [("en", True)]
    assert layout.layers[0].style.font_family == "SerifFixture"


def test_adapter_skips_source_matching_when_user_font_selected(monkeypatch) -> None:
    import src.infrastructure.text_renderer as renderer_module

    QApplication.instance() or QApplication(["font-style-test"])
    called: list = []
    monkeypatch.setattr(
        renderer_module,
        "_estimate_font_style",
        lambda document, region: called.append(1) or "serif",
    )
    adapter = QtBasicTextLayoutAdapter("Arial")
    layout = adapter.layout(_text_document(), _ocr(_region()), _translation())

    assert called == []
    assert layout.layers[0].style.font_family == "Arial"


def test_adapter_respects_match_source_font_switch(monkeypatch) -> None:
    import src.infrastructure.text_renderer as renderer_module

    QApplication.instance() or QApplication(["font-style-test"])
    seen: list = []
    monkeypatch.setattr(
        renderer_module, "_estimate_font_style", lambda document, region: "serif"
    )
    monkeypatch.setattr(
        renderer_module,
        "resolve_style_font_details",
        lambda language, serif: seen.append(serif)
        or FontResolution(language, "AnyFixture", False, None),
    )
    adapter = QtBasicTextLayoutAdapter()
    adapter.set_match_source_font(False)
    adapter.layout(_text_document(), _ocr(_region()), _translation())

    assert seen == [False]


def test_font_match_preferences_default_true_and_roundtrip(tmp_path) -> None:
    from src.infrastructure.user_preferences import JsonFontMatchPreferences

    prefs = JsonFontMatchPreferences(tmp_path / "prefs.json")
    assert prefs.load() is True
    prefs.save(False)
    assert JsonFontMatchPreferences(tmp_path / "prefs.json").load() is False


def test_adapter_prefers_loaded_font_for_plain_text(monkeypatch) -> None:
    """自动匹配首选字体：无衬线场景使用用户载入的字体。"""
    import src.infrastructure.text_renderer as renderer_module

    QApplication.instance() or QApplication(["font-style-test"])
    monkeypatch.setattr(
        renderer_module, "_estimate_font_style", lambda document, region: "sans"
    )
    adapter = QtBasicTextLayoutAdapter()
    adapter.set_preferred_font("MyLoadedFont")
    layout = adapter.layout(_text_document(), _ocr(_region()), _translation())

    assert layout.layers[0].style.font_family == "MyLoadedFont"


def test_adapter_preferred_font_does_not_override_serif(monkeypatch) -> None:
    """衬线场景仍按原图风格匹配，不被首选字体覆盖。"""
    import src.infrastructure.text_renderer as renderer_module

    QApplication.instance() or QApplication(["font-style-test"])
    monkeypatch.setattr(
        renderer_module, "_estimate_font_style", lambda document, region: "serif"
    )
    monkeypatch.setattr(
        renderer_module,
        "resolve_style_font_details",
        lambda language, serif: FontResolution(language, "SerifFixture", False, None),
    )
    adapter = QtBasicTextLayoutAdapter()
    adapter.set_preferred_font("MyLoadedFont")
    layout = adapter.layout(_text_document(), _ocr(_region()), _translation())

    assert layout.layers[0].style.font_family == "SerifFixture"


def test_user_font_beats_preferred_font(monkeypatch) -> None:
    """手动指定的译文字体优先级最高。"""
    import src.infrastructure.text_renderer as renderer_module

    QApplication.instance() or QApplication(["font-style-test"])
    monkeypatch.setattr(
        renderer_module, "_estimate_font_style", lambda document, region: "sans"
    )
    adapter = QtBasicTextLayoutAdapter("Arial")
    adapter.set_preferred_font("MyLoadedFont")
    layout = adapter.layout(_text_document(), _ocr(_region()), _translation())

    assert layout.layers[0].style.font_family == "Arial"


def test_auto_font_preferences_roundtrip(tmp_path) -> None:
    from src.infrastructure.user_preferences import JsonAutoFontPreferences

    prefs = JsonAutoFontPreferences(tmp_path / "prefs.json")
    assert prefs.load() is None
    prefs.save("SourcedHan")
    assert JsonAutoFontPreferences(tmp_path / "prefs.json").load() == "SourcedHan"
    prefs.save(None)
    assert JsonAutoFontPreferences(tmp_path / "prefs.json").load() is None


def test_estimate_font_style_detects_kai_song_and_sans() -> None:
    """三分类：楷体→kai，宋体→serif，黑体→sans（大字号）。"""
    from src.infrastructure.text_renderer import _estimate_font_style

    QApplication.instance() or QApplication(["font-style-test"])
    assert _estimate_font_style(_text_document(_SIMSUN), _region()) == "serif"
    assert _estimate_font_style(_text_document(_SIMHEI), _region()) == "sans"


def test_estimate_font_style_detects_kaiti() -> None:
    kaiti = "C:/Windows/Fonts/simkai.ttf"
    if not Path(kaiti).is_file():
        pytest.skip("需要 Windows 楷体字体")
    from src.infrastructure.text_renderer import _estimate_font_style

    QApplication.instance() or QApplication(["font-style-test"])
    assert _estimate_font_style(_text_document(kaiti), _region()) == "kai"


def test_resolve_kai_font_prefers_user_font() -> None:
    from src.platform.fonts import resolve_kai_font_details

    resolution = resolve_kai_font_details("zh-Hans", "MyKaiFont")
    assert resolution.family == "MyKaiFont"


def test_adapter_uses_kai_font_when_classifier_says_kai(monkeypatch) -> None:
    import src.infrastructure.text_renderer as renderer_module

    QApplication.instance() or QApplication(["font-style-test"])
    calls: list = []
    monkeypatch.setattr(
        renderer_module, "_estimate_font_style", lambda document, region: "kai"
    )
    monkeypatch.setattr(
        renderer_module,
        "resolve_kai_font_details",
        lambda language, preferred: calls.append((language, preferred))
        or FontResolution(language, "KaiFixture", False, None),
    )
    adapter = QtBasicTextLayoutAdapter()
    adapter.set_kai_font("MyKaiFont")
    layout = adapter.layout(_text_document(), _ocr(_region()), _translation())

    assert calls == [("en", "MyKaiFont")]
    assert layout.layers[0].style.font_family == "KaiFixture"


def test_adapter_kai_disabled_falls_back_to_default(monkeypatch) -> None:
    import src.infrastructure.text_renderer as renderer_module

    QApplication.instance() or QApplication(["font-style-test"])
    seen: list = []
    monkeypatch.setattr(
        renderer_module, "_estimate_font_style", lambda document, region: "kai"
    )
    monkeypatch.setattr(
        renderer_module,
        "resolve_style_font_details",
        lambda language, serif: seen.append(serif)
        or FontResolution(language, "SansFixture", False, None),
    )
    adapter = QtBasicTextLayoutAdapter()
    adapter.set_kai_recognition(False)
    layout = adapter.layout(_text_document(), _ocr(_region()), _translation())

    assert seen == [False]
    assert layout.layers[0].style.font_family == "SansFixture"


def test_kai_preferences_roundtrip(tmp_path) -> None:
    from src.infrastructure.user_preferences import (
        JsonKaiFontPreferences,
        JsonKaiRecognitionPreferences,
    )

    font_prefs = JsonKaiFontPreferences(tmp_path / "prefs.json")
    assert font_prefs.load() is None
    font_prefs.save("MyKai")
    assert JsonKaiFontPreferences(tmp_path / "prefs.json").load() == "MyKai"

    recognition = JsonKaiRecognitionPreferences(tmp_path / "prefs.json")
    assert recognition.load() is True
    recognition.save(False)
    assert JsonKaiRecognitionPreferences(tmp_path / "prefs.json").load() is False
