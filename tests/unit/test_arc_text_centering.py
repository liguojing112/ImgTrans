from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication

from src.domain.layout import (
    ArcTextPath,
    TextBox,
    TextLayer,
    TextStyle,
    default_arc_path,
)
from src.infrastructure.text_renderer import draw_arc_layer_preview


def test_arc_text_is_vertically_centered_on_its_box() -> None:
    """弧形文字应在识别框内垂直居中（基线贴弧线会让整块明显偏高）。"""
    QApplication.instance() or QApplication(["arc-centering-test"])
    box = TextBox(100, 60, 120, 20)
    arc = default_arc_path(box, 0.35)
    layer = TextLayer(
        "r",
        "COTTON",
        box,
        TextStyle("Arial", 14, (0, 0, 0)),
        path=ArcTextPath(arc.start, arc.control, arc.end, False),
    )

    image = QImage(220, 140, QImage.Format.Format_ARGB32)
    image.fill(0xFFFFFFFF)
    painter = QPainter(image)
    try:
        draw_arc_layer_preview(painter, layer)
    finally:
        painter.end()

    pixels = np.frombuffer(image.constBits(), dtype=np.uint8).reshape(140, 220, 4)
    rows = np.where((pixels[:, :, 0] < 100).any(axis=1))[0]
    assert len(rows) > 0
    ink_center = (rows.min() + rows.max()) / 2
    assert abs(ink_center - box.center_y) <= 5
