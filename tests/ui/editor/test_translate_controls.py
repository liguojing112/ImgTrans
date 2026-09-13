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


def test_translate_controls_font_defaults_to_auto(qtbot) -> None:
    """译文字体默认「自动匹配字体」。"""
    app = QApplication.instance() or QApplication(["imgtrans-font-test"])
    ctrl = TranslateControls()
    qtbot.addWidget(ctrl)

    assert ctrl.selected_font_family is None
    assert ctrl.translation_font.itemData(0) is None
    assert ctrl.translation_font.itemText(0) == "自动匹配字体"


def test_translation_font_choices_show_chinese_names_without_duplicates() -> None:
    """中文字体显示中文名，英文别名并入同一条，不出现重复项。"""
    from src.ui.editor.widgets.translate_controls import _translation_font_choices

    choices = _translation_font_choices(
        [
            "宋体",
            "SimSun",
            "Microsoft YaHei",
            "微软雅黑",
            "微软雅黑 Light",
            "Arial",
        ]
    )

    assert ("宋体", "SimSun") in choices
    assert ("微软雅黑", "Microsoft YaHei") in choices
    assert ("微软雅黑 Light", "微软雅黑 Light") in choices
    assert ("Arial（无衬线字体）", "Arial") in choices
    displays = [display for display, _ in choices]
    assert len(displays) == len(set(displays))
    assert "SimSun" not in displays
    assert displays == sorted(displays, key=str.casefold)


def test_font_style_label_covers_weight_variants_and_prefixes() -> None:
    """英文字体名追加中文风格说明；字重变体/同名前缀不误判。"""
    from src.ui.editor.widgets.translate_controls import _font_style_label

    # 常见字体
    assert _font_style_label("Agency FB") == "无衬线字体"
    assert _font_style_label("Times New Roman") == "衬线字体"
    assert _font_style_label("Comic Sans MS") == "装饰字体"
    assert _font_style_label("Consolas") == "等宽字体"
    assert _font_style_label("Segoe Script") == "手写体"
    assert _font_style_label("Wingdings") == "符号字体"
    assert _font_style_label("System") == "无衬线字体"
    # 字重/变体后缀命中基名
    assert _font_style_label("Arial Rounded MT Bold") == "无衬线字体"
    assert _font_style_label("Bahnschrift SemiBold Condensed") == "无衬线字体"
    assert _font_style_label("Baskerville Old Face") == "衬线字体"
    assert _font_style_label("Rockwell Extra Bold") == "衬线字体"
    # 最长前缀优先：Century Gothic 是 Sans，不能被 Century(衬线) 带偏
    assert _font_style_label("Century Gothic") == "无衬线字体"
    assert _font_style_label("Century") == "衬线字体"
    assert _font_style_label("Century Schoolbook") == "衬线字体"
    # 中文名/非 ASCII 不追加
    assert _font_style_label("宋体") is None
    # 无法确定时返回 None，不追加（宁缺勿错）
    assert _font_style_label("ZzzUnknownFont") is None


def test_translate_controls_set_translation_font(qtbot) -> None:
    """set_translation_font 选中字体族；未知字体回退自动且不触发信号。"""
    app = QApplication.instance() or QApplication(["imgtrans-font-test"])
    ctrl = TranslateControls()
    qtbot.addWidget(ctrl)
    ctrl.translation_font.addItem("TestFamily", "TestFamily")

    emitted = []
    ctrl.translation_font_changed.connect(lambda value: emitted.append(value))
    ctrl.set_translation_font("TestFamily")
    assert ctrl.selected_font_family == "TestFamily"
    assert ctrl.translation_font.currentIndex() == ctrl.translation_font.findData("TestFamily")
    assert emitted == []  # 设置时屏蔽信号

    ctrl.set_translation_font("definitely-not-a-real-font")
    assert ctrl.selected_font_family is None


def test_translate_controls_font_change_emits_signal(qtbot) -> None:
    """用户切换字体时发射所选字体族（自动时为 None）。"""
    app = QApplication.instance() or QApplication(["imgtrans-font-test"])
    ctrl = TranslateControls()
    qtbot.addWidget(ctrl)
    ctrl.translation_font.addItem("TestFamily", "TestFamily")

    emitted = []
    ctrl.translation_font_changed.connect(lambda value: emitted.append(value))
    ctrl.translation_font.setCurrentIndex(ctrl.translation_font.findData("TestFamily"))
    assert emitted == ["TestFamily"]

    ctrl.translation_font.setCurrentIndex(0)
    assert emitted == ["TestFamily", None]


def test_translate_controls_translating_disables_font(qtbot) -> None:
    """翻译进行中译文字体下拉禁用。"""
    app = QApplication.instance() or QApplication(["imgtrans-font-test"])
    ctrl = TranslateControls()
    qtbot.addWidget(ctrl)

    ctrl.set_translating(True)
    assert not ctrl.translation_font.isEnabled()

    ctrl.set_translating(False)
    assert ctrl.translation_font.isEnabled()


def test_translate_controls_paragraph_mode_defaults_to_long(qtbot) -> None:
    """段落模式默认「长文」（合并相邻行整段翻译）。"""
    app = QApplication.instance() or QApplication(["imgtrans-paragraph-test"])
    ctrl = TranslateControls()
    qtbot.addWidget(ctrl)

    assert ctrl.merge_paragraphs is True
    assert ctrl.paragraph_mode.itemData(0) == "long"
    assert ctrl.paragraph_mode.itemData(1) == "short"


def test_translate_controls_set_paragraph_mode(qtbot) -> None:
    """set_paragraph_mode 选中模式；未知模式回退默认且不触发信号。"""
    app = QApplication.instance() or QApplication(["imgtrans-paragraph-test"])
    ctrl = TranslateControls()
    qtbot.addWidget(ctrl)

    emitted = []
    ctrl.paragraph_mode_changed.connect(lambda value: emitted.append(value))
    ctrl.set_paragraph_mode("short")
    assert ctrl.merge_paragraphs is False
    assert emitted == []  # 设置时屏蔽信号

    ctrl.set_paragraph_mode("definitely-not-a-mode")
    assert ctrl.merge_paragraphs is True


def test_translate_controls_paragraph_mode_change_emits_signal(qtbot) -> None:
    """用户切换段落模式时发射所选模式。"""
    app = QApplication.instance() or QApplication(["imgtrans-paragraph-test"])
    ctrl = TranslateControls()
    qtbot.addWidget(ctrl)

    emitted = []
    ctrl.paragraph_mode_changed.connect(lambda value: emitted.append(value))
    ctrl.paragraph_mode.setCurrentIndex(ctrl.paragraph_mode.findData("short"))
    assert emitted == ["short"]

    ctrl.paragraph_mode.setCurrentIndex(0)
    assert emitted == ["short", "long"]


def test_translate_controls_translating_disables_paragraph_mode(qtbot) -> None:
    """翻译进行中段落模式下拉禁用。"""
    app = QApplication.instance() or QApplication(["imgtrans-paragraph-test"])
    ctrl = TranslateControls()
    qtbot.addWidget(ctrl)

    ctrl.set_translating(True)
    assert not ctrl.paragraph_mode.isEnabled()

    ctrl.set_translating(False)
    assert ctrl.paragraph_mode.isEnabled()


def test_theme_keeps_checked_radio_indicator_visible() -> None:
    """回归：QRadioButton 带样式表后原生选中圆点丢失（选中行不画圈，
    看起来像选中项“反着”）。主题必须显式定义 indicator:checked。"""
    from src.ui.editor.theme import EDITOR_DARK_THEME

    assert "QRadioButton::indicator:checked" in EDITOR_DARK_THEME
