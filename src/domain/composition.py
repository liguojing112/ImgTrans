from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from src.domain.layout import TextLayer, TextLayout


class CompositionError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class BackgroundPatch:
    patch_id: str
    x: int
    y: int
    width: int
    height: int
    mode: str
    pixels: bytes

    def __post_init__(self) -> None:
        channels = {"RGB": 3, "RGBA": 4}.get(self.mode)
        if not self.patch_id or channels is None:
            raise ValueError("Background patch requires an ID and RGB/RGBA mode")
        if min(self.x, self.y) < 0 or min(self.width, self.height) <= 0:
            raise ValueError("Background patch geometry is invalid")
        if len(self.pixels) != self.width * self.height * channels:
            raise ValueError("Background patch pixels do not match its geometry")


@dataclass(frozen=True, slots=True)
class CompositionState:
    layout: TextLayout
    patches: tuple[BackgroundPatch, ...] = ()

    def __post_init__(self) -> None:
        patch_ids = tuple(patch.patch_id for patch in self.patches)
        if len(patch_ids) != len(set(patch_ids)):
            raise ValueError("Background patch IDs must be unique")


@dataclass(frozen=True, slots=True)
class CompositionCommand(Protocol):
    def apply(self, state: CompositionState) -> CompositionState: ...

    def revert(self, state: CompositionState) -> CompositionState: ...


@dataclass(frozen=True, slots=True)
class ReplaceLayerCommand:
    before: TextLayer
    after: TextLayer

    def __post_init__(self) -> None:
        if self.before.region_id != self.after.region_id:
            raise ValueError("Replacement layers must have the same region ID")

    def apply(self, state: CompositionState) -> CompositionState:
        if state.layout.layer_by_id(self.before.region_id) != self.before:
            raise CompositionError("stale_edit", "文字图层已发生变化，请重新编辑")
        return CompositionState(state.layout.replace_layer(self.after), state.patches)

    def revert(self, state: CompositionState) -> CompositionState:
        if state.layout.layer_by_id(self.after.region_id) != self.after:
            raise CompositionError("stale_undo", "文字图层状态与撤销记录不一致")
        return CompositionState(state.layout.replace_layer(self.before), state.patches)


@dataclass(frozen=True, slots=True)
class AddLayerCommand:
    layer: TextLayer
    index: int

    def apply(self, state: CompositionState) -> CompositionState:
        if any(existing.region_id == self.layer.region_id for existing in state.layout.layers):
            raise CompositionError("duplicate_layer", "文字图层 ID 已存在")
        return CompositionState(state.layout.add_layer(self.layer, self.index), state.patches)

    def revert(self, state: CompositionState) -> CompositionState:
        current = state.layout.layer_by_id(self.layer.region_id)
        if current != self.layer:
            raise CompositionError("stale_undo", "新增图层状态与撤销记录不一致")
        result, _, _ = state.layout.remove_layer(self.layer.region_id)
        return CompositionState(result, state.patches)


@dataclass(frozen=True, slots=True)
class DeleteLayerCommand:
    layer: TextLayer
    index: int

    def apply(self, state: CompositionState) -> CompositionState:
        current = state.layout.layer_by_id(self.layer.region_id)
        if current != self.layer:
            raise CompositionError("stale_edit", "待删除图层已发生变化")
        result, _, _ = state.layout.remove_layer(self.layer.region_id)
        return CompositionState(result, state.patches)

    def revert(self, state: CompositionState) -> CompositionState:
        if any(existing.region_id == self.layer.region_id for existing in state.layout.layers):
            raise CompositionError("duplicate_layer", "无法恢复重复的文字图层")
        return CompositionState(state.layout.add_layer(self.layer, self.index), state.patches)


@dataclass(frozen=True, slots=True)
class ApplyManualRegionCommand:
    layer: TextLayer
    patch: BackgroundPatch
    index: int

    def apply(self, state: CompositionState) -> CompositionState:
        if any(item.patch_id == self.patch.patch_id for item in state.patches):
            raise CompositionError("duplicate_patch", "背景补丁 ID 已存在")
        return CompositionState(
            state.layout.add_layer(self.layer, self.index),
            state.patches + (self.patch,),
        )

    def revert(self, state: CompositionState) -> CompositionState:
        if not state.patches or state.patches[-1] != self.patch:
            raise CompositionError("stale_undo", "背景补丁顺序与撤销记录不一致")
        layout, layer, _ = state.layout.remove_layer(self.layer.region_id)
        if layer != self.layer:
            raise CompositionError("stale_undo", "手动文字图层状态与撤销记录不一致")
        return CompositionState(layout, state.patches[:-1])


class CompositionSession:
    def __init__(self, layout: TextLayout, history_limit: int = 100) -> None:
        if history_limit <= 0:
            raise ValueError("History limit must be positive")
        self._state = CompositionState(layout)
        self._history_limit = history_limit
        self._undo: list[CompositionCommand] = []
        self._redo: list[CompositionCommand] = []

    @property
    def layout(self) -> TextLayout:
        return self._state.layout

    @property
    def state(self) -> CompositionState:
        return self._state

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    def execute(self, command: CompositionCommand) -> TextLayout:
        self._state = command.apply(self._state)
        self._undo.append(command)
        if len(self._undo) > self._history_limit:
            self._undo.pop(0)
        self._redo.clear()
        return self._state.layout

    def undo(self) -> TextLayout:
        if not self._undo:
            raise CompositionError("nothing_to_undo", "没有可以撤销的编辑")
        command = self._undo.pop()
        self._state = command.revert(self._state)
        self._redo.append(command)
        return self._state.layout

    def redo(self) -> TextLayout:
        if not self._redo:
            raise CompositionError("nothing_to_redo", "没有可以重做的编辑")
        command = self._redo.pop()
        self._state = command.apply(self._state)
        self._undo.append(command)
        return self._state.layout
