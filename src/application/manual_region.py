from __future__ import annotations

from dataclasses import replace
from uuid import uuid4

from src.application.ocr import RecognizeText
from src.application.ports import (
    ImageCropper,
    InpaintingAdapter,
    MaskRasterizer,
    TextLayoutAdapter,
)
from src.application.translation import TranslateRegions
from src.domain.image import ImageDocument
from src.domain.inpainting import InpaintingRequest
from src.domain.manual_region import (
    ManualInputMode,
    ManualRegionError,
    ManualRegionResult,
    ManualRegionSpec,
    box_to_quad,
)
from src.domain.layout import CircularTextPath, TextBox
from src.domain.ocr import OcrResult, TextRegion
from src.domain.translation import (
    TranslationResult,
    TranslationSelection,
    TranslationStatus,
    TranslationUnit,
)


class ProcessManualRegion:
    def __init__(
        self,
        recognize: RecognizeText,
        translate: TranslateRegions,
        cropper: ImageCropper,
        rasterizer: MaskRasterizer,
        inpainting: InpaintingAdapter,
        layout: TextLayoutAdapter,
        mask_expansion: int = 2,
    ) -> None:
        self._recognize = recognize
        self._translate = translate
        self._cropper = cropper
        self._rasterizer = rasterizer
        self._inpainting = inpainting
        self._layout = layout
        self._mask_expansion = mask_expansion

    def execute(
        self,
        source: ImageDocument,
        working_background: ImageDocument,
        spec: ManualRegionSpec,
        ocr_language: str,
        selection: TranslationSelection,
        brand_terms: tuple[str, ...] = (),
        preserve_numbers: bool = True,
    ) -> ManualRegionResult:
        _validate_box(source, spec.selection_box)
        _validate_box(source, spec.erase_box)
        _validate_box(source, spec.text_box)
        region_id = f"manual-{uuid4().hex}"
        source_text = spec.source_text.strip()
        region_language = selection.source_language or ocr_language
        if spec.mode is ManualInputMode.AUTO:
            crop = self._cropper.crop(source, spec.selection_box)
            recognized = self._recognize.execute(crop, ocr_language)
            region_language = recognized.language_code
            source_text = " ".join(
                region.text.strip() for region in recognized.regions if region.text.strip()
            )
            if not source_text:
                raise ManualRegionError("manual_ocr_empty", "框选区域没有识别到文字")
        displayed_source = source_text or spec.translated_text.strip()
        region = TextRegion(
            region_id,
            box_to_quad(spec.text_box),
            displayed_source,
            1,
            region_language,
            "manual-input" if spec.mode is not ManualInputMode.AUTO else "manual-ocr",
        )
        ocr_result = OcrResult((region,), region_language, region.model_id, 0)
        if spec.mode is ManualInputMode.TRANSLATED_TEXT:
            translated_text = spec.translated_text.strip()
            translation = TranslationResult(
                (
                    TranslationUnit(
                        region_id,
                        displayed_source,
                        region_language,
                        selection.target_language,
                        translated_text,
                        TranslationStatus.TRANSLATED,
                    ),
                ),
                selection,
                "manual-direct",
                0,
            )
        else:
            translation = self._translate.execute(
                ocr_result,
                selection,
                brand_terms,
                allow_low_confidence=True,
                preserve_numbers=preserve_numbers,
            )
            unit = translation.units[0]
            if not unit.should_erase_source:
                raise ManualRegionError(
                    "manual_translation_skipped",
                    "该文本被语言筛选或保护规则跳过；可直接输入译文覆盖",
                )
            translated_text = unit.translated_text
        erase_polygon = tuple(
            (point.x, point.y) for point in box_to_quad(spec.erase_box)
        )
        erase_mask = self._rasterizer.rasterize(
            working_background.asset.width,
            working_background.asset.height,
            (erase_polygon,),
            self._mask_expansion,
        )
        reset_cancel = getattr(self._inpainting, "reset_cancel", None)
        if reset_cancel is not None:
            reset_cancel()
        repaired = self._inpainting.inpaint(
            InpaintingRequest(working_background, erase_mask)
        )
        text_layout = self._layout.layout(source, ocr_result, translation)
        if len(text_layout.layers) != 1:
            raise ManualRegionError("manual_layout_failed", "手动区域没有生成唯一译文图层")
        layer = text_layout.layers[0]
        if spec.circular_path is not None:
            use_tangent_box = (
                isinstance(spec.circular_path, CircularTextPath)
                and _contains_latin(source_text)
                and 0 < _cjk_character_count(translated_text) <= 2
            )
            text_box = (
                replace(
                    spec.text_box,
                    height=spec.text_box.height
                    + min(1.5, spec.text_box.height * 0.15),
                )
                if use_tangent_box
                else spec.text_box
            )
            layer = self._layout.reflow(
                replace(
                    layer,
                    box=text_box,
                    path=None if use_tangent_box else spec.circular_path,
                ),
                layer.text,
            )
            if (
                isinstance(spec.circular_path, CircularTextPath)
                and _contains_latin(source_text)
                and _contains_cjk(translated_text)
            ):
                maximum_font_size = spec.text_box.height * (
                    0.85 if use_tangent_box else 0.72
                )
                layer = replace(
                    layer,
                    style=replace(
                        layer.style,
                        font_size=min(
                            layer.style.font_size,
                            max(6.0, maximum_font_size),
                        ),
                        wrap=False,
                    ),
                )
        return ManualRegionResult(
            region_id,
            source_text,
            translated_text,
            erase_mask,
            repaired,
            layer,
        )

    def cancel(self) -> None:
        cancel = getattr(self._inpainting, "cancel", None)
        if cancel is not None:
            cancel()


def _validate_box(document: ImageDocument, box: TextBox) -> None:
    for point in box_to_quad(box):
        if not 0 <= point.x <= document.asset.width or not 0 <= point.y <= document.asset.height:
            raise ManualRegionError("manual_box_outside", "手动区域必须位于图片范围内")


def _contains_latin(text: str) -> bool:
    return any(
        "A" <= character <= "Z" or "a" <= character <= "z"
        for character in text
    )


def _contains_cjk(text: str) -> bool:
    return any(
        "\u3400" <= character <= "\u9fff"
        or "\uf900" <= character <= "\ufaff"
        for character in text
    )


def _cjk_character_count(text: str) -> int:
    return sum(
        "\u3400" <= character <= "\u9fff"
        or "\uf900" <= character <= "\ufaff"
        for character in text
    )
