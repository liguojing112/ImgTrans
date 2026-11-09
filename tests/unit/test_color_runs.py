"""片段上色（color_runs）领域与渲染测试。"""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from src.domain.image import ImageAsset, ImageDocument, ImageFileFormat
from src.domain.layout import ColorRun, TextBox, TextLayer, TextLayout, TextStyle
from src.infrastructure.text_renderer import QtTextRenderer


def _background(width: int = 400, height: int = 120) -> ImageDocument:
    asset = ImageAsset(
        Path("color_runs.png"), width, height, 1, ImageFileFormat.PNG, False, False
    )
    return ImageDocument(
        asset, "RGB", np.full((height, width, 3), 255, np.uint8).tobytes()
    )


def _layer(**kw) -> TextLayer:
    defaults = dict(
        region_id="r",
        text="DOUBLE 11 SALE",
        # offscreen 测试环境枚举不到系统字体，Qt 回退字体按 1em/字符 计宽
        box=TextBox(200, 60, 360, 44),
        style=TextStyle("Arial", 20, (0, 0, 0), auto_fit=False),
    )
    defaults.update(kw)
    return TextLayer(**defaults)


def _count_pixels(document: ImageDocument) -> tuple[int, int]:
    """返回 (接近红的像素数, 接近黑的像素数)。"""
    pixels = np.frombuffer(document.pixels, np.uint8).reshape(
        document.asset.height, document.asset.width, 3
    ).astype(np.int16)
    red = ((pixels[:, :, 0] > 150) & (pixels[:, :, 1] < 90) & (pixels[:, :, 2] < 90)).sum()
    dark = ((pixels[:, :, 0] < 60) & (pixels[:, :, 1] < 60) & (pixels[:, :, 2] < 60)).sum()
    return int(red), int(dark)


def test_color_run_rejects_invalid_range_and_color() -> None:
    with pytest.raises(ValueError):
        ColorRun(5, 5, (0, 0, 0))
    with pytest.raises(ValueError):
        ColorRun(5, 2, (0, 0, 0))
    with pytest.raises(ValueError):
        ColorRun(0, 3, (0, 300, 0))


def test_renderer_draws_colored_run() -> None:
    QApplication.instance() or QApplication(["color-runs-render-test"])
    layer = _layer(color_runs=(ColorRun(0, 6, (220, 20, 30)),))
    red, dark = _count_pixels(
        QtTextRenderer().render(_background(), TextLayout((layer,)))
    )
    assert red > 50, "前 6 个字符应渲染为红色"
    assert dark > 50, "其余字符仍为整体黑色"


def test_renderer_without_runs_keeps_single_color() -> None:
    QApplication.instance() or QApplication(["color-runs-render-test"])
    red, dark = _count_pixels(
        QtTextRenderer().render(_background(), TextLayout((_layer(),)))
    )
    assert red == 0
    assert dark > 50


def test_renderer_draws_colored_run_for_multiline_text() -> None:
    """多行文本（含换行符）也要支持局部上色。"""
    QApplication.instance() or QApplication(["color-runs-render-test"])
    layer = _layer(
        text="DOUBLE\nSALE",
        color_runs=(ColorRun(0, 6, (220, 20, 30)),),
    )
    red, _ = _count_pixels(QtTextRenderer().render(_background(), TextLayout((layer,))))
    assert red > 50, "多行文字里被选中的片段也应渲染为红色"


def test_renderer_draws_colored_run_for_wrapped_text() -> None:
    """自动换行的长句（文本宽于文字框）也要支持局部上色。"""
    QApplication.instance() or QApplication(["color-runs-render-test"])
    layer = _layer(
        box=TextBox(200, 60, 140, 100),
        style=TextStyle("Arial", 20, (0, 0, 0), wrap=True, auto_fit=False),
        color_runs=(ColorRun(0, 6, (220, 20, 30)),),
    )
    red, _ = _count_pixels(QtTextRenderer().render(_background(), TextLayout((layer,))))
    assert red > 50, "自动换行后选中片段仍应为红色"


def test_old_pickle_state_without_color_runs_is_healed() -> None:
    """旧版 .edit.gz 的 state 缺 color_runs 槽，读取时应补默认值而非 AttributeError。"""
    layer = _layer(color_runs=(ColorRun(0, 3, (10, 20, 30)),))
    old_state = list(layer.__getstate__())[:-1]
    healed = object.__new__(TextLayer)
    healed.__setstate__(old_state)
    assert healed.color_runs == ()
    assert healed.text == layer.text
    assert healed.mirror_x is False and healed.mirror_y is False
