import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication, QGraphicsScene

from src.domain.ocr import TextRegion, order_quad
from src.ui.editor.canvas.ocr_item import OcrRegionItem


def test_selected_ocr_region_draws_light_yellow_highlight() -> None:
    QApplication.instance() or QApplication([])
    region = TextRegion(
        "region-0021",
        order_quad(((50, 50), (90, 50), (90, 72), (50, 72))),
        "Eport",
        0.91,
        "en",
        "fixture",
    )
    item = OcrRegionItem(region)
    item.setSelected(True)
    scene = QGraphicsScene()
    scene.setSceneRect(0, 0, 140, 100)
    scene.addItem(item)

    image = QImage(140, 100, QImage.Format.Format_RGB32)
    image.fill(QColor("white"))
    painter = QPainter(image)
    scene.render(painter, QRectF(0, 0, 140, 100), scene.sceneRect())
    painter.end()

    # 选中区域使用淡黄色半透明背景高亮（识别度提升），
    # 填充较淡不会盖住已合成的译文文字。
    color = image.pixelColor(70, 61)
    assert color.red() > 200 and color.green() > 180 and color.blue() < 220

    # 区域外保持白色，无深色/不透明矩形覆盖
    for y in range(30, 49):
        for x in range(20, 121):
            color = image.pixelColor(x, y)
            assert min(color.red(), color.green(), color.blue()) > 200
