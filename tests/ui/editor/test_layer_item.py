from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QGraphicsScene

from src.domain.layout import TextBox, TextLayer, TextStyle
from src.ui.editor.canvas.layer_item import TextLayerItem


def _layer(region_id: str, center_y: float) -> TextLayer:
    return TextLayer(
        region_id,
        "A",
        TextBox(100, center_y, 160, 30),
        TextStyle("Microsoft YaHei", 18, (0, 0, 0)),
    )


def test_selected_layer_is_raised_above_overlapping_layers() -> None:
    """两层文字重叠时，选中的那层要置顶，控制点不被另一层盖住。"""
    app = QApplication.instance() or QApplication(["layer-item-zorder-test"])
    scene = QGraphicsScene()
    lower = TextLayerItem(_layer("lower", 100), 0)
    upper = TextLayerItem(_layer("upper", 110), 1)
    scene.addItem(lower)
    scene.addItem(upper)

    lower.setSelected(True)
    assert lower.zValue() > upper.zValue()

    lower.setSelected(False)
    assert lower.zValue() == upper.zValue()
