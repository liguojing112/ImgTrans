from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from typing import Protocol

from src.domain.image import ImageDocument
from src.domain.layout import TextLayer, TextLayout, TextStyle


class CompositionError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class ImageTransform(str, Enum):
    ROTATE_90_CW = "rotate_90_cw"
    ROTATE_90_CCW = "rotate_90_ccw"
    ROTATE_180 = "rotate_180"
    FLIP_HORIZONTAL = "flip_horizontal"
    FLIP_VERTICAL = "flip_vertical"


@dataclass(frozen=True, slots=True)
class BackgroundPatch:
    patch_id: str
    x: int
    y: int
    width: int
    height: int
    mode: str
    pixels: bytes
    mask: bytes = b""

    def __post_init__(self) -> None:
        channels = {"RGB": 3, "RGBA": 4}.get(self.mode)
        if not self.patch_id or channels is None:
            raise ValueError("Background patch requires an ID and RGB/RGBA mode")
        if min(self.x, self.y) < 0 or min(self.width, self.height) <= 0:
            raise ValueError("Background patch geometry is invalid")
        if len(self.pixels) != self.width * self.height * channels:
            raise ValueError("Background patch pixels do not match its geometry")
        if self.mask and len(self.mask) != self.width * self.height:
            raise ValueError("Background patch mask does not match its geometry")


@dataclass(frozen=True, slots=True)
class CropViewport:
    x: int
    y: int
    width: int
    height: int

    def __post_init__(self) -> None:
        if min(self.x, self.y) < 0 or min(self.width, self.height) <= 0:
            raise ValueError("Crop viewport geometry is invalid")


@dataclass(frozen=True, slots=True)
class WatermarkLayer:
    watermark_id: str
    kind: str
    center_x: float
    center_y: float
    width: float
    height: float
    rotation_degrees: float = 0
    opacity: float = 0.55
    tiled: bool = False
    visible: bool = True
    locked: bool = False
    text: str = ""
    style: TextStyle | None = None
    image_mode: str | None = None
    image_width: int = 0
    image_height: int = 0
    image_pixels: bytes = b""
    mirror_x: bool = False
    mirror_y: bool = False

    def __post_init__(self) -> None:
        if not self.watermark_id or self.kind not in {"text", "image"}:
            raise ValueError("Watermark requires an ID and text/image kind")
        if self.width <= 0 or self.height <= 0:
            raise ValueError("Watermark dimensions must be positive")
        if not 0 <= self.opacity <= 1:
            raise ValueError("Watermark opacity must be between zero and one")
        if self.kind == "text":
            if not self.text or self.style is None:
                raise ValueError("Text watermark requires text and style")
        else:
            channels = {"RGB": 3, "RGBA": 4}.get(self.image_mode or "")
            if (
                channels is None
                or min(self.image_width, self.image_height) <= 0
                or len(self.image_pixels)
                != self.image_width * self.image_height * channels
            ):
                raise ValueError("Image watermark pixels are invalid")


@dataclass(frozen=True, slots=True)
class CompositionState:
    layout: TextLayout
    patches: tuple[BackgroundPatch, ...] = ()
    watermarks: tuple[WatermarkLayer, ...] = ()
    viewport: CropViewport | None = None
    base_document: ImageDocument | None = None
    reference_document: ImageDocument | None = None

    def __post_init__(self) -> None:
        patch_ids = tuple(patch.patch_id for patch in self.patches)
        if len(patch_ids) != len(set(patch_ids)):
            raise ValueError("Background patch IDs must be unique")
        watermark_ids = tuple(item.watermark_id for item in self.watermarks)
        if len(watermark_ids) != len(set(watermark_ids)):
            raise ValueError("Watermark IDs must be unique")


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
        return replace(state, layout=state.layout.replace_layer(self.after))

    def revert(self, state: CompositionState) -> CompositionState:
        if state.layout.layer_by_id(self.after.region_id) != self.after:
            raise CompositionError("stale_undo", "文字图层状态与撤销记录不一致")
        return replace(state, layout=state.layout.replace_layer(self.before))


@dataclass(frozen=True, slots=True)
class AddLayerCommand:
    layer: TextLayer
    index: int

    def apply(self, state: CompositionState) -> CompositionState:
        if any(existing.region_id == self.layer.region_id for existing in state.layout.layers):
            raise CompositionError("duplicate_layer", "文字图层 ID 已存在")
        return replace(
            state, layout=state.layout.add_layer(self.layer, self.index)
        )

    def revert(self, state: CompositionState) -> CompositionState:
        current = state.layout.layer_by_id(self.layer.region_id)
        if current != self.layer:
            raise CompositionError("stale_undo", "新增图层状态与撤销记录不一致")
        result, _, _ = state.layout.remove_layer(self.layer.region_id)
        return replace(state, layout=result)


@dataclass(frozen=True, slots=True)
class DeleteLayerCommand:
    layer: TextLayer
    index: int

    def apply(self, state: CompositionState) -> CompositionState:
        current = state.layout.layer_by_id(self.layer.region_id)
        if current != self.layer:
            raise CompositionError("stale_edit", "待删除图层已发生变化")
        result, _, _ = state.layout.remove_layer(self.layer.region_id)
        return replace(state, layout=result)

    def revert(self, state: CompositionState) -> CompositionState:
        if any(existing.region_id == self.layer.region_id for existing in state.layout.layers):
            raise CompositionError("duplicate_layer", "无法恢复重复的文字图层")
        return replace(
            state, layout=state.layout.add_layer(self.layer, self.index)
        )


@dataclass(frozen=True, slots=True)
class ApplyManualRegionCommand:
    layer: TextLayer
    patch: BackgroundPatch
    index: int

    def apply(self, state: CompositionState) -> CompositionState:
        if any(item.patch_id == self.patch.patch_id for item in state.patches):
            raise CompositionError("duplicate_patch", "背景补丁 ID 已存在")
        return replace(
            state,
            layout=state.layout.add_layer(self.layer, self.index),
            patches=state.patches + (self.patch,),
        )

    def revert(self, state: CompositionState) -> CompositionState:
        if not state.patches or state.patches[-1] != self.patch:
            raise CompositionError("stale_undo", "背景补丁顺序与撤销记录不一致")
        layout, layer, _ = state.layout.remove_layer(self.layer.region_id)
        if layer != self.layer:
            raise CompositionError("stale_undo", "手动文字图层状态与撤销记录不一致")
        return replace(state, layout=layout, patches=state.patches[:-1])


@dataclass(frozen=True, slots=True)
class ReplaceCompositionStateCommand:
    before: CompositionState
    after: CompositionState

    def apply(self, state: CompositionState) -> CompositionState:
        if state != self.before:
            raise CompositionError("stale_edit", "组合状态已发生变化")
        return self.after

    def revert(self, state: CompositionState) -> CompositionState:
        if state != self.after:
            raise CompositionError("stale_undo", "组合状态与撤销记录不一致")
        return self.before


class CompositionSession:
    def __init__(
        self,
        layout: TextLayout,
        history_limit: int = 100,
        initial_state: CompositionState | None = None,
    ) -> None:
        if history_limit <= 0:
            raise ValueError("History limit must be positive")
        self._state = initial_state or CompositionState(layout)
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
