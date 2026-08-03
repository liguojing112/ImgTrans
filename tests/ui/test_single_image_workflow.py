import os
from io import BytesIO
from pathlib import Path
from typing import Any

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PIL import Image
from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtWidgets import QApplication

from src.application.bootstrap import StartupSnapshot
from src.application.image_io import ExportImage, ImportImage
from src.application.inpainting import BuildEraseMask, RepairTranslatedRegions
from src.application.ocr import RecognizeText
from src.application.translate_image import TranslateImage
from src.application.translation import TranslateRegions
from src.domain.image import ImageDocument, ImageLimits
from src.domain.inpainting import InpaintingRequest, InpaintingResult
from src.domain.job import JobStatus
from src.domain.ocr import OcrResult, TextRegion, order_quad
from src.domain.product import ProductInfo
from src.domain.protection import ProtectionEngine
from src.domain.translation import TranslationAdapterItem, TranslationStatus
from src.infrastructure.mock_translator import MockTranslationAdapter
from src.infrastructure.pillow_image_codec import PillowImageCodec
from src.infrastructure.pillow_mask_rasterizer import PillowMaskRasterizer
from src.infrastructure.text_renderer import QtBasicTextLayoutAdapter, QtTextRenderer
from src.infrastructure.user_preferences import JsonBrandTermsPreferences
from src.ui.main_window import MainWindow


class ImmediateTaskRunner:
    def submit(self, operation: Any, on_success: Any, on_error: Any) -> None:
        try:
            on_success(operation())
        except Exception as error:
            on_error(error)


class FixtureOcrAdapter:
    language_codes = ("en",)

    def recognize(self, document: ImageDocument, language_code: str, fast: bool = False) -> OcrResult:
        region = TextRegion(
            "sale",
            order_quad(((20, 20), (130, 20), (130, 54), (20, 54))),
            "SALE",
            0.99,
            "en",
            "fixture",
        )
        return OcrResult((region,), "en", "fixture", 1)


class BrandFixtureOcrAdapter:
    language_codes = ("en",)

    def recognize(self, document: ImageDocument, language_code: str, fast: bool = False) -> OcrResult:
        return OcrResult(
            (
                TextRegion(
                    "brand",
                    order_quad(((20, 20), (70, 20), (70, 54), (20, 54))),
                    "SALE",
                    0.99,
                    "en",
                    "fixture",
                ),
                TextRegion(
                    "ordinary",
                    order_quad(((80, 20), (130, 20), (130, 54), (80, 54))),
                    "DEAL",
                    0.99,
                    "en",
                    "fixture",
                ),
            ),
            "en",
            "fixture",
            1,
        )


class FixtureRepairAdapter:
    adapter_id = "fixture-repair"

    def inpaint(self, request: InpaintingRequest) -> InpaintingResult:
        image = Image.frombytes(
            request.document.mode,
            (request.document.asset.width, request.document.asset.height),
            request.document.pixels,
        )
        mask = Image.frombytes(
            "L",
            (request.erase_mask.width, request.erase_mask.height),
            request.erase_mask.pixels,
        )
        background = Image.new("RGB", image.size, "white")
        image.paste(background, mask=mask)
        repaired = ImageDocument(request.document.asset, "RGB", image.tobytes())
        return InpaintingResult(repaired, self.adapter_id, 1)


class RecordingWorkflow:
    def __init__(self, delegate: TranslateImage) -> None:
        self._delegate = delegate
        self.brand_terms: tuple[str, ...] = ()

    def execute(
        self,
        document,
        ocr_language,
        selection,
        brand_terms=(),
        on_stage=None,
    ):
        self.brand_terms = brand_terms
        return self._delegate.execute(
            document,
            ocr_language,
            selection,
            brand_terms,
            on_stage,
        )

    def cancel(self) -> None:
        self._delegate.cancel()

    def close(self) -> None:
        self._delegate.close()


class RecordingTranslationAdapter:
    adapter_id = "recording"

    def __init__(self) -> None:
        self.calls: list[tuple[tuple[str, ...], str | None, str]] = []

    def translate(self, texts, source_language, target_language):
        self.calls.append((texts, source_language, target_language))
        return tuple(
            TranslationAdapterItem("translated", "en")
            for _text in texts
        )


def _canvas_pixels(window: MainWindow) -> bytes:
    pixmap = window.image_canvas.pixmap()
    assert pixmap is not None
    buffer = QBuffer()
    assert buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    assert pixmap.save(buffer, "PNG")
    with Image.open(BytesIO(bytes(buffer.data()))) as image:
        return image.convert("RGB").tobytes()


def test_window_runs_and_exports_complete_single_image_workflow(tmp_path: Path) -> None:
    application = QApplication.instance() or QApplication(["workflow-ui-test"])
    source = tmp_path / "source.png"
    image = Image.new("RGB", (160, 80), "white")
    for x in range(20, 131):
        for y in range(20, 55):
            image.putpixel((x, y), (20, 30, 45))
    image.save(source)
    codec = PillowImageCodec()
    recognize = RecognizeText(FixtureOcrAdapter())
    translate = TranslateRegions(MockTranslationAdapter(), ProtectionEngine())
    repair = RepairTranslatedRegions(
        BuildEraseMask(PillowMaskRasterizer(), expansion=0),
        FixtureRepairAdapter(),
    )
    workflow = RecordingWorkflow(
        TranslateImage(
            recognize,
            translate,
            repair,
            QtBasicTextLayoutAdapter(),
            QtTextRenderer(),
        )
    )
    window = MainWindow(
        StartupSnapshot(ProductInfo("图片翻译", "0.1.0", "M1"), tmp_path / "data", tmp_path / "cache"),
        import_image=ImportImage(codec, ImageLimits()),
        export_image=ExportImage(codec),
        task_runner=ImmediateTaskRunner(),
        recognize_text=recognize,
        translate_regions=translate,
        repair_regions=repair,
        translate_image=workflow,
    )
    window.show()
    window.request_import(source)
    window.translation_panel.target_combo.setCurrentIndex(
        window.translation_panel.target_combo.findData("zh-Hans")
    )
    window.translation_panel.brand_terms.setText("Alpha，Beta, Alpha")
    original = window.current_document.pixels
    assert window.pipeline_panel.start_button.isEnabled()
    completed: list[Any] = []
    window.workflow_completed.connect(completed.append)
    window.request_workflow()
    application.processEvents()
    assert workflow.brand_terms == ("Alpha", "Beta")
    result = completed[0]
    assert result.job.status is JobStatus.COMPLETED
    assert result.document.pixels != original
    assert window.current_document is result.document
    assert _canvas_pixels(window) == result.document.pixels
    assert window.image_canvas.region_count == 0
    assert window.pipeline_panel.status_label.text().startswith("单图翻译完成")
    assert window.statusBar().currentMessage() == "单图翻译完成：已渲染 1 个译文区域"

    window.toggle_original_preview()
    assert _canvas_pixels(window) == original
    assert window.image_canvas.region_count == 0
    target = tmp_path / "translated.png"
    window.request_export(target)
    assert target.is_file()
    with Image.open(target) as reopened:
        assert reopened.size == (160, 80)
        assert reopened.convert(result.document.mode).tobytes() == result.document.pixels

    window.toggle_original_preview()
    assert _canvas_pixels(window) == result.document.pixels
    assert window.image_canvas.region_count == 0
    window.close()


def test_one_click_loads_persisted_brand_and_preserves_brand_pixels(
    tmp_path: Path,
) -> None:
    application = QApplication.instance() or QApplication(
        ["workflow-brand-protection-ui-test"]
    )
    source = tmp_path / "brand-source.png"
    image = Image.new("RGB", (160, 80), "white")
    for x in range(20, 131):
        for y in range(20, 55):
            image.putpixel((x, y), (20, 30, 45))
    image.save(source)
    preferences = JsonBrandTermsPreferences(tmp_path / "preferences.json")
    preferences.save(("SALE",))
    codec = PillowImageCodec()
    recognize = RecognizeText(BrandFixtureOcrAdapter())
    adapter = RecordingTranslationAdapter()
    translate = TranslateRegions(adapter, ProtectionEngine())
    repair = RepairTranslatedRegions(
        BuildEraseMask(PillowMaskRasterizer(), expansion=0),
        FixtureRepairAdapter(),
    )
    workflow = RecordingWorkflow(
        TranslateImage(
            recognize,
            translate,
            repair,
            QtBasicTextLayoutAdapter(),
            QtTextRenderer(),
        )
    )
    window = MainWindow(
        StartupSnapshot(
            ProductInfo("Image Translator", "0.1.0", "M1"),
            tmp_path / "data",
            tmp_path / "cache",
        ),
        import_image=ImportImage(codec, ImageLimits()),
        task_runner=ImmediateTaskRunner(),
        recognize_text=recognize,
        translate_regions=translate,
        repair_regions=repair,
        translate_image=workflow,
        brand_terms_preferences=preferences,
        confirm_discard=lambda _message: True,
    )
    window.request_import(source)
    window.translation_panel.target_combo.setCurrentIndex(
        window.translation_panel.target_combo.findData("zh-Hans")
    )
    original = window.current_document
    assert original is not None
    assert window.translation_panel.configured_brand_terms == ("SALE",)

    completed: list[Any] = []
    window.workflow_completed.connect(completed.append)
    window.request_workflow()
    application.processEvents()

    result = completed[0]
    assert workflow.brand_terms == ("SALE",)
    assert preferences.load() == ("SALE",)
    assert adapter.calls == [(("DEAL",), None, "zh-Hans")]
    assert result.translation.units[0].status is TranslationStatus.SKIPPED_PROTECTED
    assert result.translation.units[0].should_erase_source is False
    assert result.repair.erase_mask.pixels[30 * 160 + 40] == 0
    assert result.repair.erase_mask.pixels[30 * 160 + 100] == 255
    assert [layer.region_id for layer in result.layout.layers] == ["ordinary"]
    original_pixels = np.frombuffer(original.pixels, dtype=np.uint8).reshape(80, 160, 3)
    result_pixels = np.frombuffer(result.document.pixels, dtype=np.uint8).reshape(
        80, 160, 3
    )
    assert np.array_equal(
        result_pixels[20:55, 20:71],
        original_pixels[20:55, 20:71],
    )
    assert window.current_document is result.document
    assert _canvas_pixels(window) == result.document.pixels
    window.close()
