import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from src.domain.layout import (
    ArtisticPreset,
    CircularTextPath,
    PathPoint,
    TextBox,
    TextLayer,
    TextStyle,
)
from src.domain.ocr import OcrResult, TextRegion, order_quad
from src.domain.translation import (
    TranslationMode,
    TranslationResult,
    TranslationSelection,
    TranslationStatus,
    TranslationUnit,
)
from src.ui.editor.widgets.ocr_result_panel import OcrResultPanel
from src.ui.editor.widgets.property_panel import PropertyPanel
from src.ui.editor.widgets.translate_controls import TranslateControls


def _region(region_id: str, text: str, confidence: float) -> TextRegion:
    return TextRegion(
        region_id,
        order_quad(((0, 0), (40, 0), (40, 20), (0, 20))),
        text,
        confidence,
        "en",
        "fixture",
    )


def test_ocr_result_panel_searches_and_filters_status() -> None:
    QApplication.instance() or QApplication(["ocr-filter-test"])
    first = _region("one", "Brand Alpha", 0.99)
    second = _region("two", "Small label", 0.70)
    selection = TranslationSelection(TranslationMode.ALL, "zh-Hans")
    translation = TranslationResult(
        (
            TranslationUnit(
                "one", first.text, "en", "zh-Hans", "品牌", TranslationStatus.TRANSLATED
            ),
            TranslationUnit(
                "two",
                second.text,
                "en",
                "zh-Hans",
                second.text,
                TranslationStatus.REVIEW_REQUIRED,
            ),
        ),
        selection,
        "fixture",
        1,
    )
    panel = OcrResultPanel()
    panel.set_result(OcrResult((first, second), "en", "fixture", 1), translation)
    assert panel.tree.topLevelItemCount() == 2
    panel.search_edit.setText("品牌")
    assert panel.tree.topLevelItemCount() == 1
    panel.search_edit.clear()
    panel.status_filter.setCurrentIndex(
        panel.status_filter.findData("review_required")
    )
    assert panel.tree.topLevelItemCount() == 1
    assert panel.tree.topLevelItem(0).text(0) == "Small label"


def test_ocr_result_refresh_preserves_selected_region() -> None:
    QApplication.instance() or QApplication(["ocr-refresh-selection-test"])
    first = _region("one", "First", 0.99)
    second = _region("two", "Second", 0.98)
    panel = OcrResultPanel()
    panel.set_result(OcrResult((first, second), "en", "fixture", 1))
    panel.select_region("two")
    assert panel.tree.currentItem().data(0, Qt.ItemDataRole.UserRole) == "two"

    updated = _region("two", "Edited second", 0.98)
    panel.set_result(OcrResult((first, updated), "en", "fixture", 1))

    current = panel.tree.currentItem()
    assert current is not None
    assert current.data(0, Qt.ItemDataRole.UserRole) == "two"
    assert current.text(0) == "Edited second"


def test_review_region_enables_confirm_and_source_text_edit() -> None:
    QApplication.instance() or QApplication(["review-controls-test"])
    region = _region("review", "uncertain", 0.60)
    unit = TranslationUnit(
        "review",
        region.text,
        "en",
        "zh-Hans",
        region.text,
        TranslationStatus.REVIEW_REQUIRED,
    )
    panel = PropertyPanel()
    panel.set_ocr_region(region, unit)
    assert panel.confirm_review_btn.isEnabled()
    assert panel.retranslate_btn.isEnabled()
    assert panel.keep_original_btn.isEnabled()
    emitted = []
    panel.source_text_changed.connect(
        lambda region_id, text: emitted.append((region_id, text))
    )
    panel.source_text_edit.setPlainText("corrected")
    panel.apply_source_text_btn.click()
    assert emitted == [("review", "corrected")]


def test_ocr_only_region_exposes_editable_text_properties(qtbot) -> None:
    QApplication.instance() or QApplication(["ocr-only-property-test"])
    region = _region("ocr-only", "Detected text", 0.92)
    panel = PropertyPanel()
    qtbot.addWidget(panel)
    panel.set_ocr_region(region)

    assert panel.font_size_spin.isEnabled()
    assert panel.color_button.isEnabled()
    assert panel.x_spin.isEnabled()

    changes = []
    panel.ocr_property_changed.connect(
        lambda region_id, field, value: changes.append((region_id, field, value))
    )
    panel.text_edit.setPlainText("Edited text")
    qtbot.wait(350)
    assert ("ocr-only", "text", "Edited text") in changes
    panel.font_size_spin.setValue(32)
    qtbot.wait(350)
    assert ("ocr-only", "font_size", 32.0) in changes


def test_loading_ocr_region_does_not_emit_edit_signal(qtbot) -> None:
    QApplication.instance() or QApplication(["ocr-only-load-suppression-test"])
    region = _region("ocr-only-load", "Detected text", 0.92)
    panel = PropertyPanel()
    qtbot.addWidget(panel)
    changes = []
    panel.ocr_property_changed.connect(
        lambda region_id, field, value: changes.append((region_id, field, value))
    )

    panel.set_ocr_region(region)
    qtbot.wait(50)

    assert changes == []


def test_ocr_results_expose_explicit_edit_and_region_retranslate_actions() -> None:
    QApplication.instance() or QApplication(["ocr-region-actions-test"])
    region = _region("review", "uncertain", 0.60)
    selection = TranslationSelection(TranslationMode.ALL, "zh-Hans")
    translation = TranslationResult(
        (
            TranslationUnit(
                "review",
                region.text,
                "en",
                "zh-Hans",
                region.text,
                TranslationStatus.REVIEW_REQUIRED,
            ),
        ),
        selection,
        "fixture",
        1,
    )
    panel = OcrResultPanel()
    panel.set_result(OcrResult((region,), "en", "fixture", 1), translation)
    edits = []
    retranslations = []
    panel.edit_region_requested.connect(edits.append)
    panel.retranslate_requested.connect(retranslations.append)

    panel.tree.setCurrentItem(panel.tree.topLevelItem(0))
    assert panel.edit_source_button.isEnabled()
    assert panel.retranslate_button.isEnabled()
    panel.edit_source_button.click()
    panel.retranslate_button.click()

    assert edits == ["review"]
    assert retranslations == ["review"]


def test_protected_ocr_region_cannot_bypass_protection_with_retranslate_button() -> None:
    QApplication.instance() or QApplication(["ocr-protected-action-test"])
    region = _region("protected", "BRAND", 0.99)
    selection = TranslationSelection(TranslationMode.ALL, "zh-Hans")
    translation = TranslationResult(
        (
            TranslationUnit(
                "protected",
                region.text,
                "en",
                "zh-Hans",
                region.text,
                TranslationStatus.SKIPPED_PROTECTED,
            ),
        ),
        selection,
        "fixture",
        1,
    )
    panel = OcrResultPanel()
    panel.set_result(OcrResult((region,), "en", "fixture", 1), translation)
    panel.tree.setCurrentItem(panel.tree.topLevelItem(0))

    assert panel.edit_source_button.isEnabled()
    assert not panel.retranslate_button.isEnabled()


def test_text_style_controls_include_spacing_opacity_and_background() -> None:
    QApplication.instance() or QApplication(["style-controls-test"])
    panel = PropertyPanel()
    layer = TextLayer(
        "layer",
        "hello",
        TextBox(50, 30, 80, 24),
        TextStyle(
            "Arial",
            18,
            (1, 2, 3),
            line_height=1.4,
            letter_spacing=2.5,
            text_opacity=0.7,
            background_rgb=(4, 5, 6),
            background_opacity=0.3,
        ),
    )
    panel.set_layer(layer)
    assert panel.line_height_spin.value() == 1.4
    assert panel.letter_spacing_spin.value() == 2.5
    assert panel.text_opacity_spin.value() == 70
    assert panel.background_opacity_spin.value() == 30


def test_property_panel_round_trips_circle_path_and_artistic_preset() -> None:
    QApplication.instance() or QApplication(["path-controls-test"])
    panel = PropertyPanel()
    layer = TextLayer(
        "circle",
        "hello",
        TextBox(60, 40, 80, 24),
        TextStyle(
            "Arial",
            18,
            (1, 2, 3),
            effect_preset=ArtisticPreset.OUTLINE,
        ),
        path=CircularTextPath(PathPoint(60, 50), 32, 180, 360, True),
    )
    panel.set_image_bounds(200, 160)
    panel.set_layer(layer)
    assert panel.path_mode.currentData() == "circle"
    assert panel.circle_center_x.value() == 60
    assert panel.circle_center_y.value() == 50
    assert panel.circle_radius.value() == 32
    assert panel.circle_start.value() == 180
    assert panel.circle_end.value() == 360
    assert panel.path_reverse.isChecked()
    assert panel.artistic_preset.currentData() == ArtisticPreset.OUTLINE

    emitted = []
    panel.layer_property_changed.connect(
        lambda region_id, field, value: emitted.append((region_id, field, value))
    )
    panel.circle_radius.setValue(40)
    panel._flush_pending()
    assert emitted[-1][0:2] == ("circle", "text_path")
    assert emitted[-1][2]["radius"] == 40


def test_number_protection_is_enabled_by_default_and_user_configurable() -> None:
    QApplication.instance() or QApplication(["number-protection-control-test"])
    controls = TranslateControls()
    try:
        assert controls.preserve_numbers.isEnabled()
        assert controls.should_preserve_numbers
        controls.preserve_numbers.setChecked(False)
        assert not controls.should_preserve_numbers
        controls.set_translating(True)
        assert not controls.preserve_numbers.isEnabled()
        controls.set_translating(False)
        assert controls.preserve_numbers.isEnabled()
    finally:
        controls.close()
