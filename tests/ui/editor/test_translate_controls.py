"""编辑器翻译控件测试。"""

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from src.domain.job import ImageStage
from src.domain.ocr import OcrMode
from src.ui.editor.widgets.translate_controls import TranslateControls


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


def test_translate_controls_configures_high_recall_ring_geometry(qtbot) -> None:
    QApplication.instance() or QApplication(["imgtrans-high-recall-controls-test"])
    ctrl = TranslateControls()
    qtbot.addWidget(ctrl)

    assert ctrl.selected_ocr_mode is OcrMode.STANDARD
    assert not ctrl.high_recall_controls.isVisible()

    ctrl.ocr_mode.setCurrentIndex(
        ctrl.ocr_mode.findData(OcrMode.HIGH_RECALL.value)
    )
    ctrl.show()
    assert ctrl.selected_ocr_mode is OcrMode.HIGH_RECALL
    assert ctrl.high_recall_controls.isVisible()
    assert ctrl.high_recall_center_x.minimumHeight() >= 32
    assert ctrl.high_recall_center_y.minimumHeight() >= 32
    assert ctrl.high_recall_inner_radius.minimumHeight() >= 32
    assert ctrl.high_recall_outer_radius.minimumHeight() >= 32
    assert ctrl.high_recall_controls.minimumHeight() >= 118
    assert ctrl.configured_high_recall_options.center is None
    assert ctrl.configured_high_recall_options.ring_bands == ()

    ctrl.high_recall_center_x.setValue(320)
    ctrl.high_recall_center_y.setValue(240)
    ctrl.high_recall_inner_radius.setValue(80)
    ctrl.high_recall_outer_radius.setValue(190)
    options = ctrl.configured_high_recall_options
    assert options.center is not None
    assert (options.center.x, options.center.y) == (320, 240)
    assert len(options.ring_bands) == 1
    assert options.ring_bands[0].inner_radius == 80
    assert options.ring_bands[0].outer_radius == 190


def test_translate_controls_warns_about_wrong_rotated_ocr_configuration(qtbot) -> None:
    QApplication.instance() or QApplication(["imgtrans-high-recall-hint-test"])
    ctrl = TranslateControls()
    qtbot.addWidget(ctrl)

    assert "必须切换" in ctrl.ocr_mode_hint.text()
    ctrl.ocr_mode.setCurrentIndex(
        ctrl.ocr_mode.findData(OcrMode.HIGH_RECALL.value)
    )
    ctrl.target_language.setCurrentIndex(
        ctrl.target_language.findData("zh-Hans")
    )
    assert ctrl.selected_ocr_language == "zh-Hans"
    assert "简体中文原文 → 简体中文译文" in ctrl.ocr_mode_hint.text()
    assert "英译汉请把" in ctrl.ocr_mode_hint.text()

    ctrl.ocr_language.setCurrentIndex(ctrl.ocr_language.findData("en"))
    assert "英语原文 → 简体中文译文" in ctrl.ocr_mode_hint.text()
    assert "高召回模式已启用" in ctrl.ocr_mode_hint.text()


def test_translate_controls_show_live_stage_and_elapsed_time(qtbot) -> None:
    QApplication.instance() or QApplication(["imgtrans-progress-test"])
    ctrl = TranslateControls()
    qtbot.addWidget(ctrl)
    ctrl.show()
    ctrl.ocr_mode.setCurrentIndex(
        ctrl.ocr_mode.findData(OcrMode.HIGH_RECALL.value)
    )
    activity = []
    ctrl.activity_changed.connect(activity.append)

    ctrl.set_translating(True)
    ctrl.set_preparing()
    ctrl.set_stage(ImageStage.OCR)
    ctrl._update_activity_label()

    assert ctrl.progress.isVisible() == ctrl.isVisible()
    assert ctrl.progress.value() == 1
    assert "步骤 1/5" in ctrl.progress.format()
    assert "OCR 识别" in ctrl.stage_label.text()
    assert "已用时" in ctrl.stage_label.text()
    assert "通常需要 1～4 分钟" in ctrl.stage_label.text()
    assert activity[-1]

    ctrl.reset_progress()
    ctrl.set_translating(False)
    assert activity[-1] is False


def test_translate_controls_mode_radios_default_all(qtbot) -> None:
    """默认选中「翻译全部区域」，源语言下拉禁用。"""
    app = QApplication.instance() or QApplication(["imgtrans-mode-radio-test"])
    ctrl = TranslateControls()
    qtbot.addWidget(ctrl)
    ctrl.show()

    assert ctrl.all_mode_radio.isChecked()
    assert not ctrl.specific_mode_radio.isChecked()
    assert ctrl.selected_mode == "all"
    assert not ctrl.source_language.isEnabled()
    assert ctrl.selected_source_language == "zh-Hans"


def test_translate_controls_specific_mode_enables_source_language(qtbot) -> None:
    """切到「只翻译指定语言」后源语言启用且默认为简体中文。"""
    app = QApplication.instance() or QApplication(["imgtrans-mode-radio-test"])
    ctrl = TranslateControls()
    qtbot.addWidget(ctrl)
    ctrl.show()

    ctrl.specific_mode_radio.setChecked(True)

    assert ctrl.selected_mode == "specific_language"
    assert ctrl.source_language.isEnabled()
    assert ctrl.selected_source_language == "zh-Hans"

    # 切回全部区域 → 源语言再次禁用
    ctrl.all_mode_radio.setChecked(True)
    assert ctrl.selected_mode == "all"
    assert not ctrl.source_language.isEnabled()


def test_translate_controls_translating_disables_mode_radios(qtbot) -> None:
    """翻译进行中模式单选按钮禁用，结束后恢复。"""
    app = QApplication.instance() or QApplication(["imgtrans-mode-radio-test"])
    ctrl = TranslateControls()
    qtbot.addWidget(ctrl)
    ctrl.show()

    ctrl.set_translating(True)
    assert not ctrl.all_mode_radio.isEnabled()
    assert not ctrl.specific_mode_radio.isEnabled()
    assert not ctrl.source_language.isEnabled()

    ctrl.set_translating(False)
    assert ctrl.all_mode_radio.isEnabled()
    assert ctrl.specific_mode_radio.isEnabled()
    assert not ctrl.source_language.isEnabled()  # 默认全部区域模式


def test_translate_controls_ocr_only_button_emits_signal(qtbot) -> None:
    """「仅 OCR 识别」按钮存在且点击时发射 ocr_only_requested。"""
    app = QApplication.instance() or QApplication(["imgtrans-ocr-only-test"])
    ctrl = TranslateControls()
    qtbot.addWidget(ctrl)
    ctrl.show()

    assert ctrl.ocr_only_button.isEnabled()
    assert ctrl.ocr_only_button.text() == "仅 OCR 识别"

    emitted = []
    ctrl.ocr_only_requested.connect(lambda: emitted.append(True))
    ctrl.ocr_only_button.click()

    assert emitted == [True]


def test_translate_controls_translating_disables_ocr_only_button(qtbot) -> None:
    """翻译/识别进行中「仅 OCR 识别」按钮禁用。"""
    app = QApplication.instance() or QApplication(["imgtrans-ocr-only-test"])
    ctrl = TranslateControls()
    qtbot.addWidget(ctrl)
    ctrl.show()

    ctrl.set_translating(True)
    assert not ctrl.ocr_only_button.isEnabled()

    ctrl.set_translating(False)
    assert ctrl.ocr_only_button.isEnabled()
