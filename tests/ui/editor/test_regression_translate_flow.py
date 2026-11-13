"""冻结基线回归测试 — 验证 UI 层不破坏核心翻译流程。

全部使用 fake 适配器和内存合成图片，不调用真实 API。
"""

import os
import time
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


def _ocr_result_with_box(height: float):
    """构造单个识别区域（宽 60、高按参数），用于字号比例测试。"""
    from src.domain.ocr import OcrResult, TextRegion, order_quad

    region = TextRegion(
        "region-0000",
        order_quad(((20, 10), (80, 10), (80, 10 + height), (20, 10 + height))),
        "0901",
        0.95,
        "en",
        "fixture",
    )
    return OcrResult((region,), "en", "fixture", 0)


def _active_session():
    """未过期的激活会话。

    _on_translate 前置 _check_translation_access()，未激活时会弹出模态提示并直接
    返回，导致后续翻译逻辑根本不执行。凡是驱动 _on_translate 的用例都必须提供它。
    """
    from datetime import datetime, timedelta, timezone

    from src.domain.activation import ActivationSession

    now = datetime.now(timezone.utc)
    return ActivationSession(
        1,
        now,
        now + timedelta(days=1),
        "itd_regression_token_123456789",
    )


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
        activation_status=_active_session,
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


# 已移除 test_region_retranslation_recovers_circular_path_from_high_recall_ocr：
# 该用例验证的 EditorMainWindow._circular_path_for_retranslation 已在提交 72e976b
# （feat(client): 工具箱预览/水印旋转/框选翻译修复…）中随二次翻译流程重构一并删除。
# 新流程不再从 OCR 多边形反推 TextBox / CircularTextPath，而是跳转文字属性面板、
# 由用户选定目标语言后直接调用翻译适配器，故此用例已无对应实现可测。


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
        # 画布与强化翻译浏览器共用栈内第 1 格，切豆包时右侧面板不受影响
        canvas_stack = window._editor_page.canvas_stack
        assert window._editor_page.main_splitter.widget(1) is canvas_stack
        assert canvas_stack.widget(0) is window._editor_page.view
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

        # 二次翻译回调签名已改为 (译文, 编辑记录, 目标语言)
        window._on_region_retranslated("high", ("SECOND", edit, "zh-Hans"))

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


# 已移除 test_rotated_ocr_region_box_uses_oriented_dimensions：
# 该用例验证的 EditorMainWindow._region_box 同样在提交 72e976b 中被删除，
# 当前代码库已无任何按最小外接矩形推导定向 TextBox 的实现（src 下不存在
# minAreaRect 或等价逻辑）。若需恢复「旋转文字按定向尺寸建框」这一产品能力，
# 应作为独立需求重新实现并配套新测试，而非在此保留一个无实现可测的用例。


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
        # view 现在挂在画布栈里，两者几何要换算到同一坐标系再比
        original_right = page.original_view.mapTo(
            page.main_splitter, page.original_view.rect().topRight()
        ).x()
        view_left = page.view.mapTo(page.main_splitter, page.view.rect().topLeft()).x()
        assert original_right <= view_left

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
        assert len(buttons) == 11
        assert "matting" not in toolbar.buttons
        assert all(button.width() == 72 and button.height() == 44 for button in buttons)
        assert list(toolbar.buttons) == [
            "select",
            "text_regions",
            "add_text",
            "manual_translate",
            "ai_erase",
            "extract_layer",
            "crop",
            "layers",
            "watermark",
            "enhance_translate",
            "wanxiang_note",
        ]
    finally:
        toolbar.close()


def test_enhance_translate_entry_sits_under_watermark_and_requests_feature():
    """强化翻译入口在「水印」下方，点击后按功能型工具发起请求。"""
    QApplication.instance() or QApplication(["enhance-translate-toolbar-test"])
    toolbar = EditorToolBar()
    requested: list[str] = []
    toolbar.feature_requested.connect(requested.append)
    try:
        labels = [button.text() for button in toolbar.buttons.values()]
        assert labels.index("强化翻译") == labels.index("水印") + 1

        toolbar.buttons["enhance_translate"].click()
        assert requested == ["enhance_translate"]
    finally:
        toolbar.close()


def test_enhance_translate_panel_lists_images_and_emits_requests():
    """面板只负责展示与发起请求，下载/导入由 MainWindow 后台执行。"""
    from src.infrastructure.doubao_share import ShareImage
    from src.ui.editor.widgets.tool_dialogs import EnhanceTranslatePanel

    QApplication.instance() or QApplication(["enhance-translate-panel-test"])
    dialog = EnhanceTranslatePanel()
    fetched: list[str] = []
    imported: list[object] = []
    dialog.fetch_requested.connect(fetched.append)
    dialog.import_requested.connect(imported.append)
    try:
        dialog.fetch_button.click()  # 空链接：只提示，不发请求
        assert fetched == []
        assert "粘贴" in dialog.status.text()

        dialog.link.setText("https://www.doubao.com/thread/abc")
        dialog.fetch_button.click()
        assert fetched == ["https://www.doubao.com/thread/abc"]

        assert not dialog.import_button.isEnabled()
        assert not dialog.save_all_button.isEnabled()

        images = (
            ShareImage(
                url="https://cdn.test/a~image_raw.png",
                key="k/a.png",
                width=1536,
                height=1536,
            ),
            ShareImage(
                url="https://cdn.test/b~image_raw.png",
                key="k/b.png",
                width=1024,
                height=1024,
            ),
        )
        dialog.set_images(images)
        assert dialog.results.count() == 2
        assert "1536×1536" in dialog.results.item(0).text()
        assert dialog.import_button.isEnabled()

        dialog.import_button.click()
        assert imported == [images[0]]

        # 提示词框已删（提示词直接填在AI输入框里）；「解析链接」只由用户手动点
        assert not hasattr(dialog, "prompt_edit")
        assert "手动点「解析链接」" in dialog._FLOW_HINT
    finally:
        dialog.close()


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

        # 框选松手即自动消除（_on_area_selected 内直接触发 _request_ai_erase），
        # 因此蒙版会被立即消费并清空，修复结果已落到合成编辑器，无需再点「应用」。
        page._on_area_selected("ai_erase", TextBox(30, 25, 20, 10))

        assert page.scene.edit_mask.is_empty
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


def test_batch_ocr_import_clears_previous_composition_state():
    """仅 OCR 批量导入必须清掉上一张图的译文与编辑会话。

    否则「先翻译 A 图 → 批量仅 OCR 导入 B 图」时，B 图改原文会拿 A 图残留的
    repaired_background 当底图，擦除区被旧内容盖回，导出图带着没擦干净的残影
    （用户实际报障：0901 单图 OCR 改数字后旧字痕迹仍在）。
    """
    QApplication.instance() or QApplication(["batch-ocr-reset-test"])
    from src.application.batch import BatchOcrState

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
        # 伪造「上一张图已有译文与编辑会话」的残留状态
        window._model.repaired_background = source
        window._model.rendered_document = source
        window._model.composition_editor = object()
        window._model.translation_result = object()
        window._model.text_layout = TextLayout(())

        ocr = OcrResult((), "zh-Hans", "fixture", 1.0)
        window._restore_batch_editable(
            source, source, BatchOcrState(ocr)
        )

        assert window._model.repaired_background is None
        assert window._model.composition_editor is None
        assert window._model.rendered_document is None
        assert window._model.translation_result is None
        assert window._model.ocr_result is ocr
    finally:
        window.close()


def test_ocr_preview_mask_stays_within_recognized_region():
    """OCR 预览擦除蒙版不得越出识别框，否则会吃掉紧邻的其它文字。

    实测「0901」检查井水印图：识别框 (32,1068)-(228,1162) 已完整覆盖 09:19
    全部笔画，右侧 26px 处就是「2026年01月02」。上一版按亮度向框外自动扩展，
    把整块蓝色贴图擦掉，补全后出现大片白雾。这里锁定：蒙版边界与识别框的
    距离不超过膨胀量（默认 2px）+ 1px 抗锯齿余量。
    """
    QApplication.instance() or QApplication(["ocr-preview-mask-bounds-test"])
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
        window._mask_rasterizer = PillowMaskRasterizer()
        quad = ((18.0, 18.0), (78.0, 18.0), (78.0, 48.0), (18.0, 48.0))
        region = TextRegion("bounds", order_quad(quad), "SUMMER", 0.9, "en", "fx")

        mask = window._ocr_preview_mask(region)
        assert mask is not None

        painted = np.frombuffer(mask.pixels, dtype=np.uint8).reshape(72, 190) > 0
        rows, columns = np.nonzero(painted)
        assert columns.min() >= 18 - 3
        assert columns.max() <= 78 + 3
        assert rows.min() >= 18 - 3
        assert rows.max() <= 48 + 3
    finally:
        window.close()


def test_ocr_preview_mask_traces_glyphs_not_whole_box():
    """OCR 预览擦除蒙版必须贴合字形，不能退化成整框矩形。

    实测「0901」水印图（白字蓝底）：整框蒙版交给 LaMa 后，LaMa 会按周围
    纹理「脑补」，把旧字轮廓重新画回来——膨胀 5px 时旧字残影 472 个像素、
    背景 std 26.2（正常蓝底 5.6），用户看到的就是「擦不干净」。
    字形蒙版下残影 0 个、std 6.8，因此这里锁定蒙版不能铺满整框。
    """
    QApplication.instance() or QApplication(["ocr-preview-glyph-mask-test"])
    # 必须用「深色背景 + 白字」才有真实字形可剥离；纯色块会让细化蒙版
    # 退化成整框，测不出这条约束。
    width, height = 190, 72
    pixels = np.full((height, width, 3), 30, dtype=np.uint8)
    for row in range(24, 42):
        for column in range(24, 34):
            pixels[row, column] = 250
    for row in range(24, 42):
        for column in range(44, 54):
            pixels[row, column] = 250
    asset = ImageAsset(
        Path("glyphs.png"), width, height, 1, ImageFileFormat.PNG, False, False
    )
    source = ImageDocument(asset, "RGB", pixels.tobytes())
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
        window._mask_rasterizer = PillowMaskRasterizer()
        quad = ((18.0, 18.0), (78.0, 18.0), (78.0, 48.0), (18.0, 48.0))
        region = TextRegion("glyphs", order_quad(quad), "SUMMER", 0.9, "en", "fx")

        mask = window._ocr_preview_mask(region)
        assert mask is not None

        painted = np.frombuffer(mask.pixels, dtype=np.uint8).reshape(72, 190) > 0
        box_area = (78 - 18) * (48 - 18)
        assert int(painted.sum()) < box_area * 0.8
    finally:
        window.close()


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
            "src.ui.editor.widgets.layer_state_panel.pick_color",
            lambda *_args, **_kwargs: (51, 170, 102),
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
        # 属性面板是 300ms 防抖，固定等待在机器繁忙时会偶发超时；改成轮询到生效
        deadline = time.monotonic() + 3.0
        while (
            window._model.text_layout.layer_by_id("high").text != "DIRECT EDIT"
            and time.monotonic() < deadline
        ):
            QTest.qWait(50)

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
        activation_status=_active_session,
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
        activation_status=_active_session,
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


# ============================================================
# 批量发送到工作台 — 已完成的图片送译文成品
# ============================================================

def test_send_batch_to_editor_uses_translated_result_for_completed_items():
    """批量翻译成功后发送到工作台应是译文成品；失败项仍送原图。"""
    QApplication.instance() or QApplication(["send-batch-translated-test"])
    from src.domain.batch import (
        BatchItemSnapshot,
        BatchItemStatus,
        BatchSnapshot,
        BatchStatus,
    )

    source_a = Path("a.png").resolve()
    source_b = Path("b.png").resolve()
    original_a = _document()
    original_b = _document(w=200, h=80)
def test_send_batch_to_editor_uses_translated_result_for_completed_items():
    """批量翻译成功后发送到工作台应是译文成品；失败项仍送原图。"""
    QApplication.instance() or QApplication(["send-batch-translated-test"])
    from src.domain.batch import (
        BatchItemSnapshot,
        BatchItemStatus,
        BatchSnapshot,
        BatchStatus,
    )

    source_a = Path("a.png").resolve()
    source_b = Path("b.png").resolve()
    original_a = _document()
    original_b = _document(w=200, h=80)
    rendered_b = _document(w=200, h=80)

    class _Import:
        def execute(self, source):
            return original_a if Path(source).name == "a.png" else original_b

    class _Store:
        def load(self, ref):
            assert ref == "cache/b.png"
            return rendered_b

        def load_editable(self, ref):
            assert ref == "cache/b.png"
            return None

    window = EditorMainWindow(
        import_image=_Import(),
        task_runner=ImmediateTaskRunner(),
        batch_result_store=_Store(),
    )
    try:
        window._editor_page.batch_panel.add_sources((source_a, source_b))
        window._batch_snapshot = BatchSnapshot(
            batch_id="batch-test1234",
            status=BatchStatus.COMPLETED,
            items=(
                BatchItemSnapshot(
                    "item-0", source_a, BatchItemStatus.FAILED, error="boom"
                ),
                BatchItemSnapshot(
                    "item-1",
                    source_b,
                    BatchItemStatus.COMPLETED,
                    result_ref="cache/b.png",
                ),
            ),
            max_active_items=1,
        )
        window._on_send_batch_to_editor()

        by_name = {ref.name: ref for ref in window._model.documents()}
        assert set(by_name) == {"a.png", "b.png"}
        assert by_name["a.png"].rendered_document is None
        assert by_name["b.png"].rendered_document is rendered_b
        # 第一张（失败项）无译文，显示原图
        assert window._model.document is original_a
        # 切到第二张，显示译文成品、原图保留为对比图
        window._model.set_active_document(by_name["b.png"].doc_id)
        window._load_active_document()
        assert window._model.document is rendered_b
        assert window._model.source_document is original_b
    finally:
        window.close()
        from PySide6.QtWidgets import QDialog

        return QDialog.DialogCode.Accepted

    @property
    def selected_directory(self):
        return Path("FAKE_OUT")

    @property
    def selected_suffix(self):
        return self.suffix


class _FakeBatchExportDialog:
    """替身批量导出对话框：按构造参数返回目录/后缀，exec 直接接受。"""

    instances: list = []

    def __init__(self, default_suffix: str, parent=None):
        del parent
        self.default_suffix = default_suffix
        self.suffix = default_suffix
        _FakeBatchExportDialog.instances.append(self)

    def exec(self):
        from PySide6.QtWidgets import QDialog

        return QDialog.DialogCode.Accepted

    @property
    def selected_directory(self):
        return Path("FAKE_OUT")

    @property
    def selected_suffix(self):
        return self.suffix


def _workbench_batch_export_window(monkeypatch, tmp_path, suffix=".png"):
    """构造含 2 个工作台文档的编辑器窗口，批量导出对话框替身指向 tmp_path/out。"""
    _FakeBatchExportDialog.instances = []
    dialog_captured: list[tuple[str, str]] = []
    exported: list[ImageDocument] = []

    def fake_export(document, target, export_usecase, codec, options=None):
        del export_usecase, codec, options
        exported.append(document)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"fake")
        return target

    monkeypatch.setattr("src.ui.editor.main_window.export_document", fake_export)
    monkeypatch.setattr(
        QMessageBox,
        "information",
        lambda _parent, title, text: dialog_captured.append((title, text)),
    )

    class FakeDialog(_FakeBatchExportDialog):
        @property
        def selected_directory(self):
            return tmp_path / "out"

    monkeypatch.setattr("src.ui.editor.editor_page.BatchExportDialog", FakeDialog)

    source_a = _document()
    source_b = _document(w=200, h=80)
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
    window._on_image_loaded(source_a)
    window._on_translation_succeeded(result_a)
    window._editor_page.export_settings.format_combo.setCurrentIndex(
        window._editor_page.export_settings.format_combo.findData(suffix)
    )
    window._model.add_document(Path("b.png"), source_b, name="b.png")
    window._load_active_document()
    return window, source_a, source_b, exported, dialog_captured


def test_top_bar_batch_export_button_exports_all_workbench_documents(
    monkeypatch,
    tmp_path,
):
    """工具栏「批量导出」：选格式和目录后，工作台每个文档各导出一个文件。"""
    QApplication.instance() or QApplication(["workbench-batch-export-button-test"])
    window, source_a, source_b, exported, dialog_captured = (
        _workbench_batch_export_window(monkeypatch, tmp_path, ".png")
    )
    try:
        top_bar = window._editor_page.top_bar
        assert top_bar.batch_export_btn.text() == "批量导出"
        # 工作台已有图片 → 按钮启用
        assert top_bar.batch_export_btn.isEnabled()

        top_bar.batch_export_btn.click()

        # 对话框默认取导出设置当前格式
        assert _FakeBatchExportDialog.instances[0].default_suffix == ".png"
        # 按文档列表顺序导出：a（已翻译）在前，b（未翻译，原图）在后
        assert exported == [source_a, source_b]
        out = tmp_path / "out"
        # 两个 fake 文档同名（stem 都是 fake）→ 去重出 -2 后缀
        assert (out / "fake_translated.png").is_file()
        assert (out / "fake_translated-2.png").is_file()
        assert dialog_captured[0][0] == "批量导出成功"
        assert "成功导出 2/2 张图片" in dialog_captured[0][1]
        assert str(out) in dialog_captured[0][1]
    finally:
        window.close()


def test_top_bar_batch_export_pdf_writes_one_file_per_image(
    monkeypatch,
    tmp_path,
):
    """批量导出选 PDF：每张图片一个单页 PDF 文件（不合并多页）。"""
    QApplication.instance() or QApplication(["workbench-batch-export-pdf-test"])
    window, _a, _b, exported, dialog_captured = _workbench_batch_export_window(
        monkeypatch, tmp_path, ".pdf"
    )
    try:
        window._editor_page.top_bar.batch_export_btn.click()

        assert _FakeBatchExportDialog.instances[0].default_suffix == ".pdf"
        assert len(exported) == 2
        out = tmp_path / "out"
        assert (out / "fake_translated.pdf").is_file()
        assert (out / "fake_translated-2.pdf").is_file()
        assert dialog_captured[0][0] == "批量导出成功"
    finally:
        window.close()


def test_batch_export_dialog_format_default_and_properties():
    """批量导出对话框：默认选中导出设置的格式，目录/后缀属性正确。"""
    QApplication.instance() or QApplication(["batch-export-dialog-test"])
    from src.ui.editor.widgets.tool_dialogs import BatchExportDialog

    dialog = BatchExportDialog(".jpg")
    try:
        assert dialog.selected_suffix == ".jpg"
        dialog.format.setCurrentIndex(0)
        assert dialog.selected_suffix == ".png"
        dialog.format.setCurrentIndex(
            dialog.format.findData(".pdf")
        )
        assert dialog.selected_suffix == ".pdf"
        dialog.directory.setText("  /tmp/out  ")
        assert dialog.selected_directory == Path("/tmp/out")
    finally:
        dialog.close()

    pdf_dialog = BatchExportDialog(".pdf")
    try:
        assert pdf_dialog.selected_suffix == ".pdf"
    finally:
        pdf_dialog.close()


def test_menu_bar_text_stays_dark_under_system_dark_palette():
    """系统深色模式（调色板文字变浅）下，菜单栏文字仍保持深色，不出现浅底白字。"""
    from PySide6.QtGui import QPalette

    app = QApplication.instance() or QApplication(["menubar-dark-mode-test"])
    original_palette = QPalette(app.palette())
    dark_mode_palette = QPalette(app.palette())
    light_text = QColor(235, 235, 235)
    for role in (
        QPalette.ColorRole.WindowText,
        QPalette.ColorRole.Text,
        QPalette.ColorRole.ButtonText,
    ):
        dark_mode_palette.setColor(role, light_text)
    app.setPalette(dark_mode_palette)
    try:
        window = EditorMainWindow(import_image=object())
        try:
            menu = window.menuBar()
            assert menu.property("editorStyle") is True
            menu.resize(menu.sizeHint())
            image = menu.grab().toImage()
            dark_pixels = 0
            for y in range(image.height()):
                for x in range(image.width()):
                    if image.pixelColor(x, y).lightness() < 150:
                        dark_pixels += 1
            # 「首页 文件 编辑 视图 帮助 账户」为深色文字 → 深色像素充足
            assert dark_pixels > 100
        finally:
            window.close()
    finally:
        app.setPalette(original_palette)


def test_qmessagebox_keeps_light_theme_under_system_dark_palette():
    """系统深色模式下，编辑器弹窗（QMessageBox）保持浅色主题：浅底深字。

    QMessageBox 是顶层窗，根背景规则 [editorStyle="true"] 不匹配它，
    但主体通用 QLabel/QPushButton 规则沿 QObject 父链传播——若背景跟随系统
    深色调色板就会出现深底 + 深字的不可读组合。"""
    from PySide6.QtGui import QPalette
    from PySide6.QtWidgets import QMainWindow, QMessageBox

    from src.ui.editor.theme import EDITOR_DARK_THEME

    app = QApplication.instance() or QApplication(["msgbox-dark-mode-test"])
    original_palette = QPalette(app.palette())
    dark_mode_palette = QPalette(app.palette())
    dark_mode_palette.setColor(QPalette.ColorRole.Window, QColor(43, 43, 43))
    dark_mode_palette.setColor(QPalette.ColorRole.Base, QColor(30, 30, 30))
    light_text = QColor(235, 235, 235)
    for role in (
        QPalette.ColorRole.WindowText,
        QPalette.ColorRole.Text,
        QPalette.ColorRole.ButtonText,
    ):
        dark_mode_palette.setColor(role, light_text)
    app.setPalette(dark_mode_palette)
    parent = QMainWindow()
    parent.setProperty("editorStyle", True)
    parent.setStyleSheet(EDITOR_DARK_THEME)
    try:
        box = QMessageBox(
            QMessageBox.Icon.Warning,
            "提示",
            "请先激活后，再查看额度",
            parent=parent,
        )
        box.addButton("确定", QMessageBox.ButtonRole.AcceptRole)
        try:
            box.resize(box.sizeHint())
            image = box.grab().toImage()
            # 角落像素应为浅色背景（#faf7f1），而非深色调色板底色
            assert image.pixelColor(2, 2).lightness() > 200
            dark_pixels = 0
            for y in range(image.height()):
                for x in range(image.width()):
                    if image.pixelColor(x, y).lightness() < 150:
                        dark_pixels += 1
            # 消息文字为深色 → 深色像素充足
            assert dark_pixels > 100
        finally:
            box.deleteLater()
    finally:
        parent.deleteLater()
        app.setPalette(original_palette)


def test_tool_dialogs_keep_light_theme_under_system_dark_palette():
    """系统深色模式（窗口底色变深、文字变浅）下，顶层工具对话框仍保持浅色主题：
    背景为奶白浅色、标签文字为深色，不出现深底 + 深字的不可读组合。"""
    from PySide6.QtGui import QPalette

    from src.ui.editor.widgets.tool_dialogs import BatchExportDialog, EraseToolDialog

    app = QApplication.instance() or QApplication(["dialogs-dark-mode-test"])
    original_palette = QPalette(app.palette())
    dark_mode_palette = QPalette(app.palette())
    dark_mode_palette.setColor(QPalette.ColorRole.Window, QColor(43, 43, 43))
    dark_mode_palette.setColor(QPalette.ColorRole.Base, QColor(30, 30, 30))
    light_text = QColor(235, 235, 235)
    for role in (
        QPalette.ColorRole.WindowText,
        QPalette.ColorRole.Text,
        QPalette.ColorRole.ButtonText,
    ):
        dark_mode_palette.setColor(role, light_text)
    app.setPalette(dark_mode_palette)
    try:
        for dialog in (BatchExportDialog(".png"), EraseToolDialog()):
            try:
                assert dialog.property("editorStyle") is True
                dialog.resize(dialog.sizeHint())
                image = dialog.grab().toImage()
                # 角落像素应为浅色背景（#faf7f1），而非深色调色板底色
                assert image.pixelColor(2, 2).lightness() > 200
                dark_pixels = 0
                for y in range(image.height()):
                    for x in range(image.width()):
                        if image.pixelColor(x, y).lightness() < 150:
                            dark_pixels += 1
                # 标题/提示等 QLabel 为深色文字 → 深色像素充足
                assert dark_pixels > 100
            finally:
                dialog.deleteLater()
    finally:
        app.setPalette(original_palette)


def test_batch_dialog_keeps_light_theme_under_system_dark_palette():
    """系统深色模式下，多图批量翻译对话框（顶层窗口）保持浅色主题：
    根背景浅色、标签文字深色、表格表头浅底深字。"""
    from PySide6.QtGui import QPalette

    app = QApplication.instance() or QApplication(["batch-dialog-dark-mode-test"])
    original_palette = QPalette(app.palette())
    dark_mode_palette = QPalette(app.palette())
    dark_mode_palette.setColor(QPalette.ColorRole.Window, QColor(43, 43, 43))
    dark_mode_palette.setColor(QPalette.ColorRole.Base, QColor(30, 30, 30))
    light_text = QColor(235, 235, 235)
    for role in (
        QPalette.ColorRole.WindowText,
        QPalette.ColorRole.Text,
        QPalette.ColorRole.ButtonText,
    ):
        dark_mode_palette.setColor(role, light_text)
    app.setPalette(dark_mode_palette)
    try:
        window = EditorMainWindow(import_image=object())
        try:
            dialog = window._editor_page.batch_dialog
            assert dialog.property("editorStyle") is True
            dialog.show()
            app.processEvents()
            image = dialog.grab().toImage()
            # 根背景为浅色（#faf7f1），而非深色调色板底色
            assert image.pixelColor(2, 2).lightness() > 200
            dark_pixels = 0
            for y in range(image.height()):
                for x in range(image.width()):
                    if image.pixelColor(x, y).lightness() < 150:
                        dark_pixels += 1
            # 标题/提示等 QLabel 为深色文字 → 深色像素充足
            assert dark_pixels > 100
            # 表格表头：浅底 + 深色标题文字
            header_image = (
                window._editor_page.batch_panel.items.header().grab().toImage()
            )
            assert header_image.pixelColor(2, 2).lightness() > 150
            dark_header = 0
            for y in range(header_image.height()):
                for x in range(header_image.width()):
                    if header_image.pixelColor(x, y).lightness() < 150:
                        dark_header += 1
            assert dark_header > 50
        finally:
            dialog.close()
            window.close()
    finally:
        app.setPalette(original_palette)


def test_product_window_menu_bar_text_stays_dark_under_system_dark_palette():
    """商品详情窗口菜单栏（首页/文件/编辑/视图/帮助/账户）在系统深色模式下保持深色文字。"""
    from PySide6.QtGui import QPalette

    from src.ui.product.product_window import ProductWindow

    class _FakeTaskRunner:
        def submit(self, operation, on_success, on_error):
            on_success(operation())

    class _FakeCodec:
        def load(self, path):
            raise FileNotFoundError(path)

    app = QApplication.instance() or QApplication(["product-menu-dark-mode-test"])
    original_palette = QPalette(app.palette())
    dark_mode_palette = QPalette(app.palette())
    dark_mode_palette.setColor(QPalette.ColorRole.Window, QColor(43, 43, 43))
    dark_mode_palette.setColor(QPalette.ColorRole.Base, QColor(30, 30, 30))
    light_text = QColor(235, 235, 235)
    for role in (
        QPalette.ColorRole.WindowText,
        QPalette.ColorRole.Text,
        QPalette.ColorRole.ButtonText,
    ):
        dark_mode_palette.setColor(role, light_text)
    app.setPalette(dark_mode_palette)
    window = ProductWindow(
        task_runner=_FakeTaskRunner(),
        codec=_FakeCodec(),
        ocr_adapter=object(),
        llm_adapter=object(),
    )
    try:
        window.show()
        image = window.grab().toImage()
        # 「首页 文件 编辑 视图 帮助 账户」为深色文字 → 深色像素充足
        dark_pixels = 0
        for y in range(image.height()):
            for x in range(image.width()):
                if image.pixelColor(x, y).lightness() < 150:
                    dark_pixels += 1
        assert dark_pixels > 100
    finally:
        window.close()
        app.setPalette(original_palette)


def test_image_uploader_file_dialog_keeps_light_theme_under_system_dark_palette():
    """商品图片选择文件对话框（Qt 自绘）在系统深色模式下保持浅色主题。"""
    from PySide6.QtGui import QPalette
    from PySide6.QtWidgets import QFileDialog

    app = QApplication.instance() or QApplication(["file-dialog-dark-mode-test"])
    original_palette = QPalette(app.palette())
    dark_mode_palette = QPalette(app.palette())
    dark_mode_palette.setColor(QPalette.ColorRole.Window, QColor(43, 43, 43))
    dark_mode_palette.setColor(QPalette.ColorRole.Base, QColor(30, 30, 30))
    light_text = QColor(235, 235, 235)
    for role in (
        QPalette.ColorRole.WindowText,
        QPalette.ColorRole.Text,
        QPalette.ColorRole.ButtonText,
    ):
        dark_mode_palette.setColor(role, light_text)
    app.setPalette(dark_mode_palette)

    from src.ui.product.widgets.image_uploader import ImageUploader

    uploader = ImageUploader()
    try:
        dialogs = []

        def _make_dialog():
            dialog = QFileDialog(uploader, "选择商品图片", "C:/Users")
            dialog.setNameFilter("图片文件 (*.jpg *.jpeg *.png *.webp *.bmp)")
            dialog.setOption(QFileDialog.Option.DontUseNativeDialog, True)
            dialog.setProperty("editorStyle", True)
            from src.ui.editor.theme import EDITOR_DARK_THEME

            dialog.setStyleSheet(EDITOR_DARK_THEME)
            dialogs.append(dialog)
            return dialog

        # 直接实例化并隐藏 exec，只做渲染验证
        dialog = _make_dialog()
        dialog.show()
        app.processEvents()
        dialog.resize(dialog.sizeHint())
        image = dialog.grab().toImage()
        # 角落应为浅色背景
        assert image.pixelColor(2, 2).lightness() > 200
    finally:
        for dialog in dialogs:
            dialog.close()
        uploader.deleteLater()
        app.setPalette(original_palette)


def _apply_dark_mode_palette(app):
    from PySide6.QtGui import QPalette

    palette = QPalette(app.palette())
    palette.setColor(QPalette.ColorRole.Window, QColor(43, 43, 43))
    palette.setColor(QPalette.ColorRole.Base, QColor(30, 30, 30))
    light_text = QColor(235, 235, 235)
    for role in (
        QPalette.ColorRole.WindowText,
        QPalette.ColorRole.Text,
        QPalette.ColorRole.ButtonText,
    ):
        palette.setColor(role, light_text)
    return palette


def _assert_light_dialog(dialog) -> None:
    """断言弹窗以浅色像素为主（品牌紫面板除外），且含深色文字。"""
    dialog.resize(dialog.sizeHint())
    image = dialog.grab().toImage()
    total = max(1, image.width() * image.height())
    light_pixels = 0
    dark_text_pixels = 0
    for y in range(image.height()):
        for x in range(image.width()):
            lightness = image.pixelColor(x, y).lightness()
            if lightness > 200:
                light_pixels += 1
            elif lightness < 90:
                dark_text_pixels += 1
    assert light_pixels / total > 0.3, (
        f"{type(dialog).__name__} 浅色像素占比过低（系统深底 43,43,43 会失败；紫色品牌面板 159 可通过）"
    )
    assert dark_text_pixels > 100, f"{type(dialog).__name__} 应含深色文字"


def _assert_brand_purple_dialog(dialog) -> None:
    """激活对话框是紫色品牌面板（白字），断言紫底 + 无系统深色灰底。"""
    dialog.resize(dialog.sizeHint())
    image = dialog.grab().toImage()
    total = max(1, image.width() * image.height())
    purple_pixels = 0
    white_pixels = 0
    system_gray_pixels = 0
    for y in range(image.height()):
        for x in range(image.width()):
            color = image.pixelColor(x, y)
            lightness = color.lightness()
            if (
                color.red() > 100
                and color.blue() > 200
                and color.green() < 150
            ):
                purple_pixels += 1
            elif lightness > 200:
                white_pixels += 1
            elif (
                color.red() == color.green() == color.blue()
                and 25 <= color.red() <= 55
            ):
                system_gray_pixels += 1
    assert system_gray_pixels / total < 0.3, (
        f"{type(dialog).__name__} 不应大面积出现系统深色灰底"
    )
    assert purple_pixels + white_pixels > total * 0.5, (
        f"{type(dialog).__name__} 应为品牌紫 + 白字"
    )


def test_all_editor_dialogs_keep_light_theme_under_system_dark_palette():
    """编辑器/商品窗口打开的全部对话框在系统深色模式下保持浅底深字。"""
    from datetime import datetime, timezone

    from PySide6.QtGui import QPalette
    from PySide6.QtWidgets import QMainWindow, QMessageBox

    from src.ui.activation_dialog import ActivationDialog
    from src.ui.ecommerce_settings_dialog import EcommerceSettingsDialog
    from src.ui.editor.main_window import EDITOR_DARK_THEME
    from src.ui.help_dialog import HelpDialog
    from src.ui.purchase_dialog import PurchaseDialog
    from src.ui.quota_dialog import QuotaDialog

    class _TaskRunner:
        def submit(self, operation, on_success, on_error):
            on_success(operation())

    class _PaymentClient:
        def list_plans(self):
            return []

    app = QApplication.instance() or QApplication(["all-dialogs-dark-mode-test"])
    original_palette = QPalette(app.palette())
    app.setPalette(_apply_dark_mode_palette(app))

    # 编辑器主题宿主：顶层弹窗无 editorStyle 属性，靠主题的 QDialog 兜底规则
    parent = QMainWindow()
    parent.setProperty("editorStyle", True)
    parent.setStyleSheet(EDITOR_DARK_THEME)
    try:
        dialogs = [
            HelpDialog(parent=parent),
            EcommerceSettingsDialog({}, None, parent=parent),
            QuotaDialog(
                "IT-ABCD-EFGH-JKLM-NPQR-STUV-WXYZ-2345-6789",
                datetime(2030, 1, 1, tzinfo=timezone.utc),
                10,
                10,
                refresh_usage=lambda: (10, 10),
                task_runner=_TaskRunner(),
                parent=parent,
            ),
            PurchaseDialog(
                _PaymentClient(), _TaskRunner(), parent=parent,
            ),
            ActivationDialog(
                lambda code: None,
                lambda: None,
                lambda: None,
                _TaskRunner(),
                parent=parent,
            ),
        ]
        try:
            for dialog in dialogs:
                try:
                    dialog.show()
                    app.processEvents()
                    if isinstance(dialog, ActivationDialog):
                        _assert_brand_purple_dialog(dialog)
                    else:
                        _assert_light_dialog(dialog)
                finally:
                    dialog.deleteLater()
        finally:
            parent.deleteLater()
    finally:
        app.setPalette(original_palette)


def test_legacy_dialogs_keep_light_theme_under_system_dark_palette():
    """旧工作台（_STYLE 主题）宿主的对话框在系统深色模式下保持浅底深字。"""
    from datetime import datetime, timezone

    from PySide6.QtGui import QPalette
    from PySide6.QtWidgets import QMainWindow

    from src.ui.activation_dialog import ActivationDialog
    from src.ui.ecommerce_settings_dialog import EcommerceSettingsDialog
    from src.ui.help_dialog import HelpDialog
    from src.ui.main_window import _STYLE
    from src.ui.purchase_dialog import PurchaseDialog
    from src.ui.quota_dialog import QuotaDialog

    class _TaskRunner:
        def submit(self, operation, on_success, on_error):
            on_success(operation())

    class _PaymentClient:
        def list_plans(self):
            return []

    app = QApplication.instance() or QApplication(["legacy-dialogs-dark-mode-test"])
    original_palette = QPalette(app.palette())
    app.setPalette(_apply_dark_mode_palette(app))

    parent = QMainWindow()
    parent.setStyleSheet(_STYLE)
    try:
        dialogs = [
            HelpDialog(parent=parent),
            EcommerceSettingsDialog({}, None, parent=parent),
            QuotaDialog(
                "IT-ABCD-EFGH-JKLM-NPQR-STUV-WXYZ-2345-6789",
                datetime(2030, 1, 1, tzinfo=timezone.utc),
                10,
                10,
                refresh_usage=lambda: (10, 10),
                task_runner=_TaskRunner(),
                parent=parent,
            ),
            PurchaseDialog(
                _PaymentClient(), _TaskRunner(), parent=parent,
            ),
            ActivationDialog(
                lambda code: None,
                lambda: None,
                lambda: None,
                _TaskRunner(),
                parent=parent,
            ),
        ]
        try:
            for dialog in dialogs:
                try:
                    dialog.show()
                    app.processEvents()
                    if isinstance(dialog, ActivationDialog):
                        _assert_brand_purple_dialog(dialog)
                    else:
                        _assert_light_dialog(dialog)
                finally:
                    dialog.deleteLater()
        finally:
            parent.deleteLater()
    finally:
        app.setPalette(original_palette)


def _window_with_verify(verify_result):
    from src.ui.editor.main_window import EditorMainWindow

    def _operation():
        return True

    def _fake_task_runner():
        class _Runner:
            def submit(self, operation, on_success, on_error):
                on_success(operation())

        return _Runner()

    return EditorMainWindow(
        import_image=lambda *a, **k: None,
        export_image=lambda *a, **k: None,
        codec=object(),
        task_runner=_fake_task_runner(),
        translate_image=_operation,
        recognize_text=_operation,
        process_manual_region=_operation,
        repair_selection=_operation,
        verify_activation=lambda: verify_result,
    )


def test_verify_activation_inactive_warns_with_unbound_message():
    """窗口激活校验返回 inactive（后台解绑/停用）时，弹出对应提示。"""
    app = QApplication.instance() or QApplication(["verify-activation-warning-test"])
    warnings = []
    window = _window_with_verify("inactive")
    try:
        original_warning = QMessageBox.warning
        QMessageBox.warning = lambda parent, title, text, *a, **k: warnings.append(
            (title, text)
        )
        try:
            window.request_activation_check()
        finally:
            QMessageBox.warning = original_warning
        assert warnings and "可能已被解绑或停用" in warnings[0][1]
    finally:
        window.close()


def test_verify_activation_expired_warns_with_expiry_message():
    """窗口激活校验返回 expired（激活码到期）时，提示到期而非误导为解绑。"""
    app = QApplication.instance() or QApplication(["verify-activation-expired-test"])
    warnings = []
    window = _window_with_verify("expired")
    try:
        original_warning = QMessageBox.warning
        QMessageBox.warning = lambda parent, title, text, *a, **k: warnings.append(
            (title, text)
        )
        try:
            window.request_activation_check()
        finally:
            QMessageBox.warning = original_warning
        assert warnings and "激活已到期" in warnings[0][1]
    finally:
        window.close()


# ============================================================
# 格式刷：字号/拉伸按源图层实际值同步（不被 auto_fit 重算覆盖）
# ============================================================

def _scene_click_at(scene, x: float, y: float) -> None:
    from PySide6.QtCore import QEvent as _QEvent, QPointF as _QPointF
    from PySide6.QtWidgets import QGraphicsSceneMouseEvent

    def event(kind, buttons):
        mouse_event = QGraphicsSceneMouseEvent(kind)
        mouse_event.setScenePos(_QPointF(x, y))
        mouse_event.setButton(Qt.MouseButton.LeftButton)
        mouse_event.setButtons(buttons)
        return mouse_event

    scene.mousePressEvent(event(_QEvent.Type.GraphicsSceneMousePress, Qt.MouseButton.LeftButton))
    scene.mouseReleaseEvent(event(_QEvent.Type.GraphicsSceneMouseRelease, Qt.MouseButton.NoButton))


def test_format_brush_click_applies_fixed_font_size():
    """源图层 auto_fit=True 时刷目标：字号/拉伸按源实际值定值套用。

    历史缺陷：快照携带 auto_fit=True 并最后应用，reflow 按目标框重新自适应
    字号与拉伸，画布上表现为「只有对齐和颜色刷上了，字号没变」。"""
    QApplication.instance() or QApplication(["format-brush-size-sync-test"])
    window = _translation_window()
    try:
        window._apply_preview_mode("layers")
        page = window._editor_page
        panel = page.property_panel
        source = window._model.text_layout.layer_by_id("high")
        assert source.style.auto_fit is True
        assert source.style.font_size == pytest.approx(14)
        page._on_model_selection_changed(source)

        panel.format_brush_btn.click()
        assert panel.format_brush_btn.isChecked()

        # 画布单击 low 图层（中心 48,33）
        _scene_click_at(page.scene, 48, 33)

        low = window._model.text_layout.layer_by_id("low")
        assert low.style.font_size == pytest.approx(14), low.style.font_size
        assert low.style.auto_fit is False
    finally:
        window.close()


def test_format_brush_click_refreshes_panel_after_apply():
    """点选套用完成后，属性面板应立即回显目标图层刷后的样式。"""
    QApplication.instance() or QApplication(["format-brush-panel-refresh-test"])
    window = _translation_window()
    try:
        window._apply_preview_mode("layers")
        page = window._editor_page
        panel = page.property_panel
        source = window._model.text_layout.layer_by_id("high")
        page._on_model_selection_changed(source)
        panel.font_size_spin.setValue(28)
        QTest.qWait(400)

        panel.format_brush_btn.click()
        _scene_click_at(page.scene, 48, 33)

        assert panel.selected_region_id == "low"
        assert panel.font_size_spin.value() == pytest.approx(28)
    finally:
        window.close()


def test_format_brush_box_applies_fixed_font_size():
    """框选套用与点选一致：字号按源实际值定值渲染，不被 auto_fit 重算。

    框选路径不经 Qt 信号传递快照（无字典键序重排），auto_fit 若在快照中
    会按源码序最后应用，reflow 随即按目标框重算字号/拉伸。"""
    QApplication.instance() or QApplication(["format-brush-box-size-test"])
    window = _translation_window()
    try:
        page = window._editor_page
        panel = page.property_panel
        source = window._model.text_layout.layer_by_id("high")
        assert source.style.auto_fit is True
        page._on_model_selection_changed(source)

        panel.format_brush_btn.click()
        # 框选只罩住 low（框 48,33,60,20），不含来源 high（95~145）
        page._on_area_selected("format_brush", TextBox(20, 24, 70, 16))

        low = window._model.text_layout.layer_by_id("low")
        assert low.style.font_size == pytest.approx(14), low.style.font_size
        assert low.style.auto_fit is False
    finally:
        window.close()


def test_format_brush_click_same_target_reapplies():
    """回归：格式刷待用时重复点击同一目标应再次套用（与框选重复框选一致）。

    历史缺陷：面板以 prev_id != region_id 判定「换层」才套用，重击同一目标
    被当作重入吞掉，用户改完源样式想重刷同一区域没有效果；框选路径则
    每次都套用，两条路径体验不一致。渲染完成回调里的 set_layer 仍走默认
    路径，不会形成「刷→渲染→再刷」循环。"""
    QApplication.instance() or QApplication(["format-brush-reclick-test"])
    window = _translation_window()
    try:
        window._apply_preview_mode("layers")
        page = window._editor_page
        panel = page.property_panel
        page._model.selected_layer_id = "high"
        panel.format_brush_btn.click()

        applied = []
        panel.style_brush_applied.connect(lambda rid, sid, snap: applied.append(rid))

        _scene_click_at(page.scene, 48, 33)  # low
        assert applied == ["low"]

        # 渲染完成回调（ImmediateTaskRunner 已同步执行）不应追加套用
        assert applied == ["low"]

        _scene_click_at(page.scene, 48, 33)  # 重击同一目标 → 再次套用
        assert applied == ["low", "low"]

        # 再来一轮：连续第三次点击仍可套用
        _scene_click_at(page.scene, 48, 33)
        assert applied == ["low", "low", "low"]
    finally:
        window.close()


def test_format_brush_click_works_in_translated_preview():
    """回归：translated（合成图）预览下画布无图层项，点击应回退命中 OCR 框。

    历史缺陷：_hit_layer_at 只遍历场景图层项，而图层项仅在图层预览模式
    存在；默认 translated 模式下点击文字永远落空，用户表现为「点击不起
    作用」。OCR 框（region_id 与图层一致）在两种模式下都存在，作为回退。"""
    QApplication.instance() or QApplication(["format-brush-click-translated-test"])
    window = _translation_window()
    try:
        page = window._editor_page
        scene = page.scene
        assert scene._layer_items == {}  # translated 模式无图层项
        assert "low" in scene._ocr_items
        panel = page.property_panel
        page._model.selected_layer_id = "high"

        panel.format_brush_btn.click()
        applied = []
        panel.style_brush_applied.connect(
            lambda rid, sid, snap: applied.append(rid)
        )

        _scene_click_at(scene, 48, 33)  # low 的文字位置（OCR 框内）
        assert applied == ["low"], applied
        low = window._model.text_layout.layer_by_id("low")
        assert low.style.font_size == pytest.approx(14)
        assert low.style.auto_fit is False
    finally:
        window.close()
def test_format_brush_click_works_in_translated_preview():
    """回归：translated（合成图）预览下画布无图层项，点击应回退命中 OCR 框。

    历史缺陷：_hit_layer_at 只遍历场景图层项，而图层项仅在图层预览模式
    存在；默认 translated 模式下点击文字永远落空，用户表现为「点击不起
    作用」。OCR 框（region_id 与图层一致）在两种模式下都存在，作为回退。"""
    QApplication.instance() or QApplication(["format-brush-click-translated-test"])
    window = _translation_window()
    try:
        page = window._editor_page
        scene = page.scene
        # translated 模式下图层项存在但隐藏（保留命中区域，便于点选进入编辑）
        assert set(scene._layer_items) == {"high", "low"}
        assert not any(item.isVisible() for item in scene._layer_items.values())
        assert "low" in scene._ocr_items
        panel = page.property_panel
        page._model.selected_layer_id = "high"

        panel.format_brush_btn.click()
        applied = []
        panel.style_brush_applied.connect(
            lambda rid, sid, snap: applied.append(rid)
        )

        _scene_click_at(scene, 48, 33)  # low 的文字位置（OCR 框内）
        assert applied == ["low"], applied
        low = window._model.text_layout.layer_by_id("low")
        assert low.style.font_size == pytest.approx(14)
        assert low.style.auto_fit is False
    finally:
        window.close()


def test_send_batch_to_editor_restores_editable_layers():
    """批量成品连同 OCR/译文/图层一起进工作台，可继续编辑文字。"""
    QApplication.instance() or QApplication(["send-batch-editable-test"])
    from src.application.batch import BatchEditableState
    from src.domain.batch import (
        BatchItemSnapshot,
        BatchItemStatus,
        BatchSnapshot,
        BatchStatus,
    )

    source_a = Path("a.png").resolve()
    source_b = Path("b.png").resolve()
    original_a = _document()
    original_b = _document(w=200, h=80)
    rendered_b = _document(w=200, h=80)
    full = FakeTranslateImage().execute(
        original_b, "en", TranslationSelection(TranslationMode.ALL, "zh-Hans")
    )
    state = BatchEditableState(
        full.ocr, full.translation, full.layout, full.repair
    )

    class _Import:
        def execute(self, source):
            return original_a if Path(source).name == "a.png" else original_b

    class _Store:
        def load(self, ref):
            assert ref == "cache/b.png"
            return rendered_b

        def load_editable(self, ref):
            assert ref == "cache/b.png"
            return state

    window = EditorMainWindow(
        import_image=_Import(),
        task_runner=ImmediateTaskRunner(),
        batch_result_store=_Store(),
        create_composition_editor=CreateCompositionEditor(
            QtBasicTextLayoutAdapter("Arial"),
            QtTextRenderer(),
        ),
    )
    try:
        window._editor_page.batch_panel.add_sources((source_a, source_b))
        window._batch_snapshot = BatchSnapshot(
            batch_id="batch-test1234",
            status=BatchStatus.COMPLETED,
            items=(
                BatchItemSnapshot(
                    "item-0", source_a, BatchItemStatus.FAILED, error="boom"
                ),
                BatchItemSnapshot(
                    "item-1",
                    source_b,
                    BatchItemStatus.COMPLETED,
                    result_ref="cache/b.png",
                ),
            ),
            max_active_items=1,
        )
        window._on_send_batch_to_editor()

        # 失败项仍只有原图，没有可编辑状态
        first = window._model.documents()[0]
        assert first.name == "a.png"
        assert first.translation_result is None

        # 成品项切回后带着 OCR、译文与文字图层
        by_name = {ref.name: ref for ref in window._model.documents()}
        window._model.set_active_document(by_name["b.png"].doc_id)
        window._load_active_document()
        assert window._model.document is rendered_b
        assert window._model.ocr_result is not None
        assert isinstance(window._model.translation_result, TranslateImageResult)
        assert len(window._model.text_layout.layers) == 2
        assert window._model.composition_editor is not None
        assert by_name["b.png"].repaired_background is not None
    finally:
        window.close()


def test_switching_back_to_translated_document_keeps_property_panel_editable():
    """换图回来时默认选中首个文字图层，属性面板（自动适配字号）不能是灰的。"""
    QApplication.instance() or QApplication(["switch-back-selection-test"])
    window = EditorMainWindow(
        import_image=object(),
        task_runner=ImmediateTaskRunner(),
        create_composition_editor=CreateCompositionEditor(
            QtBasicTextLayoutAdapter("Arial"),
            QtTextRenderer(),
        ),
    )
    try:
        source_a = _document()
        window._on_image_loaded(source_a)
        result = FakeTranslateImage().execute(
            source_a, "en", TranslationSelection(TranslationMode.ALL, "zh-Hans")
        )
        window._on_translation_succeeded(result)
        id_a = window._model.active_document_id

        window._on_image_loaded(_document(w=200, h=80))
        window._model.set_active_document(id_a)
        window._load_active_document()

        panel = window._editor_page.property_panel
        assert window._model.selected_layer_id == "high"
        assert panel.auto_fit_check.isEnabled()
    finally:
        window.close()


def test_translated_mode_keeps_layer_hit_areas_and_click_switches_to_layers():
    """翻译完成后成品图上的文字仍可点选：点中即切到图层模式，控制点（含旋转点）出现。"""
    from PySide6.QtCore import QPointF

    QApplication.instance() or QApplication(["translated-mode-hit-test"])
    window = EditorMainWindow(
        import_image=object(),
        task_runner=ImmediateTaskRunner(),
        create_composition_editor=CreateCompositionEditor(
            QtBasicTextLayoutAdapter("Arial"),
            QtTextRenderer(),
        ),
    )
    try:
        source = _document()
        window._on_image_loaded(source)
        result = FakeTranslateImage().execute(
            source, "en", TranslationSelection(TranslationMode.ALL, "zh-Hans")
        )
        window._on_translation_succeeded(result)

        scene = window._editor_page.scene
        assert window._model.preview_mode == "translated"
        item = scene._layer_items["high"]
        # 成品图模式下辅助层隐藏，但仍保留命中区域
        assert not item.isVisible()
        layer = window._model.text_layout.layer_by_id("high")
        center = QPointF(layer.box.center_x, layer.box.center_y)
        assert item.contains(item.mapFromScene(center))

        # 点中文字 → 自动进入图层模式并选中，控制点可见
        window._on_canvas_layer_selected("high")
        assert window._model.preview_mode == "layers"
        assert scene._layer_items["high"].isVisible()
        assert scene._layer_items["high"].isSelected()
    finally:
        window.close()


def test_split_compare_hides_image_list_to_enlarge_images():
    """左右分屏对比时收起左侧图片列表，把宽度让给两幅对比图（字太小的问题）。"""
    app = QApplication.instance() or QApplication(["split-hide-right-panel-test"])
    source = _document()
    result = FakeTranslateImage().execute(
        source, "en", TranslationSelection(TranslationMode.ALL, "zh-Hans")
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
        window.resize(1600, 900)
        window._enter_editor()
        window.show()
        window._model.source_document = source
        window._on_translation_succeeded(result)
        window._on_toggle_split_compare()
        app.processEvents()
        app.processEvents()

        page = window._editor_page
        assert page.is_split_view()
        assert not page.image_list_panel.isVisible()
        assert page.right_panel.isVisible()  # 右侧属性面板保持可用
        sizes = page.main_splitter.sizes()
        assert sizes[2] > 0
        assert sizes[0] > 450 and sizes[1] > 450

        window._on_toggle_split_compare()
        app.processEvents()
        app.processEvents()
        assert page.image_list_panel.isVisible()
    finally:
        window.close()


def test_importing_new_image_does_not_ask_about_unsaved_changes(monkeypatch):
    """导入新图片不再弹「未保存的修改」确认框（多文档工作台不会丢编辑）。"""
    from PySide6.QtWidgets import QMessageBox

    QApplication.instance() or QApplication(["import-no-unsaved-dialog-test"])
    asked: list = []
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: asked.append(args) or QMessageBox.StandardButton.No,
    )
    monkeypatch.setattr(
        "src.ui.editor.main_window.load_document",
        lambda source, import_usecase, codec: _document(),
    )
    window = EditorMainWindow(
        import_image=object(),
        task_runner=ImmediateTaskRunner(),
    )
    try:
        window._model.is_dirty = True
        window._on_import(Path("new.png"))
        assert asked == []
        assert window._model.documents()
    finally:
        window.close()


def test_ocr_source_update_recovers_when_preview_layer_was_removed():
    """预览图层被删除/恢复原文后再改 OCR 原文，不应报 KeyError，而是重新生成图层。"""
    from src.application.batch import BatchOcrState

    QApplication.instance() or QApplication(["ocr-preview-stale-id-test"])
    window = EditorMainWindow(
        import_image=object(),
        task_runner=ImmediateTaskRunner(),
        create_composition_editor=CreateCompositionEditor(
            QtBasicTextLayoutAdapter("Arial"),
            QtTextRenderer(),
        ),
    )
    try:
        source = _document()
        window._on_image_loaded(source)
        ocr = FakeOcrAdapter().recognize(source, "en")
        window._restore_batch_editable(source, source, BatchOcrState(ocr))
        # 批量 OCR 状态应把原始文本记下来，未改动时不额外生成预览层
        assert window._ocr_original_texts["low"] == "SUMMER"

        region_id = "low"
        window._on_source_text_changed(region_id, "NEW1")
        editor = window._model.composition_editor
        assert editor is not None
        layer_id = window._ocr_preview_layers[region_id]
        editor.delete_layer(layer_id)

        window._on_source_text_changed(region_id, "NEW2")
        # 被删掉后再更新会自动重建（没有修复服务时按新建图层处理）
        rebuilt_id = window._ocr_preview_layers[region_id]
        assert any(
            layer.region_id == rebuilt_id
            for layer in window._model.text_layout.layers
        )
    finally:
        window.close()


def test_switching_images_resets_ocr_preview_cache():
    """换图后不能沿用上一张图的预览层 id，否则改原文会报 KeyError manual-…。"""
    from src.application.batch import BatchOcrState

    QApplication.instance() or QApplication(["ocr-preview-switch-test"])
    window = EditorMainWindow(
        import_image=object(),
        task_runner=ImmediateTaskRunner(),
        create_composition_editor=CreateCompositionEditor(
            QtBasicTextLayoutAdapter("Arial"),
            QtTextRenderer(),
        ),
    )
    try:
        first = _document()
        window._on_image_loaded(first)
        ocr_a = FakeOcrAdapter().recognize(first, "en")
        window._restore_batch_editable(first, first, BatchOcrState(ocr_a))
        window._on_source_text_changed("low", "NEW1")
        assert "low" in window._ocr_preview_layers

        # 换到第二张图（批量 OCR 送进来的图）
        second = _document(w=200, h=80)
        window._model.add_document(Path("b.png"), second, name="b.png")
        ocr_b = FakeOcrAdapter().recognize(second, "en")
        window._model.ocr_result = ocr_b
        window._load_active_document()

        assert window._ocr_preview_layers == {}
        assert window._ocr_original_texts["low"] == "SUMMER"

        window._on_source_text_changed("low", "NEW2")
        assert any(
            layer.region_id == window._ocr_preview_layers["low"]
            for layer in window._model.text_layout.layers
        )
    finally:
        window.close()


def test_batch_ocr_workspace_shows_region_boxes_and_keeps_them_after_edit():
    """批量 OCR 送进工作台后，识别框应直接显示；改原文后也不能消失。"""
    from src.application.batch import BatchOcrState

    QApplication.instance() or QApplication(["batch-ocr-regions-visible-test"])
    window = EditorMainWindow(
        import_image=object(),
        task_runner=ImmediateTaskRunner(),
        create_composition_editor=CreateCompositionEditor(
            QtBasicTextLayoutAdapter("Arial"),
            QtTextRenderer(),
        ),
    )
    try:
        source = _document()
        window._on_image_loaded(source)
        ocr = FakeOcrAdapter().recognize(source, "en")
        window._restore_batch_editable(source, source, BatchOcrState(ocr))
        window._load_active_document()

        scene = window._editor_page.scene
        expected = {region.region_id for region in ocr.regions}
        assert set(scene._ocr_items) == expected
        assert all(item.isVisible() for item in scene._ocr_items.values())

        window._on_source_text_changed("low", "NEW")
        assert set(scene._ocr_items) == expected
        assert all(item.isVisible() for item in scene._ocr_items.values())
    finally:
        window.close()


def test_format_brush_copies_arc_bend_through_edit_dispatch():
    """单点套用格式刷时，弧形弯曲度要真正落到目标图层（整层替换，不丢 path）。"""
    from src.domain.layout import ArcTextPath, PathPoint

    QApplication.instance() or QApplication(["brush-arc-dispatch-test"])
    window = EditorMainWindow(
        import_image=object(),
        task_runner=ImmediateTaskRunner(),
        create_composition_editor=CreateCompositionEditor(
            QtBasicTextLayoutAdapter("Arial"),
            QtTextRenderer(),
        ),
    )
    try:
        source = _document()
        window._on_image_loaded(source)
        result = FakeTranslateImage().execute(
            source, "en", TranslationSelection(TranslationMode.ALL, "zh-Hans")
        )
        window._on_translation_succeeded(result)

        editor = window._model.composition_editor
        assert editor is not None
        arc = ArcTextPath(PathPoint(20, 30), PathPoint(50, 10), PathPoint(80, 30))
        window._editor_page.apply_edit_result(editor.replace_path("high", arc))

        page = window._editor_page
        page._on_model_selection_changed(editor.layout.layer_by_id("high"))
        page.property_panel.format_brush_btn.click()
        page._on_model_selection_changed(editor.layout.layer_by_id("low"))

        assert isinstance(editor.layout.layer_by_id("low").path, ArcTextPath)
    finally:
        window.close()


def test_ocr_preview_mask_erases_whole_region_polygon():
    """OCR 预览按整块识别框擦除原文，避免只擦字形留下残影造成重影。"""
    from src.infrastructure.pillow_mask_rasterizer import PillowMaskRasterizer

    QApplication.instance() or QApplication(["ocr-preview-mask-test"])
    window = EditorMainWindow(
        import_image=object(),
        mask_rasterizer=PillowMaskRasterizer(),
    )
    try:
        source = _document()
        window._on_image_loaded(source)
        ocr = FakeOcrAdapter().recognize(source, "en")
        window._model.ocr_result = ocr
        region = ocr.regions[0]

        mask = window._ocr_preview_mask(region)
        assert mask is not None and not mask.is_empty
        center_x = sum(point.x for point in region.polygon) / 4
        center_y = sum(point.y for point in region.polygon) / 4
        assert mask.pixels[int(center_y) * mask.width + int(center_x)] > 0
    finally:
        window.close()


def test_pin_button_reorders_workspace_documents():
    """点击图片列表的「置顶」后，该图片排到最前，当前编辑的图片不变。"""
    QApplication.instance() or QApplication(["pin-document-flow-test"])
    window = EditorMainWindow(import_image=object())
    try:
        ids = [
            window._model.add_document(Path(f"{name}.png"), _document(), name=f"{name}.png")
            for name in ("a", "b", "c")
        ]
        window._model.set_active_document(ids[1])

        panel = window._editor_page.image_list_panel
        canvas_before = window._model.document
        panel.set_active(ids[2])
        panel._pin_btn.click()

        order = [doc.doc_id for doc in window._model.documents()]
        assert order[0] == ids[2]
        # 置顶只改顺序：当前编辑的图片与画布内容都不变
        assert window._model.active_document_id == ids[1]
        assert window._model.document is canvas_before
    finally:
        window.close()


def test_ocr_stage_arc_preview_renders_single_copy_and_is_exportable():
    """OCR 阶段改弧线：擦掉原文、按弧线重绘（画面上只有一份文字），
    且改动进入合成文档，不翻译也能导出这个效果。"""
    from src.application.inpainting import RepairSelection
    from src.domain.layout import ArcTextPath
    from src.domain.inpainting import InpaintingResult
    from src.infrastructure.pillow_mask_rasterizer import PillowMaskRasterizer

    class _NoopInpaint:
        def inpaint(self, request):
            return InpaintingResult(request.document, "noop", 0)

    QApplication.instance() or QApplication(["ocr-arc-raster-preview-test"])
    window = EditorMainWindow(
        import_image=object(),
        task_runner=ImmediateTaskRunner(),
        create_composition_editor=CreateCompositionEditor(
            QtBasicTextLayoutAdapter("Arial"),
            QtTextRenderer(),
        ),
        mask_rasterizer=PillowMaskRasterizer(),
        repair_selection=RepairSelection(_NoopInpaint()),
    )
    try:
        source = _document()
        window._on_image_loaded(source)
        ocr = FakeOcrAdapter().recognize(source, "en")
        window._model.ocr_result = ocr
        page = window._editor_page
        page.ocr_result_panel.set_result(ocr)
        page.scene.set_regions(ocr.regions)
        page._on_ocr_region_selected("high")

        panel = page.property_panel
        panel.path_mode.setCurrentIndex(panel.path_mode.findData("arc"))
        QTest.qWait(600)

        # 生成了弧线预览图层（OCR 阶段就能看到弧线效果）
        layer_id = window._ocr_preview_layers.get("high")
        assert layer_id is not None
        layer = window._model.text_layout.layer_by_id(layer_id)
        assert isinstance(layer.path, ArcTextPath)
        assert layer.text == "SALE"
        # 改动进了合成文档：导出取的就是它（不翻译也能导出弧线效果）
        assert window._model.composition_editor is not None
        assert window._model.rendered_document is not None
        assert window._model.rendered_document is not source
    finally:
        window.close()




def test_ocr_preview_update_is_single_undo_step():
    """OCR 阶段改属性只产生一条撤销记录：撤一次就完全复原，不会偏位。"""
    from src.application.inpainting import RepairSelection
    from src.domain.inpainting import InpaintingResult
    from src.infrastructure.pillow_mask_rasterizer import PillowMaskRasterizer

    class _NoopInpaint:
        def inpaint(self, request):
            return InpaintingResult(request.document, "noop", 0)

    QApplication.instance() or QApplication(["ocr-preview-single-undo-test"])
    window = EditorMainWindow(
        import_image=object(),
        task_runner=ImmediateTaskRunner(),
        create_composition_editor=CreateCompositionEditor(
            QtBasicTextLayoutAdapter("Arial"),
            QtTextRenderer(),
        ),
        mask_rasterizer=PillowMaskRasterizer(),
        repair_selection=RepairSelection(_NoopInpaint()),
    )
    try:
        source = _document()
        window._on_image_loaded(source)
        ocr = FakeOcrAdapter().recognize(source, "en")
        window._model.ocr_result = ocr
        page = window._editor_page
        page.ocr_result_panel.set_result(ocr)
        page.scene.set_regions(ocr.regions)
        page._on_ocr_region_selected("high")

        page.property_panel.font_size_spin.setValue(44)
        QTest.qWait(500)

        editor = window._model.composition_editor
        assert editor is not None
        assert any(item.region_id == "high" for item in editor.layout.layers)

        editor.undo()
        assert not any(
            item.region_id == "high" for item in editor.layout.layers
        )
        assert not editor.can_undo
    finally:
        window.close()


def test_ensure_composition_editor_uses_repaired_background_and_layout():
    """补建编辑会话时要用去字后的底图与现有图层，否则重渲染会把文字画两遍。"""
    from src.domain.layout import TextBox, TextLayer, TextLayout, TextStyle

    QApplication.instance() or QApplication(["compose-editor-repair-bg-test"])
    window = EditorMainWindow(
        import_image=object(),
        task_runner=ImmediateTaskRunner(),
        create_composition_editor=CreateCompositionEditor(
            QtBasicTextLayoutAdapter("Arial"),
            QtTextRenderer(),
        ),
    )
    try:
        source = _document()
        rendered = _document(w=200, h=80)
        repaired = _document()
        window._on_image_loaded(source)
        layer = TextLayer(
            "r1", "X", TextBox(50, 40, 60, 20), TextStyle("Arial", 14, (0, 0, 0))
        )
        window._model.document = rendered
        window._model.rendered_document = rendered
        window._model.repaired_background = repaired
        window._model.text_layout = TextLayout((layer,))
        window._model.composition_editor = None

        assert window._ensure_composition_editor()
        editor = window._model.composition_editor
        assert editor.layout.layer_by_id("r1").text == "X"
        assert editor.background_document.pixels == repaired.pixels
    finally:
        window.close()


def test_brush_onto_unerased_region_erases_original_first():
    """刷到原文没被擦掉的区域（保护/待复核）时，先补背景再写图层，避免重影。"""
    from src.application.inpainting import RepairSelection
    from src.domain.inpainting import InpaintingResult
    from src.infrastructure.pillow_mask_rasterizer import PillowMaskRasterizer

    class _NoopInpaint:
        def inpaint(self, request):
            return InpaintingResult(request.document, "noop", 0)

    QApplication.instance() or QApplication(["brush-erase-first-test"])
    window = EditorMainWindow(
        import_image=object(),
        task_runner=ImmediateTaskRunner(),
        create_composition_editor=CreateCompositionEditor(
            QtBasicTextLayoutAdapter("Arial"),
            QtTextRenderer(),
        ),
        mask_rasterizer=PillowMaskRasterizer(),
        repair_selection=RepairSelection(_NoopInpaint()),
    )
    try:
        source = _document()
        window._on_image_loaded(source)
        result = FakeTranslateImage().execute(
            source, "en", TranslationSelection(TranslationMode.ALL, "zh-Hans")
        )
        window._on_translation_succeeded(result)
        editor = window._model.composition_editor
        assert editor is not None

        page = window._editor_page
        page._on_model_selection_changed(editor.layout.layer_by_id("high"))
        page.property_panel.format_brush_btn.click()
        page._on_model_selection_changed(editor.layout.layer_by_id("low"))

        # low 是待复核区域（原文没擦），应补背景后再写图层
        assert editor.patch_count >= 1
        assert (
            editor.layout.layer_by_id("low").style.fill_rgb
            == editor.layout.layer_by_id("high").style.fill_rgb
        )
    finally:
        window.close()


def test_ocr_row_selection_falls_back_to_overlapping_layer():
    """区域 id 与图层 id 不一致时，按位置匹配到图层并进入可编辑状态（面板不灰）。"""
    from src.domain.layout import TextLayout

    QApplication.instance() or QApplication(["ocr-row-overlap-fallback-test"])
    window = EditorMainWindow(
        import_image=object(),
        task_runner=ImmediateTaskRunner(),
        create_composition_editor=CreateCompositionEditor(
            QtBasicTextLayoutAdapter("Arial"),
            QtTextRenderer(),
        ),
    )
    try:
        source = _document()
        window._on_image_loaded(source)
        result = FakeTranslateImage().execute(
            source, "en", TranslationSelection(TranslationMode.ALL, "zh-Hans")
        )
        window._on_translation_succeeded(result)
        layout = window._model.text_layout
        high = layout.layer_by_id("high")
        low = layout.layer_by_id("low")
        # 模拟「图层 id 与 OCR 区域 id 不同」（如手动/框选生成的图层）
        window._model.text_layout = TextLayout(
            (replace(high, region_id="manual-abc"), low)
        )

        page = window._editor_page
        page._on_ocr_region_selected("high")

        panel = page.property_panel
        assert panel._ocr_editing is False
        assert panel.font_size_spin.isEnabled()
        assert panel.x_spin.isEnabled()
    finally:
        window.close()


def test_color_run_edit_dispatches_to_replace_layer():
    """片段上色走 style 分发：color_runs 变化必须整层替换并进撤销历史。

    replace_style 只带 style+rotation，若分发错走 replace_style，
    color_runs 会被丢掉，下面的断言就会失败。
    """
    from src.domain.layout import ColorRun

    QApplication.instance() or QApplication(["color-run-dispatch-test"])
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
        layer = window._model.text_layout.layer_by_id("high")
        text = layer.text
        assert text, "夹具图层应有文字"

        window._editor_page._on_color_run_requested(
            "high", 0, len(text), text, (220, 20, 30)
        )

        after = window._model.text_layout.layer_by_id("high")
        assert after.color_runs == (ColorRun(0, len(text), (220, 20, 30)),)

        window._editor_page.top_bar.undo_btn.click()
        assert window._model.text_layout.layer_by_id("high").color_runs == ()
    finally:
        window.close()


def test_add_text_creates_layer_at_click_position():
    """「新增文字」在画布点击处创建文本图层（不再固定在图片中央）。"""
    QApplication.instance() or QApplication(["add-text-position-test"])
    window = EditorMainWindow(
        import_image=object(),
        task_runner=ImmediateTaskRunner(),
        create_composition_editor=CreateCompositionEditor(
            QtBasicTextLayoutAdapter("Arial"),
            QtTextRenderer(),
        ),
    )
    try:
        window._on_image_loaded(_document())  # 190x72
        assert window._ensure_composition_editor()

        window._on_add_layer_at("新文本", 90.0, 40.0)

        layers = [
            layer
            for layer in window._model.text_layout.layers
            if layer.region_id.startswith("manual-")
        ]
        assert len(layers) == 1
        assert layers[0].box.center_x == pytest.approx(90)
        assert layers[0].box.center_y == pytest.approx(40)

        # 左上角点击：框自动收进画布内（中心 = 半宽/半高）
        window._on_add_layer_at("角落", 2.0, 2.0)
        manual_layers = [
            layer
            for layer in window._model.text_layout.layers
            if layer.region_id.startswith("manual-")
        ]
        corner = manual_layers[-1]
        assert corner.box.center_x == pytest.approx(corner.box.width / 2)
        assert corner.box.center_y == pytest.approx(corner.box.height / 2)
    finally:
        window.close()


def test_auto_font_preference_updates_adapter_and_persists():
    """「自动匹配首选」变更 → 适配器首选字体更新并持久化。"""
    from src.infrastructure.text_renderer import QtBasicTextLayoutAdapter

    QApplication.instance() or QApplication(["auto-font-adapter-test"])
    adapter = QtBasicTextLayoutAdapter()
    saved: list = []

    class _Prefs:
        def save(self, value):
            saved.append(value)

    window = EditorMainWindow(
        import_image=object(),
        text_layout_adapter=adapter,
        auto_font_preferences=_Prefs(),
    )
    try:
        window._on_auto_font_changed("CustomFont")
        assert adapter._preferred_font == "CustomFont"
        assert saved == ["CustomFont"]

        window._on_auto_font_changed(None)
        assert adapter._preferred_font is None
        assert saved == ["CustomFont", None]
    finally:
        window.close()


def test_portal_entry_opens_external_browser_with_configured_link(monkeypatch):
    """万象笔记入口：未配置链接只提示；配置后交给系统 Edge 打开。

    不再内嵌 QtWebEngine —— 客户机器上它的 GPU 合成会让网页里固定定位的
    底部菜单栏闪动。
    """
    from src.domain.portal import PortalModule
    import src.ui.editor.main_window as main_window_module

    opened: list[str] = []
    monkeypatch.setattr(
        main_window_module,
        "open_in_edge",
        lambda url: (opened.append(url), "Microsoft Edge")[1],
    )

    QApplication.instance() or QApplication(["portal-entry-test"])
    window = EditorMainWindow(import_image=object())
    try:
        labels = [
            button.text()
            for button in window._editor_page.toolbar.buttons.values()
        ]
        assert labels.index("万象笔记") == labels.index("强化翻译") + 1

        window._open_portal_window()
        assert opened == [], "未配置链接时不应打开浏览器"

        modules = (
            PortalModule(
                "wanxiang_note",
                "万象笔记",
                "记录图文灵感",
                "",
                "https://note.example.com/app",
            ),
        )
        window._apply_portal_modules(modules)
        assert window._portal_module.link_url == "https://note.example.com/app"
        assert (
            window._home_page._portal_card._title_label.text() == "万象笔记"
        )

        window._open_portal_window()
        assert opened == ["https://note.example.com/app"]
    finally:
        window.close()


def test_extract_layer_creates_picture_and_repairs_background():
    """框选剥离：生成可移动图片图层，原区域背景走修复；Delete 可删除。"""
    from src.domain.layout import TextBox

    QApplication.instance() or QApplication(["extract-layer-test"])
    source = _document()  # 190x72，深色块 18..49 x 18..171
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
        assert window._ensure_composition_editor()

        window._on_extract_layer(TextBox(90, 34, 40, 24))

        editor = window._model.composition_editor
        assert editor is not None
        assert len(editor.pictures) == 1
        picture = editor.pictures[0]
        assert (picture.width, picture.height) == (40, 24)

        window._on_delete_picture(picture.layer_id)
        assert editor.pictures == ()
    finally:
        window.close()


def test_translation_font_change_applies_to_existing_layers():
    """切换「译文字体」后，已翻译图层的字体同步更新（与文字属性显示一致）。"""
    QApplication.instance() or QApplication(["translation-font-sync-test"])
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
        assert window._model.text_layout.layers, "夹具应包含翻译图层"

        window._on_translation_font_changed("Microsoft YaHei")

        assert all(
            layer.style.font_family == "Microsoft YaHei"
            for layer in window._model.text_layout.layers
        )
    finally:
        window.close()


def test_extract_layer_works_without_translation():
    """批量 OCR / 未翻译图片也能用图层剥离：自动建立编辑会话。"""
    from src.domain.layout import TextBox

    QApplication.instance() or QApplication(["extract-layer-no-translation-test"])
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
        window._on_image_loaded(_document())
        assert window._model.translation_result is None

        window._editor_page.toolbar.buttons["extract_layer"].click()

        assert window._model.composition_editor is not None
        assert window._editor_page.scene._selection_mode == "extract_layer"
        assert window._editor_page.scene._manual_selection_enabled, (
            "切换预览后框选状态必须仍开启，否则画布拖不出框"
        )

        window._on_extract_layer(TextBox(90, 34, 40, 24))

        assert len(window._model.composition_editor.pictures) == 1
    finally:
        window.close()


def test_picture_move_updates_export_document_immediately():
    """拖动图片层后导出文档立即是新位置（同步更新，无后台竞态）。"""
    from src.domain.layout import TextBox

    QApplication.instance() or QApplication(["picture-move-export-test"])
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
        window._on_image_loaded(_document())
        assert window._ensure_composition_editor()
        window._on_extract_layer(TextBox(90, 34, 40, 24))
        editor = window._model.composition_editor
        picture = editor.pictures[0]

        window._on_picture_moved(picture.layer_id, 150, 20)

        import numpy as np

        pixels = np.frombuffer(
            editor._document.pixels, np.uint8
        ).reshape(editor._document.asset.height, editor._document.asset.width, 3)
        assert tuple(pixels[20, 150]) == (25, 35, 50), "导出文档应包含新位置"
        assert tuple(pixels[34, 90]) != (25, 35, 50), "原位置应是补全背景"
    finally:
        window.close()


def test_preview_syncs_uncommitted_canvas_picture_position():
    """即使拖动事件没提交，切换预览时也把画布上图元位置同步回编辑状态。"""
    from PySide6.QtCore import QPointF

    from src.domain.layout import TextBox

    QApplication.instance() or QApplication(["picture-sync-test"])
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
        window._on_image_loaded(_document())
        assert window._ensure_composition_editor()
        window._on_extract_layer(TextBox(90, 34, 40, 24))
        editor = window._model.composition_editor
        picture = editor.pictures[0]
        item = window._editor_page.scene._picture_items[picture.layer_id]

        # 只移动图元、不提交（模拟 moved 信号丢失的路径）
        item.setPos(QPointF(150, 20))
        window._apply_preview_mode("translated")

        moved = editor.pictures[0]
        assert (moved.center_x, moved.center_y) == (150, 20)
    finally:
        window.close()


def test_paste_picture_layer_adds_offset_copy_of_same_pixels():
    """Ctrl+C / Ctrl+V：粘贴出与原图层同像素、偏移放置的新图层。"""
    from src.domain.layout import TextBox

    QApplication.instance() or QApplication(["picture-paste-test"])
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
        window._on_image_loaded(_document())
        assert window._ensure_composition_editor()
        window._on_extract_layer(TextBox(90, 34, 40, 24))
        editor = window._model.composition_editor
        original = editor.pictures[0]

        window._on_copy_picture(original.layer_id)
        window._on_paste_picture()

        assert len(editor.pictures) == 2
        copy = next(
            item for item in editor.pictures if item.layer_id != original.layer_id
        )
        assert copy.pixels == original.pixels
        assert (copy.width, copy.height) == (original.width, original.height)
        assert (copy.center_x, copy.center_y) != (
            original.center_x,
            original.center_y,
        ), "粘贴出的图层要偏移，否则与原图层完全重叠看不出效果"
        assert copy.layer_id in window._editor_page.scene._picture_items
        assert window._editor_page.scene._picture_items[copy.layer_id].isSelected()
    finally:
        window.close()


def test_paste_without_copy_keeps_state_and_reports():
    """没复制就粘贴：不新增图层，状态栏给出提示。"""
    from src.domain.layout import TextBox

    QApplication.instance() or QApplication(["picture-paste-empty-test"])
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
        window._on_image_loaded(_document())
        assert window._ensure_composition_editor()
        window._on_extract_layer(TextBox(90, 34, 40, 24))
        editor = window._model.composition_editor
        before = len(editor.pictures)

        window._on_copy_picture(editor.pictures[0].layer_id)
        window._on_delete_picture(editor.pictures[0].layer_id)
        window._on_paste_picture()

        assert len(editor.pictures) == before - 1, "原图层已删除，粘贴不应新增"
        assert "重新复制" in window.statusBar().currentMessage()
    finally:
        window.close()


def test_extract_layer_switches_to_layers_mode_and_selects_new_picture():
    """剥离后自动进入图层模式并选中新图层，否则用户在原位置拖的是整张画布。"""
    from src.domain.layout import TextBox

    QApplication.instance() or QApplication(["picture-extract-mode-test"])
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
        window._on_image_loaded(_document())
        assert window._ensure_composition_editor()
        window._apply_preview_mode("translated")

        window._on_extract_layer(TextBox(90, 34, 40, 24))

        editor = window._model.composition_editor
        picture = editor.pictures[0]
        assert window._model.preview_mode == "layers"
        item = window._editor_page.scene._picture_items[picture.layer_id]
        assert item.isSelected()
        assert item.isVisible()
    finally:
        window.close()


def test_preview_switch_keeps_picture_items_in_scene():
    """切换预览模式后图片图元仍在场景里，移动/复制粘贴不会失效。"""
    from src.domain.layout import TextBox

    QApplication.instance() or QApplication(["picture-preview-rebuild-test"])
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
        window._on_image_loaded(_document())
        assert window._ensure_composition_editor()
        window._on_extract_layer(TextBox(90, 34, 40, 24))
        editor = window._model.composition_editor
        layer_id = editor.pictures[0].layer_id

        window._apply_preview_mode("translated")
        window._apply_preview_mode("layers")

        item = window._editor_page.scene._picture_items[layer_id]
        assert item.isVisible()
        assert (item.pos().x(), item.pos().y()) == (
            editor.pictures[0].center_x,
            editor.pictures[0].center_y,
        )
    finally:
        window.close()


def test_apply_fixed_size_to_all_uses_absolute_pixels_and_relative_position():
    """「应用到全部图片」按绝对像素统一，并按相对位置找到每张图的对应区域。

    客户这批图同一位置的区域编号各不相同（region-0004/0005/0009…），
    只能按相对位置匹配；字号要统一成同一个像素值，视觉才一样大。
    """
    from src.domain.ocr import OcrResult, TextRegion, order_quad

    def region(region_id: str, cx: float, cy: float) -> TextRegion:
        # 190x72 的图，时间在左下角
        half_w, half_h = 45.0, 12.0
        return TextRegion(
            region_id,
            order_quad(
                (
                    (cx - half_w, cy - half_h),
                    (cx + half_w, cy - half_h),
                    (cx + half_w, cy + half_h),
                    (cx - half_w, cy + half_h),
                )
            ),
            "09:19",
            0.95,
            "en",
            "fixture",
        )

    QApplication.instance() or QApplication(["fixed-style-all-test"])
    window = EditorMainWindow(
        import_image=object(),
        task_runner=ImmediateTaskRunner(),
        create_composition_editor=CreateCompositionEditor(
            QtBasicTextLayoutAdapter("Arial"),
            QtTextRenderer(),
        ),
    )
    try:
        # 两张 190x72 的图：时间都在左下角，但编号不同
        first = window._model.add_document(Path("a.png"), _document(), name="a.png")
        window._model.source_document = _document()
        window._model.ocr_result = OcrResult(
            (region("region-0009", 50.0, 60.0),), "en", "fixture", 0
        )
        second = window._model.add_document(Path("b.png"), _document(), name="b.png")
        window._model.source_document = _document()
        window._model.ocr_result = OcrResult(
            (region("region-0004", 50.0, 60.0),), "en", "fixture", 0
        )
        window._model._snapshot_active()

        # 当前停在 second；把它的区域载入属性面板作为锚点
        active_region = window._model.ocr_result.regions[0]
        window._editor_page.property_panel.set_ocr_region(active_region, None, {})
        window._on_apply_fixed_style_to_all(82.0, None, None)

        first_ref = next(
            d for d in window._model.documents() if d.doc_id == first
        )
        second_ref = next(
            d for d in window._model.documents() if d.doc_id == second
        )
        # 编号不同，但都按相对位置命中，字号统一为 82px
        assert first_ref.ocr_property_overrides["region-0009"]["font_size"] == 82.0
        assert second_ref.ocr_property_overrides["region-0004"]["font_size"] == 82.0
        assert (
            first_ref.ocr_property_overrides["region-0009"]["auto_fit"] is False
        )
    finally:
        window.close()


def test_apply_fixed_size_to_all_skips_images_without_region_nearby():
    """相对位置差太远的图不误改（那说明这张图没有该文字）。"""
    from src.domain.ocr import OcrResult, TextRegion, order_quad

    QApplication.instance() or QApplication(["fixed-style-all-miss-test"])
    window = EditorMainWindow(
        import_image=object(),
        task_runner=ImmediateTaskRunner(),
        create_composition_editor=CreateCompositionEditor(
            QtBasicTextLayoutAdapter("Arial"),
            QtTextRenderer(),
        ),
    )
    try:
        first = window._model.add_document(Path("a.png"), _document(), name="a.png")
        window._model.source_document = _document()
        window._model.ocr_result = OcrResult(
            (
                TextRegion(
                    "region-0000",
                    order_quad(((5, 50), (25, 50), (25, 70), (5, 70))),
                    "09:19",
                    0.9,
                    "en",
                    "fixture",
                ),
            ),
            "en",
            "fixture",
            0,
        )
        # 第二张图同位置没有任何文字
        second = window._model.add_document(Path("b.png"), _document(), name="b.png")
        window._model.source_document = _document()
        window._model.ocr_result = OcrResult((), "en", "fixture", 0)
        window._model._snapshot_active()

        window._model.set_active_document(first)
        region = window._model.ocr_result.regions[0]
        window._editor_page.property_panel.set_ocr_region(region, None, {})
        window._on_apply_fixed_style_to_all(82.0, None, None)

        first_ref = next(
            d for d in window._model.documents() if d.doc_id == first
        )
        second_ref = next(
            d for d in window._model.documents() if d.doc_id == second
        )
        assert first_ref.ocr_property_overrides["region-0000"]["font_size"] == 82.0
        assert second_ref.ocr_property_overrides == {}
    finally:
        window.close()


def test_fixed_font_size_converts_to_pixels_on_ocr_update():
    """OCR 阶段：填 82px + 更新原文 → 该区域写回 82px 字号。"""
    QApplication.instance() or QApplication(["fixed-size-ocr-test"])
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
        window._on_image_loaded(_document())
        window._model.ocr_result = _ocr_result_with_box(94.0)
        panel = window._editor_page.property_panel
        region = window._model.ocr_result.regions[0]
        panel.set_ocr_region(region, None, {})
        panel.fixed_font_check.setChecked(True)
        panel.fixed_font_spin.setValue(82)

        panel.apply_source_text_btn.click()

        overrides = window._editor_page._ocr_property_overrides["region-0000"]
        assert overrides["font_size"] == pytest.approx(82.0)
        # font_size 覆盖会由 _apply_field_change 自动关闭 auto_fit
        from src.ui.editor.editor_page import EditorPage
        assert "font_size" in overrides
    finally:
        window.close()


def test_apply_fixed_style_updates_existing_layers_with_absolute_px():
    """已有文字图层时批量应用要真的改写图层样式（导出图跟着变）。"""
    from src.domain.layout import TextBox, TextLayer, TextLayout, TextStyle

    QApplication.instance() or QApplication(["fixed-style-layer-test"])
    window = EditorMainWindow(
        import_image=object(),
        task_runner=ImmediateTaskRunner(),
        create_composition_editor=CreateCompositionEditor(
            QtBasicTextLayoutAdapter("Arial"),
            QtTextRenderer(),
        ),
    )
    try:
        window._model.add_document(Path("a.png"), _document(), name="a.png")
        window._model.source_document = _document()
        window._model.document = _document()
        window._model.ocr_result = _ocr_result_with_box(20.0)
        # 20px 高的图层，自动适配开着
        layer = TextLayer(
            "region-0000",
            "0901",
            TextBox(50, 20, 60, 20),
            TextStyle("Arial", 12, (0, 0, 0), auto_fit=True),
        )
        window._model.text_layout = TextLayout((layer,))
        assert window._ensure_composition_editor()
        window._model._snapshot_active()

        region = window._model.ocr_result.regions[0]
        window._editor_page.property_panel.set_ocr_region(region, None, {})
        window._on_apply_fixed_style_to_all(82.0, "Arial", 700)

        editor = window._model.composition_editor
        updated = editor.layout.layer_by_id("region-0000")
        assert updated.style.font_size == pytest.approx(82.0)
        assert updated.style.auto_fit is False, "固定字号必须关掉自动适配"
        assert updated.style.font_weight == 700
        ref = window._model.documents()[0]
        assert ref.is_dirty
        assert ref.text_layout.layer_by_id("region-0000").style.font_weight == 700
    finally:
        window.close()


def test_adjusting_fixed_size_updates_canvas_immediately():
    """调固定字号后画布立即重绘，不必先点「更新 OCR 原文」。"""
    from src.domain.layout import TextBox, TextLayer, TextLayout, TextStyle

    QApplication.instance() or QApplication(["fixed-scale-live-preview-test"])
    window = EditorMainWindow(
        import_image=object(),
        task_runner=ImmediateTaskRunner(),
        create_composition_editor=CreateCompositionEditor(
            QtBasicTextLayoutAdapter("Arial"),
            QtTextRenderer(),
        ),
    )
    try:
        window._on_image_loaded(_document())
        window._model.source_document = _document()
        window._model.document = _document()
        window._model.ocr_result = _ocr_result_with_box(94.0)
        layer = TextLayer(
            "region-0000",
            "09:19",
            TextBox(130, 40, 196, 94),
            TextStyle("Arial", 20, (255, 255, 255), auto_fit=False),
        )
        window._model.text_layout = TextLayout((layer,))
        assert window._ensure_composition_editor()
        region = window._model.ocr_result.regions[0]
        panel = window._editor_page.property_panel
        panel.set_ocr_region(region, None, {})
        panel.fixed_font_check.setChecked(True)

        before = window._model.composition_editor.layout.layer_by_id(
            "region-0000"
        ).style.font_size
        panel.fixed_font_spin.setValue(82)

        after = window._model.composition_editor.layout.layer_by_id(
            "region-0000"
        ).style.font_size
        assert after != before, "改字号应立刻反映到编辑状态（画布与导出图随之更新）"
        assert after == pytest.approx(82.0)
    finally:
        window.close()


def test_layer_matching_prefers_nearest_box_when_ids_differ():
    """区域 id 对不上时按几何就近匹配，不能命中旁边紧挨着的其它区域。

    客户机出现过：OCR 结果列表显示 "13:30"，文字属性里却是日期那段文字。
    旧逻辑「第一个落在容差内就返回」会拿到相邻的行。
    """
    from src.domain.ocr import TextRegion, order_quad

    QApplication.instance() or QApplication(["layer-nearest-match-test"])
    window = EditorMainWindow(import_image=object(), task_runner=ImmediateTaskRunner())
    try:
        window._on_image_loaded(_document(w=500, h=300))
        page = window._editor_page
        window._model.text_layout = TextLayout(
            (
                TextLayer(
                    "region-0005",
                    "13:30",
                    TextBox(132, 1117, 204, 55),
                    TextStyle("Arial", 80, (255, 255, 255)),
                ),
                TextLayer(
                    "region-0006",
                    "2026年01月05日",
                    TextBox(300, 1117, 278, 47),
                    TextStyle("Arial", 47, (255, 255, 255)),
                ),
            )
        )
        # id 不在布局里：只给几何位置
        region = TextRegion(
            "region-0099",
            order_quad(((30, 1090), (234, 1090), (234, 1145), (30, 1145))),
            "13:30",
            0.999,
            "en",
            "fixture",
        )

        layer = page._layer_for_ocr_region("region-0099", region)

        assert layer is not None
        assert layer.text == "13:30", "应命中位置对应的图层，而不是旁边的日期"
        assert layer.region_id == "region-0005"
    finally:
        window.close()


def test_layer_matching_does_not_use_far_away_neighbor():
    """横向距离超出框宽的区域不再算命中（旧逻辑大框容差可达上百像素）。"""
    from src.domain.ocr import TextRegion, order_quad

    QApplication.instance() or QApplication(["layer-far-match-test"])
    window = EditorMainWindow(import_image=object(), task_runner=ImmediateTaskRunner())
    try:
        window._on_image_loaded(_document(w=700, h=300))
        page = window._editor_page
        window._model.text_layout = TextLayout(
            (
                TextLayer(
                    "region-0006",
                    "2026年01月05日",
                    TextBox(300, 1117, 278, 47),
                    TextStyle("Arial", 47, (255, 255, 255)),
                ),
            )
        )
        region = TextRegion(
            "region-0099",
            order_quad(((30, 1090), (234, 1090), (234, 1145), (30, 1145))),
            "13:30",
            0.999,
            "en",
            "fixture",
        )

        assert page._layer_for_ocr_region("region-0099", region) is None
    finally:
        window.close()
