import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from src.domain.image import ImageAsset, ImageDocument, ImageFileFormat
from src.domain.layout import (
    ArtisticPreset,
    TextBox,
    TextLayer,
    TextLayout,
    TextStyle,
    default_arc_path,
)
from src.ui.curved_text_panel import CurvedTextPanel
from src.ui.image_canvas import ImageCanvas
from src.ui.layer_style_panel import LayerStylePanel


def _send_mouse(canvas, event_type, position, button, buttons) -> None:
    event = QMouseEvent(
        event_type,
        position,
        canvas.mapToGlobal(position.toPoint()),
        button,
        buttons,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(canvas, event)


def _layer() -> TextLayer:
    box = TextBox(100, 50, 120, 40)
    return TextLayer(
        "curve",
        "CURVE",
        box,
        TextStyle("Arial", 20, (20, 30, 40)),
        path=default_arc_path(box),
    )


def test_canvas_control_point_drag_emits_original_coordinate_path() -> None:
    application = QApplication.instance() or QApplication(["curve-canvas-ui"])
    canvas = ImageCanvas()
    canvas.resize(600, 400)
    canvas.show()
    asset = ImageAsset(Path("curve.png"), 200, 100, 1, ImageFileFormat.PNG, False, False)
    canvas.set_document(ImageDocument(asset, "RGB", bytes([245]) * 200 * 100 * 3))
    canvas.set_text_layout(TextLayout((_layer(),)))
    canvas.select_layer("curve")
    application.processEvents()
    emitted = []
    canvas.path_edit_requested.connect(lambda region_id, path: emitted.append((region_id, path)))
    start = canvas.document_to_view(_layer().path.control)
    target = canvas.document_to_view(QPointF(100, 20))
    _send_mouse(canvas, QEvent.Type.MouseButtonPress, start, Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton)
    _send_mouse(canvas, QEvent.Type.MouseMove, target, Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton)
    _send_mouse(canvas, QEvent.Type.MouseButtonRelease, target, Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton)
    assert emitted[0][0] == "curve"
    assert emitted[0][1].control.x == 100
    assert emitted[0][1].control.y == 20
    canvas.close()


def test_curve_panel_and_artistic_preset_expose_editable_parameters() -> None:
    QApplication.instance() or QApplication(["curve-panels-ui"])
    layer = _layer()
    curve_panel = CurvedTextPanel()
    applied = []
    curve_panel.apply_requested.connect(lambda: applied.append(curve_panel.edited_path))
    curve_panel.set_layer(layer)
    curve_panel.control.y.setValue(5)
    curve_panel.apply_button.click()
    assert applied[-1].control.y == 5

    style_panel = LayerStylePanel()
    style_panel.set_layer(layer)
    style_panel.effect_preset.setCurrentIndex(
        style_panel.effect_preset.findData(ArtisticPreset.POSTER.value)
    )
    style_panel.apply_preset_button.click()
    style, _ = style_panel.edited_style()
    assert style.effect_preset is ArtisticPreset.POSTER
    assert style.stroke_width >= 3
    assert style.shadow_opacity == 0.55
