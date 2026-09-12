from __future__ import annotations

from dataclasses import dataclass, replace
from functools import lru_cache
from math import ceil, floor
from pathlib import Path
import platform
from threading import Lock
from uuid import uuid4

from PIL import Image, ImageDraw, ImageFont

from src.application.ports import TextLayoutAdapter, TextRenderer
from src.domain.composition import (
    AddLayerCommand,
    ApplyManualRegionCommand,
    BackgroundPatch,
    CompositionState,
    CompositionSession,
    CropViewport,
    DeleteLayerCommand,
    ImageTransform,
    ReplaceCompositionStateCommand,
    ReplaceLayerCommand,
    WatermarkLayer,
)
from src.domain.image import ImageDocument
from src.domain.inpainting import EraseMask
from src.domain.layout import (
    ArcTextPath,
    CircularTextPath,
    PathPoint,
    TextBox,
    TextLayer,
    TextLayout,
    TextPath,
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
    watermarks: tuple[WatermarkLayer, ...] = ()
    viewport: CropViewport | None = None
    reference_document: ImageDocument | None = None


class EditComposition:
    def __init__(
        self,
        background: ImageDocument,
        initial_document: ImageDocument,
        layout: TextLayout,
        layout_adapter: TextLayoutAdapter,
        renderer: TextRenderer,
        history_limit: int = 100,
        reference_document: ImageDocument | None = None,
        record_initial_translation: bool = False,
        initial_watermarks: tuple[WatermarkLayer, ...] = (),
    ) -> None:
        self._background = background
        self._document = initial_document
        self._initial_document = initial_document
        self._layout_adapter = layout_adapter
        self._renderer = renderer
        self._lock = Lock()
        viewport = CropViewport(
            0,
            0,
            background.asset.width,
            background.asset.height,
        )
        translated_state = CompositionState(
            layout,
            watermarks=initial_watermarks,
            viewport=viewport,
            base_document=background,
            reference_document=reference_document or background,
        )
        if record_initial_translation and reference_document is not None:
            self._initial_translated_state: CompositionState | None = translated_state
            original_state = CompositionState(
                TextLayout(()),
                watermarks=initial_watermarks,
                viewport=viewport,
                base_document=reference_document,
                reference_document=reference_document,
            )
            self._session = CompositionSession(
                TextLayout(()),
                history_limit,
                original_state,
            )
            self._session.execute(
                ReplaceCompositionStateCommand(
                    original_state,
                    translated_state,
                )
            )
        else:
            self._initial_translated_state = None
            self._session = CompositionSession(
                layout,
                history_limit,
                translated_state,
            )
        if initial_watermarks:
            self._document = self._render_state(self._session.state)

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
        base = self._session.state.base_document or self._background
        return _materialize_background(
            base,
            self._session.state.patches,
            self._session.state.viewport,
        )

    @property
    def reference_document(self) -> ImageDocument:
        state = self._session.state
        reference = state.reference_document or state.base_document or self._background
        if state.viewport is None:
            return reference
        return _crop_document(reference, state.viewport)

    @property
    def document(self) -> ImageDocument:
        return self._document

    @property
    def editing_document(self) -> ImageDocument:
        """返回不含水印的编辑底图，水印由画布交互项单独显示。"""
        return self._render_state(
            replace(self._session.state, watermarks=())
        )

    @property
    def watermarks(self) -> tuple[WatermarkLayer, ...]:
        return self._session.state.watermarks

    @property
    def patch_count(self) -> int:
        return len(self._session.state.patches)

    @property
    def viewport(self) -> CropViewport:
        viewport = self._session.state.viewport
        if viewport is None:
            return CropViewport(
                0, 0, self._background.asset.width, self._background.asset.height
            )
        return viewport

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

    def replace_layer(self, replacement: TextLayer) -> CompositionEditResult:
        with self._lock:
            before = self._session.layout.layer_by_id(replacement.region_id)
            if before.locked and replacement != replace(
                before,
                locked=replacement.locked,
                visible=replacement.visible,
            ):
                raise ValueError("Locked text layer cannot be edited")
            if replacement == before:
                return self._result(replacement.region_id)
            command = ReplaceLayerCommand(before, replacement)
            candidate_state = command.apply(self._session.state)
            candidate_document = self._render_state(candidate_state)
            self._session.execute(command)
            self._document = candidate_document
            return self._result(replacement.region_id)

    def replace_box(self, region_id: str, box: TextBox) -> CompositionEditResult:
        with self._lock:
            before = self._session.layout.layer_by_id(region_id)
            if before.locked:
                raise ValueError("Locked text layer cannot be edited")
            if before.locked:
                raise ValueError("Locked text layer cannot be edited")
            box = _bound_box(box, self.background_document)
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
        path: TextPath | None,
    ) -> CompositionEditResult:
        with self._lock:
            before = self._session.layout.layer_by_id(region_id)
            if before.locked:
                raise ValueError("Locked text layer cannot be edited")
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
            if before.locked:
                raise ValueError("Locked text layer cannot be edited")
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

    def replace_style_many(
        self,
        region_styles: list[tuple[str, TextStyle, float]],
    ) -> CompositionEditResult:
        """批量套用文字样式：一次加锁、逐层 reflow、一次渲染、一条撤销记录。

        region_styles 为 (region_id, 新样式, 目标自身旋转角) 三元组，供格式刷
        框选多区域时合并为单次后台任务，避免并发 re-render 竞争。
        """
        with self._lock:
            before_state = self._session.state
            mapping = {rid: (style, rot) for rid, style, rot in region_styles}
            if not mapping:
                return self._result()
            changed = False
            after_layers: list[TextLayer] = []
            for layer in before_state.layout.layers:
                if layer.region_id in mapping:
                    if layer.locked:
                        raise ValueError("Locked text layer cannot be edited")
                    style, rotation = mapping[layer.region_id]
                    candidate = replace(
                        layer,
                        style=style,
                        box=replace(layer.box, rotation_degrees=rotation),
                    )
                    after = self._layout_adapter.reflow(candidate, layer.text)
                    if after != layer:
                        changed = True
                        after_layers.append(after)
                        continue
                after_layers.append(layer)
            if not changed:
                return self._result()
            after_state = replace(
                before_state, layout=TextLayout(tuple(after_layers))
            )
            return self._commit_state(before_state, after_state)

    def add_layer(self, text: str = "新译文") -> CompositionEditResult:
        with self._lock:
            region_id = f"manual-{uuid4().hex}"
            document = self.background_document
            box = TextBox(
                document.asset.width / 2,
                document.asset.height / 2,
                max(40, document.asset.width * 0.4),
                max(24, min(80, document.asset.height * 0.15)),
            )
            layer = self._layout_adapter.create_layer(region_id, text, box)
            command = AddLayerCommand(layer, len(self._session.layout.layers))
            candidate_state = command.apply(self._session.state)
            candidate_document = self._render_state(candidate_state)
            self._session.execute(command)
            self._document = candidate_document
            return self._result(region_id)

    def duplicate_layer(self, region_id: str) -> CompositionEditResult:
        with self._lock:
            source = self._session.layout.layer_by_id(region_id)
            new_id = f"manual-{uuid4().hex}"
            box = _bound_box(
                replace(
                    source.box,
                    center_x=source.box.center_x + 12,
                    center_y=source.box.center_y + 12,
                ),
                self.background_document,
            )
            layer = replace(
                source,
                region_id=new_id,
                box=box,
                path=(
                    transform_arc_path(source.path, source.box, box)
                    if source.path is not None
                    else None
                ),
                locked=False,
            )
            command = AddLayerCommand(layer, len(self._session.layout.layers))
            candidate_state = command.apply(self._session.state)
            candidate_document = self._render_state(candidate_state)
            self._session.execute(command)
            self._document = candidate_document
            return self._result(new_id)

    def delete_layer(self, region_id: str) -> CompositionEditResult:
        with self._lock:
            layer = self._session.layout.layer_by_id(region_id)
            if layer.locked:
                raise ValueError("Locked text layer cannot be deleted")
            index = self._session.layout.layers.index(layer)
            command = DeleteLayerCommand(layer, index)
            candidate_state = command.apply(self._session.state)
            candidate_document = self._render_state(candidate_state)
            self._session.execute(command)
            self._document = candidate_document
            return self._result(region_id)

    def move_layer(self, region_id: str, offset: int) -> CompositionEditResult:
        if offset not in {-1, 1}:
            raise ValueError("Layer move offset must be -1 or 1")
        with self._lock:
            before = self._session.state
            layers = list(before.layout.layers)
            index = next(
                (
                    current
                    for current, item in enumerate(layers)
                    if item.region_id == region_id
                ),
                -1,
            )
            if index < 0:
                raise KeyError(region_id)
            target = max(0, min(len(layers) - 1, index + offset))
            if target == index:
                return self._result(region_id)
            layers[index], layers[target] = layers[target], layers[index]
            after = replace(before, layout=TextLayout(tuple(layers)))
            return self._commit_state(before, after, region_id)

    def apply_manual_region(
        self,
        repaired_background: ImageDocument,
        layer: TextLayer,
        erase_mask: EraseMask,
    ) -> CompositionEditResult:
        with self._lock:
            viewport = self.viewport
            patch = _extract_patch(
                repaired_background,
                erase_mask,
                viewport.x,
                viewport.y,
            )
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

    def replace_region_from_manual(
        self,
        region_id: str,
        repaired_background: ImageDocument,
        layer: TextLayer,
        erase_mask: EraseMask,
    ) -> CompositionEditResult:
        with self._lock:
            viewport = self.viewport
            patch = _extract_patch(
                repaired_background,
                erase_mask,
                viewport.x,
                viewport.y,
            )
            before = self._session.state
            replacement = replace(layer, region_id=region_id)
            layers = tuple(
                replacement if item.region_id == region_id else item
                for item in before.layout.layers
            )
            if all(item.region_id != region_id for item in before.layout.layers):
                layers = (*layers, replacement)
            after = replace(
                before,
                layout=TextLayout(layers),
                patches=before.patches + (patch,),
            )
            return self._commit_state(before, after, region_id)

    def restore_original_region(
        self,
        region_id: str,
        source_document: ImageDocument,
        restore_mask: EraseMask,
    ) -> CompositionEditResult:
        with self._lock:
            viewport = self.viewport
            patch = _extract_patch(
                source_document,
                restore_mask,
                viewport.x,
                viewport.y,
            )
            before = self._session.state
            after = replace(
                before,
                layout=TextLayout(
                    tuple(
                        layer
                        for layer in before.layout.layers
                        if layer.region_id != region_id
                    )
                ),
                patches=before.patches + (patch,),
            )
            return self._commit_state(before, after, region_id)

    def apply_background_repair(
        self,
        repaired_background: ImageDocument,
        erase_mask: EraseMask,
    ) -> CompositionEditResult:
        with self._lock:
            viewport = self.viewport
            patch = _extract_patch(
                repaired_background,
                erase_mask,
                viewport.x,
                viewport.y,
            )
            before = self._session.state
            after = replace(before, patches=before.patches + (patch,))
            return self._commit_state(before, after)

    def crop(self, box: TextBox) -> CompositionEditResult:
        with self._lock:
            current = self.background_document
            left = max(0, floor(box.center_x - box.width / 2))
            top = max(0, floor(box.center_y - box.height / 2))
            right = min(current.asset.width, ceil(box.center_x + box.width / 2))
            bottom = min(current.asset.height, ceil(box.center_y + box.height / 2))
            if right <= left or bottom <= top:
                raise ValueError("Crop area cannot be empty")

            before = self._session.state
            viewport = self.viewport
            next_viewport = CropViewport(
                viewport.x + left,
                viewport.y + top,
                right - left,
                bottom - top,
            )
            layers = tuple(
                transformed
                for layer in before.layout.layers
                if (transformed := _crop_text_layer(layer, left, top, right, bottom))
                is not None
            )
            watermarks = tuple(
                transformed
                for watermark in before.watermarks
                if (
                    transformed := _crop_watermark(
                        watermark, left, top, right, bottom
                    )
                )
                is not None
            )
            after = replace(
                before,
                layout=TextLayout(layers),
                watermarks=watermarks,
                viewport=next_viewport,
            )
            return self._commit_state(before, after)

    def transform_canvas(
        self,
        operation: ImageTransform,
    ) -> CompositionEditResult:
        with self._lock:
            before = self._session.state
            background = self.background_document
            reference = self.reference_document
            transformed_background = transform_image_document(background, operation)
            transformed_reference = transform_image_document(reference, operation)
            width = background.asset.width
            height = background.asset.height
            layout = TextLayout(
                tuple(
                    _transform_text_layer(layer, operation, width, height)
                    for layer in before.layout.layers
                )
            )
            watermarks = tuple(
                _transform_watermark(item, operation, width, height)
                for item in before.watermarks
            )
            after = replace(
                before,
                layout=layout,
                patches=(),
                watermarks=watermarks,
                viewport=CropViewport(
                    0,
                    0,
                    transformed_background.asset.width,
                    transformed_background.asset.height,
                ),
                base_document=transformed_background,
                reference_document=transformed_reference,
            )
            return self._commit_state(before, after)

    def add_text_watermark(
        self,
        text: str,
        style: TextStyle,
        tiled: bool = False,
        opacity: float = 0.55,
        position: str = "center",
    ) -> CompositionEditResult:
        if not text.strip():
            raise ValueError("Watermark text cannot be empty")
        with self._lock:
            document = self.background_document
            center_x, center_y = _watermark_position(
                position,
                document.asset.width,
                document.asset.height,
            )
            watermark = WatermarkLayer(
                f"watermark-{uuid4().hex}",
                "text",
                center_x,
                center_y,
                max(80.0, min(document.asset.width * 0.5, len(text) * style.font_size)),
                max(30.0, style.font_size * 1.6),
                opacity=opacity,
                tiled=tiled,
                text=text,
                style=style,
            )
            before = self._session.state
            after = replace(
                before, watermarks=before.watermarks + (watermark,)
            )
            return self._commit_state(before, after, watermark.watermark_id)

    def add_image_watermark(
        self,
        document: ImageDocument,
        tiled: bool = False,
        opacity: float = 0.55,
        position: str = "center",
    ) -> CompositionEditResult:
        with self._lock:
            canvas = self.background_document
            scale = min(
                1.0,
                canvas.asset.width * 0.35 / document.asset.width,
                canvas.asset.height * 0.35 / document.asset.height,
            )
            center_x, center_y = _watermark_position(
                position,
                canvas.asset.width,
                canvas.asset.height,
            )
            watermark = WatermarkLayer(
                f"watermark-{uuid4().hex}",
                "image",
                center_x,
                center_y,
                max(1.0, document.asset.width * scale),
                max(1.0, document.asset.height * scale),
                opacity=opacity,
                tiled=tiled,
                image_mode=document.mode,
                image_width=document.asset.width,
                image_height=document.asset.height,
                image_pixels=document.pixels,
            )
            before = self._session.state
            after = replace(
                before, watermarks=before.watermarks + (watermark,)
            )
            return self._commit_state(before, after, watermark.watermark_id)

    def replace_watermark(
        self,
        replacement: WatermarkLayer,
    ) -> CompositionEditResult:
        with self._lock:
            before = self._session.state
            current = next(
                (
                    item
                    for item in before.watermarks
                    if item.watermark_id == replacement.watermark_id
                ),
                None,
            )
            if current is None:
                raise KeyError(replacement.watermark_id)
            if current.locked and replacement != replace(
                current,
                locked=replacement.locked,
                visible=replacement.visible,
            ):
                raise ValueError("Locked watermark cannot be edited")
            after = replace(
                before,
                watermarks=tuple(
                    replacement if item.watermark_id == replacement.watermark_id else item
                    for item in before.watermarks
                ),
            )
            return self._commit_state(before, after, replacement.watermark_id)

    def delete_watermark(self, watermark_id: str) -> CompositionEditResult:
        with self._lock:
            before = self._session.state
            current = next(
                (item for item in before.watermarks if item.watermark_id == watermark_id),
                None,
            )
            if current is None:
                raise KeyError(watermark_id)
            if current.locked:
                raise ValueError("Locked watermark cannot be deleted")
            after = replace(
                before,
                watermarks=tuple(
                    item for item in before.watermarks if item.watermark_id != watermark_id
                ),
            )
            return self._commit_state(before, after, watermark_id)

    def duplicate_watermark(self, watermark_id: str) -> CompositionEditResult:
        with self._lock:
            before = self._session.state
            source = next(
                (item for item in before.watermarks if item.watermark_id == watermark_id),
                None,
            )
            if source is None:
                raise KeyError(watermark_id)
            duplicate = replace(
                source,
                watermark_id=f"watermark-{uuid4().hex}",
                center_x=source.center_x + 16,
                center_y=source.center_y + 16,
                locked=False,
            )
            after = replace(
                before,
                watermarks=before.watermarks + (duplicate,),
            )
            return self._commit_state(before, after, duplicate.watermark_id)

    def move_watermark(
        self,
        watermark_id: str,
        offset: int,
    ) -> CompositionEditResult:
        if offset not in {-1, 1}:
            raise ValueError("Watermark move offset must be -1 or 1")
        with self._lock:
            before = self._session.state
            watermarks = list(before.watermarks)
            index = next(
                (
                    current
                    for current, item in enumerate(watermarks)
                    if item.watermark_id == watermark_id
                ),
                -1,
            )
            if index < 0:
                raise KeyError(watermark_id)
            target = max(0, min(len(watermarks) - 1, index + offset))
            if target == index:
                return self._result(watermark_id)
            watermarks[index], watermarks[target] = (
                watermarks[target],
                watermarks[index],
            )
            after = replace(before, watermarks=tuple(watermarks))
            return self._commit_state(before, after, watermark_id)

    def undo(self) -> CompositionEditResult:
        with self._lock:
            self._session.undo()
            try:
                self._document = self._render_session_state()
            except Exception:
                self._session.redo()
                raise
            return self._result()

    def redo(self) -> CompositionEditResult:
        with self._lock:
            self._session.redo()
            try:
                self._document = self._render_session_state()
            except Exception:
                self._session.undo()
                raise
            return self._result()

    def _render_session_state(self) -> ImageDocument:
        if (
            self._initial_translated_state is not None
            and self._session.state == self._initial_translated_state
        ):
            return self._initial_document
        return self._render_state(self._session.state)

    def _result(self, affected_region_id: str | None = None) -> CompositionEditResult:
        return CompositionEditResult(
            self._document,
            self._session.layout,
            self._session.can_undo,
            self._session.can_redo,
            affected_region_id,
            self._session.state.watermarks,
            self._session.state.viewport,
            self.reference_document,
        )

    def _render_state(self, state: CompositionState) -> ImageDocument:
        visible_layout = TextLayout(
            tuple(layer for layer in state.layout.layers if layer.visible)
        )
        rendered = self._renderer.render(
            _materialize_background(
                state.base_document or self._background,
                state.patches,
                state.viewport,
            ),
            visible_layout,
        )
        return _render_watermarks(rendered, state.watermarks)

    def _commit_state(
        self,
        before: CompositionState,
        after: CompositionState,
        affected_id: str | None = None,
    ) -> CompositionEditResult:
        command = ReplaceCompositionStateCommand(before, after)
        candidate_document = self._render_state(after)
        self._session.execute(command)
        self._document = candidate_document
        return self._result(affected_id)


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
        reference_document: ImageDocument | None = None,
        record_initial_translation: bool = False,
        initial_watermarks: tuple[WatermarkLayer, ...] = (),
    ) -> EditComposition:
        return EditComposition(
            background,
            initial_document,
            layout,
            self._layout_adapter,
            self._renderer,
            self._history_limit,
            reference_document,
            record_initial_translation,
            initial_watermarks,
        )


def _materialize_background(
    base: ImageDocument,
    patches: tuple[BackgroundPatch, ...],
    viewport: CropViewport | None = None,
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
            if not patch.mask:
                target = (patch.y + row) * row_bytes + patch.x * channels
                source = row * patch_row_bytes
                pixels[target : target + patch_row_bytes] = patch.pixels[
                    source : source + patch_row_bytes
                ]
                continue
            for column in range(patch.width):
                if not patch.mask[row * patch.width + column]:
                    continue
                target = (
                    (patch.y + row) * row_bytes
                    + (patch.x + column) * channels
                )
                source = (row * patch.width + column) * channels
                pixels[target : target + channels] = patch.pixels[
                    source : source + channels
                ]
    materialized = ImageDocument(base.asset, base.mode, bytes(pixels))
    if viewport is None:
        return materialized
    return _crop_document(materialized, viewport)


def _extract_patch(
    document: ImageDocument,
    mask: EraseMask,
    origin_x: int = 0,
    origin_y: int = 0,
) -> BackgroundPatch:
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
    patch_mask = bytearray(width * height)
    for row in range(height):
        source = (y + row) * source_row_bytes + x * channels
        target = row * patch_row_bytes
        pixels[target : target + patch_row_bytes] = document.pixels[
            source : source + patch_row_bytes
        ]
        mask_source = (y + row) * mask.width + x
        mask_target = row * width
        patch_mask[mask_target : mask_target + width] = mask.pixels[
            mask_source : mask_source + width
        ]
    return BackgroundPatch(
        f"patch-{uuid4().hex}",
        x + origin_x,
        y + origin_y,
        width,
        height,
        document.mode,
        bytes(pixels),
        bytes(patch_mask),
    )


def _bound_box(box: TextBox, document: ImageDocument) -> TextBox:
    half_width = min(box.width, document.asset.width) / 2
    half_height = min(box.height, document.asset.height) / 2
    return replace(
        box,
        center_x=min(max(box.center_x, half_width), document.asset.width - half_width),
        center_y=min(max(box.center_y, half_height), document.asset.height - half_height),
        width=half_width * 2,
        height=half_height * 2,
    )


def transform_image_document(
    document: ImageDocument,
    operation: ImageTransform,
) -> ImageDocument:
    image = Image.frombytes(
        document.mode,
        (document.asset.width, document.asset.height),
        document.pixels,
    )
    transforms = {
        ImageTransform.ROTATE_90_CW: Image.Transpose.ROTATE_270,
        ImageTransform.ROTATE_90_CCW: Image.Transpose.ROTATE_90,
        ImageTransform.ROTATE_180: Image.Transpose.ROTATE_180,
        ImageTransform.FLIP_HORIZONTAL: Image.Transpose.FLIP_LEFT_RIGHT,
        ImageTransform.FLIP_VERTICAL: Image.Transpose.FLIP_TOP_BOTTOM,
    }
    transformed = image.transpose(transforms[operation])
    width, height = transformed.size
    asset = replace(
        document.asset,
        width=width,
        height=height,
        has_alpha=document.mode == "RGBA",
        orientation_applied=True,
    )
    return ImageDocument(asset, document.mode, transformed.tobytes())


def crop_image_document(
    document: ImageDocument,
    box: TextBox,
) -> ImageDocument:
    left = max(0, floor(box.center_x - box.width / 2))
    top = max(0, floor(box.center_y - box.height / 2))
    right = min(document.asset.width, ceil(box.center_x + box.width / 2))
    bottom = min(document.asset.height, ceil(box.center_y + box.height / 2))
    if right <= left or bottom <= top:
        raise ValueError("Crop area cannot be empty")
    return _crop_document(
        document,
        CropViewport(left, top, right - left, bottom - top),
    )


def _transform_point(
    point: PathPoint,
    operation: ImageTransform,
    width: int,
    height: int,
) -> PathPoint:
    if operation is ImageTransform.ROTATE_90_CW:
        return PathPoint(height - point.y, point.x)
    if operation is ImageTransform.ROTATE_90_CCW:
        return PathPoint(point.y, width - point.x)
    if operation is ImageTransform.ROTATE_180:
        return PathPoint(width - point.x, height - point.y)
    if operation is ImageTransform.FLIP_HORIZONTAL:
        return PathPoint(width - point.x, point.y)
    return PathPoint(point.x, height - point.y)


def _transform_angle(angle: float, operation: ImageTransform) -> float:
    if operation is ImageTransform.ROTATE_90_CW:
        value = angle + 90
    elif operation is ImageTransform.ROTATE_90_CCW:
        value = angle - 90
    elif operation is ImageTransform.ROTATE_180:
        value = angle + 180
    elif operation is ImageTransform.FLIP_HORIZONTAL:
        value = 180 - angle
    else:
        value = -angle
    return (value + 180) % 360 - 180


def _transform_path(
    path: TextPath | None,
    operation: ImageTransform,
    width: int,
    height: int,
) -> TextPath | None:
    if path is None:
        return None
    if isinstance(path, CircularTextPath):
        return CircularTextPath(
            _transform_point(path.center, operation, width, height),
            path.radius,
            _transform_angle(path.start_angle_degrees, operation),
            _transform_angle(path.end_angle_degrees, operation),
            path.reverse
            ^ (
                operation
                in {ImageTransform.FLIP_HORIZONTAL, ImageTransform.FLIP_VERTICAL}
            ),
        )
    return ArcTextPath(
        _transform_point(path.start, operation, width, height),
        _transform_point(path.control, operation, width, height),
        _transform_point(path.end, operation, width, height),
        path.reverse
        ^ (
            operation
            in {ImageTransform.FLIP_HORIZONTAL, ImageTransform.FLIP_VERTICAL}
        ),
    )


def _transform_text_layer(
    layer: TextLayer,
    operation: ImageTransform,
    width: int,
    height: int,
) -> TextLayer:
    center = _transform_point(
        PathPoint(layer.box.center_x, layer.box.center_y),
        operation,
        width,
        height,
    )
    box = TextBox(
        center.x,
        center.y,
        layer.box.width,
        layer.box.height,
        _transform_angle(layer.box.rotation_degrees, operation),
    )
    return replace(
        layer,
        box=box,
        path=_transform_path(layer.path, operation, width, height),
        mirror_x=(
            not layer.mirror_x
            if operation is ImageTransform.FLIP_HORIZONTAL
            else layer.mirror_x
        ),
        mirror_y=(
            not layer.mirror_y
            if operation is ImageTransform.FLIP_VERTICAL
            else layer.mirror_y
        ),
    )


def _transform_watermark(
    watermark: WatermarkLayer,
    operation: ImageTransform,
    width: int,
    height: int,
) -> WatermarkLayer:
    center = _transform_point(
        PathPoint(watermark.center_x, watermark.center_y),
        operation,
        width,
        height,
    )
    return replace(
        watermark,
        center_x=center.x,
        center_y=center.y,
        width=watermark.width,
        height=watermark.height,
        rotation_degrees=_transform_angle(
            watermark.rotation_degrees, operation
        ),
        mirror_x=(
            not watermark.mirror_x
            if operation is ImageTransform.FLIP_HORIZONTAL
            else watermark.mirror_x
        ),
        mirror_y=(
            not watermark.mirror_y
            if operation is ImageTransform.FLIP_VERTICAL
            else watermark.mirror_y
        ),
    )


def _watermark_position(
    position: str,
    width: int,
    height: int,
) -> tuple[float, float]:
    values = {
        "top_left": (0.15, 0.15),
        "top_center": (0.5, 0.15),
        "top_right": (0.85, 0.15),
        "middle_left": (0.15, 0.5),
        "center": (0.5, 0.5),
        "middle_right": (0.85, 0.5),
        "bottom_left": (0.15, 0.85),
        "bottom_center": (0.5, 0.85),
        "bottom_right": (0.85, 0.85),
    }
    try:
        x_ratio, y_ratio = values[position]
    except KeyError as error:
        raise ValueError("Unsupported watermark position") from error
    return width * x_ratio, height * y_ratio


def apply_watermark_template(
    document: ImageDocument,
    template: object,
) -> ImageDocument:
    center_x, center_y = _watermark_position(
        str(getattr(template, "position")),
        document.asset.width,
        document.asset.height,
    )
    kind = str(getattr(template, "kind"))
    if kind == "text":
        text = str(getattr(template, "text"))
        style = getattr(template, "style")
        watermark = WatermarkLayer(
            f"watermark-{uuid4().hex}",
            "text",
            center_x,
            center_y,
            max(
                80.0,
                min(
                    document.asset.width * 0.5,
                    len(text) * style.font_size,
                ),
            ),
            max(30.0, style.font_size * 1.6),
            opacity=float(getattr(template, "opacity")),
            tiled=bool(getattr(template, "tiled")),
            text=text,
            style=style,
        )
    else:
        source = getattr(template, "image")
        scale = min(
            1.0,
            document.asset.width * 0.35 / source.asset.width,
            document.asset.height * 0.35 / source.asset.height,
        )
        watermark = WatermarkLayer(
            f"watermark-{uuid4().hex}",
            "image",
            center_x,
            center_y,
            max(1.0, source.asset.width * scale),
            max(1.0, source.asset.height * scale),
            opacity=float(getattr(template, "opacity")),
            tiled=bool(getattr(template, "tiled")),
            image_mode=source.mode,
            image_width=source.asset.width,
            image_height=source.asset.height,
            image_pixels=source.pixels,
        )
    return _render_watermarks(document, (watermark,))


def _translate_path(path: TextPath, dx: float, dy: float) -> TextPath:
    if isinstance(path, CircularTextPath):
        return replace(
            path,
            center=PathPoint(path.center.x + dx, path.center.y + dy),
        )
    return ArcTextPath(
        PathPoint(path.start.x + dx, path.start.y + dy),
        PathPoint(path.control.x + dx, path.control.y + dy),
        PathPoint(path.end.x + dx, path.end.y + dy),
        path.reverse,
    )


def _crop_text_layer(
    layer: TextLayer,
    left: int,
    top: int,
    right: int,
    bottom: int,
) -> TextLayer | None:
    box = layer.box
    box_left = box.center_x - box.width / 2
    box_top = box.center_y - box.height / 2
    box_right = box.center_x + box.width / 2
    box_bottom = box.center_y + box.height / 2
    if (
        box_right <= left
        or box_bottom <= top
        or box_left >= right
        or box_top >= bottom
    ):
        return None
    return replace(
        layer,
        box=replace(
            box,
            center_x=box.center_x - left,
            center_y=box.center_y - top,
        ),
        path=(
            _translate_path(layer.path, -left, -top)
            if layer.path is not None
            else None
        ),
    )


def _crop_watermark(
    watermark: WatermarkLayer,
    left: int,
    top: int,
    right: int,
    bottom: int,
) -> WatermarkLayer | None:
    if (
        watermark.center_x + watermark.width / 2 <= left
        or watermark.center_y + watermark.height / 2 <= top
        or watermark.center_x - watermark.width / 2 >= right
        or watermark.center_y - watermark.height / 2 >= bottom
    ):
        return None
    return replace(
        watermark,
        center_x=watermark.center_x - left,
        center_y=watermark.center_y - top,
    )


def _crop_document(document: ImageDocument, viewport: CropViewport) -> ImageDocument:
    channels = 4 if document.mode == "RGBA" else 3
    source_row = document.asset.width * channels
    target_row = viewport.width * channels
    output = bytearray(viewport.height * target_row)
    for row in range(viewport.height):
        source = (viewport.y + row) * source_row + viewport.x * channels
        target = row * target_row
        output[target : target + target_row] = document.pixels[
            source : source + target_row
        ]
    asset = replace(
        document.asset,
        width=viewport.width,
        height=viewport.height,
        has_alpha=document.mode == "RGBA",
    )
    return ImageDocument(asset, document.mode, bytes(output))


def _render_watermarks(
    document: ImageDocument,
    watermarks: tuple[WatermarkLayer, ...],
) -> ImageDocument:
    visible = tuple(item for item in watermarks if item.visible)
    if not visible:
        return document
    base = Image.frombytes(
        document.mode,
        (document.asset.width, document.asset.height),
        document.pixels,
    ).convert("RGBA")
    for watermark in visible:
        overlay = _watermark_image(watermark)
        if watermark.tiled:
            step_x = max(20, int(watermark.width * 1.5))
            step_y = max(20, int(watermark.height * 2.0))
            for y in range(-step_y, base.height + step_y, step_y):
                for x in range(-step_x, base.width + step_x, step_x):
                    _paste_center(base, overlay, x + step_x // 2, y + step_y // 2)
        else:
            _paste_center(
                base,
                overlay,
                watermark.center_x,
                watermark.center_y,
            )
    output = base if document.mode == "RGBA" else base.convert("RGB")
    return ImageDocument(document.asset, document.mode, output.tobytes())


def _watermark_image(watermark: WatermarkLayer) -> Image.Image:
    width = max(1, round(watermark.width))
    height = max(1, round(watermark.height))
    if watermark.kind == "image":
        image = Image.frombytes(
            watermark.image_mode or "RGBA",
            (watermark.image_width, watermark.image_height),
            watermark.image_pixels,
        ).convert("RGBA")
        image = image.resize((width, height), Image.Resampling.LANCZOS)
    else:
        style = watermark.style
        assert style is not None
        image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        font_size = max(1, round(style.font_size))
        font = _load_watermark_font(style.font_family, font_size)
        draw = ImageDraw.Draw(image)
        bounds = draw.textbbox((0, 0), watermark.text, font=font)
        while (
            font_size > 4
            and (
                bounds[2] - bounds[0] > max(1, width - 4)
                or bounds[3] - bounds[1] > max(1, height - 4)
            )
        ):
            font_size -= 1
            font = _load_watermark_font(style.font_family, font_size)
            bounds = draw.textbbox((0, 0), watermark.text, font=font)
        text_width = bounds[2] - bounds[0]
        text_height = bounds[3] - bounds[1]
        draw.text(
            ((width - text_width) / 2, (height - text_height) / 2 - bounds[1]),
            watermark.text,
            font=font,
            fill=(*style.fill_rgb, 255),
            stroke_width=max(0, round(style.stroke_width)),
            stroke_fill=(*style.stroke_rgb, 255),
        )
    if watermark.opacity < 1:
        alpha = image.getchannel("A").point(
            lambda value: round(value * watermark.opacity)
        )
        image.putalpha(alpha)
    if watermark.mirror_x:
        image = image.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    if watermark.mirror_y:
        image = image.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
    if watermark.rotation_degrees:
        image = image.rotate(
            -watermark.rotation_degrees,
            expand=True,
            resample=Image.Resampling.BICUBIC,
        )
    return image


@lru_cache(maxsize=256)
def _load_watermark_font(family: str, size: int):
    for candidate in _watermark_font_candidates(family):
        try:
            return ImageFont.truetype(str(candidate), size)
        except OSError:
            continue
    try:
        return ImageFont.truetype(family, size)
    except OSError:
        return ImageFont.load_default()


def _watermark_font_candidates(family: str) -> tuple[Path, ...]:
    normalized = family.casefold().replace(" ", "")
    system = platform.system()
    if system == "Windows":
        root = Path("C:/Windows/Fonts")
        preferred = {
            "microsoftyaheiui": ("msyh.ttc", "msyhbd.ttc"),
            "microsoftyahei": ("msyh.ttc", "msyhbd.ttc"),
            "segoeui": ("segoeui.ttf", "seguisb.ttf"),
            "arial": ("arial.ttf", "arialbd.ttf"),
        }
        names = preferred.get(normalized, ())
        return tuple(root / name for name in names) + (
            root / "msyh.ttc",
            root / "segoeui.ttf",
            root / "arial.ttf",
        )
    if system == "Darwin":
        return (
            Path("/System/Library/Fonts/PingFang.ttc"),
            Path("/System/Library/Fonts/Helvetica.ttc"),
            Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
        )
    return (
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
        Path("/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    )


def _paste_center(
    base: Image.Image,
    overlay: Image.Image,
    center_x: float,
    center_y: float,
) -> None:
    base.alpha_composite(
        overlay,
        (
            round(center_x - overlay.width / 2),
            round(center_y - overlay.height / 2),
        ),
    )
