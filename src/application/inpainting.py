from __future__ import annotations

from dataclasses import dataclass

from src.application.ports import InpaintingAdapter, MaskRasterizer
from src.domain.image import ImageDocument
from src.domain.inpainting import (
    EraseMask,
    InpaintingError,
    InpaintingResult,
    InpaintingRequest,
    RepairOutcome,
)
from src.domain.ocr import OcrMode, OcrResult
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
        translated_regions = tuple(
            region
            for region in ocr_result.regions
            if region.region_id in translated
        )
        if not translated_regions:
            raise InpaintingError("no_erase_regions", "没有需要擦除的已翻译文字区域")
        rasterize_text = getattr(self._rasterizer, "rasterize_text", None)
        high_recall = ocr_result.mode is OcrMode.HIGH_RECALL
        regular_polygons = tuple(
            tuple((point.x, point.y) for point in region.polygon)
            for region in translated_regions
            if not high_recall and not region.enhanced_only
        )
        enhanced_polygons = tuple(
            tuple((point.x, point.y) for point in region.polygon)
            for region in translated_regions
            if high_recall or region.enhanced_only
        )
        masks: list[EraseMask] = []
        if regular_polygons:
            masks.append(
                rasterize_text(document, regular_polygons, self._expansion)
                if rasterize_text is not None
                else self._rasterizer.rasterize(
                    document.asset.width,
                    document.asset.height,
                    regular_polygons,
                    self._expansion,
                )
            )
        if enhanced_polygons:
            rasterize_mapped_text = (
                getattr(
                    self._rasterizer,
                    "rasterize_high_recall_text",
                    None,
                )
                if high_recall
                else None
            ) or getattr(
                self._rasterizer,
                "rasterize_mapped_text",
                None,
            )
            masks.append(
                rasterize_mapped_text(
                    document,
                    enhanced_polygons,
                    max(1, self._expansion),
                )
                if rasterize_mapped_text is not None
                else rasterize_text(
                    document,
                    enhanced_polygons,
                    self._expansion + 1,
                )
                if rasterize_text is not None
                else self._rasterizer.rasterize(
                    document.asset.width,
                    document.asset.height,
                    enhanced_polygons,
                    self._expansion,
                )
            )
        mask = masks[0]
        for additional in masks[1:]:
            mask = EraseMask(
                mask.width,
                mask.height,
                bytes(
                    max(existing, value)
                    for existing, value in zip(
                        mask.pixels,
                        additional.pixels,
                        strict=True,
                    )
                ),
            )
        if mask.is_empty:
            raise InpaintingError("empty_erase_mask", "擦除蒙版为空，请检查文字区域")
        protect_mask = self.build_automatic_protect_mask(
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

    def build_automatic_protect_mask(
        self,
        document: ImageDocument,
        ocr_result: OcrResult,
        translation_result: TranslationResult,
    ) -> EraseMask | None:
        protected = {
            unit.region_id
            for unit in translation_result.units
            if unit.status
            in {
                TranslationStatus.REVIEW_REQUIRED,
                TranslationStatus.SKIPPED_LANGUAGE,
                TranslationStatus.SKIPPED_PROTECTED,
            }
        }
        return self.build_region_protect_mask(
            document,
            ocr_result,
            protected,
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

    def translated_protection_conflicts(
        self,
        document: ImageDocument,
        ocr_result: OcrResult,
        translation_result: TranslationResult,
        minimum_overlap_ratio: float = 0.6,
    ) -> frozenset[str]:
        if ocr_result.mode is not OcrMode.HIGH_RECALL:
            return frozenset()
        protected_ids = {
            unit.region_id
            for unit in translation_result.units
            if unit.status
            in {
                TranslationStatus.REVIEW_REQUIRED,
                TranslationStatus.SKIPPED_LANGUAGE,
                TranslationStatus.SKIPPED_PROTECTED,
            }
        }
        translated_ids = {
            unit.region_id
            for unit in translation_result.units
            if unit.should_erase_source
        }
        regions = {region.region_id: region for region in ocr_result.regions}
        protected_masks = tuple(
            (
                regions[region_id],
                self._single_region_mask(document, regions[region_id]),
            )
            for region_id in protected_ids
            if region_id in regions
        )
        conflicts = set()
        for region_id in translated_ids:
            region = regions.get(region_id)
            if region is None or not region.enhanced_only:
                continue
            translated_mask = self._single_region_mask(document, region)
            translated_area = sum(value > 0 for value in translated_mask.pixels)
            if not translated_area:
                continue
            for protected_region, protected_mask in protected_masks:
                if region.confidence < protected_region.confidence + 0.15:
                    continue
                protected_area = sum(value > 0 for value in protected_mask.pixels)
                overlap = sum(
                    translated > 0 and protected > 0
                    for translated, protected in zip(
                        translated_mask.pixels,
                        protected_mask.pixels,
                        strict=True,
                    )
                )
                if overlap / max(1, min(translated_area, protected_area)) >= minimum_overlap_ratio:
                    conflicts.add(region_id)
                    break
        return frozenset(conflicts)

    def _single_region_mask(
        self,
        document: ImageDocument,
        region,
    ) -> EraseMask:
        return self._rasterizer.rasterize(
            document.asset.width,
            document.asset.height,
            (
                tuple((point.x, point.y) for point in region.polygon),
            ),
            0,
        )


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
        if not any(unit.should_erase_source for unit in translation_result.units):
            empty_mask = EraseMask(
                document.asset.width,
                document.asset.height,
                bytes(document.asset.width * document.asset.height),
            )
            return RepairOutcome(
                empty_mask,
                InpaintingResult(
                    document,
                    "original-preserved",
                    0,
                    "没有可靠的自动修改区域，已保留原图并等待人工复核",
                ),
            )
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

    def restore_automatic_protected_pixels(
        self,
        original: ImageDocument,
        rendered: ImageDocument,
        ocr_result: OcrResult,
        translation_result: TranslationResult,
    ) -> ImageDocument:
        protect_mask = self._mask_builder.build_automatic_protect_mask(
            original,
            ocr_result,
            translation_result,
        )
        return self._restore_protected_pixels(original, rendered, protect_mask)

    def translated_protection_conflicts(
        self,
        document: ImageDocument,
        ocr_result: OcrResult,
        translation_result: TranslationResult,
    ) -> frozenset[str]:
        return self._mask_builder.translated_protection_conflicts(
            document,
            ocr_result,
            translation_result,
        )

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


class RepairSelection:
    """手动 AI 消除：对用户蒙版膨胀/羽化后调用修复服务。"""

    def __init__(
        self,
        inpainting: InpaintingAdapter,
        context_pixels: int = 96,
        expansion_px: int = 3,
        feather_px: int = 0,
    ) -> None:
        self._inpainting = inpainting
        self._context_pixels = context_pixels
        self._expansion_px = expansion_px
        self._feather_px = feather_px

    def expand_mask(
        self,
        mask: EraseMask,
        expansion_px: int | None = None,
        feather_px: int | None = None,
    ) -> EraseMask:
        """对蒙版做膨胀/羽化（与 execute 内部使用相同参数）。"""
        return _expand_erase_mask(
            mask,
            self._expansion_px if expansion_px is None else expansion_px,
            self._feather_px if feather_px is None else feather_px,
        )

    def execute(
        self,
        document: ImageDocument,
        mask: EraseMask,
        expansion_px: int | None = None,
        feather_px: int | None = None,
    ) -> InpaintingResult:
        if mask.is_empty:
            raise InpaintingError("empty_erase_mask", "请先框选或绘制消除区域")
        reset_cancel = getattr(self._inpainting, "reset_cancel", None)
        if reset_cancel is not None:
            reset_cancel()
        expanded = self.expand_mask(mask, expansion_px, feather_px)
        return self._inpainting.inpaint(
            InpaintingRequest(
                document,
                expanded,
                self._context_pixels,
            )
        )

    def cancel(self) -> None:
        cancel = getattr(self._inpainting, "cancel", None)
        if cancel is not None:
            cancel()


def _expand_erase_mask(
    mask: EraseMask,
    expansion_px: int,
    feather_px: int,
) -> EraseMask:
    """膨胀蒙版（2~6px 避免残留文字边缘）；feather_px>0 时边缘高斯羽化。

    返回新 EraseMask；无膨胀/羽化时原样返回。
    """
    if expansion_px <= 0 and feather_px <= 0:
        return mask
    import numpy as np

    pixels = np.frombuffer(mask.pixels, dtype=np.uint8).reshape(
        mask.height, mask.width
    )
    if expansion_px > 0:
        import cv2

        kernel = np.ones(
            (expansion_px * 2 + 1, expansion_px * 2 + 1),
            dtype=np.uint8,
        )
        pixels = cv2.dilate(pixels, kernel)
    if feather_px > 0:
        import cv2

        sigma = max(0.5, feather_px / 2)
        pixels = cv2.GaussianBlur(
            pixels, (0, 0), sigmaX=sigma, sigmaY=sigma
        )
    return EraseMask(
        mask.width,
        mask.height,
        pixels.astype(np.uint8).tobytes(),
    )
