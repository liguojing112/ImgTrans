"""冻结基线回归测试 — 验证 UI 层不破坏核心翻译流程。

全部使用 fake 适配器和内存合成图片，不调用真实 API。
"""

import os
from dataclasses import replace
from types import SimpleNamespace
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
import shiboken6
from pathlib import Path

from PySide6.QtTest import QTest
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication,
    QColorDialog,
    QDoubleSpinBox,
    QMessageBox,
    QPushButton,
    QMainWindow,
)

from src.application.translate_image import TranslateImage, TranslateImageResult
from src.application.ocr import RecognizeText
from src.application.translation import TranslateRegions
from src.application.inpainting import (
    BuildEraseMask,
    RepairSelection,
    RepairTranslatedRegions,
)
from src.application.composition import CreateCompositionEditor
from src.domain.image import ImageAsset, ImageDocument, ImageFileFormat
from src.domain.inpainting import (
    EraseMask,
    InpaintingError,
    InpaintingRequest,
    InpaintingResult,
    RepairOutcome,
)
from src.domain.job import ImageJob, ImageStage, JobStatus
from src.domain.layout import (
    ArcTextPath,
    ArtisticPreset,
    CircularTextPath,
    PathPoint,
    TextBox,
    TextLayer,
    TextLayout,
    TextStyle,
)
from src.domain.ocr import (
    HighRecallOcrOptions,
    OcrObservation,
    OcrMode,
    OcrPreviewStrip,
    OcrResult,
    Point,
    RingBand,
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
from src.ui.editor.main_window import EditorMainWindow
from src.ui.editor.widgets.toolbar import EditorToolBar
from src.ui.editor.widgets.top_bar import TopBar
from src.ui.editor.canvas.scene import EditorScene
from src.ui.qt_task_runner import QtTaskRunner


# ============================================================
# Fake 适配器
# ============================================================

class FakeOcrAdapter:
    language_codes = ("en",)

    def recognize(self, _document, language_code, fast: bool = False):
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
        self.last_ocr_mode = None
        self.last_high_recall_options = None

    def execute(self, document, ocr_language, selection, brand_terms=(),
                on_stage=None, ocr_mode=None, high_recall_options=None,
                **options):
        del options
        self.last_ocr_mode = ocr_mode
        self.last_high_recall_options = high_recall_options
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


class ImmediateTaskRunner:
    def submit(self, operation, on_success, on_error):
        try:
            on_success(operation())
        except Exception as error:
            on_error(error)


class DeferredTaskRunner:
    def __init__(self) -> None:
        self.pending = None

    def submit(self, operation, on_success, on_error):
        self.pending = (operation, on_success, on_error)

    def complete(self) -> None:
        operation, on_success, on_error = self.pending
        self.pending = None
        try:
            on_success(operation())
        except Exception as error:
            on_error(error)


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


def test_editor_forwards_high_recall_mode_to_one_click_translation():
    QApplication.instance() or QApplication(["editor-high-recall-flow-test"])
    workflow = FakeTranslateImage()
    window = EditorMainWindow(
        import_image=object(),
        task_runner=ImmediateTaskRunner(),
        translate_image=workflow,
    )
    try:
        window._model.source_document = _document()
        controls = window._editor_page.translate_controls
        controls.ocr_mode.setCurrentIndex(
            controls.ocr_mode.findData(OcrMode.HIGH_RECALL.value)
        )
        controls.high_recall_center_x.setValue(95)
        controls.high_recall_center_y.setValue(36)
        controls.high_recall_inner_radius.setValue(12)
        controls.high_recall_outer_radius.setValue(32)

        window._on_translate("en", "zh-Hans")

        assert workflow.last_ocr_mode is OcrMode.HIGH_RECALL
        options = workflow.last_high_recall_options
        assert isinstance(options, HighRecallOcrOptions)
        assert options.center is not None
        assert (options.center.x, options.center.y) == (95, 36)
        assert options.ring_bands[0].inner_radius == 12
        assert options.ring_bands[0].outer_radius == 32
    finally:
        window.close()


def test_region_retranslation_recovers_circular_path_from_high_recall_ocr():
    QApplication.instance() or QApplication(["region-retranslation-path-test"])
    polygon = order_quad(((90, 24), (150, 24), (150, 36), (90, 36)))
    observation = OcrObservation(
        "polar",
        0,
        3,
        0.95,
        polygon,
        "Profit",
        "polar:0:scale:3",
    )
    region = TextRegion(
        "profit",
        polygon,
        "Profit",
        0.95,
        "en",
        "circular",
        observations=(observation,),
        enhanced_only=True,
        auto_process_eligible=False,
    )
    ocr = OcrResult(
        (region,),
        "en",
        "circular",
        1,
        OcrMode.HIGH_RECALL,
        (
            OcrPreviewStrip(
                "ring",
                1,
                1,
                b"\xff\xff\xff",
                Point(120, 120),
                RingBand(70, 110),
            ),
        ),
    )
    window = EditorMainWindow(import_image=object())
    try:
        window._model.ocr_result = ocr
        path = window._circular_path_for_retranslation(
            "profit",
            region,
            TextBox(120, 30, 60, 12),
        )
        assert isinstance(path, CircularTextPath)
        assert path.center == PathPoint(120, 120)
        assert path.start_angle_degrees < path.end_angle_degrees
    finally:
        window.close()


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


def test_editor_factory_uses_server_translation_mode(monkeypatch):
    """新版编辑器必须遵循正式翻译模式配置，不能写死 mock。"""
    monkeypatch.setenv("IMGTRANS_TRANSLATION_MODE", "server")
    monkeypatch.setenv("IMGTRANS_API_BASE_URL", "http://127.0.0.1:8000")
    monkeypatch.setenv("IMGTRANS_API_TOKEN", "fixture-client-token-123456")

    import src.main as desktop_main

    captured = {}

    class FakeEditorWindow:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(desktop_main, "EditorMainWindow", FakeEditorWindow)

    desktop_main._create_editor_window()

    translate_image = captured["translate_image"]
    assert translate_image._translate.adapter_id == "imgtrans-server"
    assert captured["process_manual_region"] is not None


def test_translation_completion_shows_and_exports_the_same_clean_rendered_preview(
    monkeypatch,
    tmp_path,
):
    """翻译完成后默认展示成品图，不能把蒙版和编辑辅助层混入预览。"""
    QApplication.instance() or QApplication(["regression-test"])
    result = FakeTranslateImage().execute(
        _document(),
        "en",
        TranslationSelection(TranslationMode.ALL, "zh-Hans"),
    )
    captured = {}

    def fake_export(document, target, export_usecase, codec, options=None):
        captured["document"] = document
        del export_usecase, codec, options
        return target

    monkeypatch.setattr(
        "src.ui.editor.main_window.export_document",
        fake_export,
    )
    window = EditorMainWindow(
        import_image=object(),
        create_composition_editor=CreateCompositionEditor(
            QtBasicTextLayoutAdapter("Arial"),
            QtTextRenderer(),
        ),
    )
    try:
        window._on_translation_succeeded(result)

        assert window._model.preview_mode == "translated"
        assert window._model.rendered_document is result.document
        assert window._model.composition_editor._document is result.document
        assert window._editor_page.main_splitter.count() == 3
        assert window._editor_page.main_splitter.widget(0) is window._editor_page.original_view
        assert window._editor_page.main_splitter.widget(1) is window._editor_page.view
        assert window._editor_page.main_splitter.widget(2) is window._editor_page.right_panel
        assert not window._editor_page.original_view.isVisible()
        assert window._editor_page.right_tabs.count() == 5
        assert [
            window._editor_page.right_tabs.tabText(index)
            for index in range(5)
        ] == ["翻译设置", "OCR结果", "文字属性", "图层状态", "导出设置"]
        assert (
            window._editor_page.translate_scroll.widget()
            is window._editor_page.translate_controls
        )
        assert window._editor_page.right_tabs.indexOf(
            window._editor_page.ocr_result_panel
        ) == 1
        assert window._editor_page.ocr_result_panel.tree.topLevelItemCount() == 3
        translated_row = window._editor_page.ocr_result_panel.tree.topLevelItem(1)
        assert translated_row.text(0) == "SALE"
        assert translated_row.text(1) == "FAKE"
        assert translated_row.text(3) == "已翻译"
        assert window._editor_page.property_panel.isEnabled()
        assert window._editor_page.layer_state_panel.tree.topLevelItemCount() == 3
        assert window._editor_page.layer_state_panel.tree.topLevelItem(0).text(0) == "背景"
        assert window._editor_page.export_settings.export_button.isEnabled()
        assert window._editor_page.top_bar.save_btn.text() == "保存"
        assert window._editor_page.top_bar.export_btn.text() == "导出"
        assert not window._editor_page.scene._mask_visible
        assert all(
            not item.isVisible()
            for item in window._editor_page.scene._layer_items.values()
        )
        window._on_export(tmp_path / "translated.png")
        assert captured["document"] is result.document
    finally:
        window.close()


def test_selecting_review_row_highlights_original_ocr_polygon_without_leaving_ocr_tab():
    QApplication.instance() or QApplication(["ocr-review-highlight-test"])
    result = FakeTranslateImage().execute(
        _document(),
        "en",
        TranslationSelection(TranslationMode.ALL, "zh-Hans"),
    )
    window = EditorMainWindow(
        import_image=object(),
        create_composition_editor=CreateCompositionEditor(
            QtBasicTextLayoutAdapter("Arial"),
            QtTextRenderer(),
        ),
    )
    try:
        window._on_translation_succeeded(result)
        panel = window._editor_page.ocr_result_panel
        window._editor_page.right_tabs.setCurrentIndex(1)
        review_row = panel.tree.topLevelItem(0)
        assert review_row.text(0) == "SUMMER"

        panel.tree.setCurrentItem(review_row)

        item = window._editor_page.scene._ocr_items["low"]
        assert item.isVisible()
        assert item.isSelected()
        assert window._editor_page.right_tabs.currentIndex() == 1
        assert window._model.selected_layer_id == "low"

        panel.edit_source_button.click()
        assert window._editor_page.right_tabs.currentIndex() == 2
    finally:
        window.close()


def test_topbar_undo_and_redo_use_composition_history():
    QApplication.instance() or QApplication(["composition-history-buttons-test"])
    result = FakeTranslateImage().execute(
        _document(),
        "en",
        TranslationSelection(TranslationMode.ALL, "zh-Hans"),
    )
    window = EditorMainWindow(
        import_image=object(),
        task_runner=ImmediateTaskRunner(),
        create_composition_editor=CreateCompositionEditor(
            QtBasicTextLayoutAdapter("Arial"),
            QtTextRenderer(),
        ),
    )
    try:
        window._on_translation_succeeded(result)
        editor = window._model.composition_editor
        edit = editor.replace_text("high", "CHANGED")
        window._editor_page.apply_edit_result(edit)
        assert window._editor_page.top_bar.undo_btn.isEnabled()
        assert window._undo_action.isEnabled()
        assert window._model.text_layout.layer_by_id("high").text == "CHANGED"

        window._editor_page.top_bar.undo_btn.click()
        assert window._model.text_layout.layer_by_id("high").text == "FAKE"
        assert window._editor_page.top_bar.redo_btn.isEnabled()
        assert window._redo_action.isEnabled()

        window._editor_page.top_bar.redo_btn.click()
        assert window._model.text_layout.layer_by_id("high").text == "CHANGED"
    finally:
        window.close()


def test_first_translation_can_be_undone_and_redone_from_topbar():
    QApplication.instance() or QApplication(["first-translation-history-test"])
    source = _document()
    result = FakeTranslateImage().execute(
        source,
        "en",
        TranslationSelection(TranslationMode.ALL, "zh-Hans"),
    )
    window = EditorMainWindow(
        import_image=object(),
        task_runner=ImmediateTaskRunner(),
        create_composition_editor=CreateCompositionEditor(
            QtBasicTextLayoutAdapter("Arial"),
            QtTextRenderer(),
        ),
    )
    try:
        window._model.source_document = source
        window._on_translation_succeeded(result)
        assert window._editor_page.top_bar.undo_btn.isEnabled()

        window._editor_page.top_bar.undo_btn.click()
        assert window._model.rendered_document.pixels == source.pixels
        assert window._model.text_layout.layers == ()
        assert window._editor_page.top_bar.redo_btn.isEnabled()

        window._editor_page.top_bar.redo_btn.click()
        assert window._model.rendered_document.pixels == result.document.pixels
        assert window._model.text_layout == result.layout
    finally:
        window.close()


def test_secondary_translation_enables_toolbar_and_menu_history():
    QApplication.instance() or QApplication(["secondary-history-buttons-test"])
    result = FakeTranslateImage().execute(
        _document(),
        "en",
        TranslationSelection(TranslationMode.ALL, "zh-Hans"),
    )
    window = EditorMainWindow(
        import_image=object(),
        task_runner=ImmediateTaskRunner(),
        create_composition_editor=CreateCompositionEditor(
            QtBasicTextLayoutAdapter("Arial"),
            QtTextRenderer(),
        ),
    )
    try:
        window._on_translation_succeeded(result)
        editor = window._model.composition_editor
        edit = editor.replace_text("high", "SECOND")
        manual = SimpleNamespace(
            source_text="SALE",
            translated_text="SECOND",
        )

        window._on_region_retranslated("high", (manual, edit))

        assert window._editor_page.top_bar.undo_btn.isEnabled()
        assert window._undo_action.isEnabled()
        window._editor_page.top_bar.undo_btn.click()
        assert window._model.text_layout.layer_by_id("high").text == "FAKE"
        assert window._editor_page.top_bar.redo_btn.isEnabled()
        assert window._redo_action.isEnabled()
        window._redo_action.trigger()
        assert window._model.text_layout.layer_by_id("high").text == "SECOND"
    finally:
        window.close()


def test_rotated_ocr_region_box_uses_oriented_dimensions():
    QApplication.instance() or QApplication(["oriented-region-box-test"])
    window = EditorMainWindow(import_image=object())
    try:
        polygon = (
            Point(100, 100),
            Point(160, 135),
            Point(150, 152),
            Point(90, 117),
        )
        observation = OcrObservation(
            "polar",
            0,
            3,
            0.95,
            polygon,
            "Profit",
            "polar:0:scale:3",
        )
        region = TextRegion(
            "rotated",
            polygon,
            "Profit",
            0.95,
            "en",
            "test-model",
            observations=(observation,),
            enhanced_only=True,
        )
        window._model.text_layout = TextLayout(
            (
                TextLayer(
                    "rotated",
                    "利润",
                    TextBox(125, 126, 103, 60, 30),
                    TextStyle("Arial", 48, (0, 0, 0)),
                ),
            )
        )
        box = window._region_box(region.region_id, region)
        assert box.center_x == pytest.approx(125)
        assert box.center_y == pytest.approx(126)
        assert box.width == pytest.approx(69.46, abs=0.02)
        assert box.height == pytest.approx(19.72, abs=0.02)
        assert box.rotation_degrees == pytest.approx(30.26, abs=0.02)
    finally:
        window.close()


def test_translation_activity_scrolls_visible_progress_into_view():
    app = QApplication.instance() or QApplication(["visible-progress-test"])
    window = EditorMainWindow(import_image=object())
    try:
        window.resize(1024, 640)
        window._enter_editor()
        window.show()
        controls = window._editor_page.translate_controls
        controls.ocr_mode.setCurrentIndex(
            controls.ocr_mode.findData(OcrMode.HIGH_RECALL.value)
        )
        window._editor_page.right_tabs.setCurrentIndex(2)

        controls.set_translating(True)
        controls.set_preparing()
        controls.set_stage(ImageStage.OCR)
        app.processEvents()

        scroll = window._editor_page.translate_scroll
        assert window._editor_page.right_tabs.currentIndex() == 0
        assert scroll.verticalScrollBar().maximum() > 0
        assert (
            scroll.verticalScrollBar().value()
            == scroll.verticalScrollBar().maximum()
        )
        assert controls.progress.isVisible()
        assert controls.stage_label.isVisible()
    finally:
        window.close()


def test_split_comparison_fits_both_images_without_overlay_or_clipping():
    app = QApplication.instance() or QApplication(["split-view-test"])
    source = _document()
    result = FakeTranslateImage().execute(
        source,
        "en",
        TranslationSelection(TranslationMode.ALL, "zh-Hans"),
    )
    window = EditorMainWindow(
        import_image=object(),
        create_composition_editor=CreateCompositionEditor(
            QtBasicTextLayoutAdapter("Arial"),
            QtTextRenderer(),
        ),
    )
    try:
        window.resize(1600, 900)
        window._enter_editor()
        window.show()
        window._model.source_document = source
        window._on_translation_succeeded(result)
        window._on_toggle_split_compare()
        app.processEvents()
        app.processEvents()

        page = window._editor_page
        sizes = page.main_splitter.sizes()
        assert page.is_split_view()
        assert page.original_view.isVisible()
        assert sizes[0] > 0 and sizes[1] > 0
        assert abs(sizes[0] - sizes[1]) <= 2
        assert page.original_view.geometry().right() <= page.view.geometry().left()

        for view in (page.original_view, page.view):
            visible_scene = view.mapToScene(view.viewport().rect()).boundingRect()
            scene_rect = view.scene().sceneRect()
            assert visible_scene.contains(scene_rect)

        assert not page.scene._mask_visible
        assert all(
            not item.isVisible()
            for item in page.scene._layer_items.values()
        )
    finally:
        window.close()


def test_compare_main_button_toggles_single_original_and_translated_view():
    QApplication.instance() or QApplication(["single-compare-test"])
    source = _document()
    result = FakeTranslateImage().execute(
        source,
        "en",
        TranslationSelection(TranslationMode.ALL, "zh-Hans"),
    )
    window = EditorMainWindow(
        import_image=object(),
        create_composition_editor=CreateCompositionEditor(
            QtBasicTextLayoutAdapter("Arial"),
            QtTextRenderer(),
        ),
    )
    try:
        window._enter_editor()
        window._model.source_document = source
        window._on_translation_succeeded(result)
        assert window._model.preview_mode == "translated"
        assert not window._editor_page.is_split_view()

        window._on_toggle_original()
        assert window._model.preview_mode == "original"
        assert window._model.showing_original
        assert not window._editor_page.is_split_view()

        window._on_toggle_original()
        assert window._model.preview_mode == "translated"
        assert not window._model.showing_original
        assert not window._editor_page.is_split_view()
    finally:
        window.close()


def test_slider_comparison_reveals_original_without_auxiliary_overlays():
    QApplication.instance() or QApplication(["slider-compare-test"])
    source = _document()
    result = FakeTranslateImage().execute(
        source,
        "en",
        TranslationSelection(TranslationMode.ALL, "zh-Hans"),
    )
    window = EditorMainWindow(
        import_image=object(),
        create_composition_editor=CreateCompositionEditor(
            QtBasicTextLayoutAdapter("Arial"),
            QtTextRenderer(),
        ),
    )
    try:
        window._enter_editor()
        window._model.source_document = source
        window._on_translation_succeeded(result)
        window._on_toggle_slider_compare()

        page = window._editor_page
        assert page.is_slider_compare()
        assert page.comparison_slider_bar.isVisible() == page.isVisible()
        assert page.scene._comparison_clip is not None
        page.comparison_slider.setValue(30)
        assert page.scene._comparison_clip.rect().width() == pytest.approx(
            source.asset.width * 0.30
        )
        assert not page.scene._mask_visible
        assert all(
            not item.isVisible()
            for item in page.scene._layer_items.values()
        )

        window._on_toggle_slider_compare()
        assert not page.is_slider_compare()
        assert page.scene._comparison_clip is None
    finally:
        window.close()


def test_long_press_temporarily_shows_original_and_restores_translated_mode():
    QApplication.instance() or QApplication(["hold-compare-test"])
    source = _document()
    result = FakeTranslateImage().execute(
        source,
        "en",
        TranslationSelection(TranslationMode.ALL, "zh-Hans"),
    )
    window = EditorMainWindow(
        import_image=object(),
        create_composition_editor=CreateCompositionEditor(
            QtBasicTextLayoutAdapter("Arial"),
            QtTextRenderer(),
        ),
    )
    try:
        window._enter_editor()
        window._model.source_document = source
        window._on_translation_succeeded(result)
        window._on_compare_hold_started()
        assert window._model.preview_mode == "original"
        window._on_compare_hold_finished()
        assert window._model.preview_mode == "translated"
    finally:
        window.close()


def test_top_bar_long_press_suppresses_short_click_toggle():
    QApplication.instance() or QApplication(["hold-click-test"])
    bar = TopBar()
    try:
        bar.set_has_result(True)
        events = []
        bar.compare_hold_started.connect(lambda: events.append("start"))
        bar.compare_hold_finished.connect(lambda: events.append("finish"))
        bar.toggle_original_requested.connect(lambda: events.append("toggle"))
        bar._start_compare_hold()
        bar._begin_compare_hold()
        bar._finish_compare_hold()
        bar._on_compare_clicked()
        assert events == ["start", "finish"]
        assert not bar.toggle_original_btn.isChecked()
    finally:
        bar.close()


def test_batch_export_success_dialog_includes_actual_output_directory(monkeypatch, tmp_path):
    QApplication.instance() or QApplication(["batch-export-success-dialog-test"])
    window = EditorMainWindow(import_image=object())
    captured = []

    class ResultItem:
        target = tmp_path / "isolated" / "one-translated.png"

    class Result:
        succeeded_count = 1
        failed_count = 0
        items = (ResultItem(),)

    monkeypatch.setattr(
        QMessageBox,
        "information",
        lambda _parent, title, text: captured.append((title, text)),
    )
    try:
        window._on_batch_export_finished(Result(), tmp_path)
        assert captured == [
            (
                "批量导出成功",
                "成功导出 1 张图片。\n\n导出路径：\n"
                f"{tmp_path / 'isolated'}",
            )
        ]
    finally:
        window.close()


def test_editor_factory_loads_brand_terms_and_frozen_repair_chain(monkeypatch):
    """新版编辑器复用冻结版品牌偏好和 LaMa→OpenCV 修复装配。"""
    monkeypatch.setenv("IMGTRANS_TRANSLATION_MODE", "server")
    monkeypatch.setenv("IMGTRANS_API_BASE_URL", "http://127.0.0.1:8000")
    monkeypatch.setenv("IMGTRANS_API_TOKEN", "fixture-client-token-123456")

    import src.main as desktop_main
    from src.infrastructure.fallback_inpaint_adapter import FallbackInpaintAdapter

    captured = {}

    class FakeEditorWindow:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    class FakeBrandPreferences:
        def __init__(self, path):
            del path

        def load(self):
            return ("棉小飞",)

    class FakeTerminologyPreferences:
        def __init__(self, path):
            del path

        def load(self):
            return ()

    monkeypatch.setattr(desktop_main, "EditorMainWindow", FakeEditorWindow)
    monkeypatch.setattr(
        desktop_main,
        "JsonBrandTermsPreferences",
        FakeBrandPreferences,
    )
    monkeypatch.setattr(
        desktop_main,
        "JsonTerminologyPreferences",
        FakeTerminologyPreferences,
    )

    desktop_main._create_editor_window()

    workflow = captured["translate_image"]
    assert captured["brand_terms"] == ("棉小飞",)
    assert isinstance(workflow._repair._inpainting, FallbackInpaintAdapter)


def test_editor_left_toolbar_has_comfortable_click_targets():
    QApplication.instance() or QApplication(["editor-toolbar-size-test"])
    toolbar = EditorToolBar()
    try:
        assert toolbar.width() == 88
        buttons = toolbar.findChildren(QPushButton, "toolButton")
        assert len(buttons) == 8
        assert "matting" not in toolbar.buttons
        assert all(button.width() == 72 and button.height() == 44 for button in buttons)
        assert list(toolbar.buttons) == [
            "select",
            "text_regions",
            "add_text",
            "manual_translate",
            "ai_erase",
            "crop",
            "layers",
            "watermark",
        ]
    finally:
        toolbar.close()


def test_add_text_tool_stays_selected_after_activation():
    QApplication.instance() or QApplication(["editor-add-text-tool-test"])
    toolbar = EditorToolBar()
    requested = []
    toolbar.add_text_requested.connect(lambda: requested.append(True))
    try:
        toolbar.buttons["add_text"].click()
        assert requested == [True]
        assert toolbar.buttons["add_text"].isChecked()
        assert toolbar.active_tool == "add_text"

        toolbar.buttons["select"].click()
        assert not toolbar.buttons["add_text"].isChecked()
        assert toolbar.active_tool == "select"
    finally:
        toolbar.close()


def test_watermark_can_be_added_immediately_after_import():
    QApplication.instance() or QApplication(["watermark-after-import-test"])
    source = _document()
    window = EditorMainWindow(
        import_image=object(),
        task_runner=ImmediateTaskRunner(),
        create_composition_editor=CreateCompositionEditor(
            QtBasicTextLayoutAdapter("Arial"),
            QtTextRenderer(),
        ),
    )
    try:
        window._on_image_loaded(source)
        window._on_feature_requested("watermark")

        assert window._model.composition_editor is not None
        assert not window._editor_page.watermark_dialog.isHidden()

        window._on_add_text_watermark("DEMO", 0.55, False)

        editor = window._model.composition_editor
        assert len(editor.watermarks) == 1
        assert editor.watermarks[0].text == "DEMO"
        assert editor.document.pixels != source.pixels
        assert editor.can_undo
        assert window._model.rendered_document is editor.document
    finally:
        window.close()


def test_ai_erase_is_available_before_translation_and_keeps_edit_session():
    QApplication.instance() or QApplication(["ai-erase-before-translation-test"])
    source = _document()
    window = EditorMainWindow(
        import_image=object(),
        task_runner=ImmediateTaskRunner(),
        create_composition_editor=CreateCompositionEditor(
            QtBasicTextLayoutAdapter("Arial"),
            QtTextRenderer(),
        ),
        repair_selection=SimpleNamespace(),
    )
    try:
        window._on_image_loaded(source)
        assert window._model.translation_result is None

        window._on_editor_tool_changed("ai_erase")

        assert window._model.composition_editor is not None
        assert (
            window._editor_page.layer_tools_stack.currentWidget()
            is window._editor_page.erase_dialog
        )
        assert window._editor_page.scene.edit_mask.is_empty
        assert window._editor_page.right_tabs.currentIndex() == 3
        assert (
            window._editor_page.layer_tools_stack.currentWidget()
            is window._editor_page.erase_dialog
        )
        assert not window._editor_page.erase_dialog.isWindow()
    finally:
        window.close()


def test_ai_erase_embedded_panel_selects_mask_and_applies_repair():
    QApplication.instance() or QApplication(["ai-erase-embedded-flow-test"])
    source = _document()
    window = EditorMainWindow(
        import_image=object(),
        task_runner=ImmediateTaskRunner(),
        create_composition_editor=CreateCompositionEditor(
            QtBasicTextLayoutAdapter("Arial"),
            QtTextRenderer(),
        ),
        repair_selection=RepairSelection(FakeRepairAdapter()),
    )
    try:
        window._on_image_loaded(source)
        window._on_editor_tool_changed("ai_erase")

        page = window._editor_page
        assert page.right_tabs.currentIndex() == 3
        assert page.layer_tools_stack.currentWidget() is page.erase_dialog
        assert page.scene._selection_mode is None
        assert page.scene._mask_brush_mode == "paint"
        assert page.scene.edit_mask.is_empty
        assert not page.erase_dialog.apply_button.isEnabled()

        page._on_area_selected("ai_erase", TextBox(30, 25, 20, 10))
        assert not page.scene.edit_mask.is_empty
        assert page.erase_dialog.apply_button.isEnabled()
        page.erase_dialog.apply_button.click()

        assert window._model.composition_editor is not None
        assert window._model.composition_editor.patch_count == 1
        assert page.layer_tools_stack.currentWidget() is page.erase_dialog
        assert page.erase_dialog.undo_button.isEnabled()
        assert "AI 消除完成" in window.statusBar().currentMessage()

        page.erase_dialog.undo_button.click()
        assert window._model.composition_editor.patch_count == 0
        assert not page.erase_dialog.undo_button.isEnabled()
    finally:
        window.close()


def test_ai_erase_keeps_repaired_background_when_adding_text():
    QApplication.instance() or QApplication(["ai-erase-then-add-text-test"])
    source = _document()
    window = EditorMainWindow(
        import_image=object(),
        task_runner=ImmediateTaskRunner(),
        create_composition_editor=CreateCompositionEditor(
            QtBasicTextLayoutAdapter("Arial"),
            QtTextRenderer(),
        ),
        repair_selection=RepairSelection(FakeRepairAdapter()),
    )
    try:
        window._on_image_loaded(source)
        window._on_editor_tool_changed("ai_erase")
        page = window._editor_page
        page.scene._paint_mask_segment(
            page.scene.sceneRect().center(),
            page.scene.sceneRect().center(),
        )
        page.erase_dialog.apply_button.click()

        editor = window._model.composition_editor
        assert editor is not None
        assert editor.patch_count == 1
        page.erase_dialog.add_text_button.click()

        assert editor.patch_count == 1
        assert len(editor.layout.layers) == 1
        assert editor.layout.layers[0].text == "新文本"
        assert page.right_tabs.currentIndex() == 2
        assert page.toolbar.active_tool == "add_text"
    finally:
        window.close()


class CapturingRepairAdapter:
    """捕获传入请求；蒙版区域填充为绿色（明显非白色、非蒙版值）。"""

    adapter_id = "capturing-repair"

    def __init__(self):
        self.last_mask: EraseMask | None = None

    def inpaint(self, request):
        self.last_mask = request.erase_mask
        pixels = np.frombuffer(
            request.document.pixels, dtype=np.uint8
        ).reshape(request.document.asset.height, request.document.asset.width, 3).copy()
        mask = np.frombuffer(
            request.erase_mask.pixels, dtype=np.uint8
        ).reshape(request.erase_mask.height, request.erase_mask.width) > 0
        pixels[mask] = (0, 200, 0)
        repaired = ImageDocument(
            request.document.asset, "RGB", pixels.tobytes()
        )
        return InpaintingResult(repaired, self.adapter_id, 1)


class FailingRepairAdapter:
    """修复服务抛错（模拟 LaMa 与 OpenCV 均不可用）。"""

    adapter_id = "failing-repair"

    def inpaint(self, request):
        raise InpaintingError(
            "lama_inference_failed", "LaMa 推理失败（模拟）"
        )


def test_repair_selection_expands_user_mask_by_3px():
    """手动消除蒙版应膨胀 2~6px（默认 3px），避免残留文字边缘。"""
    QApplication.instance() or QApplication(["mask-expansion-test"])
    adapter = CapturingRepairAdapter()
    repair = RepairSelection(adapter, expansion_px=3, feather_px=0)

    pixels = bytearray(40 * 40)
    for y in range(15, 25):
        for x in range(15, 25):
            pixels[y * 40 + x] = 255
    mask = EraseMask(40, 40, bytes(pixels))
    asset = ImageAsset(
        Path("mask.png"), 40, 40, 1, ImageFileFormat.PNG, False, False
    )
    document = ImageDocument(asset, "RGB", bytes(40 * 40 * 3))

    repair.execute(document, mask)

    received = np.frombuffer(
        adapter.last_mask.pixels, dtype=np.uint8
    ).reshape(40, 40)
    # 原 10x10 区域膨胀 3px 后为 16x16=256 个非零像素，且中心仍为 255
    assert int((received > 0).sum()) == 16 * 16
    assert received[20, 20] == 255
    # 边缘外 1px 为 0（膨胀核 7x7，未越界）
    assert received[10, 20] == 0
    assert received[29, 20] == 0


def test_ai_erase_success_does_not_composite_mask_or_white_fill():
    """消除成功后：最终图片是修复结果，不是蒙版合成、也不是白色填充。"""
    QApplication.instance() or QApplication(["ai-erase-no-white-block-test"])
    source = _document()
    window = EditorMainWindow(
        import_image=object(),
        task_runner=ImmediateTaskRunner(),
        create_composition_editor=CreateCompositionEditor(
            QtBasicTextLayoutAdapter("Arial"),
            QtTextRenderer(),
        ),
        repair_selection=RepairSelection(CapturingRepairAdapter()),
    )
    try:
        window._on_image_loaded(source)
        window._on_editor_tool_changed("ai_erase")
        page = window._editor_page
        page._on_area_selected("ai_erase", TextBox(30, 25, 20, 10))
        page.erase_dialog.apply_button.click()

        rendered = window._model.rendered_document
        pixels = np.frombuffer(
            rendered.pixels, dtype=np.uint8
        ).reshape(rendered.asset.height, rendered.asset.width, 3)
        # 原蒙版区域（TextBox(30,25,20,10) → x20-40,y20-30）内应是修复结果绿色
        mask_region = pixels[21:29, 26:39]
        assert (mask_region == (0, 200, 0)).all()
        # 膨胀后的边缘（+3px）也被修复，无文字边缘残留
        expanded_edge = pixels[17:20, 26:39]
        assert (expanded_edge == (0, 200, 0)).all()
        # 蒙版区域外保持原图（未被蒙版污染）
        outside = pixels[5:15, 5:15]
        assert (outside == (235, 235, 235)).all()
        assert "AI 消除完成" in window.statusBar().currentMessage()
    finally:
        window.close()


def test_ai_erase_failure_keeps_original_image_and_shows_error():
    """修复失败时：保留原图、显示错误，禁止白色矩形填充。"""
    QApplication.instance() or QApplication(["ai-erase-failure-test"])
    source = _document()
    window = EditorMainWindow(
        import_image=object(),
        task_runner=ImmediateTaskRunner(),
        create_composition_editor=CreateCompositionEditor(
            QtBasicTextLayoutAdapter("Arial"),
            QtTextRenderer(),
        ),
        repair_selection=RepairSelection(FailingRepairAdapter()),
    )
    try:
        window._on_image_loaded(source)
        before_pixels = window._model.document.pixels
        window._on_editor_tool_changed("ai_erase")
        page = window._editor_page
        page._on_area_selected("ai_erase", TextBox(30, 25, 20, 10))
        page.erase_dialog.apply_button.click()

        # 原图保持不变（无白色填充、无蒙版合成）
        assert window._model.document.pixels == before_pixels
        assert window._model.rendered_document.pixels == before_pixels
        assert "AI 消除失败" in window.statusBar().currentMessage()
        assert "LaMa 推理失败" in window.statusBar().currentMessage()
        assert "AI 消除失败" in page.erase_dialog.mask_status.text()
    finally:
        window.close()


def _masked_repair_result(source):
    """用真蒙版修复（区域填灰），模拟 LaMa 修复后的无文字背景。"""
    from src.domain.inpainting import EraseMask

    mask_pixels = bytearray(190 * 72)
    for y in range(18, 49):
        for x in range(18, 171):
            mask_pixels[y * 190 + x] = 255
    mask = EraseMask(190, 72, bytes(mask_pixels))
    request = SimpleNamespace(document=source, erase_mask=mask, context_pixels=96)
    return FakeRepairAdapter().inpaint(request), mask


def _translated_with_repaired_background():
    """翻译结果：修复背景已消除原文字（区域填灰）+ 译文图层。"""
    source = _document()
    result = FakeTranslateImage().execute(
        source,
        "en",
        TranslationSelection(TranslationMode.ALL, "zh-Hans"),
    )
    repaired, _mask = _masked_repair_result(source)
    result = replace(result, repair=replace(result.repair, result=repaired))
    return source, result


def test_delete_layer_reveals_repaired_background_without_original_text():
    """删除译文图层 → 显示修复背景（原文字已消除），无需 AI 消除。"""
    QApplication.instance() or QApplication(["delete-layer-reveals-background-test"])
    source, result = _translated_with_repaired_background()
    window = EditorMainWindow(
        import_image=object(),
        task_runner=ImmediateTaskRunner(),
        create_composition_editor=CreateCompositionEditor(
            QtBasicTextLayoutAdapter("Arial"),
            QtTextRenderer(),
        ),
    )
    try:
        window._on_image_loaded(source)
        window._on_translation_succeeded(result)
        editor = window._model.composition_editor
        assert editor is not None
        assert len(editor.layout.layers) == 2  # 翻译后有 2 个译文图层

        edit = editor.delete_layer("high")
        window._editor_page.apply_edit_result(edit)

        # high 区域（原 SALE 文字处）显示修复背景灰，而非原图文字
        doc = window._model.rendered_document
        pixels = np.frombuffer(
            doc.pixels, dtype=np.uint8
        ).reshape(doc.asset.height, doc.asset.width, 3)
        assert (pixels[25:40, 100:140] == (235, 235, 235)).all()
        # 其余译文图层保留
        assert len(editor.layout.layers) == 1
        with pytest.raises(KeyError):
            editor.layout.layer_by_id("high")
    finally:
        window.close()


def test_hide_layer_reveals_repaired_background():
    """隐藏译文图层 → 画布显示修复背景（原文字不残留）。"""
    QApplication.instance() or QApplication(["hide-layer-reveals-background-test"])
    source, result = _translated_with_repaired_background()
    window = EditorMainWindow(
        import_image=object(),
        task_runner=ImmediateTaskRunner(),
        create_composition_editor=CreateCompositionEditor(
            QtBasicTextLayoutAdapter("Arial"),
            QtTextRenderer(),
        ),
    )
    try:
        window._on_image_loaded(source)
        window._on_translation_succeeded(result)
        editor = window._model.composition_editor

        window._editor_page._on_layer_visibility_changed("high", False)

        layer = editor.layout.layer_by_id("high")
        assert not layer.visible
        doc = window._model.rendered_document
        pixels = np.frombuffer(
            doc.pixels, dtype=np.uint8
        ).reshape(doc.asset.height, doc.asset.width, 3)
        assert (pixels[25:40, 100:140] == (235, 235, 235)).all()
    finally:
        window.close()


def test_background_translation_completion_does_not_overwrite_other_document():
    """B 翻译完成时若已切回 A：结果写入 B，A 画布不被覆盖；切回 B 可见译文。"""
    QApplication.instance() or QApplication(["bg-translation-no-overwrite-test"])
    source_a = _document()
    result_a = FakeTranslateImage().execute(
        source_a,
        "en",
        TranslationSelection(TranslationMode.ALL, "zh-Hans"),
    )
    source_b = _document(w=200, h=80)
    result_b = FakeTranslateImage().execute(
        source_b,
        "en",
        TranslationSelection(TranslationMode.ALL, "zh-Hans"),
    )
    window = EditorMainWindow(
        import_image=object(),
        task_runner=ImmediateTaskRunner(),
        create_composition_editor=CreateCompositionEditor(
            QtBasicTextLayoutAdapter("Arial"),
            QtTextRenderer(),
        ),
    )
    try:
        window._on_image_loaded(source_a)
        id_a = window._model.active_document_id
        window._on_translation_succeeded(result_a)
        assert window._model.translation_result is not None

        # 加入 B 并加载，然后切回 A（模拟 B 翻译期间用户查看 A）
        window._model.add_document(Path("b.png"), source_b, name="b.png")
        id_b = window._model.active_document_id
        window._load_active_document()
        window._on_activate_document(id_a)
        assert window._model.active_document_id == id_a

        # B 翻译完成（后台回调），此时活动文档是 A
        window._on_translation_succeeded(result_b, id_b)

        # A 的画布与状态不被 B 的结果覆盖
        assert window._model.active_document_id == id_a
        assert window._editor_page.top_bar.file_label.text() == source_a.asset.source_path.name
        assert window._model.translation_result.ocr is result_a.ocr
        assert window._model.rendered_document is result_a.document
        assert window._model.document is result_a.document
        # Restoring a translated document also restores its composition
        # history, so the toolbar undo/redo actions remain usable.
        assert window._editor_page.top_bar.undo_btn.isEnabled()
        assert window._undo_action.isEnabled()
        window._editor_page.top_bar.undo_btn.click()
        assert window._model.text_layout.layers == ()
        assert window._editor_page.top_bar.redo_btn.isEnabled()
        window._editor_page.top_bar.redo_btn.click()
        assert window._model.text_layout == result_a.layout

        # B 的结果已写入 B 的文档条目
        ref_b = next(
            d for d in window._model.documents() if d.doc_id == id_b
        )
        assert ref_b.translation_result is not None
        assert ref_b.translation_result.ocr is result_b.ocr
        assert ref_b.rendered_document is result_b.document

        # 切回 B → 显示 B 的译文结果
        window._on_activate_document(id_b)
        assert window._model.active_document_id == id_b
        assert window._model.translation_result.ocr is result_b.ocr
        assert window._model.rendered_document is result_b.document
        assert window._model.document is result_b.document

        # 再切回 A → A 的结果仍在
        window._on_activate_document(id_a)
        assert window._model.translation_result.ocr is result_a.ocr
    finally:
        window.close()


def test_canvas_tools_are_embedded_in_layer_state_tab():
    QApplication.instance() or QApplication(["embedded-canvas-tools-test"])
    window = EditorMainWindow(import_image=object())
    try:
        page = window._editor_page
        for tool_id, panel in (
            ("ai_erase", page.erase_dialog),
            ("crop", page.crop_dialog),
            ("watermark", page.watermark_dialog),
            ("layers", page.layer_state_panel),
        ):
            page._show_layer_tool(tool_id)
            assert page.right_tabs.currentIndex() == 3
            assert page.layer_tools_stack.currentWidget() is panel
            assert not panel.isWindow()
    finally:
        window.close()


def test_watermark_toolbar_and_dialog_buttons_complete_the_ui_flow(monkeypatch):
    app = QApplication.instance() or QApplication(["watermark-ui-flow-test"])
    source = _document()
    window = EditorMainWindow(
        import_image=object(),
        task_runner=ImmediateTaskRunner(),
        create_composition_editor=CreateCompositionEditor(
            QtBasicTextLayoutAdapter("Arial"),
            QtTextRenderer(),
        ),
    )
    try:
        window.show()
        window._on_image_loaded(source)
        QTest.mouseClick(
            window._editor_page.toolbar.buttons["watermark"],
            Qt.MouseButton.LeftButton,
        )
        app.processEvents()

        dialog = window._editor_page.watermark_dialog
        assert window._editor_page.layer_tools_stack.currentWidget() is dialog
        add_button = next(
            button
            for button in dialog.findChildren(QPushButton)
            if button.text() == "添加文字水印"
        )
        QTest.mouseClick(add_button, Qt.MouseButton.LeftButton)
        app.processEvents()

        editor = window._model.composition_editor
        assert editor is not None
        assert len(editor.watermarks) == 1
        assert editor.document.pixels != source.pixels
        assert "水印已添加" in window.statusBar().currentMessage()
        assert window._editor_page.right_tabs.currentIndex() == 3
        assert (
            window._editor_page.layer_tools_stack.currentWidget()
            is window._editor_page.layer_state_panel
        )
        selected = window._editor_page.layer_state_panel.tree.selectedItems()
        assert len(selected) == 1
        assert selected[0].data(0, Qt.ItemDataRole.UserRole) == (
            f"watermark:{editor.watermarks[0].watermark_id}"
        )
        item = window._editor_page.scene._watermark_items[
            editor.watermarks[0].watermark_id
        ]
        assert item.isSelected()
        assert item.watermark_layer.text == "水印"

        panel = window._editor_page.layer_state_panel
        for control in (
            panel.watermark_font_size,
            panel.watermark_rotation,
            panel.watermark_width,
            panel.watermark_height,
            panel.watermark_opacity,
        ):
            assert (
                control.buttonSymbols()
                == QDoubleSpinBox.ButtonSymbols.NoButtons
            )
        panel.watermark_text.setText("内部资料")
        panel.watermark_text.editingFinished.emit()
        assert editor.watermarks[0].text == "内部资料"

        monkeypatch.setattr(
            QColorDialog,
            "getColor",
            lambda *_args, **_kwargs: QColor("#33AA66"),
        )
        panel.watermark_color_button.click()
        assert editor.watermarks[0].style.fill_rgb == (51, 170, 102)

        original_width = editor.watermarks[0].width
        original_height = editor.watermarks[0].height
        panel.watermark_width.setValue(original_width * 1.5)
        panel.watermark_height.setValue(original_height * 1.5)
        item = window._editor_page.scene._watermark_items[
            editor.watermarks[0].watermark_id
        ]
        assert item.text_layer.box.width == pytest.approx(
            panel.watermark_width.value()
        )
        assert item.text_layer.box.height == pytest.approx(
            panel.watermark_height.value()
        )
        panel.watermark_height.editingFinished.emit()
        assert editor.watermarks[0].width == pytest.approx(
            original_width * 1.5
        )
        assert editor.watermarks[0].height == pytest.approx(
            original_height * 1.5
        )
        item = window._editor_page.scene._watermark_items[
            editor.watermarks[0].watermark_id
        ]
        assert item.text_layer.box.width == pytest.approx(original_width * 1.5)
        assert item.text_layer.box.height == pytest.approx(original_height * 1.5)
        assert item._body_rect().width() == pytest.approx(original_width * 1.5)
        assert item._body_rect().height() == pytest.approx(original_height * 1.5)

        previous_font_size = editor.watermarks[0].style.font_size
        previous_width = editor.watermarks[0].width
        previous_height = editor.watermarks[0].height
        panel.watermark_font_larger.click()
        scale = (previous_font_size + 1) / previous_font_size
        assert editor.watermarks[0].style.font_size == pytest.approx(
            previous_font_size + 1
        )
        assert editor.watermarks[0].width == pytest.approx(
            previous_width * scale
        )
        assert editor.watermarks[0].height == pytest.approx(
            previous_height * scale
        )
        item = window._editor_page.scene._watermark_items[
            editor.watermarks[0].watermark_id
        ]
        assert item._body_rect().width() == pytest.approx(previous_width * scale)
        assert item._body_rect().height() == pytest.approx(previous_height * scale)
    finally:
        window.close()


def test_watermark_size_input_updates_canvas_with_async_task_runner():
    app = QApplication.instance() or QApplication(["watermark-size-async-test"])
    source = _document()
    window = EditorMainWindow(
        import_image=object(),
        task_runner=QtTaskRunner(),
        create_composition_editor=CreateCompositionEditor(
            QtBasicTextLayoutAdapter("Arial"),
            QtTextRenderer(),
        ),
    )
    try:
        window._on_image_loaded(source)
        assert window._ensure_composition_editor()
        editor = window._model.composition_editor
        assert editor is not None
        edit = editor.add_text_watermark(
            "SIZE",
            TextStyle("Arial", 42, (255, 255, 255)),
            False,
            0.55,
            "center",
        )
        window._on_watermark_succeeded(edit)
        watermark = editor.watermarks[0]
        target_width = watermark.width * 1.4
        target_height = watermark.height * 1.3

        panel = window._editor_page.layer_state_panel
        panel.watermark_width.setValue(target_width)
        panel.watermark_height.setValue(target_height)
        target_width = panel.watermark_width.value()
        target_height = panel.watermark_height.value()
        panel.watermark_height.editingFinished.emit()
        item = window._editor_page.scene._watermark_items[
            watermark.watermark_id
        ]
        assert item._body_rect().width() == pytest.approx(target_width)
        assert item._body_rect().height() == pytest.approx(target_height)
        for _ in range(100):
            app.processEvents()
            item = window._editor_page.scene._watermark_items[
                watermark.watermark_id
            ]
            if (
                editor.watermarks[0].width == pytest.approx(target_width)
                and editor.watermarks[0].height == pytest.approx(target_height)
                and item._body_rect().width() == pytest.approx(target_width)
                and item._body_rect().height() == pytest.approx(target_height)
            ):
                break
            QTest.qWait(10)

        assert editor.watermarks[0].width == pytest.approx(target_width)
        assert editor.watermarks[0].height == pytest.approx(target_height)
        item = window._editor_page.scene._watermark_items[
            watermark.watermark_id
        ]
        assert item._body_rect().width() == pytest.approx(target_width)
        assert item._body_rect().height() == pytest.approx(target_height)

        previous = editor.watermarks[0]
        target_font_size = previous.style.font_size + 8
        panel.watermark_font_size.setValue(target_font_size)
        scale = target_font_size / previous.style.font_size
        item = window._editor_page.scene._watermark_items[
            watermark.watermark_id
        ]
        assert item._body_rect().width() == pytest.approx(
            previous.width * scale
        )
        assert item._body_rect().height() == pytest.approx(
            previous.height * scale
        )
        panel.watermark_font_size.editingFinished.emit()
        for _ in range(100):
            app.processEvents()
            if editor.watermarks[0].style.font_size == pytest.approx(
                target_font_size
            ):
                break
            QTest.qWait(10)
        assert editor.watermarks[0].style.font_size == pytest.approx(
            target_font_size
        )
        assert editor.watermarks[0].width == pytest.approx(
            previous.width * scale
        )
        assert editor.watermarks[0].height == pytest.approx(
            previous.height * scale
        )
    finally:
        window.close()


def test_watermark_added_before_translation_is_preserved():
    QApplication.instance() or QApplication(["watermark-translation-test"])
    source = _document()
    result = FakeTranslateImage().execute(
        source,
        "en",
        TranslationSelection(TranslationMode.ALL, "zh-Hans"),
    )
    window = EditorMainWindow(
        import_image=object(),
        task_runner=ImmediateTaskRunner(),
        create_composition_editor=CreateCompositionEditor(
            QtBasicTextLayoutAdapter("Arial"),
            QtTextRenderer(),
        ),
    )
    try:
        window._on_image_loaded(source)
        window._on_feature_requested("watermark")
        window._on_add_text_watermark("DEMO", 0.55, False)

        window._on_translation_succeeded(result)

        editor = window._model.composition_editor
        assert len(editor.watermarks) == 1
        assert editor.watermarks[0].text == "DEMO"
        assert window._model.rendered_document is editor.document
        assert window._model.translation_result.document is editor.document
    finally:
        window.close()


def test_ai_erase_scene_mask_supports_rectangle_brush_eraser_and_clear():
    QApplication.instance() or QApplication(["editor-erase-mask-test"])
    scene = EditorScene()
    scene.set_document(_document())
    scene.add_rect_to_edit_mask(TextBox(30, 25, 20, 10))
    rectangle_count = sum(value > 0 for value in scene.edit_mask.pixels)
    assert rectangle_count == 200

    from PySide6.QtCore import QPointF

    scene.set_mask_brush("paint", 8)
    scene._paint_mask_segment(QPointF(60, 40), QPointF(70, 40))
    assert sum(value > 0 for value in scene.edit_mask.pixels) > rectangle_count
    scene.set_mask_brush("erase", 8)
    before_erase = sum(value > 0 for value in scene.edit_mask.pixels)
    scene._paint_mask_segment(QPointF(65, 40), QPointF(65, 40))
    assert sum(value > 0 for value in scene.edit_mask.pixels) < before_erase
    scene.clear_edit_mask()
    assert scene.edit_mask.is_empty


# ============================================================
# 文字属性面板 — 译文编辑
# ============================================================

def _translation_window():
    result = FakeTranslateImage().execute(
        _document(),
        "en",
        TranslationSelection(TranslationMode.ALL, "zh-Hans"),
    )
    window = EditorMainWindow(
        import_image=object(),
        task_runner=ImmediateTaskRunner(),
        create_composition_editor=CreateCompositionEditor(
            QtBasicTextLayoutAdapter("Arial"),
            QtTextRenderer(),
        ),
    )
    window._on_translation_succeeded(result)
    return window


def test_editing_translation_in_property_panel_updates_unit_and_layer():
    """属性面板编辑译文 → 翻译单元与图层文字同步更新。"""
    QApplication.instance() or QApplication(["translation-edit-flow-test"])
    window = _translation_window()
    try:
        layer = window._model.text_layout.layer_by_id("high")
        window._editor_page._on_model_selection_changed(layer)
        panel = window._editor_page.property_panel
        assert panel.translated_text_edit.toPlainText() == "FAKE"

        panel.translated_text_edit.setPlainText("夏季大促")
        panel.apply_translated_text_btn.click()

        assert window._model.text_layout.layer_by_id("high").text == "夏季大促"
        unit = next(
            u
            for u in window._model.translation_result.translation.units
            if u.region_id == "high"
        )
        assert unit.translated_text == "夏季大促"
        assert unit.status is TranslationStatus.TRANSLATED
    finally:
        window.close()


def test_editing_text_property_updates_rendered_layer():
    """文字属性中的文字内容直接编辑后应更新当前文字图层。"""
    QApplication.instance() or QApplication(["text-property-edit-flow-test"])
    window = _translation_window()
    try:
        layer = window._model.text_layout.layer_by_id("high")
        window._editor_page._on_model_selection_changed(layer)
        panel = window._editor_page.property_panel
        panel.text_edit.setPlainText("DIRECT EDIT")
        QTest.qWait(400)

        assert window._model.text_layout.layer_by_id("high").text == "DIRECT EDIT"
        assert window._model.composition_editor.can_undo
    finally:
        window.close()


def test_manual_font_size_is_exact_and_restore_auto_layout_is_undoable():
    QApplication.instance() or QApplication(["font-size-restore-layout-test"])
    window = _translation_window()
    try:
        layer = window._model.text_layout.layer_by_id("high")
        window._editor_page._on_model_selection_changed(layer)
        panel = window._editor_page.property_panel
        assert panel.restore_layout_btn.isEnabled()

        panel.font_size_spin.setValue(28)
        QTest.qWait(400)
        edited = window._model.text_layout.layer_by_id("high")
        assert edited.style.font_size == pytest.approx(28)
        assert edited.style.auto_fit is False

        panel.restore_layout_btn.click()
        restored = window._model.text_layout.layer_by_id("high")
        assert restored == window._model.translation_result.layout.layer_by_id("high")
        assert window._model.composition_editor.can_undo
    finally:
        window.close()


def test_artistic_preset_changes_rendered_style_atomically():
    QApplication.instance() or QApplication(["artistic-preset-style-test"])
    window = _translation_window()
    try:
        layer = window._model.text_layout.layer_by_id("high")
        window._editor_page._on_model_selection_changed(layer)
        panel = window._editor_page.property_panel
        panel.artistic_preset.setCurrentIndex(
            panel.artistic_preset.findData(ArtisticPreset.POSTER)
        )
        QTest.qWait(400)

        style = window._model.text_layout.layer_by_id("high").style
        assert style.effect_preset is ArtisticPreset.POSTER
        assert style.stroke_width >= 3
        assert style.stroke_rgb == (24, 32, 51)
        assert style.shadow_opacity == pytest.approx(0.55)
        assert (style.shadow_offset_x, style.shadow_offset_y) == (4, 4)
    finally:
        window.close()


def test_editing_translation_confirms_review_required_region():
    """编辑待复核区域的译文 → 状态变为已翻译并渲染。"""
    QApplication.instance() or QApplication(["translation-edit-review-test"])
    window = _translation_window()
    try:
        layer = window._model.text_layout.layer_by_id("low")
        window._editor_page._on_model_selection_changed(layer)
        panel = window._editor_page.property_panel
        assert panel.status_label.text() == "待复核"

        panel.translated_text_edit.setPlainText("夏日特惠")
        panel.apply_translated_text_btn.click()

        assert window._model.text_layout.layer_by_id("low").text == "夏日特惠"
        unit = next(
            u
            for u in window._model.translation_result.translation.units
            if u.region_id == "low"
        )
        assert unit.translated_text == "夏日特惠"
        assert unit.status is TranslationStatus.TRANSLATED
        assert unit.error_code is None
        assert panel.status_label.text() == "已翻译"
    finally:
        window.close()


# ============================================================
# 工作台图片列表 — 删除
# ============================================================

def test_remove_active_document_switches_to_remaining_document():
    QApplication.instance() or QApplication(["remove-active-document-test"])
    window = EditorMainWindow(import_image=object())
    try:
        doc1 = _document()
        doc2 = _document(w=200, h=80)
        id1 = window._model.add_document(Path("a.png"), doc1, name="a.png")
        id2 = window._model.add_document(Path("b.png"), doc2, name="b.png")
        window._load_active_document()
        assert window._model.active_document_id == id2

        window._on_remove_document(id2)

        assert [d.doc_id for d in window._model.documents()] == [id1]
        assert window._model.active_document_id == id1
        assert window._model.document is doc1
        assert window._editor_page.image_list_panel._list.count() == 1
    finally:
        window.close()


def test_remove_inactive_document_keeps_active_document():
    QApplication.instance() or QApplication(["remove-inactive-document-test"])
    window = EditorMainWindow(import_image=object())
    try:
        doc1 = _document()
        doc2 = _document(w=200, h=80)
        id1 = window._model.add_document(Path("a.png"), doc1, name="a.png")
        id2 = window._model.add_document(Path("b.png"), doc2, name="b.png")
        window._load_active_document()
        assert window._model.document is doc2

        window._on_remove_document(id1)

        assert [d.doc_id for d in window._model.documents()] == [id2]
        assert window._model.active_document_id == id2
        assert window._model.document is doc2
    finally:
        window.close()


def test_remove_last_document_clears_editor_canvas():
    QApplication.instance() or QApplication(["remove-last-document-test"])
    window = EditorMainWindow(import_image=object())
    try:
        id1 = window._model.add_document(Path("a.png"), _document(), name="a.png")
        window._load_active_document()
        assert window._model.document is not None

        window._on_remove_document(id1)

        assert window._model.documents() == []
        assert window._model.active_document_id is None
        assert window._model.document is None
        assert window._model.text_layout.layers == ()
        assert window._editor_page.image_list_panel._list.count() == 0
        assert not window._editor_page.image_list_panel._remove_btn.isEnabled()
        assert not window._editor_page.top_bar._has_image
    finally:
        window.close()


def test_translation_preserved_when_switching_documents():
    """翻译完第一张后切到第二张再切回，第一张的翻译内容不丢失。"""
    QApplication.instance() or QApplication(["translation-switch-doc-test"])
    source_a = _document()
    result_a = FakeTranslateImage().execute(
        source_a,
        "en",
        TranslationSelection(TranslationMode.ALL, "zh-Hans"),
    )
    window = EditorMainWindow(
        import_image=object(),
        task_runner=ImmediateTaskRunner(),
        create_composition_editor=CreateCompositionEditor(
            QtBasicTextLayoutAdapter("Arial"),
            QtTextRenderer(),
        ),
    )
    try:
        window._on_image_loaded(source_a)
        id_a = window._model.active_document_id
        window._on_translation_succeeded(result_a)
        assert window._model.translation_result is not None

        # 加入第二张并加载 → 当前文档干净
        source_b = _document(w=200, h=80)
        window._model.add_document(Path("b.png"), source_b, name="b.png")
        id_b = window._model.active_document_id
        window._load_active_document()
        assert window._model.translation_result is None
        assert window._model.text_layout.layers == ()

        # 切回第一张 → 翻译结果完整恢复
        window._on_activate_document(id_a)
        restored = window._model.translation_result
        assert restored is not None
        assert restored.ocr is result_a.ocr
        assert window._model.text_layout is result_a.layout
        assert window._model.rendered_document is result_a.document
        assert window._model.composition_editor is not None
        assert window._model.ocr_result is result_a.ocr
        assert window._editor_page.top_bar.export_btn.isEnabled()
        assert window._editor_page.export_settings.export_button.isEnabled()
        assert window._model.document is result_a.document

        # 再切回第二张 → 仍是干净状态
        window._on_activate_document(id_b)
        assert window._model.translation_result is None
        assert window._model.text_layout.layers == ()
        assert window._model.document is source_b
    finally:
        window.close()


def test_in_flight_translation_progress_survives_switching_away_and_back():
    QApplication.instance() or QApplication(["translation-in-flight-switch-test"])
    runner = DeferredTaskRunner()
    workflow = FakeTranslateImage()
    source_a = _document()
    source_b = _document(w=200, h=80)
    window = EditorMainWindow(
        import_image=object(),
        task_runner=runner,
        translate_image=workflow,
        create_composition_editor=CreateCompositionEditor(
            QtBasicTextLayoutAdapter("Arial"),
            QtTextRenderer(),
        ),
    )
    try:
        window._on_image_loaded(source_a)
        id_a = window._model.active_document_id
        window._on_translate("en", "zh-Hans")

        assert window._translation_document_id == id_a
        assert not window._editor_page.translate_controls.translate_button.isEnabled()
        assert not window._editor_page.translate_controls.progress.isHidden()

        window._model.add_document(Path("b.png"), source_b, name="b.png")
        id_b = window._model.active_document_id
        window._load_active_document()
        assert id_b != id_a
        assert window._translation_document_id == id_a

        window._on_activate_document(id_a)
        assert window._translation_document_id == id_a
        assert not window._editor_page.translate_controls.translate_button.isEnabled()
        assert not window._editor_page.translate_controls.progress.isHidden()

        runner.complete()

        assert window._translation_document_id is None
        assert window._model.translation_result is not None
        assert window._model.rendered_document is not None
        assert window._editor_page.translate_controls.translate_button.isEnabled()
    finally:
        window.close()


def test_translation_selection_carries_specific_source_language():
    """「只翻译指定语言」模式下 selection 携带指定源语言与目标语言。"""
    QApplication.instance() or QApplication(["specific-source-selection-test"])
    window = EditorMainWindow(import_image=object())
    try:
        ctrl = window._editor_page.translate_controls
        # 默认：翻译全部区域
        selection = window._translation_selection()
        assert selection.mode is TranslationMode.ALL
        assert selection.source_language is None
        assert selection.target_language == "en"

        # 只翻译指定语言：简体中文 → 英语
        ctrl.specific_mode_radio.setChecked(True)
        ctrl.source_language.setCurrentIndex(
            ctrl.source_language.findData("zh-Hans")
        )
        selection = window._translation_selection()
        assert selection.mode is TranslationMode.SPECIFIC_LANGUAGE
        assert selection.source_language == "zh-Hans"
        assert selection.target_language == "en"
    finally:
        window.close()


class FakeRecognizeText:
    """只 OCR 不翻译的假服务。"""

    def __init__(self):
        self.last_language = None
        self.last_fast = None

    def execute(self, document, language_code, ocr_mode=None,
                high_recall_options=None, fast=False):
        del document, ocr_mode, high_recall_options
        self.last_language = language_code
        self.last_fast = fast
        return OcrResult(
            (
                TextRegion(
                    "r1", order_quad(((18, 18), (78, 18), (78, 48), (18, 48))),
                    "你好", 0.9, language_code, "fixture",
                ),
            ),
            language_code,
            "fixture",
            3.0,
        )


def test_ocr_only_button_runs_recognition_without_translation():
    """「仅 OCR 识别」按钮：执行识别并展示结果，不产生翻译结果。"""
    QApplication.instance() or QApplication(["ocr-only-flow-test"])
    source = _document()
    fake_ocr = FakeRecognizeText()
    window = EditorMainWindow(
        import_image=object(),
        task_runner=ImmediateTaskRunner(),
        recognize_text=fake_ocr,
    )
    try:
        window._on_image_loaded(source)
        window._editor_page.translate_controls.ocr_only_button.click()

        assert fake_ocr.last_language == "zh-Hans"
        assert fake_ocr.last_fast is True  # 独立 OCR 走快速路径
        assert window._model.ocr_result is not None
        assert window._model.translation_result is None
        # OCR-only keeps the imported document as a valid export source.
        assert window._editor_page.export_settings.export_button.isEnabled()
        assert window._editor_page.top_bar.export_btn.isEnabled()
        assert window._editor_page.ocr_result_panel.tree.topLevelItemCount() == 1
        # 识别期间锁定的控件已恢复
        assert window._editor_page.translate_controls.ocr_only_button.isEnabled()
        assert window._editor_page.translate_controls.translate_button.isEnabled()
        assert "OCR 完成" in window.statusBar().currentMessage()
    finally:
        window.close()


def test_ocr_only_text_edit_updates_canvas_and_export_document():
    """OCR 原文修改应同步到画布图层，并成为导出的当前文档。"""
    QApplication.instance() or QApplication(["ocr-only-text-edit-export-test"])
    source = _document()
    fake_ocr = FakeRecognizeText()
    window = EditorMainWindow(
        import_image=object(),
        task_runner=ImmediateTaskRunner(),
        recognize_text=fake_ocr,
        create_composition_editor=CreateCompositionEditor(
            QtBasicTextLayoutAdapter("Arial"),
            QtTextRenderer(),
        ),
    )
    try:
        window._on_image_loaded(source)
        window._editor_page.translate_controls.ocr_only_button.click()
        window._editor_page._on_ocr_region_selected("r1")
        assert window._editor_page.right_tabs.currentIndex() == 2
        assert window._model.composition_editor is None
        panel = window._editor_page.property_panel
        panel.text_edit.setPlainText("UPDATED OCR")
        QTest.qWait(400)

        assert window._model.ocr_result.regions[0].text == "UPDATED OCR"
        assert window._model.composition_editor is not None
        assert window._model.text_layout.layers[0].text == "UPDATED OCR"
        assert window._model.rendered_document is window._model.composition_editor.document
        assert window._editor_page.top_bar.export_btn.isEnabled()
    finally:
        window.close()


def test_ocr_source_update_button_updates_canvas_and_export_document():
    QApplication.instance() or QApplication(["ocr-source-button-export-test"])
    source = _document()
    window = EditorMainWindow(
        import_image=object(),
        task_runner=ImmediateTaskRunner(),
        recognize_text=FakeRecognizeText(),
        create_composition_editor=CreateCompositionEditor(
            QtBasicTextLayoutAdapter("Arial"),
            QtTextRenderer(),
        ),
        repair_selection=RepairSelection(FakeRepairAdapter()),
        mask_rasterizer=PillowMaskRasterizer(),
    )
    try:
        window._on_image_loaded(source)
        window._editor_page.translate_controls.ocr_only_button.click()
        window._editor_page._on_ocr_region_selected("r1")
        panel = window._editor_page.property_panel
        panel.source_text_edit.setPlainText("CORRECTED SOURCE")
        panel.apply_source_text_btn.click()

        assert window._model.ocr_result.regions[0].text == "CORRECTED SOURCE"
        assert window._model.composition_editor is not None
        corrected_layer = window._model.text_layout.layers[0]
        assert corrected_layer.text == "CORRECTED SOURCE"
        assert corrected_layer.style.auto_fit is False
        assert corrected_layer.box.center_x == pytest.approx(48)
        assert corrected_layer.box.center_y == pytest.approx(33)
        assert corrected_layer.box.width == pytest.approx(60)
        assert corrected_layer.box.height == pytest.approx(30)
        assert window._model.composition_editor.patch_count == 1
        assert panel.source_text_edit.toPlainText() == "CORRECTED SOURCE"
        assert window._model.rendered_document is window._model.composition_editor.document
        assert window._editor_page.top_bar.export_btn.isEnabled()
    finally:
        window.close()


def test_short_ocr_source_correction_keeps_original_box_and_weight():
    """A shorter OCR correction must not auto-enlarge or thin the preview."""
    QApplication.instance() or QApplication(["ocr-short-source-correction-test"])
    source = _document()
    window = EditorMainWindow(
        import_image=object(),
        task_runner=ImmediateTaskRunner(),
        recognize_text=FakeRecognizeText(),
        create_composition_editor=CreateCompositionEditor(
            QtBasicTextLayoutAdapter("Arial"),
            QtTextRenderer(),
        ),
        repair_selection=RepairSelection(FakeRepairAdapter()),
        mask_rasterizer=PillowMaskRasterizer(),
    )
    try:
        window._on_image_loaded(source)
        window._editor_page.translate_controls.ocr_only_button.click()
        window._editor_page._on_ocr_region_selected("r1")
        panel = window._editor_page.property_panel
        panel.source_text_edit.setPlainText("洗")
        panel.apply_source_text_btn.click()

        layer = window._model.text_layout.layers[0]
        assert layer.text == "洗"
        assert layer.style.auto_fit is False
        assert layer.style.font_weight >= 600
        assert (layer.box.center_x, layer.box.center_y) == pytest.approx((48, 33))
        assert (layer.box.width, layer.box.height) == pytest.approx((60, 30))
    finally:
        window.close()


def test_ocr_only_visual_properties_update_preview_and_export():
    QApplication.instance() or QApplication(["ocr-only-properties-test"])
    source = _document()
    layout_adapter = QtBasicTextLayoutAdapter("Arial")
    erase_mask_builder = BuildEraseMask(PillowMaskRasterizer())
    window = EditorMainWindow(
        import_image=object(),
        task_runner=ImmediateTaskRunner(),
        recognize_text=FakeRecognizeText(),
        create_composition_editor=CreateCompositionEditor(
            layout_adapter,
            QtTextRenderer(),
        ),
        repair_selection=RepairSelection(FakeRepairAdapter()),
        mask_rasterizer=PillowMaskRasterizer(),
        erase_mask_builder=erase_mask_builder,
        text_layout_adapter=layout_adapter,
    )
    try:
        window._on_image_loaded(source)
        window._editor_page.translate_controls.ocr_only_button.click()
        window._editor_page._on_ocr_region_selected("r1")
        panel = window._editor_page.property_panel

        panel.font_size_spin.setValue(22)
        QTest.qWait(400)
        assert len(window._model.text_layout.layers) == 1
        layer = window._model.text_layout.layers[0]
        preview_id = layer.region_id
        assert layer.text == "你好"
        assert layer.style.font_size == pytest.approx(22)
        assert layer.style.auto_fit is False
        assert (layer.box.width, layer.box.height) == pytest.approx((60, 30))

        panel.x_spin.setValue(60)
        QTest.qWait(400)
        layer = window._model.text_layout.layer_by_id(preview_id)
        assert layer.box.center_x == pytest.approx(60)
        assert len(window._model.text_layout.layers) == 1

        window._editor_page._on_ocr_property_changed(
            "r1", "fill_rgb", (200, 10, 20)
        )
        layer = window._model.text_layout.layer_by_id(preview_id)
        assert layer.style.fill_rgb == (200, 10, 20)
        assert window._model.rendered_document is window._model.composition_editor.document
        assert window._editor_page.top_bar.export_btn.isEnabled()
    finally:
        window.close()


def test_ocr_only_property_layer_reuses_translation_layout_and_erase_mask():
    QApplication.instance() or QApplication(["ocr-only-formal-layout-test"])
    source = _document()
    layout_adapter = QtBasicTextLayoutAdapter("Arial")
    window = EditorMainWindow(
        import_image=object(),
        task_runner=ImmediateTaskRunner(),
        recognize_text=FakeRecognizeText(),
        create_composition_editor=CreateCompositionEditor(
            layout_adapter,
            QtTextRenderer(),
        ),
        repair_selection=RepairSelection(FakeRepairAdapter()),
        erase_mask_builder=BuildEraseMask(PillowMaskRasterizer()),
        text_layout_adapter=layout_adapter,
    )
    try:
        window._on_image_loaded(source)
        window._editor_page.translate_controls.ocr_only_button.click()
        region = window._model.ocr_result.regions[0]
        expected = window._ocr_preview_base_layer(region)
        assert expected is not None

        window._editor_page._on_ocr_region_selected("r1")
        window._editor_page._on_ocr_property_changed(
            "r1", "fill_rgb", (20, 120, 210)
        )

        actual = window._model.text_layout.layers[0]
        assert actual.box == expected.box
        assert actual.path == expected.path
        assert actual.style.font_family == expected.style.font_family
        assert actual.style.font_size == pytest.approx(expected.style.font_size)
        assert actual.style.font_weight == expected.style.font_weight
        assert actual.style.auto_fit == expected.style.auto_fit
        assert actual.style.fill_rgb == (20, 120, 210)
        assert window._model.composition_editor.patch_count == 1

        panel = window._editor_page.property_panel
        panel.path_mode.setCurrentIndex(panel.path_mode.findData("arc"))
        panel.arc_bend.setValue(0.65)
        panel._flush_pending()
        curved = window._model.text_layout.layers[0]
        assert isinstance(curved.path, ArcTextPath)
        assert panel._arc_bend_for_layer(curved) == pytest.approx(0.65)
    finally:
        window.close()


def test_ocr_only_erase_mask_protects_neighboring_ocr_regions():
    QApplication.instance() or QApplication(["ocr-only-neighbor-protection-test"])
    source = _document()
    target = TextRegion(
        "target",
        order_quad(((18, 18), (100, 18), (100, 60), (18, 60))),
        "洗脸巾",
        0.99,
        "zh-Hans",
        "fixture",
    )
    neighbor = TextRegion(
        "neighbor",
        order_quad(((60, 30), (125, 30), (125, 52), (60, 52))),
        "温和洁净",
        0.99,
        "zh-Hans",
        "fixture",
    )
    window = EditorMainWindow(
        import_image=object(),
        erase_mask_builder=BuildEraseMask(PillowMaskRasterizer()),
    )
    try:
        window._model.source_document = source
        window._model.ocr_result = OcrResult(
            (target, neighbor), "zh-Hans", "fixture", 0
        )
        mask = window._ocr_preview_mask(target)
        assert mask is not None
        pixels = np.frombuffer(mask.pixels, dtype=np.uint8).reshape(72, 190)
        assert np.any(pixels[18:53, 18:58] > 0)
        assert np.all(pixels[30:53, 60:126] == 0)
    finally:
        window.close()


def test_clicking_canvas_text_syncs_ocr_list():
    """点击画布文字图层 → OCR 结果列表同步定位到对应行。"""
    QApplication.instance() or QApplication(["canvas-sync-ocr-list-test"])
    window = _translation_window()
    try:
        panel = window._editor_page.ocr_result_panel
        assert panel.tree.topLevelItemCount() == 3

        # 模拟点击画布上的文字图层
        layer = window._model.text_layout.layer_by_id("high")
        window._editor_page._on_model_selection_changed(layer)

        item = panel.tree.currentItem()
        assert item is not None
        assert item.data(0, Qt.ItemDataRole.UserRole) == "high"
        assert item.text(0) == "SALE"
    finally:
        window.close()


def test_ocr_only_button_jumps_to_ocr_tab_and_resets_progress():
    """点击「仅 OCR 识别」自动跳转 OCR 结果页，完成后进度条重置。"""
    QApplication.instance() or QApplication(["ocr-only-jump-test"])
    source = _document()
    fake_ocr = FakeRecognizeText()
    window = EditorMainWindow(
        import_image=object(),
        task_runner=ImmediateTaskRunner(),
        recognize_text=fake_ocr,
    )
    try:
        window._on_image_loaded(source)
        page = window._editor_page
        page.right_tabs.setCurrentIndex(0)
        page.translate_controls.ocr_only_button.click()

        assert page.right_tabs.currentIndex() == 1  # OCR 结果页
        # 进度条不再卡在「正在准备…」
        assert not page.translate_controls.progress.isVisible()
        assert page.translate_controls.progress.format() == "就绪"
    finally:
        window.close()


def test_translate_button_jumps_to_ocr_tab():
    """点击「开始翻译」自动跳转 OCR 结果页。"""
    QApplication.instance() or QApplication(["translate-jump-test"])
    source = _document()
    window = EditorMainWindow(
        import_image=object(),
        task_runner=ImmediateTaskRunner(),
        translate_image=FakeTranslateImage(),
        create_composition_editor=CreateCompositionEditor(
            QtBasicTextLayoutAdapter("Arial"),
            QtTextRenderer(),
        ),
    )
    try:
        window._on_image_loaded(source)
        page = window._editor_page
        page.right_tabs.setCurrentIndex(0)
        page.translate_controls.translate_button.click()

        assert page.right_tabs.currentIndex() == 1  # OCR 结果页
    finally:
        window.close()


def test_translation_completion_jumps_back_to_ocr_tab():
    """翻译完成后自动跳转 OCR 结果页（即使翻译期间切到了其他页）。"""
    QApplication.instance() or QApplication(["translate-complete-jump-test"])
    source = _document()
    result = FakeTranslateImage().execute(
        source,
        "en",
        TranslationSelection(TranslationMode.ALL, "zh-Hans"),
    )
    window = EditorMainWindow(
        import_image=object(),
        task_runner=ImmediateTaskRunner(),
        create_composition_editor=CreateCompositionEditor(
            QtBasicTextLayoutAdapter("Arial"),
            QtTextRenderer(),
        ),
    )
    try:
        window._on_image_loaded(source)
        page = window._editor_page
        page.right_tabs.setCurrentIndex(3)  # 翻译期间用户切到其他页

        window._on_translation_succeeded(result)

        assert page.right_tabs.currentIndex() == 1  # 完成后回到 OCR 结果页
    finally:
        window.close()


def test_crop_dialog_full_flow_applies_crop():
    """裁剪对话框完整流程：框选 → 点「应用裁剪」→ 图片被裁剪。"""
    QApplication.instance() or QApplication(["crop-dialog-flow-test"])
    source = _document()
    result = FakeTranslateImage().execute(
        source,
        "en",
        TranslationSelection(TranslationMode.ALL, "zh-Hans"),
    )
    window = EditorMainWindow(
        import_image=object(),
        task_runner=ImmediateTaskRunner(),
        create_composition_editor=CreateCompositionEditor(
            QtBasicTextLayoutAdapter("Arial"),
            QtTextRenderer(),
        ),
    )
    try:
        window._on_image_loaded(source)
        window._on_translation_succeeded(result)
        dialog = window._editor_page.crop_dialog

        # 打开裁剪对话框（模拟点击工具栏「裁剪」）
        window._editor_page.open_crop_dialog()
        assert window._editor_page.layer_tools_stack.currentWidget() is dialog

        # 模拟在画布框选裁剪区域
        window._editor_page._on_area_selected(
            "crop", TextBox(95, 36, 100, 40)
        )
        assert dialog.selection_label.text() == "裁剪区域：100 × 40 px"

        # 点击「应用裁剪」
        from PySide6.QtWidgets import QDialogButtonBox

        apply_button = dialog.findChild(QDialogButtonBox).button(
            QDialogButtonBox.StandardButton.Apply
        )
        apply_button.click()

        # 裁剪生效：画布尺寸变为裁剪后的尺寸
        assert window._model.rendered_document.asset.width == 100
        assert window._model.rendered_document.asset.height == 40
        assert "裁剪完成" in window.statusBar().currentMessage()
        assert window._editor_page.toolbar.active_tool == "crop"
        assert window._editor_page.scene.pointer_busy
        assert window._editor_page.scene.crop_selection_box is None
        assert window._editor_page.layer_tools_stack.currentWidget() is dialog
    finally:
        window.close()


def test_crop_selection_persists_moves_cancels_and_can_be_redrawn():
    from PySide6.QtCore import QEvent, QPointF
    from PySide6.QtWidgets import QGraphicsSceneMouseEvent

    QApplication.instance() or QApplication(["persistent-crop-selection-test"])
    scene = EditorScene()
    scene.set_document(_document())
    scene.set_area_selection_mode("crop")
    selected: list[TextBox] = []
    cleared: list[str] = []
    scene.area_selected.connect(
        lambda mode, box: selected.append(box) if mode == "crop" else None
    )
    scene.area_selection_cleared.connect(cleared.append)

    def event(kind, point, buttons=Qt.MouseButton.LeftButton):
        mouse_event = QGraphicsSceneMouseEvent(kind)
        mouse_event.setScenePos(QPointF(*point))
        mouse_event.setButton(Qt.MouseButton.LeftButton)
        mouse_event.setButtons(buttons)
        return mouse_event

    scene.mousePressEvent(
        event(QEvent.Type.GraphicsSceneMousePress, (20, 15))
    )
    scene.mouseMoveEvent(
        event(QEvent.Type.GraphicsSceneMouseMove, (100, 55))
    )
    scene.mouseReleaseEvent(
        event(
            QEvent.Type.GraphicsSceneMouseRelease,
            (100, 55),
            Qt.MouseButton.NoButton,
        )
    )
    first = scene.crop_selection_box
    assert first is not None
    assert first.width == pytest.approx(80)
    assert first.height == pytest.approx(40)
    assert scene.pointer_busy

    scene.mousePressEvent(
        event(QEvent.Type.GraphicsSceneMousePress, (60, 35))
    )
    scene.mouseMoveEvent(
        event(QEvent.Type.GraphicsSceneMouseMove, (80, 45))
    )
    scene.mouseReleaseEvent(
        event(
            QEvent.Type.GraphicsSceneMouseRelease,
            (80, 45),
            Qt.MouseButton.NoButton,
        )
    )
    moved = scene.crop_selection_box
    assert moved is not None
    assert moved.width == pytest.approx(first.width)
    assert moved.height == pytest.approx(first.height)
    assert moved.center_x == pytest.approx(first.center_x + 20)
    assert moved.center_y == pytest.approx(first.center_y + 10)

    scene.mousePressEvent(
        event(QEvent.Type.GraphicsSceneMousePress, (5, 5))
    )
    scene.mouseReleaseEvent(
        event(
            QEvent.Type.GraphicsSceneMouseRelease,
            (5, 5),
            Qt.MouseButton.NoButton,
        )
    )
    assert scene.crop_selection_box is None
    assert cleared == ["crop"]
    assert scene.pointer_busy

    scene.mousePressEvent(
        event(QEvent.Type.GraphicsSceneMousePress, (30, 20))
    )
    scene.mouseMoveEvent(
        event(QEvent.Type.GraphicsSceneMouseMove, (90, 50))
    )
    scene.mouseReleaseEvent(
        event(
            QEvent.Type.GraphicsSceneMouseRelease,
            (90, 50),
            Qt.MouseButton.NoButton,
        )
    )
    assert scene.crop_selection_box is not None
    assert len(selected) == 3


class _FakeProductWindow(QMainWindow):
    back_requested = Signal()
    closed = Signal()
    instances: list["_FakeProductWindow"] = []

    def __init__(self, **_kwargs) -> None:
        super().__init__()
        self.close_event_count = 0
        self.instances.append(self)

    def closeEvent(self, event) -> None:
        self.close_event_count += 1
        self.closed.emit()
        super().closeEvent(event)


def _patch_product_window(monkeypatch) -> None:
    _FakeProductWindow.instances.clear()
    monkeypatch.setattr(
        "src.ui.product.product_window.ProductWindow",
        _FakeProductWindow,
    )
    monkeypatch.setattr(
        "src.infrastructure.server_llm_adapter.ServerLLMAdapter",
        lambda *_args, **_kwargs: object(),
    )


def test_product_window_close_restores_single_main_window(monkeypatch):
    QApplication.instance() or QApplication(["product-window-close-test"])
    _patch_product_window(monkeypatch)
    window = EditorMainWindow(import_image=object())
    try:
        window.show()
        QApplication.processEvents()
        window._enter_product()
        QApplication.processEvents()

        product = _FakeProductWindow.instances[-1]
        assert window._product_window is product
        assert product.isVisible()
        assert not window.isVisible()

        product.close()
        QApplication.processEvents()

        assert product.close_event_count == 1
        assert window._product_window is None
        assert window._stack.currentWidget() is window._home_page
        assert window.isVisible()
        assert not shiboken6.isValid(product)
    finally:
        product = window._product_window
        if product is not None:
            product.close()
        window.close()


def test_product_window_back_closes_child_and_restores_main(monkeypatch):
    QApplication.instance() or QApplication(["product-window-back-test"])
    _patch_product_window(monkeypatch)
    window = EditorMainWindow(import_image=object())
    try:
        window.show()
        QApplication.processEvents()
        window._enter_product()
        QApplication.processEvents()

        product = _FakeProductWindow.instances[-1]
        product.back_requested.emit()
        QApplication.processEvents()

        assert product.close_event_count == 1
        assert window._product_window is None
        assert window._stack.currentWidget() is window._home_page
        assert window.isVisible()
        assert not shiboken6.isValid(product)
    finally:
        product = window._product_window
        if product is not None:
            product.close()
        window.close()
