import os
from io import BytesIO
from pathlib import Path
from typing import Any

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

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
from src.infrastructure.mock_translator import MockTranslationAdapter
from src.infrastructure.pillow_image_codec import PillowImageCodec
from src.infrastructure.pillow_mask_rasterizer import PillowMaskRasterizer
from src.infrastructure.text_renderer import QtBasicTextLayoutAdapter, QtTextRenderer
from src.ui.main_window import MainWindow


class ImmediateTaskRunner:
    def submit(self, operation: Any, on_success: Any, on_error: Any) -> None:
        try:
            on_success(operation())
        except Exception as error:
            on_error(error)


class FixtureOcrAdapter:
    language_codes = ("en",)

    def recognize(self, document: ImageDocument, language_code: str) -> OcrResult:
        region = TextRegion(
            "sale",
            order_quad(((20, 20), (130, 20), (130, 54), (20, 54))),
            "SALE",
            0.99,
            "en",
            "fixture",
        )
        return OcrResult((region,), "en", "fixture", 1)


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
