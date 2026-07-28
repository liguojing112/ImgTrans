"""QUndoCommand 测试。"""

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QUndoStack

from src.domain.layout import TextBox, TextLayer, TextLayout, TextStyle
from src.ui.editor.editor_model import EditorModel
from src.ui.editor.undo_commands import (
    ReplaceLayerUndoCommand,
    AddLayerUndoCommand,
    DeleteLayerUndoCommand,
)


def _make_layer(region_id: str = "l1", text: str = "Test") -> TextLayer:
    return TextLayer(
        region_id=region_id,
        text=text,
        box=TextBox(100, 50, 80, 24),
        style=TextStyle("Microsoft YaHei", 14, (24, 32, 51)),
    )


def test_replace_layer_undo_redo() -> None:
    app = QApplication.instance() or QApplication(["imgtrans-test"])
    model = EditorModel()
    stack = QUndoStack()

    before = _make_layer("l1", "Original")
    after = _make_layer("l1", "Modified")
    model.text_layout = TextLayout((before,))

    cmd = ReplaceLayerUndoCommand(model, before, after)
    stack.push(cmd)

    assert model.text_layout.layer_by_id("l1").text == "Modified"

    stack.undo()
    assert model.text_layout.layer_by_id("l1").text == "Original"

    stack.redo()
    assert model.text_layout.layer_by_id("l1").text == "Modified"


def test_add_layer_undo_redo() -> None:
    app = QApplication.instance() or QApplication(["imgtrans-test"])
    model = EditorModel()
    stack = QUndoStack()

    layer = _make_layer("l1", "New")
    cmd = AddLayerUndoCommand(model, layer)
    stack.push(cmd)

    assert len(model.text_layout.layers) == 1

    stack.undo()
    assert len(model.text_layout.layers) == 0

    stack.redo()
    assert len(model.text_layout.layers) == 1


def test_delete_layer_undo_redo() -> None:
    app = QApplication.instance() or QApplication(["imgtrans-test"])
    model = EditorModel()
    stack = QUndoStack()

    layer = _make_layer("l1", "Delete me")
    model.text_layout = TextLayout((layer,))

    cmd = DeleteLayerUndoCommand(model, layer)
    stack.push(cmd)

    assert len(model.text_layout.layers) == 0

    stack.undo()
    assert len(model.text_layout.layers) == 1

    stack.redo()
    assert len(model.text_layout.layers) == 0
