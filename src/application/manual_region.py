from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from src.application.ocr import RecognizeText
from src.application.ports import (
    ImageCropper,
    InpaintingAdapter,
    MaskRasterizer,
    TextLayoutAdapter,
)
from src.application.translation import TranslateRegions
from src.domain.image import ImageAsset, ImageDocument, ImageFileFormat
from src.domain.inpainting import InpaintingRequest
from src.domain.manual_region import (
    ManualInputMode,
    ManualRegionError,
    ManualRegionResult,
    ManualRegionSpec,
    box_to_quad,
)
from src.domain.layout import CircularTextPath, TextBox
from src.domain.ocr import OcrResult, Quad, TextRegion
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
        merge_paragraphs: bool = True,
    ) -> ManualRegionResult:
        _validate_box(source, spec.selection_box)
        _validate_box(source, spec.erase_box)
        _validate_box(source, spec.text_box)
        region_id = f"manual-{uuid4().hex}"
        source_text = spec.source_text.strip()
        region_language = selection.source_language or ocr_language
        line_texts: tuple[str, ...] | None = None
        if spec.mode is ManualInputMode.AUTO:
            crop = self._cropper.crop(source, spec.selection_box)
            recognized = self._recognize.execute(
                _embed_crop_on_canvas(crop), ocr_language
            )
            region_language = recognized.language_code
            ocr_lines = tuple(
                region.text.strip() for region in recognized.regions if region.text.strip()
            )
            if not ocr_lines:
                raise ManualRegionError("manual_ocr_empty", "框选区域没有识别到文字")
            source_text = " ".join(ocr_lines)
            if not merge_paragraphs:
                line_texts = ocr_lines
        elif spec.mode is ManualInputMode.SOURCE_TEXT and not merge_paragraphs:
            input_lines = tuple(
                line.strip() for line in source_text.splitlines() if line.strip()
            )
            if len(input_lines) > 1:
                line_texts = input_lines
        line_translations: tuple[str, ...] | None = (
            self._translate_lines_independently(
                region_id,
                box_to_quad(spec.text_box),
                line_texts,
                region_language,
                selection,
                brand_terms,
                preserve_numbers,
            )
            if line_texts is not None
            else None
        )
        displayed_source = source_text or spec.translated_text.strip()
        # 短文模式：译文按行拼接（硬换行），渲染时逐行显示，避免挤成一段
        region_text = (
            "\n".join(line_texts) if line_texts is not None else displayed_source
        )
        region = TextRegion(
            region_id,
            box_to_quad(spec.text_box),
            region_text,
            1,
            region_language,
            "manual-input" if spec.mode is not ManualInputMode.AUTO else "manual-ocr",
        )
        ocr_result = OcrResult((region,), region_language, region.model_id, 0)
        if line_translations is not None:
            translated_text = "\n".join(line_translations)
            translation = TranslationResult(
                (
                    TranslationUnit(
                        region_id,
                        region_text,
                        region_language,
                        selection.target_language,
                        translated_text,
                        TranslationStatus.TRANSLATED,
                    ),
                ),
                selection,
                "manual-ocr",
                0,
            )
        elif spec.mode is ManualInputMode.TRANSLATED_TEXT:
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

    def _translate_lines_independently(
        self,
        region_id: str,
        quad: Quad,
        lines: tuple[str, ...],
        region_language: str,
        selection: TranslationSelection,
        brand_terms: tuple[str, ...],
        preserve_numbers: bool,
    ) -> tuple[str, ...]:
        """短文模式：逐行独立翻译，保留每行各自的语言筛选与保护规则。"""
        line_regions = tuple(
            TextRegion(
                f"{region_id}-{index}",
                quad,
                line,
                1,
                region_language,
                "manual-ocr",
            )
            for index, line in enumerate(lines)
        )
        line_ocr = OcrResult(line_regions, region_language, "manual-ocr", 0)
        translation = self._translate.execute(
            line_ocr,
            selection,
            brand_terms,
            allow_low_confidence=True,
            preserve_numbers=preserve_numbers,
            merge_paragraphs=False,
        )
        by_id = {unit.region_id: unit for unit in translation.units}
        ordered = tuple(by_id[f"{region_id}-{index}"] for index in range(len(lines)))
        if any(not unit.should_erase_source for unit in ordered):
            raise ManualRegionError(
                "manual_translation_skipped",
                "该文本被语言筛选或保护规则跳过；可直接输入译文覆盖",
            )
        return tuple(unit.translated_text for unit in ordered)

    def cancel(self) -> None:
        cancel = getattr(self._inpainting, "cancel", None)
        if cancel is not None:
            cancel()


def _validate_box(document: ImageDocument, box: TextBox) -> None:
    for point in box_to_quad(box):
        if not 0 <= point.x <= document.asset.width or not 0 <= point.y <= document.asset.height:
            raise ManualRegionError("manual_box_outside", "手动区域必须位于图片范围内")


def _embed_crop_on_canvas(
    crop: ImageDocument,
    minimum_size: int = 320,
) -> ImageDocument:
    """把框选裁剪图嵌入一个白底画布中央。

    DBNet 检测器对孤立小裁剪图（文字框紧贴文字）常常检不出任何文字，
    而同样的内容放在足够大的画布上就能正常识别。这里把裁剪子图原尺寸
    居中放入至少 320px 的白底画布，子图不缩放，避免引入额外失真。
    """
    import numpy as np

    height = crop.asset.height
    width = crop.asset.width
    canvas_size = max(minimum_size, width, height)
    channels = 4 if crop.mode == "RGBA" else 3
    pixels = np.frombuffer(crop.pixels, dtype=np.uint8).reshape(
        height, width, channels
    )
    canvas = np.full((canvas_size, canvas_size, channels), 255, dtype=np.uint8)
    y0 = (canvas_size - height) // 2
    x0 = (canvas_size - width) // 2
    canvas[y0 : y0 + height, x0 : x0 + width] = pixels
    asset = ImageAsset(
        Path("manual-crop-canvas.png"),
        canvas_size,
        canvas_size,
        1,
        ImageFileFormat.PNG,
        crop.mode == "RGBA",
        False,
    )
    return ImageDocument(asset, crop.mode, canvas.tobytes())


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
