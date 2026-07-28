"""编辑器翻译控件测试。"""

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from src.ui.editor.translate_controls import TranslateControls


def test_translate_controls_creates(qtbot) -> None:
    app = QApplication.instance() or QApplication(["imgtrans-test"])
    ctrl = TranslateControls()
    qtbot.addWidget(ctrl)
    ctrl.show()

    assert ctrl.selected_ocr_language == "zh-Hans"
    assert ctrl.selected_target_language == "en"
    assert ctrl.translate_button.isEnabled()


def test_translate_controls_set_translating(qtbot) -> None:
    app = QApplication.instance() or QApplication(["imgtrans-test"])
    ctrl = TranslateControls()
    qtbot.addWidget(ctrl)
    ctrl.show()

    ctrl.set_translating(True)
    assert not ctrl.translate_button.isEnabled()
    assert not ctrl.ocr_language.isEnabled()
    assert not ctrl.target_language.isEnabled()

    ctrl.set_translating(False)
    assert ctrl.translate_button.isEnabled()
    assert ctrl.ocr_language.isEnabled()
    assert ctrl.target_language.isEnabled()


def test_translate_controls_signal(qtbot) -> None:
    app = QApplication.instance() or QApplication(["imgtrans-test"])
    ctrl = TranslateControls()
    qtbot.addWidget(ctrl)
    ctrl.show()

    received = []

    def on_translate(ocr, target):
        received.append((ocr, target))

    ctrl.translate_requested.connect(on_translate)

    # 手动选择日语为 OCR 语言，中文为目标
    idx_ja = ctrl.ocr_language.findData("ja")
    if idx_ja >= 0:
        ctrl.ocr_language.setCurrentIndex(idx_ja)
    idx_zh = ctrl.target_language.findData("zh-Hans")
    if idx_zh >= 0:
        ctrl.target_language.setCurrentIndex(idx_zh)

    ctrl._on_translate()
    assert received == [("ja", "zh-Hans")]
