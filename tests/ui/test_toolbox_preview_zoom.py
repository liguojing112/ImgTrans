"""图片工具箱预览 — 缩放/平移交互测试（与翻译画布一致：滚轮缩放 + 拖拽移动 + 双击复位）。"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import QApplication

from src.ui.toolbox.widgets.watermark_preview import InteractivePreview


def _make_preview(
    qtbot, width=400, height=300, img_w=800, img_h=600
) -> InteractivePreview:
    QApplication.instance() or QApplication(["toolbox-preview-zoom-test"])
    w = InteractivePreview()
    w.resize(width, height)
    pix = QPixmap(img_w, img_h)
    pix.fill(QColor(120, 120, 200))
    w.set_image(pix)
    qtbot.addWidget(w)
    return w


def test_default_is_fit_centered(qtbot):
    w = _make_preview(qtbot)
    rect = w._image_draw_rect()
    cr = w.contentsRect()
    assert rect is not None
    # zoom=1, pan=0 → 图片居中于内容区
    assert abs(rect.center().x() - cr.center().x()) <= 1
    assert abs(rect.center().y() - cr.center().y()) <= 1
    fw, fh = w._fit_size()
    assert rect.width() == fw
    assert rect.height() == fh
    assert w.zoom_factor() == 1.0


def test_zoom_about_increases_display_size(qtbot):
    w = _make_preview(qtbot)
    fit_w = w._fit_size()[0]
    base_rect = w._image_draw_rect()
    w._zoom_about(QPoint(200, 150), 1.5)
    assert abs(w.zoom_factor() - 1.5) < 1e-6
    new_rect = w._image_draw_rect()
    assert new_rect.width() > base_rect.width()
    assert new_rect.width() == max(1, round(fit_w * 1.5))


def test_zoom_clamped_to_max(qtbot):
    w = _make_preview(qtbot)
    w._zoom_about(QPoint(200, 150), 1000.0)
    assert w.zoom_factor() == w._MAX_ZOOM


def test_zoom_clamped_to_min(qtbot):
    w = _make_preview(qtbot)
    w._zoom_about(QPoint(200, 150), 0.0001)
    assert w.zoom_factor() == w._MIN_ZOOM


def test_zoom_anchor_keeps_point_stable(qtbot):
    """锚点下的图片像素在缩放后仍映射到同一 Label 位置。"""
    w = _make_preview(qtbot)
    anchor = QPoint(200, 150)
    # 锚点对应的图片归一化坐标（缩放前）
    r0 = w._image_draw_rect()
    nx = (anchor.x() - r0.x()) / r0.width()
    ny = (anchor.y() - r0.y()) / r0.height()
    w._zoom_about(anchor, 1.6)
    r1 = w._image_draw_rect()
    # 缩放后同一图片点仍落在锚点附近（允许取整误差）
    px = r1.x() + nx * r1.width()
    py = r1.y() + ny * r1.height()
    assert abs(px - anchor.x()) <= 1
    assert abs(py - anchor.y()) <= 1


def test_pan_shifts_image_rect(qtbot):
    w = _make_preview(qtbot)
    r0 = w._image_draw_rect()
    w._pan = QPoint(15, 10)
    w._clamp_pan()
    r1 = w._image_draw_rect()
    assert r1.x() == r0.x() + 15
    assert r1.y() == r0.y() + 10


def test_clamp_pan_keeps_image_visible(qtbot):
    w = _make_preview(qtbot)
    cr = w.contentsRect()
    fw, fh = w._fit_size()
    dw = max(1, round(fw * w.zoom_factor()))
    dh = max(1, round(fh * w.zoom_factor()))
    base_x = (cr.width() - dw) // 2
    base_y = (cr.height() - dh) // 2
    keep = 40
    w._pan = QPoint(100000, 100000)
    w._clamp_pan()
    ax = base_x + w._pan.x()
    ay = base_y + w._pan.y()
    assert ax <= cr.width() - keep + 1
    assert ax + dw >= keep - 1
    assert ay <= cr.height() - keep + 1
    assert ay + dh >= keep - 1


def test_middle_button_drag_pans(qtbot):
    w = _make_preview(qtbot)
    qtbot.mousePress(w, Qt.MouseButton.MiddleButton, pos=QPoint(100, 100))
    assert w._panning is True
    qtbot.mouseMove(w, QPoint(60, 40))
    qtbot.mouseRelease(w, Qt.MouseButton.MiddleButton, pos=QPoint(60, 40))
    assert w._panning is False
    # 平移量 = 终点 - 起点 = (60-100, 40-100)
    assert w._pan == QPoint(-40, -60)


def test_reset_view_restores_fit(qtbot):
    w = _make_preview(qtbot)
    w._zoom = 2.0
    w._pan = QPoint(50, 50)
    w.reset_view()
    assert w.zoom_factor() == 1.0
    assert w._pan == QPoint(0, 0)


def test_entering_crop_mode_resets_view(qtbot):
    w = _make_preview(qtbot)
    w._zoom = 2.0
    w._pan = QPoint(60, 30)
    w.set_crop_mode(True)
    assert w.zoom_factor() == 1.0
    assert w._pan == QPoint(0, 0)
    w.set_crop_mode(False)


def test_double_click_resets_view(qtbot):
    w = _make_preview(qtbot)
    w._zoom = 3.0
    w._pan = QPoint(20, 20)
    qtbot.mouseDClick(w, Qt.MouseButton.LeftButton, pos=QPoint(200, 150))
    assert w.zoom_factor() == 1.0
    assert w._pan == QPoint(0, 0)


def test_size_hint_decoupled_from_image(qtbot):
    """全分辨率原图不得撑爆布局：sizeHint/minimumSizeHint 与图片尺寸解耦。"""
    w = _make_preview(qtbot)  # 800x600 图
    assert w.sizeHint().width() < 800
    assert w.sizeHint().height() < 600
    assert w.minimumSizeHint().width() < 800


def test_preview_paints_image_not_blank(qtbot):
    """渲染回归：预览必须真正画出图片（中心像素=图片色，非背景灰）。

    覆盖 _draw_base_image 的 drawPixmap 矩形类型问题（QRect+QRectF 混用会抛错）。
    """
    from PySide6.QtCore import QRect

    w = _make_preview(qtbot)  # 图片填充色 (120,120,200)，蓝通道明显偏高
    w.setGeometry(QRect(0, 0, 340, 300))
    shot = w.grab()
    assert not shot.isNull()
    c = shot.toImage().pixelColor(shot.width() // 2, shot.height() // 2)
    # 图片 (120,120,200): 蓝-红 ≈ 80；背景灰 (230,232,236): 蓝-红 ≈ 6
    assert c.blue() - c.red() > 30
