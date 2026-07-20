from __future__ import annotations

from dataclasses import dataclass

from src.application.ports import InpaintingAdapter, MaskRasterizer
from src.domain.image import ImageDocument
from src.domain.inpainting import (
    EraseMask,
    InpaintingError,
    InpaintingRequest,
    RepairOutcome,
)
from src.domain.ocr import OcrResult
from src.domain.translation import TranslationResult, TranslationStatus


@dataclass(frozen=True, slots=True)
class EraseMaskPlan:
    erase_mask: EraseMask
    protect_mask: EraseMask | None


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
        return self.build_plan(document, ocr_result, translation_result).erase_mask

    def build_plan(
        self,
        document: ImageDocument,
        ocr_result: OcrResult,
        translation_result: TranslationResult,
    ) -> EraseMaskPlan:
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
        protect_mask = self.build_review_protect_mask(
            document,
            ocr_result,
            translation_result,
        )
        if protect_mask is None:
            return EraseMaskPlan(mask, None)
        effective_mask = EraseMask(
            mask.width,
            mask.height,
            bytes(
                erase if protected == 0 else 0
                for erase, protected in zip(
                    mask.pixels,
                    protect_mask.pixels,
                    strict=True,
                )
            ),
        )
        if effective_mask.is_empty:
            raise InpaintingError("empty_erase_mask", "擦除蒙版为空，请检查文字区域")
        return EraseMaskPlan(effective_mask, protect_mask)

    def build_review_protect_mask(
        self,
        document: ImageDocument,
        ocr_result: OcrResult,
        translation_result: TranslationResult,
    ) -> EraseMask | None:
        review_required = {
            unit.region_id
            for unit in translation_result.units
            if unit.status is TranslationStatus.REVIEW_REQUIRED
        }
        return self.build_region_protect_mask(
            document,
            ocr_result,
            review_required,
        )

    def build_region_protect_mask(
        self,
        document: ImageDocument,
        ocr_result: OcrResult,
        region_ids: set[str] | frozenset[str],
    ) -> EraseMask | None:
        if not region_ids:
            return None
        protect_polygons = tuple(
            tuple((point.x, point.y) for point in region.polygon)
            for region in ocr_result.regions
            if region.region_id in region_ids
        )
        if not protect_polygons:
            return None
        protect_mask = self._rasterizer.rasterize(
            document.asset.width,
            document.asset.height,
            protect_polygons,
            0,
        )
        return protect_mask


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
        plan = self._mask_builder.build_plan(document, ocr_result, translation_result)
        result = self._inpainting.inpaint(
            InpaintingRequest(
                document,
                plan.erase_mask,
                self._context_pixels,
                protect_mask=plan.protect_mask,
            )
        )
        return RepairOutcome(plan.erase_mask, result)

    def restore_review_pixels(
        self,
        original: ImageDocument,
        rendered: ImageDocument,
        ocr_result: OcrResult,
        translation_result: TranslationResult,
    ) -> ImageDocument:
        protect_mask = self._mask_builder.build_review_protect_mask(
            original,
            ocr_result,
            translation_result,
        )
        return self._restore_protected_pixels(original, rendered, protect_mask)

    def restore_region_pixels(
        self,
        original: ImageDocument,
        rendered: ImageDocument,
        ocr_result: OcrResult,
        region_ids: set[str] | frozenset[str],
    ) -> ImageDocument:
        protect_mask = self._mask_builder.build_region_protect_mask(
            original,
            ocr_result,
            region_ids,
        )
        return self._restore_protected_pixels(original, rendered, protect_mask)

    @staticmethod
    def _restore_protected_pixels(
        original: ImageDocument,
        rendered: ImageDocument,
        protect_mask: EraseMask | None,
    ) -> ImageDocument:
        if protect_mask is None:
            return rendered
        if (
            original.asset.width != rendered.asset.width
            or original.asset.height != rendered.asset.height
            or original.mode != rendered.mode
        ):
            raise ValueError("Original and rendered images must have matching geometry")
        channels = 4 if original.mode == "RGBA" else 3
        source = memoryview(original.pixels)
        restored = bytearray(rendered.pixels)
        for pixel_index, protected in enumerate(protect_mask.pixels):
            if protected:
                offset = pixel_index * channels
                restored[offset : offset + channels] = source[offset : offset + channels]
        return ImageDocument(rendered.asset, rendered.mode, bytes(restored))

    def close(self) -> None:
        close = getattr(self._inpainting, "close", None)
        if close is not None:
            close()

    def cancel(self) -> None:
        cancel = getattr(self._inpainting, "cancel", None)
        if cancel is not None:
            cancel()
