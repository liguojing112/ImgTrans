"""QUndoCommand 测试。"""

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QUndoStack

from src.domain.layout import TextBox, TextLayer, TextStyle
from src.ui.editor.undo_commands import ReplaceLayerUndoCommand


def test_replace_layer_undo_command() -> None:
    """ReplaceLayerUndoCommand 通过回调调用 undo/redo 操作。"""
    app = QApplication.instance() or QApplication(["imgtrans-test"])
    stack = QUndoStack()

    redo_called = []
    undo_called = []

    cmd = ReplaceLayerUndoCommand("测试修改")
    cmd.set_operations(
        redo_op=lambda: redo_called.append("redo"),
        undo_op=lambda: undo_called.append("undo"),
    )
    stack.push(cmd)

    assert redo_called == ["redo"]

    stack.undo()
    assert undo_called == ["undo"]

    stack.redo()
    assert redo_called == ["redo", "redo"]


def test_undo_redo_returns_none_when_no_ops() -> None:
    """无回调时 undo/redo 返回 None。"""
    app = QApplication.instance() or QApplication(["imgtrans-test"])
    cmd = ReplaceLayerUndoCommand("无操作")

    assert cmd.redo() is None
    assert cmd.undo() is None
