import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from src.application.inpainting import BuildEraseMask, RepairTranslatedRegions
from src.application.ocr import RecognizeText
from src.application.translate_image import TranslateImage
from src.application.translation import TranslateRegions
from src.domain.image import ImageAsset, ImageDocument, ImageFileFormat
from src.domain.inpainting import InpaintingRequest, InpaintingResult
from src.domain.job import ImageStage, JobCancelled, JobStatus
from src.domain.layout import TextBox, TextLayer, TextLayout, TextStyle
from src.domain.ocr import OcrResult, TextRegion, order_quad
from src.domain.protection import ProtectionEngine
from src.domain.translation import (
    TranslationAdapterItem,
    TranslationMode,
    TranslationSelection,
    TranslationStatus,
)
from src.infrastructure.pillow_mask_rasterizer import PillowMaskRasterizer
from src.infrastructure.text_renderer import QtBasicTextLayoutAdapter, QtTextRenderer


class FixtureOcrAdapter:
    language_codes = ("en",)

    def recognize(self, document: ImageDocument, language_code: str) -> OcrResult:
        regions = (
            TextRegion(
                "low",
                order_quad(((18, 18), (78, 18), (78, 48), (18, 48))),
                "SUMMER",
                0.74,
                "en",
                "fixture",
            ),
            TextRegion(
                "high",
                order_quad(((95, 18), (145, 18), (145, 48), (95, 48))),
                "SALE",
                0.90,
                "en",
                "fixture",
            ),
            TextRegion(
                "number",
                order_quad(((150, 18), (180, 18), (180, 48), (150, 48))),
                "2026",
                0.99,
                "en",
                "fixture",
            ),
        )
        return OcrResult(regions, language_code, "fixture", 1)


class RecordingTranslationAdapter:
    adapter_id = "recording-fixture"

    def __init__(self) -> None:
        self.calls: list[tuple[tuple[str, ...], str | None, str]] = []

    def translate(self, texts, source_language, target_language):
        self.calls.append((texts, source_language, target_language))
        return tuple(
            TranslationAdapterItem(translated_text="translated")
            for _ in texts
        )


class FixtureRepairAdapter:
    adapter_id = "fixture-repair"

    def inpaint(self, request: InpaintingRequest) -> InpaintingResult:
        pixels = np.frombuffer(request.document.pixels, dtype=np.uint8).reshape(72, 190, 3).copy()
        mask = np.frombuffer(request.erase_mask.pixels, dtype=np.uint8).reshape(72, 190) > 0
        pixels[mask] = (235, 235, 235)
        repaired = ImageDocument(request.document.asset, "RGB", pixels.tobytes())
        return InpaintingResult(repaired, self.adapter_id, 1)


class RecordingRenderer:
    def __init__(self) -> None:
        self.received_layout: TextLayout | None = None

    def render(self, document: ImageDocument, layout: TextLayout) -> ImageDocument:
        self.received_layout = layout
        return QtTextRenderer().render(document, layout)


def _document() -> ImageDocument:
    pixels = np.full((72, 190, 3), 235, dtype=np.uint8)
    pixels[18:49, 18:171] = (25, 35, 50)
    asset = ImageAsset(Path("workflow.png"), 190, 72, 1, ImageFileFormat.PNG, False, False)
    return ImageDocument(asset, "RGB", pixels.tobytes())


def _workflow(
    translation_adapter: RecordingTranslationAdapter | None = None,
    renderer: RecordingRenderer | None = None,
) -> TranslateImage:
    recognize = RecognizeText(FixtureOcrAdapter())
    translate = TranslateRegions(
        translation_adapter or RecordingTranslationAdapter(),
        ProtectionEngine(),
    )
    repair = RepairTranslatedRegions(
        BuildEraseMask(PillowMaskRasterizer(), expansion=0),
        FixtureRepairAdapter(),
    )
    return TranslateImage(
        recognize,
        translate,
        repair,
        QtBasicTextLayoutAdapter(),
        renderer or QtTextRenderer(),
    )


def test_workflow_completes_all_stages_and_excludes_protected_region() -> None:
    QApplication.instance() or QApplication(["workflow-integration-test"])
    stages: list[ImageStage] = []
    adapter = RecordingTranslationAdapter()
    renderer = RecordingRenderer()
    source = _document()
    result = _workflow(adapter, renderer).execute(
        source,
        "en",
        TranslationSelection(TranslationMode.ALL, "zh-Hans"),
        on_stage=stages.append,
    )
    assert result.job.status is JobStatus.COMPLETED
    assert tuple(stages) == tuple(ImageStage)
    assert [unit.status for unit in result.translation.units] == [
        TranslationStatus.REVIEW_REQUIRED,
        TranslationStatus.TRANSLATED,
        TranslationStatus.SKIPPED_PROTECTED,
    ]
    assert adapter.calls == [(("SALE",), None, "zh-Hans")]
    assert not any(layer.overflow for layer in result.layout.layers)
    assert renderer.received_layout is result.layout
    assert [layer.region_id for layer in result.layout.layers] == ["high"]
    assert result.repair.erase_mask.pixels[25 * 190 + 25] == 0
    assert result.repair.erase_mask.pixels[25 * 190 + 120] == 255
    assert result.repair.erase_mask.pixels[25 * 190 + 165] == 0
    before = np.frombuffer(source.pixels, dtype=np.uint8).reshape(72, 190, 3)
    after = np.frombuffer(result.document.pixels, dtype=np.uint8).reshape(72, 190, 3)
    assert result.document.pixels != result.repair.result.document.pixels
    assert np.array_equal(after[18:49, 18:79], before[18:49, 18:79])
    assert not np.array_equal(after[18:49, 95:146], before[18:49, 95:146])
    assert not any(
        unit.status is TranslationStatus.FAILED for unit in result.translation.units
    )


def test_workflow_cancels_at_stage_boundary() -> None:
    QApplication.instance() or QApplication(["workflow-cancel-test"])
    workflow = _workflow()

    def cancel_on_translation(stage: ImageStage) -> None:
        if stage is ImageStage.TRANSLATION:
            workflow.cancel()

    with pytest.raises(JobCancelled):
        workflow.execute(
            _document(),
            "en",
            TranslationSelection(TranslationMode.ALL, "zh-Hans"),
            on_stage=cancel_on_translation,
        )


class AdjacentFixtureOcrAdapter:
    language_codes = ("en",)

    def recognize(self, document: ImageDocument, language_code: str) -> OcrResult:
        return OcrResult(
            (
                TextRegion(
                    "high",
                    order_quad(((18, 18), (68, 18), (68, 48), (18, 48))),
                    "SALE",
                    0.90,
                    "en",
                    "fixture",
                ),
                TextRegion(
                    "low",
                    order_quad(((70, 18), (120, 18), (120, 48), (70, 48))),
                    "SUMMER",
                    0.74,
                    "en",
                    "fixture",
                ),
            ),
            language_code,
            "fixture",
            1,
        )


class ShortTranslationAdapter(RecordingTranslationAdapter):
    def translate(self, texts, source_language, target_language):
        self.calls.append((texts, source_language, target_language))
        return tuple(TranslationAdapterItem(translated_text="OK") for _ in texts)


class RecordingProtectRepairAdapter:
    adapter_id = "recording-protect-repair"

    def __init__(self) -> None:
        self.request = None

    def inpaint(self, request: InpaintingRequest) -> InpaintingResult:
        self.request = request
        height = request.document.asset.height
        width = request.document.asset.width
        channels = 4 if request.document.mode == "RGBA" else 3
        pixels = np.frombuffer(request.document.pixels, dtype=np.uint8).reshape(
            height, width, channels
        ).copy()
        mask = np.frombuffer(request.erase_mask.pixels, dtype=np.uint8).reshape(
            height, width
        ) > 0
        if request.protect_mask is not None:
            protected = np.frombuffer(
                request.protect_mask.pixels, dtype=np.uint8
            ).reshape(height, width) > 0
            mask &= ~protected
        pixels[mask, :3] = (235, 235, 235)
        repaired = ImageDocument(
            request.document.asset,
            request.document.mode,
            pixels.tobytes(),
        )
        return InpaintingResult(repaired, self.adapter_id, 1)


def _adjacent_document(mode: str = "RGB") -> ImageDocument:
    channels = 4 if mode == "RGBA" else 3
    pixels = np.full((72, 190, channels), 235, dtype=np.uint8)
    pixels[18:49, 18:69, :3] = (25, 35, 50)
    pixels[18:49, 70:121, :3] = (65, 20, 25)
    if mode == "RGBA":
        pixels[:, :, 3] = 211
        pixels[18:49, 70:121, 3] = 123
    asset = ImageAsset(
        Path("adjacent.png"),
        190,
        72,
        1,
        ImageFileFormat.PNG,
        mode == "RGBA",
        False,
    )
    return ImageDocument(asset, mode, pixels.tobytes())


class BleedingTextRenderer:
    def __init__(self) -> None:
        self.raw_rendered: ImageDocument | None = None

    def render(self, document: ImageDocument, layout) -> ImageDocument:
        rendered = QtTextRenderer().render(document, layout)
        channels = 4 if rendered.mode == "RGBA" else 3
        pixels = np.frombuffer(rendered.pixels, dtype=np.uint8).reshape(
            72, 190, channels
        ).copy()
        pixels[30, 75] = (1, 2, 3, 4) if channels == 4 else (1, 2, 3)
        self.raw_rendered = ImageDocument(
            rendered.asset,
            rendered.mode,
            pixels.tobytes(),
        )
        return self.raw_rendered


def test_adjacent_review_region_pixels_survive_expanded_translation_mask() -> None:
    QApplication.instance() or QApplication(["workflow-adjacent-review-test"])
    translation_adapter = ShortTranslationAdapter()
    repair_adapter = RecordingProtectRepairAdapter()
    workflow = TranslateImage(
        RecognizeText(AdjacentFixtureOcrAdapter()),
        TranslateRegions(translation_adapter, ProtectionEngine()),
        RepairTranslatedRegions(
            BuildEraseMask(PillowMaskRasterizer(), expansion=2),
            repair_adapter,
        ),
        QtBasicTextLayoutAdapter(),
        QtTextRenderer(),
    )
    source = _adjacent_document()
    result = workflow.execute(
        source,
        "en",
        TranslationSelection(TranslationMode.ALL, "zh-Hans"),
    )

    assert [unit.status for unit in result.translation.units] == [
        TranslationStatus.TRANSLATED,
        TranslationStatus.REVIEW_REQUIRED,
    ]
    assert translation_adapter.calls == [(("SALE",), None, "zh-Hans")]
    assert [layer.region_id for layer in result.layout.layers] == ["high"]
    assert repair_adapter.request is not None
    assert repair_adapter.request.protect_mask is not None
    effective = np.frombuffer(
        repair_adapter.request.erase_mask.pixels, dtype=np.uint8
    ).reshape(72, 190)
    protected = np.frombuffer(
        repair_adapter.request.protect_mask.pixels, dtype=np.uint8
    ).reshape(72, 190)
    assert effective[30, 70] == 0
    assert protected[30, 70] == 255
    assert effective[30, 30] == 255
    assert np.count_nonzero((effective > 0) & (protected > 0)) == 0
    before = np.frombuffer(source.pixels, dtype=np.uint8).reshape(72, 190, 3)
    after = np.frombuffer(result.document.pixels, dtype=np.uint8).reshape(72, 190, 3)
    assert np.array_equal(after[18:49, 70:121], before[18:49, 70:121])
    assert not np.array_equal(after[18:49, 18:69], before[18:49, 18:69])
    assert not any(
        unit.status is TranslationStatus.FAILED for unit in result.translation.units
    )


@pytest.mark.parametrize("mode", ("RGB", "RGBA"))
def test_review_pixels_are_restored_after_text_rendering(mode: str) -> None:
    QApplication.instance() or QApplication(["workflow-render-protection-test"])
    translation_adapter = ShortTranslationAdapter()
    repair_adapter = RecordingProtectRepairAdapter()
    renderer = BleedingTextRenderer()
    workflow = TranslateImage(
        RecognizeText(AdjacentFixtureOcrAdapter()),
        TranslateRegions(translation_adapter, ProtectionEngine()),
        RepairTranslatedRegions(
            BuildEraseMask(PillowMaskRasterizer(), expansion=2),
            repair_adapter,
        ),
        QtBasicTextLayoutAdapter(),
        renderer,
    )
    source = _adjacent_document(mode)
    result = workflow.execute(
        source,
        "en",
        TranslationSelection(TranslationMode.ALL, "zh-Hans"),
    )

    channels = 4 if mode == "RGBA" else 3
    before = np.frombuffer(source.pixels, dtype=np.uint8).reshape(72, 190, channels)
    assert renderer.raw_rendered is not None
    raw_rendered = np.frombuffer(
        renderer.raw_rendered.pixels, dtype=np.uint8
    ).reshape(72, 190, channels)
    after = np.frombuffer(result.document.pixels, dtype=np.uint8).reshape(
        72, 190, channels
    )
    assert not np.array_equal(raw_rendered[30, 75], before[30, 75])
    assert np.array_equal(after[18:49, 70:121], before[18:49, 70:121])
    assert not np.array_equal(after[18:49, 18:69], before[18:49, 18:69])
    assert [layer.region_id for layer in result.layout.layers] == ["high"]
    assert not any(
        unit.status is TranslationStatus.FAILED for unit in result.translation.units
    )


class OverflowFixtureOcrAdapter:
    language_codes = ("en",)

    def recognize(self, document: ImageDocument, language_code: str) -> OcrResult:
        return OcrResult(
            (
                TextRegion(
                    "overflow",
                    order_quad(((18, 18), (58, 18), (58, 48), (18, 48))),
                    "OVERFLOW",
                    0.90,
                    "en",
                    "fixture",
                ),
                TextRegion(
                    "normal",
                    order_quad(((60, 18), (100, 18), (100, 48), (60, 48))),
                    "SALE",
                    0.90,
                    "en",
                    "fixture",
                ),
                TextRegion(
                    "review",
                    order_quad(((102, 18), (142, 18), (142, 48), (102, 48))),
                    "UNCERTAIN",
                    0.74,
                    "en",
                    "fixture",
                ),
            ),
            language_code,
            "fixture",
            1,
        )


class OverflowFixtureLayoutAdapter:
    def layout(self, source, ocr_result, translation_result) -> TextLayout:
        overflow_style = TextStyle(
            "Arial",
            18,
            (255, 255, 255),
            stroke_rgb=(0, 0, 0),
            stroke_width=2,
            shadow_opacity=0.8,
        )
        normal_style = TextStyle("Arial", 12, (255, 255, 255))
        return TextLayout(
            (
                TextLayer(
                    "overflow",
                    "TOO LONG",
                    TextBox(38, 33, 40, 30),
                    overflow_style,
                    overflow=True,
                ),
                TextLayer(
                    "normal",
                    "OK",
                    TextBox(80, 33, 40, 30),
                    normal_style,
                ),
            )
        )


class OverflowBleedingRenderer:
    def __init__(self) -> None:
        self.received_layout: TextLayout | None = None
        self.raw_rendered: ImageDocument | None = None

    def render(self, document: ImageDocument, layout: TextLayout) -> ImageDocument:
        self.received_layout = layout
        rendered = QtTextRenderer().render(document, layout)
        channels = 4 if rendered.mode == "RGBA" else 3
        pixels = np.frombuffer(rendered.pixels, dtype=np.uint8).reshape(
            72, 190, channels
        ).copy()
        changed = (1, 2, 3, 4) if channels == 4 else (1, 2, 3)
        pixels[30, 40] = changed
        pixels[30, 120] = changed
        self.raw_rendered = ImageDocument(
            rendered.asset,
            rendered.mode,
            pixels.tobytes(),
        )
        return self.raw_rendered


def _overflow_document(mode: str) -> ImageDocument:
    channels = 4 if mode == "RGBA" else 3
    pixels = np.full((72, 190, channels), 235, dtype=np.uint8)
    pixels[18:49, 18:59, :3] = (25, 35, 50)
    pixels[18:49, 60:101, :3] = (45, 55, 65)
    pixels[18:49, 102:143, :3] = (65, 20, 25)
    if mode == "RGBA":
        pixels[:, :, 3] = 211
        pixels[18:49, 18:59, 3] = 87
        pixels[18:49, 102:143, 3] = 123
    asset = ImageAsset(
        Path("overflow.png"),
        190,
        72,
        1,
        ImageFileFormat.PNG,
        mode == "RGBA",
        False,
    )
    return ImageDocument(asset, mode, pixels.tobytes())


@pytest.mark.parametrize("mode", ("RGB", "RGBA"))
def test_overflow_layer_is_not_rendered_and_original_pixels_are_restored(
    mode: str,
) -> None:
    QApplication.instance() or QApplication(["workflow-overflow-safety-test"])
    translation_adapter = ShortTranslationAdapter()
    repair_adapter = RecordingProtectRepairAdapter()
    renderer = OverflowBleedingRenderer()
    workflow = TranslateImage(
        RecognizeText(OverflowFixtureOcrAdapter()),
        TranslateRegions(translation_adapter, ProtectionEngine()),
        RepairTranslatedRegions(
            BuildEraseMask(PillowMaskRasterizer(), expansion=2),
            repair_adapter,
        ),
        OverflowFixtureLayoutAdapter(),
        renderer,
    )
    source = _overflow_document(mode)
    result = workflow.execute(
        source,
        "en",
        TranslationSelection(TranslationMode.ALL, "zh-Hans"),
    )

    assert renderer.received_layout is not None
    assert [layer.region_id for layer in renderer.received_layout.layers] == [
        "normal"
    ]
    assert [layer.region_id for layer in result.layout.layers] == [
        "overflow",
        "normal",
    ]
    assert result.layout.layer_by_id("overflow").overflow
    assert not result.layout.layer_by_id("normal").overflow
    assert [unit.status for unit in result.translation.units] == [
        TranslationStatus.TRANSLATED,
        TranslationStatus.TRANSLATED,
        TranslationStatus.REVIEW_REQUIRED,
    ]
    channels = 4 if mode == "RGBA" else 3
    before = np.frombuffer(source.pixels, dtype=np.uint8).reshape(72, 190, channels)
    assert renderer.raw_rendered is not None
    raw = np.frombuffer(renderer.raw_rendered.pixels, dtype=np.uint8).reshape(
        72, 190, channels
    )
    after = np.frombuffer(result.document.pixels, dtype=np.uint8).reshape(
        72, 190, channels
    )
    assert not np.array_equal(raw[30, 40], before[30, 40])
    assert not np.array_equal(raw[30, 120], before[30, 120])
    assert np.array_equal(after[18:49, 18:59], before[18:49, 18:59])
    assert np.array_equal(after[18:49, 102:143], before[18:49, 102:143])
    assert not np.array_equal(after[18:49, 60:101], before[18:49, 60:101])
    assert not any(
        unit.status is TranslationStatus.FAILED for unit in result.translation.units
    )
