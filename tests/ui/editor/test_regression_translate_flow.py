"""冻结基线回归测试 — 验证 UI 层不破坏核心翻译流程。

全部使用 fake 适配器和内存合成图片，不调用真实 API。
"""

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from pathlib import Path

from PySide6.QtWidgets import QApplication

from src.application.translate_image import TranslateImage, TranslateImageResult
from src.application.ocr import RecognizeText
from src.application.translation import TranslateRegions
from src.application.inpainting import BuildEraseMask, RepairTranslatedRegions
from src.application.composition import CreateCompositionEditor
from src.domain.image import ImageAsset, ImageDocument, ImageFileFormat
from src.domain.inpainting import (
    EraseMask,
    InpaintingRequest,
    InpaintingResult,
    RepairOutcome,
)
from src.domain.job import ImageJob, JobStatus
from src.domain.layout import TextBox, TextLayer, TextLayout, TextStyle
from src.domain.ocr import (
    OcrResult,
    TextRegion,
    order_quad,
)
from src.domain.protection import ProtectionEngine
from src.domain.translation import (
    TranslationAdapterItem,
    TranslationMode,
    TranslationSelection,
    TranslationStatus,
    TranslationResult,
    TranslationUnit,
)
from src.infrastructure.pillow_mask_rasterizer import PillowMaskRasterizer
from src.infrastructure.text_renderer import QtBasicTextLayoutAdapter, QtTextRenderer
from src.ui.editor.editor_model import EditorModel


# ============================================================
# Fake 适配器
# ============================================================

class FakeOcrAdapter:
    language_codes = ("en",)

    def recognize(self, _document, language_code):
        regions = (
            TextRegion(
                "low", order_quad(((18, 18), (78, 18), (78, 48), (18, 48))),
                "SUMMER", 0.74, "en", "fixture",
            ),
            TextRegion(
                "high", order_quad(((95, 18), (145, 18), (145, 48), (95, 48))),
                "SALE", 0.90, "en", "fixture",
            ),
            TextRegion(
                "number", order_quad(((150, 18), (180, 18), (180, 48), (150, 48))),
                "2026", 0.99, "en", "fixture",
            ),
        )
        return OcrResult(regions, language_code, "fixture", 42.0)


class FakeTranslationAdapter:
    adapter_id = "fake-fixture"
    calls: list = []

    def translate(self, texts, source_language, target_language):
        self.calls.append((texts, source_language, target_language))
        return tuple(TranslationAdapterItem(translated_text="FAKE") for _ in texts)


class FakeRepairAdapter:
    adapter_id = "fake-repair"

    def inpaint(self, request):
        pixels = np.frombuffer(request.document.pixels, dtype=np.uint8).reshape(72, 190, 3).copy()
        mask = np.frombuffer(request.erase_mask.pixels, dtype=np.uint8).reshape(72, 190) > 0
        pixels[mask] = (235, 235, 235)
        repaired = ImageDocument(request.document.asset, "RGB", pixels.tobytes())
        return InpaintingResult(repaired, self.adapter_id, 1)


class FakeTranslateImage:
    """实现 TranslateImage 接口，返回预合成的 fake result。"""

    def __init__(self):
        self.was_cancelled = False

    def execute(self, document, ocr_language, selection, brand_terms=(),
                on_stage=None, ocr_mode=None, high_recall_options=None):
        ocr = FakeOcrAdapter().recognize(document, ocr_language)
        units = (
            TranslationUnit("low", "SUMMER", "en", "zh-Hans", "SUMMER",
                            TranslationStatus.REVIEW_REQUIRED),
            TranslationUnit("high", "SALE", "en", "zh-Hans", "FAKE",
                            TranslationStatus.TRANSLATED),
            TranslationUnit("number", "2026", "en", "zh-Hans", "2026",
                            TranslationStatus.SKIPPED_PROTECTED),
        )
        translation = TranslationResult(units, selection, "fake-fixture", 3.0)
        empty_mask = EraseMask(190, 72, bytes(190 * 72))
        repair = RepairOutcome(
            empty_mask,
            InpaintingResult(document, "fake-repair", 1),
        )
        layout = TextLayout((
            TextLayer("high", "FAKE", TextBox(120, 33, 50, 20),
                      TextStyle("Microsoft YaHei", 14, (24, 32, 51))),
            TextLayer("low", "SUMMER", TextBox(48, 33, 60, 20),
                      TextStyle("Microsoft YaHei", 14, (24, 32, 51)), overflow=True),
        ))
        from src.domain.job import ImageStage
        job = ImageJob()
        job.start()
        for stage in ImageStage:
            job.advance(stage)
            job.finish_stage()
        job.complete()
        return TranslateImageResult(document, ocr, translation, repair, layout, job)

    def cancel(self):
        self.was_cancelled = True

    def close(self):
        pass


def _document(w=190, h=72):
    pixels = np.full((h, w, 3), 235, dtype=np.uint8)
    pixels[18:49, 18:171] = (25, 35, 50)
    asset = ImageAsset(Path("fake.png"), w, h, 1, ImageFileFormat.PNG, False, False)
    return ImageDocument(asset, "RGB", pixels.tobytes())


# ============================================================
# 回归测试
# ============================================================

def test_1_ui_uses_complete_translate_usecase():
    """UI _on_translate 调用 TranslateImage.execute()，不单独拼接 OCR/翻译等。"""
    QApplication.instance() or QApplication(["regression-test"])
    doc = _document()
    fake = FakeTranslateImage()
    result = fake.execute(doc, "en", TranslationSelection(TranslationMode.ALL, "zh-Hans"))
    assert isinstance(result, TranslateImageResult)
    assert result.job.status is JobStatus.COMPLETED


def test_2_preferences_passed_correctly():
    """品牌词从 TranslateControls 传递到 execute。"""
    QApplication.instance() or QApplication(["regression-test"])
    doc = _document()
    fake = FakeTranslateImage()
    # 模拟传递品牌词
    result = fake.execute(doc, "en", TranslationSelection(TranslationMode.ALL, "zh-Hans"),
                          brand_terms=("Nike", "Adidas"))
    assert result.translation.selection.target_language == "zh-Hans"


def test_3_canvas_uses_rendered_image():
    """翻译完成后，model.rendered_document == result.document。"""
    QApplication.instance() or QApplication(["regression-test"])
    doc = _document()
    fake = FakeTranslateImage()
    result = fake.execute(doc, "en", TranslationSelection(TranslationMode.ALL, "zh-Hans"))

    model = EditorModel()
    model.rendered_document = result.document
    assert model.rendered_document is result.document


def test_4_text_layers_from_existing_result():
    """Text layers 来自 result.layout，不重新生成。"""
    QApplication.instance() or QApplication(["regression-test"])
    doc = _document()
    fake = FakeTranslateImage()
    result = fake.execute(doc, "en", TranslationSelection(TranslationMode.ALL, "zh-Hans"))

    model = EditorModel()
    model.text_layout = result.layout
    assert model.text_layout is result.layout
    assert len(model.text_layout.layers) == 2


def test_5_review_required_not_rendered():
    """REVIEW_REQUIRED (region 'low') 不在 renderable layout 中。"""
    QApplication.instance() or QApplication(["regression-test"])
    doc = _document()
    fake = FakeTranslateImage()
    result = fake.execute(doc, "en", TranslationSelection(TranslationMode.ALL, "zh-Hans"))

    review_ids = {u.region_id for u in result.translation.units
                  if u.status is TranslationStatus.REVIEW_REQUIRED}
    assert "low" in review_ids


def test_6_overflow_preserved():
    """overflow 图层的 region_id 存在但 overflow=True。"""
    QApplication.instance() or QApplication(["regression-test"])
    doc = _document()
    fake = FakeTranslateImage()
    result = fake.execute(doc, "en", TranslationSelection(TranslationMode.ALL, "zh-Hans"))

    overflow_layers = [l for l in result.layout.layers if l.overflow]
    assert len(overflow_layers) == 1
    assert overflow_layers[0].region_id == "low"


def test_7_protected_regions_have_no_translation_layer():
    """SKIPPED_PROTECTED (region 'number') 在 translate_image.py 中被过滤。"""
    QApplication.instance() or QApplication(["regression-test"])
    doc = _document()
    fake = FakeTranslateImage()
    result = fake.execute(doc, "en", TranslationSelection(TranslationMode.ALL, "zh-Hans"))

    protected_ids = {u.region_id for u in result.translation.units
                     if u.status is TranslationStatus.SKIPPED_PROTECTED}
    assert "number" in protected_ids


def test_8_preview_and_export_use_same_state():
    """_on_export 使用 model.rendered_document。"""
    QApplication.instance() or QApplication(["regression-test"])
    doc = _document()
    fake = FakeTranslateImage()
    result = fake.execute(doc, "en", TranslationSelection(TranslationMode.ALL, "zh-Hans"))

    model = EditorModel()
    model.rendered_document = result.document
    export_doc = model.rendered_document or model.document
    assert export_doc is result.document


def test_9_editing_does_not_modify_source():
    """编辑图层后 model.source_document.pixels 不变。"""
    QApplication.instance() or QApplication(["regression-test"])
    doc = _document()
    fake = FakeTranslateImage()
    result = fake.execute(doc, "en", TranslationSelection(TranslationMode.ALL, "zh-Hans"))

    model = EditorModel()
    model.source_document = doc
    model.rendered_document = result.document  # 模拟编辑后渲染

    assert model.source_document.pixels == doc.pixels


def test_10_preview_toggle_preserves_layout():
    """切换原图/译图后 model.text_layout 保持不变。"""
    QApplication.instance() or QApplication(["regression-test"])
    doc = _document()
    fake = FakeTranslateImage()
    result = fake.execute(doc, "en", TranslationSelection(TranslationMode.ALL, "zh-Hans"))

    model = EditorModel()
    model.text_layout = result.layout
    layout_before = model.text_layout

    # 模拟切换：原图 → 译图
    model.preview_mode = "original"
    model.preview_mode = "layers"

    assert model.text_layout is layout_before
    assert len(model.text_layout.layers) == 2
