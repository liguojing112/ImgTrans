from __future__ import annotations

from pathlib import Path
from typing import Protocol

from src.domain.image import ImageDocument, ImageFileFormat, ImageLimits
from src.domain.inpainting import EraseMask, InpaintingRequest, InpaintingResult
from src.domain.layout import TextBox, TextLayer, TextLayout
from src.domain.ocr import OcrResult
from src.domain.translation import TranslationAdapterItem, TranslationResult


class ImageCodec(Protocol):
    def load(self, source: Path, limits: ImageLimits) -> ImageDocument: ...

    def save(
        self, document: ImageDocument, target: Path, output_format: ImageFileFormat
    ) -> None: ...


class ImageCropper(Protocol):
    def crop(self, document: ImageDocument, box: TextBox) -> ImageDocument: ...


class OcrAdapter(Protocol):
    @property
    def language_codes(self) -> tuple[str, ...]: ...

    def recognize(self, document: ImageDocument, language_code: str) -> OcrResult: ...


class TranslationAdapter(Protocol):
    @property
    def adapter_id(self) -> str: ...

    def translate(
        self,
        texts: tuple[str, ...],
        source_language: str | None,
        target_language: str,
    ) -> tuple[TranslationAdapterItem, ...]: ...


class MaskRasterizer(Protocol):
    def rasterize(
        self,
        width: int,
        height: int,
        polygons: tuple[tuple[tuple[float, float], ...], ...],
        expansion: int,
    ) -> EraseMask: ...


class InpaintingAdapter(Protocol):
    @property
    def adapter_id(self) -> str: ...

    def inpaint(self, request: InpaintingRequest) -> InpaintingResult: ...


class TextLayoutAdapter(Protocol):
    def layout(
        self,
        source: ImageDocument,
        ocr_result: OcrResult,
        translation_result: TranslationResult,
    ) -> TextLayout: ...

    def reflow(self, layer: TextLayer, text: str) -> TextLayer: ...

    def create_layer(
        self, region_id: str, text: str, box: TextBox
    ) -> TextLayer: ...


class TextRenderer(Protocol):
    def render(self, document: ImageDocument, layout: TextLayout) -> ImageDocument: ...


class BatchResultStore(Protocol):
    def save(
        self, batch_id: str, item_id: str, document: ImageDocument
    ) -> str: ...

    def load(self, result_ref: str) -> ImageDocument: ...

    def clear(self, batch_id: str) -> None: ...
