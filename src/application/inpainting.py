from __future__ import annotations

from src.application.ports import InpaintingAdapter, MaskRasterizer
from src.domain.image import ImageDocument
from src.domain.inpainting import (
    EraseMask,
    InpaintingError,
    InpaintingRequest,
    RepairOutcome,
)
from src.domain.ocr import OcrResult
from src.domain.translation import TranslationResult


class BuildEraseMask:
    def __init__(self, rasterizer: MaskRasterizer, expansion: int = 2) -> None:
        if expansion < 0:
            raise ValueError("Mask expansion cannot be negative")
        self._rasterizer = rasterizer
        self._expansion = expansion

    def execute(
        self,
        document: ImageDocument,
        ocr_result: OcrResult,
        translation_result: TranslationResult,
    ) -> EraseMask:
        translated = {
            unit.region_id
            for unit in translation_result.units
            if unit.should_erase_source
        }
        polygons = tuple(
            tuple((point.x, point.y) for point in region.polygon)
            for region in ocr_result.regions
            if region.region_id in translated
        )
        if not polygons:
            raise InpaintingError("no_erase_regions", "没有需要擦除的已翻译文字区域")
        mask = self._rasterizer.rasterize(
            document.asset.width,
            document.asset.height,
            polygons,
            self._expansion,
        )
        if mask.is_empty:
            raise InpaintingError("empty_erase_mask", "擦除蒙版为空，请检查文字区域")
        return mask


class RepairTranslatedRegions:
    def __init__(
        self,
        mask_builder: BuildEraseMask,
        inpainting: InpaintingAdapter,
        context_pixels: int = 96,
    ) -> None:
        self._mask_builder = mask_builder
        self._inpainting = inpainting
        self._context_pixels = context_pixels

    def execute(
        self,
        document: ImageDocument,
        ocr_result: OcrResult,
        translation_result: TranslationResult,
    ) -> RepairOutcome:
        reset_cancel = getattr(self._inpainting, "reset_cancel", None)
        if reset_cancel is not None:
            reset_cancel()
        mask = self._mask_builder.execute(document, ocr_result, translation_result)
        result = self._inpainting.inpaint(
            InpaintingRequest(document, mask, self._context_pixels)
        )
        return RepairOutcome(mask, result)

    def close(self) -> None:
        close = getattr(self._inpainting, "close", None)
        if close is not None:
            close()

    def cancel(self) -> None:
        cancel = getattr(self._inpainting, "cancel", None)
        if cancel is not None:
            cancel()
