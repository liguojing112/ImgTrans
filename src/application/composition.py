from __future__ import annotations

from dataclasses import dataclass, replace
from threading import Lock
from uuid import uuid4

from src.application.ports import TextLayoutAdapter, TextRenderer
from src.domain.composition import (
    AddLayerCommand,
    ApplyManualRegionCommand,
    BackgroundPatch,
    CompositionState,
    CompositionSession,
    DeleteLayerCommand,
    ReplaceLayerCommand,
)
from src.domain.image import ImageDocument
from src.domain.inpainting import EraseMask
from src.domain.layout import (
    ArcTextPath,
    TextBox,
    TextLayer,
    TextLayout,
    TextStyle,
    transform_arc_path,
)


@dataclass(frozen=True, slots=True)
class CompositionEditResult:
    document: ImageDocument
    layout: TextLayout
    can_undo: bool
    can_redo: bool
    affected_region_id: str | None = None


class EditComposition:
    def __init__(
        self,
        background: ImageDocument,
        initial_document: ImageDocument,
        layout: TextLayout,
        layout_adapter: TextLayoutAdapter,
        renderer: TextRenderer,
        history_limit: int = 100,
    ) -> None:
        self._background = background
        self._document = initial_document
        self._session = CompositionSession(layout, history_limit)
        self._layout_adapter = layout_adapter
        self._renderer = renderer
        self._lock = Lock()

    @property
    def layout(self) -> TextLayout:
        return self._session.layout

    @property
    def can_undo(self) -> bool:
        return self._session.can_undo

    @property
    def can_redo(self) -> bool:
        return self._session.can_redo

    @property
    def background_document(self) -> ImageDocument:
        return _materialize_background(self._background, self._session.state.patches)

    def replace_text(self, region_id: str, text: str) -> CompositionEditResult:
        with self._lock:
            before = self._session.layout.layer_by_id(region_id)
            after = self._layout_adapter.reflow(before, text)
            if after == before:
                return self._result(region_id)
            command = ReplaceLayerCommand(before, after)
            candidate_state = command.apply(self._session.state)
            candidate_document = self._render_state(candidate_state)
            self._session.execute(command)
            self._document = candidate_document
            return self._result(region_id)

    def replace_box(self, region_id: str, box: TextBox) -> CompositionEditResult:
        with self._lock:
            before = self._session.layout.layer_by_id(region_id)
            path = (
                transform_arc_path(before.path, before.box, box)
                if before.path is not None
                else None
            )
            after = self._layout_adapter.reflow(
                replace(before, box=box, path=path), before.text
            )
            if after == before:
                return self._result(region_id)
            command = ReplaceLayerCommand(before, after)
            candidate_state = command.apply(self._session.state)
            candidate_document = self._render_state(candidate_state)
            self._session.execute(command)
            self._document = candidate_document
            return self._result(region_id)

    def replace_path(
        self,
        region_id: str,
        path: ArcTextPath | None,
    ) -> CompositionEditResult:
        with self._lock:
            before = self._session.layout.layer_by_id(region_id)
            after = self._layout_adapter.reflow(
                replace(before, path=path), before.text
            )
            if after == before:
                return self._result(region_id)
            command = ReplaceLayerCommand(before, after)
            candidate_state = command.apply(self._session.state)
            candidate_document = self._render_state(candidate_state)
            self._session.execute(command)
            self._document = candidate_document
            return self._result(region_id)

    def replace_style(
        self,
        region_id: str,
        style: TextStyle,
        rotation_degrees: float,
    ) -> CompositionEditResult:
        with self._lock:
            before = self._session.layout.layer_by_id(region_id)
            candidate = replace(
                before,
                style=style,
                box=replace(before.box, rotation_degrees=rotation_degrees),
            )
            after = self._layout_adapter.reflow(candidate, before.text)
            if after == before:
                return self._result(region_id)
            command = ReplaceLayerCommand(before, after)
            candidate_state = command.apply(self._session.state)
            candidate_document = self._render_state(candidate_state)
            self._session.execute(command)
            self._document = candidate_document
            return self._result(region_id)

    def add_layer(self, text: str = "新译文") -> CompositionEditResult:
        with self._lock:
            region_id = f"manual-{uuid4().hex}"
            box = TextBox(
                self._background.asset.width / 2,
                self._background.asset.height / 2,
                max(40, self._background.asset.width * 0.4),
                max(24, min(80, self._background.asset.height * 0.15)),
            )
            layer = self._layout_adapter.create_layer(region_id, text, box)
            command = AddLayerCommand(layer, len(self._session.layout.layers))
            candidate_state = command.apply(self._session.state)
            candidate_document = self._render_state(candidate_state)
            self._session.execute(command)
            self._document = candidate_document
            return self._result(region_id)

    def delete_layer(self, region_id: str) -> CompositionEditResult:
        with self._lock:
            layer = self._session.layout.layer_by_id(region_id)
            index = self._session.layout.layers.index(layer)
            command = DeleteLayerCommand(layer, index)
            candidate_state = command.apply(self._session.state)
            candidate_document = self._render_state(candidate_state)
            self._session.execute(command)
            self._document = candidate_document
            return self._result(region_id)

    def apply_manual_region(
        self,
        repaired_background: ImageDocument,
        layer: TextLayer,
        erase_mask: EraseMask,
    ) -> CompositionEditResult:
        with self._lock:
            patch = _extract_patch(repaired_background, erase_mask)
            command = ApplyManualRegionCommand(
                layer,
                patch,
                len(self._session.layout.layers),
            )
            candidate_state = command.apply(self._session.state)
            candidate_document = self._render_state(candidate_state)
            self._session.execute(command)
            self._document = candidate_document
            return self._result(layer.region_id)

    def undo(self) -> CompositionEditResult:
        with self._lock:
            self._session.undo()
            try:
                self._document = self._render_state(self._session.state)
            except Exception:
                self._session.redo()
                raise
            return self._result()

    def redo(self) -> CompositionEditResult:
        with self._lock:
            self._session.redo()
            try:
                self._document = self._render_state(self._session.state)
            except Exception:
                self._session.undo()
                raise
            return self._result()

    def _result(self, affected_region_id: str | None = None) -> CompositionEditResult:
        return CompositionEditResult(
            self._document,
            self._session.layout,
            self._session.can_undo,
            self._session.can_redo,
            affected_region_id,
        )

    def _render_state(self, state: CompositionState) -> ImageDocument:
        return self._renderer.render(
            _materialize_background(self._background, state.patches),
            state.layout,
        )


class CreateCompositionEditor:
    def __init__(
        self,
        layout_adapter: TextLayoutAdapter,
        renderer: TextRenderer,
        history_limit: int = 100,
    ) -> None:
        self._layout_adapter = layout_adapter
        self._renderer = renderer
        self._history_limit = history_limit

    def execute(
        self,
        background: ImageDocument,
        initial_document: ImageDocument,
        layout: TextLayout,
    ) -> EditComposition:
        return EditComposition(
            background,
            initial_document,
            layout,
            self._layout_adapter,
            self._renderer,
            self._history_limit,
        )


def _materialize_background(
    base: ImageDocument,
    patches: tuple[BackgroundPatch, ...],
) -> ImageDocument:
    channels = 4 if base.mode == "RGBA" else 3
    row_bytes = base.asset.width * channels
    pixels = bytearray(base.pixels)
    for patch in patches:
        if patch.mode != base.mode:
            raise ValueError("Background patch mode does not match composition")
        if patch.x + patch.width > base.asset.width or patch.y + patch.height > base.asset.height:
            raise ValueError("Background patch exceeds composition bounds")
        patch_row_bytes = patch.width * channels
        for row in range(patch.height):
            target = (patch.y + row) * row_bytes + patch.x * channels
            source = row * patch_row_bytes
            pixels[target : target + patch_row_bytes] = patch.pixels[
                source : source + patch_row_bytes
            ]
    return ImageDocument(base.asset, base.mode, bytes(pixels))


def _extract_patch(document: ImageDocument, mask: EraseMask) -> BackgroundPatch:
    if (document.asset.width, document.asset.height) != (mask.width, mask.height):
        raise ValueError("Manual repair mask dimensions do not match image")
    min_x, min_y = mask.width, mask.height
    max_x = max_y = -1
    for point_y in range(mask.height):
        row = mask.pixels[point_y * mask.width : (point_y + 1) * mask.width]
        point_x = next((index for index, value in enumerate(row) if value), -1)
        if point_x < 0:
            continue
        right_x = len(row) - next(
            index for index, value in enumerate(reversed(row)) if value
        ) - 1
        min_x, min_y = min(min_x, point_x), min(min_y, point_y)
        max_x, max_y = max(max_x, right_x), max(max_y, point_y)
    if max_x < 0:
        raise ValueError("Manual repair mask cannot be empty")
    x, y = min_x, min_y
    width, height = max_x - x + 1, max_y - y + 1
    channels = 4 if document.mode == "RGBA" else 3
    source_row_bytes = document.asset.width * channels
    patch_row_bytes = width * channels
    pixels = bytearray(patch_row_bytes * height)
    for row in range(height):
        source = (y + row) * source_row_bytes + x * channels
        target = row * patch_row_bytes
        pixels[target : target + patch_row_bytes] = document.pixels[
            source : source + patch_row_bytes
        ]
    return BackgroundPatch(
        f"patch-{uuid4().hex}", x, y, width, height, document.mode, bytes(pixels)
    )
