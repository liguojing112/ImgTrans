import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QPointF, Qt, QEvent
from PySide6.QtGui import QMouseEvent, QWheelEvent
from PySide6.QtWidgets import QApplication

from src.domain.image import ImageAsset, ImageDocument, ImageFileFormat
from src.domain.layout import TextBox, TextLayer, TextLayout, TextStyle
from src.ui.image_canvas import ImageCanvas


def _send_mouse(
    canvas: ImageCanvas,
    event_type: QEvent.Type,
    position: QPointF,
    button: Qt.MouseButton,
    buttons: Qt.MouseButton,
) -> None:
    event = QMouseEvent(
        event_type,
        position,
        canvas.mapToGlobal(position.toPoint()),
        button,
        buttons,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(canvas, event)


def test_coordinate_roundtrip_zoom_pan_and_move_emit_original_coordinates() -> None:
    application = QApplication.instance() or QApplication(["canvas-geometry-test"])
    canvas = ImageCanvas()
    canvas.resize(600, 400)
    canvas.show()
    asset = ImageAsset(Path("canvas.png"), 200, 100, 1, ImageFileFormat.PNG, False, False)
    document = ImageDocument(asset, "RGB", bytes([240]) * 200 * 100 * 3)
    original_box = TextBox(100, 50, 80, 30)
    layout = TextLayout(
        (TextLayer("r1", "TEXT", original_box, TextStyle("Arial", 18, (0, 0, 0))),)
    )
    canvas.set_document(document)
    canvas.set_text_layout(layout)
    application.processEvents()

    source_point = QPointF(37.5, 68.25)
    mapped = canvas.document_to_view(source_point)
    round_trip = canvas.view_to_document(mapped)
    assert abs(round_trip.x() - source_point.x()) < 1e-6
    assert abs(round_trip.y() - source_point.y()) < 1e-6

    anchor = QPointF(300, 200)
    before_zoom = canvas.view_to_document(anchor)
    wheel = QWheelEvent(
        anchor,
        canvas.mapToGlobal(anchor.toPoint()),
        QPoint(),
        QPoint(0, 120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.ScrollUpdate,
        False,
    )
    QApplication.sendEvent(canvas, wheel)
    after_zoom = canvas.view_to_document(anchor)
    assert canvas.zoom_factor > 1
    assert abs(after_zoom.x() - before_zoom.x()) < 1e-6
    assert abs(after_zoom.y() - before_zoom.y()) < 1e-6

    _send_mouse(canvas, QEvent.Type.MouseButtonPress, QPointF(280, 180), Qt.MouseButton.MiddleButton, Qt.MouseButton.MiddleButton)
    _send_mouse(canvas, QEvent.Type.MouseMove, QPointF(320, 215), Qt.MouseButton.NoButton, Qt.MouseButton.MiddleButton)
    _send_mouse(canvas, QEvent.Type.MouseButtonRelease, QPointF(320, 215), Qt.MouseButton.MiddleButton, Qt.MouseButton.NoButton)
    shifted = canvas.document_to_view(source_point)
    assert shifted != mapped

    emitted: list[tuple[str, TextBox]] = []
    canvas.geometry_edit_requested.connect(lambda region_id, box: emitted.append((region_id, box)))
    center = canvas.document_to_view(QPointF(original_box.center_x, original_box.center_y))
    _send_mouse(canvas, QEvent.Type.MouseButtonPress, center, Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton)
    target = center + QPointF(36, 18)
    _send_mouse(canvas, QEvent.Type.MouseMove, target, Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton)
    _send_mouse(canvas, QEvent.Type.MouseButtonRelease, target, Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton)
    assert canvas.selected_region_id == "r1"
    assert emitted[0][0] == "r1"
    assert emitted[0][1].center_x != original_box.center_x
    assert emitted[0][1].center_y != original_box.center_y
    assert layout.layer_by_id("r1").box == original_box
    canvas.close()


def test_resize_and_rotate_handles_emit_geometry() -> None:
    application = QApplication.instance() or QApplication(["canvas-handles-test"])
    canvas = ImageCanvas()
    canvas.resize(600, 400)
    canvas.show()
    asset = ImageAsset(Path("handles.png"), 200, 100, 1, ImageFileFormat.PNG, False, False)
    canvas.set_document(ImageDocument(asset, "RGB", bytes([240]) * 200 * 100 * 3))
    original = TextBox(100, 50, 80, 30)
    layout = TextLayout(
        (TextLayer("r1", "TEXT", original, TextStyle("Arial", 18, (0, 0, 0))),)
    )
    canvas.set_text_layout(layout)
    canvas.select_layer("r1")
    application.processEvents()
    emitted: list[TextBox] = []
    canvas.geometry_edit_requested.connect(lambda region_id, box: emitted.append(box))

    resize_handle = canvas.document_to_view(QPointF(140, 65))
    resize_target = canvas.document_to_view(QPointF(160, 75))
    _send_mouse(canvas, QEvent.Type.MouseButtonPress, resize_handle, Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton)
    _send_mouse(canvas, QEvent.Type.MouseMove, resize_target, Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton)
    _send_mouse(canvas, QEvent.Type.MouseButtonRelease, resize_target, Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton)
    assert emitted[-1].width == 120
    assert emitted[-1].height == 50

    canvas.set_text_layout(layout)
    canvas.select_layer("r1")
    scale = canvas.document_to_view(QPointF(1, 0)).x() - canvas.document_to_view(QPointF(0, 0)).x()
    rotate_handle = canvas.document_to_view(QPointF(100, 50 - 15 - 24 / scale))
    rotate_target = canvas.document_to_view(QPointF(140, 50))
    _send_mouse(canvas, QEvent.Type.MouseButtonPress, rotate_handle, Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton)
    _send_mouse(canvas, QEvent.Type.MouseMove, rotate_target, Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton)
    _send_mouse(canvas, QEvent.Type.MouseButtonRelease, rotate_target, Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton)
    assert abs(emitted[-1].rotation_degrees - 90) < 0.01
    canvas.close()
