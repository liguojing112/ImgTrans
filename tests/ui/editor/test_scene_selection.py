from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtWidgets import QApplication, QGraphicsSceneMouseEvent

from src.domain.image import ImageAsset, ImageDocument, ImageFileFormat
from src.ui.editor.canvas.scene import EditorScene


def _document() -> ImageDocument:
    asset = ImageAsset(Path("a.png"), 120, 80, 1, ImageFileFormat.PNG, False, False)
    return ImageDocument(asset, "RGB", bytes([240]) * 120 * 80 * 3)


def test_manual_selection_rect_pen_keeps_screen_width_at_any_zoom() -> None:
    """缩小显示时框选矩形也要看得见：线宽必须是屏幕像素（cosmetic）。"""
    QApplication.instance() or QApplication(["scene-selection-pen-test"])
    scene = EditorScene()
    scene.set_document(_document())
    scene.set_area_selection_mode("manual_translate")

    press = QGraphicsSceneMouseEvent(QEvent.Type.GraphicsSceneMousePress)
    press.setScenePos(QPointF(20, 10))
    press.setButton(Qt.MouseButton.LeftButton)
    press.setButtons(Qt.MouseButton.LeftButton)
    scene.mousePressEvent(press)

    item = scene._manual_selection_item
    assert item is not None
    pen = item.pen()
    assert pen.isCosmetic()
    assert pen.width() >= 2


def test_manual_selection_preview_tracks_box_and_rotation() -> None:
    """框选后的区域常驻显示在画布上，改旋转角时跟着转。"""
    QApplication.instance() or QApplication(["scene-manual-preview-test"])
    from src.domain.layout import TextBox

    scene = EditorScene()
    scene.set_document(_document())

    scene.set_manual_selection_preview(TextBox(60, 40, 80, 20))
    item = scene._manual_preview_item
    assert item is not None
    assert item.pos().x() == 60 and item.pos().y() == 40
    assert item.box.width == 80
    assert item.rotation() == 0

    scene.set_manual_selection_preview(TextBox(60, 40, 80, 20, 25))
    assert scene._manual_preview_item.rotation() == 25

    scene.set_manual_selection_preview(None)
    assert scene._manual_preview_item is None


def _mouse_event(kind, pos, scene_pos, button=Qt.MouseButton.LeftButton):
    event = QGraphicsSceneMouseEvent(kind)
    event.setPos(QPointF(*pos))
    event.setScenePos(QPointF(*scene_pos))
    event.setButton(button)
    event.setButtons(Qt.MouseButton.LeftButton)
    return event


def test_manual_selection_overlay_can_be_dragged_and_resized() -> None:
    """常驻框选区域可用鼠标拖动移动、拖角点改大小，并把结果同步回面板。"""
    from src.application.manual_region import ManualRegionSpec  # noqa: F401
    from src.domain.layout import TextBox
    from src.ui.editor.canvas.manual_selection_item import ManualSelectionItem

    QApplication.instance() or QApplication(["manual-overlay-drag-test"])
    item = ManualSelectionItem(TextBox(60, 40, 80, 20))
    changed: list = []
    item.box_changed.connect(changed.append)

    # 拖动框体：向左上移动
    item.mousePressEvent(
        _mouse_event(
            QEvent.Type.GraphicsSceneMousePress, (0, 0), (60, 40)
        )
    )
    item.mouseMoveEvent(
        _mouse_event(
            QEvent.Type.GraphicsSceneMouseMove, (10, 5), (70, 45)
        )
    )
    item.mouseReleaseEvent(
        _mouse_event(
            QEvent.Type.GraphicsSceneMouseRelease, (10, 5), (70, 45)
        )
    )
    assert changed[-1].center_x == 70 and changed[-1].center_y == 45
    assert changed[-1].width == 80 and changed[-1].height == 20

    # 拖右下角放大
    item.mousePressEvent(
        _mouse_event(
            QEvent.Type.GraphicsSceneMousePress, (40, 10), (110, 55)
        )
    )
    item.mouseMoveEvent(
        _mouse_event(
            QEvent.Type.GraphicsSceneMouseMove, (50, 15), (120, 60)
        )
    )
    item.mouseReleaseEvent(
        _mouse_event(
            QEvent.Type.GraphicsSceneMouseRelease, (50, 15), (120, 60)
        )
    )
    assert changed[-1].width == 90
    assert changed[-1].height == 25


def test_dragging_canvas_overlay_updates_manual_region_numbers() -> None:
    """在画布上拖动框选区域后，右侧擦除/译文区域的数值同步更新。"""
    from PySide6.QtGui import QUndoStack

    from src.domain.layout import TextBox
    from src.ui.editor.editor_page import EditorPage

    QApplication.instance() or QApplication(["manual-overlay-panel-sync-test"])
    page = EditorPage(QUndoStack())
    page.show()
    page.scene.set_document(_document())
    page.open_manual_region_dialog()
    page._on_manual_selection(TextBox(60, 40, 80, 20))

    overlay = page.scene._manual_preview_item
    assert overlay is not None and overlay.box == TextBox(60, 40, 80, 20)

    overlay.mousePressEvent(
        _mouse_event(QEvent.Type.GraphicsSceneMousePress, (0, 0), (60, 40))
    )
    overlay.mouseMoveEvent(
        _mouse_event(QEvent.Type.GraphicsSceneMouseMove, (10, 5), (70, 45))
    )
    overlay.mouseReleaseEvent(
        _mouse_event(QEvent.Type.GraphicsSceneMouseRelease, (10, 5), (70, 45))
    )

    spec = page.manual_region_panel.spec
    assert spec.text_box.center_x == 70
    assert spec.text_box.center_y == 45
    assert spec.erase_box.center_x == 70
    page.close()


def test_clicking_rotate_handle_of_covered_layer_keeps_it_selected() -> None:
    """两层重叠时，点下层（已选中）的旋转手柄不能被上层抢走选择。"""
    from src.domain.layout import TextBox, TextLayer, TextStyle
    from src.ui.editor.canvas.layer_item import TextLayerItem

    QApplication.instance() or QApplication(["overlap-rotate-handle-test"])
    scene = EditorScene()
    scene.set_document(_document())

    lower = TextLayerItem(
        TextLayer("lower", "A", TextBox(60, 50, 80, 20), TextStyle("Arial", 14, (0, 0, 0))),
        0,
    )
    upper = TextLayerItem(
        TextLayer("upper", "B", TextBox(60, 30, 80, 50), TextStyle("Arial", 14, (0, 0, 0))),
        1,
    )
    scene.addItem(lower)
    scene.addItem(upper)
    lower.setSelected(True)

    _, rotate = lower._handle_rects()
    handle_pos = lower.mapToScene(rotate.center())
    assert upper.contains(upper.mapFromScene(handle_pos))  # 手柄确实落在上层框里

    press = QGraphicsSceneMouseEvent(QEvent.Type.GraphicsSceneMousePress)
    press.setScenePos(handle_pos)
    press.setButton(Qt.MouseButton.LeftButton)
    press.setButtons(Qt.MouseButton.LeftButton)
    scene.mousePressEvent(press)

    assert lower.isSelected()
    assert not upper.isSelected()
    assert lower.zValue() > upper.zValue()


def test_add_text_mode_emits_click_point_and_exits() -> None:
    """「新增文字」放置模式：点哪里发哪里，点完退出模式。"""
    QApplication.instance() or QApplication(["scene-add-text-test"])
    scene = EditorScene()
    scene.set_document(_document())
    scene.set_area_selection_mode("add_text")
    points = []
    scene.add_text_at.connect(points.append)

    press = QGraphicsSceneMouseEvent(QEvent.Type.GraphicsSceneMousePress)
    press.setScenePos(QPointF(40, 30))
    press.setButton(Qt.MouseButton.LeftButton)
    press.setButtons(Qt.MouseButton.LeftButton)
    scene.mousePressEvent(press)

    assert len(points) == 1
    assert (points[0].x(), points[0].y()) == (40, 30)
    assert scene._selection_mode is None


def test_delete_key_emits_layer_delete_for_selected_layer() -> None:
    """选中文字图层后按 Delete 发出删除请求；未选中时不发。"""
    QApplication.instance() or QApplication(["scene-delete-key-test"])
    from PySide6.QtGui import QKeyEvent

    from src.domain.layout import TextBox, TextLayer, TextLayout, TextStyle

    scene = EditorScene()
    scene.set_document(_document())
    layer = TextLayer(
        "r1", "ABC", TextBox(60, 40, 40, 16), TextStyle("Arial", 12, (0, 0, 0))
    )
    scene.set_text_layout(TextLayout((layer,)))
    scene.select_layer("r1")

    deleted = []
    scene.layer_delete_requested.connect(deleted.append)
    key = QKeyEvent(
        QEvent.Type.KeyPress,
        Qt.Key.Key_Delete,
        Qt.KeyboardModifier.NoModifier,
    )
    scene.keyPressEvent(key)
    assert deleted == ["r1"]

    scene.clear_selection()
    scene.keyPressEvent(key)
    assert deleted == ["r1"], "未选中图层时 Delete 不应发删除请求"


def test_picture_selection_survives_scene_rebuild() -> None:
    """编辑后场景重建（set_document）时，图片图层选中状态恢复，Delete 才能继续用。"""
    from src.domain.composition import PictureLayer

    QApplication.instance() or QApplication(["picture-selection-test"])
    scene = EditorScene()
    scene.set_document(_document())
    picture = PictureLayer(
        "picture-1", bytes([220, 30, 30] * (10 * 10)), 10, 10, 50, 40
    )
    scene.set_picture_layers([picture])
    scene.select_picture("picture-1")
    assert scene._picture_items["picture-1"].isSelected()

    # 模拟一次编辑后的重建
    scene.set_document(_document())
    scene.set_picture_layers([picture])

    assert scene._picture_items["picture-1"].isSelected()

    deleted = []
    scene.picture_delete_requested.connect(deleted.append)
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtCore import QEvent, Qt

    scene.keyPressEvent(
        QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Delete, Qt.KeyboardModifier.NoModifier)
    )
    assert deleted == ["picture-1"]
