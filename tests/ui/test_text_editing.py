import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtWidgets import QApplication

from src.application.bootstrap import StartupSnapshot
from src.application.composition import CreateCompositionEditor
from src.domain.image import ImageAsset, ImageDocument, ImageFileFormat
from src.domain.inpainting import EraseMask, InpaintingResult, RepairOutcome
from src.domain.job import ImageJob
from src.domain.layout import TextBox, TextLayer, TextLayout, TextStyle
from src.domain.ocr import OcrResult, TextRegion, order_quad
from src.domain.product import ProductInfo
from src.domain.translation import (
    TranslationMode,
    TranslationResult,
    TranslationSelection,
    TranslationStatus,
    TranslationUnit,
)
from src.application.translate_image import TranslateImageResult
from src.infrastructure.text_renderer import QtBasicTextLayoutAdapter, QtTextRenderer
from src.platform.fonts import resolve_system_font
from src.ui.main_window import MainWindow


class ImmediateTaskRunner:
    def submit(self, operation, on_success, on_error) -> None:
        try:
            on_success(operation())
        except Exception as error:
            on_error(error)


def test_window_edits_translation_and_undoes_redoes(tmp_path: Path) -> None:
    application = QApplication.instance() or QApplication(["text-edit-ui-test"])
    asset = ImageAsset(tmp_path / "edit.png", 180, 80, 1, ImageFileFormat.PNG, False, False)
    background = ImageDocument(asset, "RGB", np.full((80, 180, 3), 245, np.uint8).tobytes())
    region = TextRegion(
        "r1",
        order_quad(((25, 22), (155, 22), (155, 54), (25, 54))),
        "SALE",
        0.99,
        "en",
        "fixture",
    )
    ocr = OcrResult((region,), "en", "fixture", 1)
    translation = TranslationResult(
        (TranslationUnit("r1", "SALE", "en", "zh-Hans", "促销", TranslationStatus.TRANSLATED),),
        TranslationSelection(TranslationMode.ALL, "zh-Hans"),
        "fixture",
        1,
    )
    layout = TextLayout(
        (
            TextLayer(
                "r1",
                "促销",
                TextBox(90, 38, 130, 32),
                TextStyle(resolve_system_font("zh-Hans"), 22, (20, 30, 40)),
            ),
        )
    )
    renderer = QtTextRenderer()
    rendered = renderer.render(background, layout)
    repair = RepairOutcome(
        EraseMask(180, 80, bytes(180 * 80)),
        InpaintingResult(background, "fixture", 1),
    )
    factory = CreateCompositionEditor(QtBasicTextLayoutAdapter(), renderer)
    window = MainWindow(
        StartupSnapshot(ProductInfo("图片翻译", "0.1.0", "M2"), tmp_path / "data", tmp_path / "cache"),
        task_runner=ImmediateTaskRunner(),
        create_composition_editor=factory,
    )
    window.show()
    window._workflow_succeeded(
        TranslateImageResult(rendered, ocr, translation, repair, layout, ImageJob())
    )
    assert window.text_edit_panel.layers.count() == 1
    assert window.text_edit_panel.text.toPlainText() == "促销"
    original_rendered = window.current_document.pixels
    window.text_edit_panel.text.setPlainText("夏季新品促销")
    window.request_text_edit()
    application.processEvents()
    assert window.text_edit_panel.text.toPlainText() == "夏季新品促销"
    assert window.current_document.pixels != original_rendered
    assert window.text_edit_panel.undo_button.isEnabled()
    window.request_undo_edit()
    assert window.text_edit_panel.text.toPlainText() == "促销"
    assert window.current_document.pixels == original_rendered
    assert window.text_edit_panel.redo_button.isEnabled()
    window.request_redo_edit()
    assert window.text_edit_panel.text.toPlainText() == "夏季新品促销"
    before_geometry = window.current_document.pixels
    moved = TextBox(110, 48, 95, 24, 12)
    window.request_geometry_edit("r1", moved)
    assert window._composition_editor.layout.layer_by_id("r1").box == moved
    assert window.current_document.pixels != before_geometry
    window.request_undo_edit()
    restored = window._composition_editor.layout.layer_by_id("r1")
    assert restored.text == "夏季新品促销"
    assert restored.box == layout.layer_by_id("r1").box
    window.layer_style_panel.auto_fit.setChecked(False)
    window.layer_style_panel.font_size.setValue(15)
    window.layer_style_panel.stroke_width.setValue(2)
    window.layer_style_panel.shadow_enabled.setChecked(True)
    window.layer_style_panel.shadow_opacity.setValue(60)
    window.layer_style_panel.rotation.setValue(20)
    window.request_style_edit()
    styled = window._composition_editor.layout.layer_by_id("r1")
    assert styled.style.font_size == 15
    assert styled.style.stroke_width == 2
    assert styled.style.shadow_opacity == 0.6
    assert styled.box.rotation_degrees == 20
    window.request_add_layer()
    assert len(window._composition_editor.layout.layers) == 2
    added_id = window.text_edit_panel.selected_region_id
    assert added_id.startswith("manual-")
    window.request_delete_layer()
    assert len(window._composition_editor.layout.layers) == 1
    window.request_undo_edit()
    assert len(window._composition_editor.layout.layers) == 2
    window.close()
