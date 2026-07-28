from pathlib import Path

import numpy as np
import pytest

from src.application.inpainting import BuildEraseMask, RepairTranslatedRegions
from src.domain.image import ImageAsset, ImageDocument, ImageFileFormat
from src.domain.inpainting import (
    EraseMask,
    InpaintingError,
    InpaintingRequest,
    InpaintingResult,
)
from src.domain.ocr import OcrMode, OcrResult, TextRegion, order_quad
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


def test_confirmed_enhanced_region_expands_glyph_mask_without_erasing_background() -> None:
    pixels = np.full((50, 100, 3), 255, dtype=np.uint8)
    pixels[20:30, 45:49] = 0
    document = ImageDocument(
        ImageAsset(
            Path("enhanced-ring.png"),
            100,
            50,
            1,
            ImageFileFormat.PNG,
            False,
            False,
        ),
        "RGB",
        pixels.tobytes(),
    )
    region = TextRegion(
        "enhanced",
        order_quad(((30, 15), (70, 15), (70, 35), (30, 35))),
        "Sales",
        0.95,
        "en",
        "fixture",
        enhanced_only=True,
        auto_process_eligible=True,
    )
    translation = TranslationResult(
        (
            TranslationUnit(
                "enhanced",
                "Sales",
                "en",
                "zh-Hans",
                "销售",
                TranslationStatus.TRANSLATED,
            ),
        ),
        TranslationSelection(TranslationMode.ALL, "zh-Hans"),
        "fixture",
        1,
    )

    mask = BuildEraseMask(PillowMaskRasterizer(), expansion=0).execute(
        document,
        OcrResult((region,), "en", "fixture", 1),
        translation,
    )

    assert mask.pixels[16 * mask.width + 31] == 0
    assert mask.pixels[20 * mask.width + 44] == 255
    assert mask.pixels[25 * mask.width + 47] == 255
    assert mask.pixels[10 * mask.width + 20] == 0


def test_high_recall_smooth_background_uses_complete_region_mask() -> None:
    pixels = np.full((50, 100, 3), 255, dtype=np.uint8)
    pixels[20:30, 45:49] = 0
    document = ImageDocument(
        ImageAsset(
            Path("high-recall-ring.png"),
            100,
            50,
            1,
            ImageFileFormat.PNG,
            False,
            False,
        ),
        "RGB",
        pixels.tobytes(),
    )
    region = TextRegion(
        "confirmed",
        order_quad(((30, 15), (70, 15), (70, 35), (30, 35))),
        "Sales",
        0.95,
        "en",
        "fixture",
        enhanced_only=True,
        auto_process_eligible=True,
    )
    translation = TranslationResult(
        (
            TranslationUnit(
                "confirmed",
                "Sales",
                "en",
                "zh-Hans",
                "销售",
                TranslationStatus.TRANSLATED,
            ),
        ),
        TranslationSelection(TranslationMode.ALL, "zh-Hans"),
        "fixture",
        1,
    )

    mask = BuildEraseMask(PillowMaskRasterizer(), expansion=0).execute(
        document,
        OcrResult(
            (region,),
            "en",
            "fixture",
            1,
            OcrMode.HIGH_RECALL,
        ),
        translation,
    )

    assert mask.pixels[16 * mask.width + 31] == 255
    assert mask.pixels[25 * mask.width + 50] == 255


def test_high_recall_stronger_confirmed_duplicate_is_preserved_as_one_region() -> None:
    document = _document()
    confirmed = TextRegion(
        "confirmed",
        order_quad(((10, 10), (50, 10), (50, 30), (10, 30))),
        "Global",
        0.95,
        "en",
        "fixture",
        enhanced_only=True,
        auto_process_eligible=True,
    )
    protected = TextRegion(
        "protected",
        order_quad(((11, 10), (49, 10), (49, 30), (11, 30))),
        "G1al",
        0.60,
        "en",
        "fixture",
    )
    selection = TranslationSelection(TranslationMode.ALL, "zh-Hans")
    translation = TranslationResult(
        (
            TranslationUnit(
                "confirmed",
                "Global",
                "en",
                "zh-Hans",
                "全球",
                TranslationStatus.TRANSLATED,
            ),
            TranslationUnit(
                "protected",
                "G1al",
                "en",
                "zh-Hans",
                "G1al",
                TranslationStatus.SKIPPED_PROTECTED,
            ),
        ),
        selection,
        "fixture",
        1,
    )

    conflicts = BuildEraseMask(
        PillowMaskRasterizer(),
        expansion=0,
    ).translated_protection_conflicts(
        document,
        OcrResult(
            (confirmed, protected),
            "en",
            "fixture",
            1,
            OcrMode.HIGH_RECALL,
        ),
        translation,
    )

    assert conflicts == frozenset({"confirmed"})


def test_color_aware_mask_erases_light_text_without_erasing_label_background() -> None:
    pixels = np.full((50, 100, 3), (178, 38, 24), dtype=np.uint8)
    pixels[16:34, 15:22] = (245, 235, 228)
    pixels[16:34, 35:42] = (245, 235, 228)
    pixels[16:34, 55:62] = (245, 235, 228)
    document = ImageDocument(
        ImageAsset(
            Path("solid-label.png"),
            100,
            50,
            1,
            ImageFileFormat.PNG,
            False,
            False,
        ),
        "RGB",
        pixels.tobytes(),
    )

    mask = PillowMaskRasterizer().rasterize_text(
        document,
        (((5, 5), (95, 5), (95, 45), (5, 45)),),
        0,
    )

    assert mask.pixels[20 * 100 + 18] == 255
    assert mask.pixels[20 * 100 + 38] == 255
    assert mask.pixels[20 * 100 + 58] == 255
    assert mask.pixels[10 * 100 + 10] == 0
    assert mask.pixels[25 * 100 + 75] == 0


def test_color_aware_mask_preserves_multiple_saturated_label_colors() -> None:
    pixels = np.full((50, 100, 3), (174, 38, 24), dtype=np.uint8)
    pixels[:, :35] = (3, 145, 126)
    pixels[16:34, 18:25] = (240, 232, 225)
    pixels[16:34, 48:55] = (240, 232, 225)
    document = ImageDocument(
        ImageAsset(
            Path("split-label.png"),
            100,
            50,
            1,
            ImageFileFormat.PNG,
            False,
            False,
        ),
        "RGB",
        pixels.tobytes(),
    )

    mask = PillowMaskRasterizer().rasterize_text(
        document,
        (((5, 5), (95, 5), (95, 45), (5, 45)),),
        0,
    )

    assert mask.pixels[20 * 100 + 20] == 255
    assert mask.pixels[20 * 100 + 50] == 255
    assert mask.pixels[25 * 100 + 10] == 0
    assert mask.pixels[25 * 100 + 80] == 0


@pytest.mark.parametrize(
    ("background", "foreground"),
    (
        ((139, 91, 155), (248, 248, 248)),
        ((151, 195, 55), (35, 35, 35)),
    ),
)
def test_vertical_colored_label_mask_erases_glyphs_without_erasing_background(
    background,
    foreground,
) -> None:
    pixels = np.full((120, 100, 3), (245, 245, 245), dtype=np.uint8)
    pixels[15:105, 40:60] = background
    for top in (25, 45, 65, 85):
        pixels[top : top + 10, 46:54] = foreground
    document = ImageDocument(
        ImageAsset(
            Path("vertical-label.png"),
            100,
            120,
            1,
            ImageFileFormat.PNG,
            False,
            False,
        ),
        "RGB",
        pixels.tobytes(),
    )

    mask = PillowMaskRasterizer().rasterize_text(
        document,
        (((38, 13), (62, 13), (62, 107), (38, 107)),),
        2,
    )

    assert mask.pixels[30 * 100 + 50] == 255
    assert mask.pixels[40 * 100 + 42] == 0
    assert mask.pixels[10 * 100 + 50] == 0


def test_color_aware_mask_erases_colored_text_on_neutral_background() -> None:
    pixels = np.full((50, 100, 3), (238, 238, 238), dtype=np.uint8)
    pixels[16:34, 18:25] = (30, 165, 180)
    pixels[16:34, 48:55] = (30, 165, 180)
    document = ImageDocument(
        ImageAsset(
            Path("colored-text.png"),
            100,
            50,
            1,
            ImageFileFormat.PNG,
            False,
            False,
        ),
        "RGB",
        pixels.tobytes(),
    )

    mask = PillowMaskRasterizer().rasterize_text(
        document,
        (((5, 5), (95, 5), (95, 45), (5, 45)),),
        0,
    )

    assert mask.pixels[20 * 100 + 20] == 255
    assert mask.pixels[20 * 100 + 50] == 255
    assert mask.pixels[25 * 100 + 10] == 0
    assert mask.pixels[25 * 100 + 80] == 0


def test_transparent_mask_uses_alpha_to_select_text_pixels() -> None:
    pixels = np.zeros((50, 100, 4), dtype=np.uint8)
    pixels[16:34, 18:25] = (30, 165, 180, 255)
    pixels[16:34, 48:55] = (220, 60, 95, 255)
    document = ImageDocument(
        ImageAsset(
            Path("transparent-text.png"),
            100,
            50,
            1,
            ImageFileFormat.PNG,
            True,
            False,
        ),
        "RGBA",
        pixels.tobytes(),
    )

    mask = PillowMaskRasterizer().rasterize_text(
        document,
        (((5, 5), (95, 5), (95, 45), (5, 45)),),
        0,
    )

    assert mask.pixels[20 * 100 + 20] == 255
    assert mask.pixels[20 * 100 + 50] == 255
    assert mask.pixels[25 * 100 + 10] == 0
    assert mask.pixels[25 * 100 + 80] == 0


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


def test_repair_preserves_original_when_all_regions_require_review() -> None:
    document = _document()
    region = _region("review", 10)
    ocr = OcrResult((region,), "en", "fixture", 1)
    translation = TranslationResult(
        (
            TranslationUnit(
                "review",
                "label",
                "en",
                "zh-Hans",
                "label",
                TranslationStatus.REVIEW_REQUIRED,
            ),
        ),
        TranslationSelection(TranslationMode.ALL, "zh-Hans"),
        "fixture",
        1,
    )
    repair = RepairTranslatedRegions(
        BuildEraseMask(PillowMaskRasterizer()),
        RecordingInpaintAdapter(),
    ).execute(document, ocr, translation)

    assert repair.erase_mask.is_empty
    assert repair.result.document is document
    assert repair.result.backend_id == "original-preserved"


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


def test_language_skipped_region_is_protected_from_adjacent_erase_mask() -> None:
    document = _document()
    ocr = OcrResult(
        (_region("translated", 10), _region("existing-target-text", 31)),
        "en",
        "fixture",
        1,
    )
    translation = TranslationResult(
        (
            TranslationUnit(
                "translated",
                "促销",
                "zh-Hans",
                "en",
                "Sale",
                TranslationStatus.TRANSLATED,
            ),
            TranslationUnit(
                "existing-target-text",
                "MIANXIAOFEI",
                "en",
                "en",
                "MIANXIAOFEI",
                TranslationStatus.SKIPPED_LANGUAGE,
            ),
        ),
        TranslationSelection(TranslationMode.ALL, "en"),
        "fixture",
        1,
    )

    plan = BuildEraseMask(
        PillowMaskRasterizer(),
        expansion=2,
    ).build_plan(document, ocr, translation)

    overlap = 20 * 100 + 31
    skipped_center = 20 * 100 + 40
    assert plan.protect_mask is not None
    assert plan.protect_mask.pixels[overlap] == 255
    assert plan.erase_mask.pixels[overlap] == 0
    assert plan.protect_mask.pixels[skipped_center] == 255


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
