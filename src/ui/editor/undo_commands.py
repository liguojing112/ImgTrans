"""QUndoCommand 子类 — 桥接 QUndoStack 与 EditComposition。

undo/redo 通过回调触发 composition_editor 重渲染，不再直接操作 TextLayout。
EditComposition 的 CompositionSession 是唯一的撤销源。
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtGui import QUndoCommand


class ReplaceLayerUndoCommand(QUndoCommand):
    """替换文字图层 — undo/redo 通过回调触发 EditComposition 重渲染。"""

    def __init__(
        self,
        text: str = "修改文字图层",
    ) -> None:
        super().__init__(text)
        self._redo_op: Callable[[], object] | None = None  # → CompositionEditResult
        self._undo_op: Callable[[], object] | None = None

    def set_operations(
        self,
        redo_op: Callable[[], object],
        undo_op: Callable[[], object],
    ) -> None:
        self._redo_op = redo_op
        self._undo_op = undo_op

    def redo(self) -> object | None:
        if self._redo_op is not None:
            return self._redo_op()
        return None

    def undo(self) -> object | None:
        if self._undo_op is not None:
            return self._undo_op()
        return None


class EditUndoCommand(QUndoCommand):
    """通用编辑命令 — 直接调用 composition_editor.undo()/redo()。"""

    def __init__(
        self,
        editor: object,
        is_redo: bool,
        text: str = "编辑",
    ) -> None:
        super().__init__(text)
        self._editor = editor
        self._is_redo = is_redo

    def redo(self) -> object | None:
        if self._is_redo:
            return self._editor.redo()
        return self._editor.undo()

    def undo(self) -> object | None:
        if self._is_redo:
            return self._editor.undo()
        return self._editor.redo()
