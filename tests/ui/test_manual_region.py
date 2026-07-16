import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from src.application.bootstrap import StartupSnapshot
from src.application.composition import CreateCompositionEditor
from src.application.manual_region import ProcessManualRegion
from src.application.ocr import RecognizeText
from src.application.translation import TranslateRegions
from src.domain.image import ImageAsset, ImageDocument, ImageFileFormat
from src.domain.inpainting import InpaintingRequest, InpaintingResult
from src.domain.layout import TextBox
from src.domain.manual_region import ManualInputMode
from src.domain.ocr import OcrResult
from src.domain.product import ProductInfo
from src.domain.protection import ProtectionEngine
from src.infrastructure.mock_translator import MockTranslationAdapter
from src.infrastructure.pillow_image_cropper import PillowImageCropper
from src.infrastructure.pillow_mask_rasterizer import PillowMaskRasterizer
from src.infrastructure.text_renderer import QtBasicTextLayoutAdapter, QtTextRenderer
from src.ui.image_canvas import ImageCanvas
from src.ui.main_window import MainWindow


class _ImmediateTaskRunner:
    def submit(self, operation, on_success, on_error) -> None:
        try:
            on_success(operation())
        except Exception as error:
            on_error(error)


class _UnusedOcr:
    language_codes = ("en",)

    def recognize(self, document: ImageDocument, language_code: str) -> OcrResult:
        return OcrResult((), language_code, "unused", 0)


class _FillInpaint:
    adapter_id = "ui-fill"

    def inpaint(self, request: InpaintingRequest) -> InpaintingResult:
        pixels = bytearray(request.document.pixels)
        for index, value in enumerate(request.erase_mask.pixels):
            if value:
                pixels[index * 3 : index * 3 + 3] = bytes((90, 90, 90))
        return InpaintingResult(
            ImageDocument(request.document.asset, "RGB", bytes(pixels)),
            self.adapter_id,
            1,
        )


def _document(tmp_path: Path) -> ImageDocument:
    asset = ImageAsset(
        tmp_path / "manual-ui.png",
        120,
        80,
        1,
        ImageFileFormat.PNG,
        False,
        False,
    )
    return ImageDocument(asset, "RGB", bytes([240]) * 120 * 80 * 3)


def _send_mouse(
    canvas: ImageCanvas,
    event_type: QEvent.Type,
    position: QPointF,
    button: Qt.MouseButton,
    buttons: Qt.MouseButton,
) -> None:
    event = QMouseEvent(
        event_type,
        position,
        canvas.mapToGlobal(position.toPoint()),
        button,
        buttons,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(canvas, event)


def test_canvas_emits_manual_selection_in_document_coordinates(tmp_path: Path) -> None:
    application = QApplication.instance() or QApplication(["manual-canvas-ui"])
    canvas = ImageCanvas()
    canvas.resize(600, 400)
    canvas.show()
    canvas.set_document(_document(tmp_path))
    application.processEvents()
    emitted: list[TextBox] = []
    canvas.manual_region_selected.connect(emitted.append)
    canvas.set_manual_selection_enabled(True)
    start = canvas.document_to_view(QPointF(20, 10))
    end = canvas.document_to_view(QPointF(90, 60))
    _send_mouse(canvas, QEvent.Type.MouseButtonPress, start, Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton)
    _send_mouse(canvas, QEvent.Type.MouseMove, end, Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton)
    _send_mouse(canvas, QEvent.Type.MouseButtonRelease, end, Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton)
    assert len(emitted) == 1
    assert emitted[0] == TextBox(55, 35, 70, 50)
    assert not canvas.manual_selection_enabled
    canvas.close()


def test_window_applies_direct_translation_and_undoes_repair_and_layer(tmp_path: Path) -> None:
    application = QApplication.instance() or QApplication(["manual-window-ui"])
    document = _document(tmp_path)
    recognize = RecognizeText(_UnusedOcr())
    translate = TranslateRegions(MockTranslationAdapter(), ProtectionEngine())
    layout = QtBasicTextLayoutAdapter("Arial")
    renderer = QtTextRenderer()
    processor = ProcessManualRegion(
        recognize,
        translate,
        PillowImageCropper(),
        PillowMaskRasterizer(),
        _FillInpaint(),
        layout,
        mask_expansion=0,
    )
    window = MainWindow(
        StartupSnapshot(
            ProductInfo("图片翻译", "0.1.0", "M2"),
            tmp_path / "data",
            tmp_path / "cache",
        ),
        recognize_text=recognize,
        translate_regions=translate,
        task_runner=_ImmediateTaskRunner(),
        create_composition_editor=CreateCompositionEditor(layout, renderer),
        process_manual_region=processor,
    )
    window.show()
    window._import_succeeded(document)
    panel = window.manual_region_panel
    panel.set_selection(TextBox(60, 40, 40, 20))
    panel.mode_combo.setCurrentIndex(
        panel.mode_combo.findData(ManualInputMode.TRANSLATED_TEXT.value)
    )
    panel.translated_text.setPlainText("人工译文")
    window.request_manual_region()
    application.processEvents()
    assert window._composition_editor is not None
    assert len(window._composition_editor.layout.layers) == 1
    assert window._composition_editor.layout.layers[0].text == "人工译文"
    assert window.current_document is not None
    assert window.current_document.pixels != document.pixels
    assert window.text_edit_panel.undo_button.isEnabled()
    window.request_undo_edit()
    assert window._composition_editor.layout.layers == ()
    assert window.current_document.pixels == document.pixels
    window.close()
