from pathlib import Path

import pytest

from src.application.inpainting import BuildEraseMask, RepairTranslatedRegions
from src.domain.image import ImageAsset, ImageDocument, ImageFileFormat
from src.domain.inpainting import (
    EraseMask,
    InpaintingError,
    InpaintingRequest,
    InpaintingResult,
)
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

class RecordingRasterizer:
    def __init__(self) -> None:
        self._delegate = PillowMaskRasterizer()
        self.calls = []

    def rasterize(self, width, height, polygons, expansion):
        self.calls.append((width, height, polygons, expansion))
        return self._delegate.rasterize(width, height, polygons, expansion)


class RecordingInpaintAdapter:
    adapter_id = "recording-inpaint"

    def __init__(self) -> None:
        self.request = None

    def inpaint(self, request: InpaintingRequest) -> InpaintingResult:
        self.request = request
        return InpaintingResult(request.document, self.adapter_id, 1)


def _translated_and_review_result() -> TranslationResult:
    return TranslationResult(
        (
            TranslationUnit(
                "translated", "sale", "en", "zh-Hans", "促销", TranslationStatus.TRANSLATED
            ),
            TranslationUnit(
                "review", "label", "en", "zh-Hans", "label", TranslationStatus.REVIEW_REQUIRED
            ),
        ),
        TranslationSelection(TranslationMode.ALL, "zh-Hans"),
        "fixture",
        1,
    )


def test_review_mask_is_subtracted_from_adjacent_expanded_erase_mask() -> None:
    document = _document()
    ocr = OcrResult(
        (_region("translated", 10), _region("review", 31)),
        "en",
        "fixture",
        1,
    )
    rasterizer = RecordingRasterizer()
    builder = BuildEraseMask(rasterizer, expansion=2)
    plan = builder.build_plan(document, ocr, _translated_and_review_result())

    assert plan.protect_mask is not None
    assert (plan.protect_mask.width, plan.protect_mask.height) == (100, 80)
    assert [call[3] for call in rasterizer.calls] == [2, 0]
    assert rasterizer.calls[0][2] == (
        ((10.0, 10.0), (30.0, 10.0), (30.0, 30.0), (10.0, 30.0)),
    )
    original_erase = PillowMaskRasterizer().rasterize(
        100,
        80,
        rasterizer.calls[0][2],
        2,
    )
    overlap = 20 * 100 + 31
    translated_center = 20 * 100 + 20
    review_center = 20 * 100 + 40
    assert original_erase.pixels[overlap] == 255
    assert plan.protect_mask.pixels[overlap] == 255
    assert plan.erase_mask.pixels[overlap] == 0
    assert plan.protect_mask.pixels[review_center] == 255
    assert plan.erase_mask.pixels[translated_center] == 255
    assert not any(
        erase and protected
        for erase, protected in zip(
            plan.erase_mask.pixels,
            plan.protect_mask.pixels,
            strict=True,
        )
    )


def test_no_review_keeps_original_erase_mask_and_no_protection() -> None:
    document = _document()
    region = _region("translated", 10)
    ocr = OcrResult((region,), "en", "fixture", 1)
    translation = TranslationResult(
        (
            TranslationUnit(
                "translated", "sale", "en", "zh-Hans", "促销", TranslationStatus.TRANSLATED
            ),
        ),
        TranslationSelection(TranslationMode.ALL, "zh-Hans"),
        "fixture",
        1,
    )
    expected = PillowMaskRasterizer().rasterize(
        100,
        80,
        (((10.0, 10.0), (30.0, 10.0), (30.0, 30.0), (10.0, 30.0)),),
        2,
    )
    plan = BuildEraseMask(PillowMaskRasterizer(), expansion=2).build_plan(
        document, ocr, translation
    )
    assert plan.protect_mask is None
    assert plan.erase_mask.pixels == expected.pixels


def test_repair_passes_protection_and_returns_effective_mask() -> None:
    document = _document()
    ocr = OcrResult(
        (_region("translated", 10), _region("review", 31)),
        "en",
        "fixture",
        1,
    )
    adapter = RecordingInpaintAdapter()
    outcome = RepairTranslatedRegions(
        BuildEraseMask(PillowMaskRasterizer(), expansion=2),
        adapter,
    ).execute(document, ocr, _translated_and_review_result())
    assert adapter.request is not None
    assert adapter.request.protect_mask is not None
    assert outcome.erase_mask == adapter.request.erase_mask
    assert not any(
        erase and protected
        for erase, protected in zip(
            outcome.erase_mask.pixels,
            adapter.request.protect_mask.pixels,
            strict=True,
        )
    )


def test_repair_without_review_passes_no_protection() -> None:
    document = _document()
    region = _region("translated", 10)
    ocr = OcrResult((region,), "en", "fixture", 1)
    translation = TranslationResult(
        (
            TranslationUnit(
                "translated", "sale", "en", "zh-Hans", "促销", TranslationStatus.TRANSLATED
            ),
        ),
        TranslationSelection(TranslationMode.ALL, "zh-Hans"),
        "fixture",
        1,
    )
    adapter = RecordingInpaintAdapter()
    RepairTranslatedRegions(
        BuildEraseMask(PillowMaskRasterizer()), adapter
    ).execute(document, ocr, translation)
    assert adapter.request is not None
    assert adapter.request.protect_mask is None


def test_request_rejects_protection_mask_with_wrong_dimensions() -> None:
    with pytest.raises(ValueError):
        InpaintingRequest(
            _document(),
            EraseMask(100, 80, bytes(8000)),
            protect_mask=EraseMask(99, 80, bytes(99 * 80)),
        )
