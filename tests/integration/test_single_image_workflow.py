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
from src.domain.ocr import OcrResult, TextRegion, order_quad
from src.domain.protection import ProtectionEngine
from src.domain.translation import TranslationMode, TranslationSelection
from src.infrastructure.mock_translator import MockTranslationAdapter
from src.infrastructure.pillow_mask_rasterizer import PillowMaskRasterizer
from src.infrastructure.text_renderer import QtBasicTextLayoutAdapter, QtTextRenderer


class FixtureOcrAdapter:
    language_codes = ("en",)

    def recognize(self, document: ImageDocument, language_code: str) -> OcrResult:
        regions = (
            TextRegion(
                "sale",
                order_quad(((18, 18), (122, 18), (122, 48), (18, 48))),
                "SALE",
                0.99,
                "en",
                "fixture",
            ),
            TextRegion(
                "number",
                order_quad(((130, 18), (170, 18), (170, 48), (130, 48))),
                "2026",
                0.99,
                "en",
                "fixture",
            ),
        )
        return OcrResult(regions, language_code, "fixture", 1)


class FixtureRepairAdapter:
    adapter_id = "fixture-repair"

    def inpaint(self, request: InpaintingRequest) -> InpaintingResult:
        pixels = np.frombuffer(request.document.pixels, dtype=np.uint8).reshape(72, 190, 3).copy()
        mask = np.frombuffer(request.erase_mask.pixels, dtype=np.uint8).reshape(72, 190) > 0
        pixels[mask] = (235, 235, 235)
        repaired = ImageDocument(request.document.asset, "RGB", pixels.tobytes())
        return InpaintingResult(repaired, self.adapter_id, 1)


def _document() -> ImageDocument:
    pixels = np.full((72, 190, 3), 235, dtype=np.uint8)
    pixels[18:49, 18:171] = (25, 35, 50)
    asset = ImageAsset(Path("workflow.png"), 190, 72, 1, ImageFileFormat.PNG, False, False)
    return ImageDocument(asset, "RGB", pixels.tobytes())


def _workflow() -> TranslateImage:
    recognize = RecognizeText(FixtureOcrAdapter())
    translate = TranslateRegions(MockTranslationAdapter(), ProtectionEngine())
    repair = RepairTranslatedRegions(
        BuildEraseMask(PillowMaskRasterizer(), expansion=0),
        FixtureRepairAdapter(),
    )
    return TranslateImage(
        recognize,
        translate,
        repair,
        QtBasicTextLayoutAdapter(),
        QtTextRenderer(),
    )


def test_workflow_completes_all_stages_and_excludes_protected_region() -> None:
    QApplication.instance() or QApplication(["workflow-integration-test"])
    stages: list[ImageStage] = []
    result = _workflow().execute(
        _document(),
        "en",
        TranslationSelection(TranslationMode.ALL, "zh-Hans"),
        on_stage=stages.append,
    )
    assert result.job.status is JobStatus.COMPLETED
    assert tuple(stages) == tuple(ImageStage)
    assert [layer.region_id for layer in result.layout.layers] == ["sale"]
    assert result.translation.units[1].translated_text == "2026"
    assert not result.translation.units[1].should_erase_source
    assert result.document.pixels != _document().pixels


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
