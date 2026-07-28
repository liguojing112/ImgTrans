"""QUndoCommand 子类 — 将 TextLayer 操作适配为 Qt 撤销命令。

这些命令直接操作 EditorModel.text_layout（前端状态），
后续可桥接到 CompositionSession 进行完整渲染。
"""

from __future__ import annotations

from PySide6.QtGui import QUndoCommand

from src.domain.layout import TextLayer
from src.ui.editor.editor_model import EditorModel


class _LayerCommand(QUndoCommand):
    """基类：持有 EditorModel 引用和前后图层快照。"""

    def __init__(
        self,
        model: EditorModel,
        before: TextLayer,
        after: TextLayer,
        text: str,
    ) -> None:
        super().__init__(text)
        self._model = model
        self._before = before
        self._after = after

    def redo(self) -> None:
        self._model.replace_layer(self._before, self._after)

    def undo(self) -> None:
        self._model.replace_layer(self._after, self._before)


class ReplaceLayerUndoCommand(_LayerCommand):
    """替换文字图层 — 文本、位置、尺寸、样式 变更。"""

    def __init__(self, model: EditorModel, before: TextLayer, after: TextLayer) -> None:
        super().__init__(model, before, after, "修改文字图层")


class AddLayerUndoCommand(QUndoCommand):
    """新增文字图层。"""

    def __init__(self, model: EditorModel, layer: TextLayer) -> None:
        super().__init__("新增文字图层")
        self._model = model
        self._layer = layer

    def redo(self) -> None:
        self._model.add_layer(self._layer)

    def undo(self) -> None:
        self._model.remove_layer(self._layer.region_id)


class DeleteLayerUndoCommand(QUndoCommand):
    """删除文字图层。"""

    def __init__(self, model: EditorModel, layer: TextLayer) -> None:
        super().__init__("删除文字图层")
        self._model = model
        self._layer = layer

    def redo(self) -> None:
        self._model.remove_layer(self._layer.region_id)

    def undo(self) -> None:
        self._model.add_layer(self._layer)
