import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
import pytest

from src.application.manual_region import ProcessManualRegion
from src.application.ocr import RecognizeText
from src.application.translation import TranslateRegions
from src.domain.image import ImageAsset, ImageDocument, ImageFileFormat
from src.domain.inpainting import InpaintingRequest, InpaintingResult
from src.domain.layout import TextBox
from src.domain.manual_region import ManualInputMode, ManualRegionSpec
from src.domain.ocr import OcrResult, TextRegion, order_quad
from src.domain.protection import ProtectionEngine
from src.domain.translation import TranslationMode, TranslationSelection
from src.infrastructure.mock_translator import MockTranslationAdapter
from src.infrastructure.pillow_image_cropper import PillowImageCropper
from src.infrastructure.pillow_mask_rasterizer import PillowMaskRasterizer
from src.infrastructure.text_renderer import QtBasicTextLayoutAdapter


class _FixtureOcr:
    language_codes = ("en",)

    def recognize(self, document: ImageDocument, language_code: str) -> OcrResult:
        region = TextRegion(
            "crop-1",
            order_quad(((1, 1), (30, 1), (30, 12), (1, 12))),
            "SUMMER SALE",
            0.99,
            "en",
            "fixture",
        )
        return OcrResult((region,), "en", "fixture", 1)


class _FillInpaint:
    adapter_id = "fixture-fill"

    def inpaint(self, request: InpaintingRequest) -> InpaintingResult:
        pixels = bytearray(request.document.pixels)
        channels = 4 if request.document.mode == "RGBA" else 3
        for index, value in enumerate(request.erase_mask.pixels):
            if value:
                pixels[index * channels : index * channels + channels] = bytes([80]) * channels
        return InpaintingResult(
            ImageDocument(request.document.asset, request.document.mode, bytes(pixels)),
            self.adapter_id,
            1,
        )


def _document() -> ImageDocument:
    asset = ImageAsset(Path("manual.png"), 120, 80, 1, ImageFileFormat.PNG, False, False)
    return ImageDocument(asset, "RGB", bytes([240]) * 120 * 80 * 3)


def _processor() -> ProcessManualRegion:
    return ProcessManualRegion(
        RecognizeText(_FixtureOcr()),
        TranslateRegions(MockTranslationAdapter(), ProtectionEngine()),
        PillowImageCropper(),
        PillowMaskRasterizer(),
        _FillInpaint(),
        QtBasicTextLayoutAdapter("Arial"),
        mask_expansion=0,
    )


def test_auto_mode_uses_independent_selection_erase_and_text_boxes() -> None:
    QApplication.instance() or QApplication(["manual-region-integration"])
    document = _document()
    result = _processor().execute(
        document,
        document,
        ManualRegionSpec(
            ManualInputMode.AUTO,
            TextBox(30, 20, 45, 20),
            TextBox(65, 50, 20, 10),
            TextBox(88, 22, 42, 18, 12),
        ),
        "en",
        TranslationSelection(TranslationMode.ALL, "zh-Hans"),
    )
    assert result.source_text == "SUMMER SALE"
    assert result.translated_text == "夏季促销"
    assert result.layer.text == "夏季促销"
    assert result.layer.box.center_x == 88
    assert result.layer.box.center_y == 22
    assert result.layer.box.width == 42
    assert result.layer.box.height == 18
    assert result.layer.box.rotation_degrees == pytest.approx(12)
    assert result.erase_mask.pixels[50 * 120 + 65] == 255
    assert result.repaired_background.document.pixels != document.pixels


def test_direct_source_and_translated_modes_skip_the_expected_steps() -> None:
    QApplication.instance() or QApplication(["manual-direct-integration"])
    document = _document()
    common = (TextBox(30, 20, 30, 15),) * 3
    source = _processor().execute(
        document,
        document,
        ManualRegionSpec(ManualInputMode.SOURCE_TEXT, *common, source_text="SALE"),
        "en",
        TranslationSelection(TranslationMode.ALL, "zh-Hans"),
    )
    direct = _processor().execute(
        document,
        document,
        ManualRegionSpec(
            ManualInputMode.TRANSLATED_TEXT,
            *common,
            translated_text="人工译文",
        ),
        "en",
        TranslationSelection(TranslationMode.ALL, "zh-Hans"),
    )
    assert source.translated_text == "促销"
    assert direct.source_text == ""
    assert direct.translated_text == "人工译文"
    assert direct.layer.text == "人工译文"
