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
from src.domain.layout import CircularTextPath, PathPoint, TextBox
from src.domain.manual_region import ManualInputMode, ManualRegionSpec
from src.domain.ocr import OcrResult, TextRegion, order_quad
from src.domain.protection import ProtectionEngine
from src.domain.terminology import TerminologyCatalog, TerminologyEntry
from src.domain.translation import (
    TranslationAdapterItem,
    TranslationMode,
    TranslationSelection,
)
from src.infrastructure.mock_translator import MockTranslationAdapter
from src.infrastructure.pillow_image_cropper import PillowImageCropper
from src.infrastructure.pillow_mask_rasterizer import PillowMaskRasterizer
from src.infrastructure.text_renderer import QtBasicTextLayoutAdapter


class _FixtureOcr:
    language_codes = ("en",)

    def recognize(self, document: ImageDocument, language_code: str, fast: bool = False) -> OcrResult:
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


def _processor(
    translation_adapter=None,
    terminology_catalog: TerminologyCatalog | None = None,
) -> ProcessManualRegion:
    return ProcessManualRegion(
        RecognizeText(_FixtureOcr()),
        TranslateRegions(
            translation_adapter or MockTranslationAdapter(),
            ProtectionEngine(),
            terminology_catalog=terminology_catalog,
        ),
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


def test_short_cjk_manual_translation_uses_clear_tangent_text() -> None:
    QApplication.instance() or QApplication(["manual-circular-font-height-test"])
    document = _document()
    box = TextBox(60, 30, 70, 20, 32)
    path = CircularTextPath(
        PathPoint(60, 80),
        50,
        -125,
        -45,
    )
    result = _processor().execute(
        document,
        document,
        ManualRegionSpec(
            ManualInputMode.SOURCE_TEXT,
            box,
            box,
            box,
            source_text="SALE",
            circular_path=path,
        ),
        "en",
        TranslationSelection(TranslationMode.ALL, "zh-Hans"),
    )

    assert result.layer.path is None
    assert result.layer.box.center_x == box.center_x
    assert result.layer.box.center_y == box.center_y
    assert result.layer.box.width == box.width
    assert result.layer.box.height == pytest.approx(21.5)
    assert result.layer.box.rotation_degrees == box.rotation_degrees
    # 字号按「占框高的比例」断言，而非绝对 pt 区间。
    # 译文为中文而样式字体是 Arial（不含 CJK 字形），实际排版走 Qt 的 CJK 回退字体，
    # 各平台回退字体（macOS 苹方/黑体、Windows 雅黑/宋体）的 ascent/descent 比例不同，
    # 拟合字号随之不同（本机实测 15.49，占框高 0.72）。原 (16.0, 17.0] 仅 1pt 宽，
    # 是按单一平台标定的，跨平台必然失败。相对区间同样能守住本用例意图：
    # 切向文字要足够清晰，不能被压成小字。
    assert result.layer.box.height * 0.65 < result.layer.style.font_size
    assert result.layer.style.font_size <= result.layer.box.height * 0.85
    assert not result.layer.overflow


def test_manual_source_translation_uses_current_brand_terms() -> None:
    class RecordingAdapter:
        adapter_id = "recording"

        def __init__(self) -> None:
            self.calls = []

        def translate(self, texts, source_language, target_language):
            self.calls.append((texts, source_language, target_language))
            return tuple(
                TranslationAdapterItem(translated_text=f"{text} translated")
                for text in texts
            )

    QApplication.instance() or QApplication(["manual-brand-terms-test"])
    adapter = RecordingAdapter()
    document = _document()
    box = TextBox(40, 30, 50, 20)
    result = _processor(adapter).execute(
        document,
        document,
        ManualRegionSpec(
            ManualInputMode.SOURCE_TEXT,
            box,
            box,
            box,
            source_text="Alpha SALE",
        ),
        "en",
        TranslationSelection(TranslationMode.ALL, "zh-Hans"),
        ("Alpha",),
    )

    assert adapter.calls == [
        (("⟦0⟧ SALE",), None, "zh-Hans"),
    ]
    assert result.translated_text == "Alpha SALE translated"


def test_manual_source_translation_uses_exact_terminology_without_adapter() -> None:
    class FailingAdapter:
        adapter_id = "must-not-run"

        def translate(self, texts, source_language, target_language):
            raise AssertionError("Exact terminology must bypass the adapter")

    QApplication.instance() or QApplication(["manual-terminology-test"])
    document = _document()
    box = TextBox(40, 30, 50, 20)
    result = _processor(
        FailingAdapter(),
        TerminologyCatalog(
            (TerminologyEntry("en", "zh-Hans", "Clamp", "卡箍"),)
        ),
    ).execute(
        document,
        document,
        ManualRegionSpec(
            ManualInputMode.SOURCE_TEXT,
            box,
            box,
            box,
            source_text="Clamp",
        ),
        "en",
        TranslationSelection(TranslationMode.ALL, "zh-Hans"),
    )

    assert result.translated_text == "卡箍"
