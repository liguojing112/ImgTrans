from pathlib import Path

import pytest

from src.application.inpainting import BuildEraseMask
from src.domain.image import ImageAsset, ImageDocument, ImageFileFormat
from src.domain.inpainting import EraseMask, InpaintingError, InpaintingRequest
from src.domain.ocr import OcrResult, TextRegion, order_quad
from src.domain.translation import (
    TranslationMode,
    TranslationResult,
    TranslationSelection,
    TranslationStatus,
    TranslationUnit,
)
from src.infrastructure.pillow_mask_rasterizer import PillowMaskRasterizer


def _document() -> ImageDocument:
    asset = ImageAsset(Path("fixture.png"), 100, 80, 1, ImageFileFormat.PNG, False, False)
    return ImageDocument(asset, "RGB", bytes(100 * 80 * 3))


def _region(region_id: str, x: int) -> TextRegion:
    return TextRegion(
        region_id,
        order_quad(((x, 10), (x + 20, 10), (x + 20, 30), (x, 30))),
        region_id,
        0.99,
        "en",
        "fixture",
    )


def test_mask_buffer_must_match_dimensions() -> None:
    with pytest.raises(ValueError):
        EraseMask(2, 2, b"\x00")


def test_request_carries_independent_protection_mask() -> None:
    document = _document()
    erase = EraseMask(100, 80, bytes([255]) * 8000)
    protected = bytearray(8000)
    protected[10] = 255
    request = InpaintingRequest(
        document,
        erase,
        protect_mask=EraseMask(100, 80, bytes(protected)),
    )
    assert request.protect_mask is not None
    assert request.erase_mask.pixels[10] == 255
    assert request.protect_mask.pixels[10] == 255


def test_builder_only_rasterizes_regions_marked_for_erasure() -> None:
    document = _document()
    regions = (_region("translated", 10), _region("protected", 60))
    ocr = OcrResult(regions, "en", "fixture", 1)
    selection = TranslationSelection(TranslationMode.ALL, "zh-Hans")
    translation = TranslationResult(
        (
            TranslationUnit(
                "translated", "sale", "en", "zh-Hans", "促销", TranslationStatus.TRANSLATED
            ),
            TranslationUnit(
                "protected", "ACME", "en", "zh-Hans", "ACME", TranslationStatus.SKIPPED_PROTECTED
            ),
        ),
        selection,
        "fixture",
        1,
    )
    mask = BuildEraseMask(PillowMaskRasterizer(), expansion=0).execute(
        document, ocr, translation
    )
    assert mask.pixels[20 * mask.width + 15] == 255
    assert mask.pixels[20 * mask.width + 65] == 0


def test_builder_rejects_result_without_erasable_regions() -> None:
    document = _document()
    region = _region("protected", 10)
    ocr = OcrResult((region,), "en", "fixture", 1)
    translation = TranslationResult(
        (
            TranslationUnit(
                "protected", "123", "en", "zh-Hans", "123", TranslationStatus.SKIPPED_PROTECTED
            ),
        ),
        TranslationSelection(TranslationMode.ALL, "zh-Hans"),
        "fixture",
        1,
    )
    with pytest.raises(InpaintingError) as error:
        BuildEraseMask(PillowMaskRasterizer()).execute(document, ocr, translation)
    assert error.value.code == "no_erase_regions"
