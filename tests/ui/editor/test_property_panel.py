"""属性面板测试。"""

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QStyleOptionGraphicsItem,
    QWidget,
)

from src.domain.layout import ArcTextPath, PathPoint, TextBox, TextLayer, TextStyle
from src.domain.translation import TranslationStatus, TranslationUnit
from src.ui.editor.widgets.property_panel import PropertyPanel
from src.ui.editor.canvas.layer_item import TextLayerItem


def _make_layer(**kw) -> TextLayer:
    defaults = dict(
        region_id="l1",
        text="Hello",
        box=TextBox(100, 50, 80, 24),
        style=TextStyle("Microsoft YaHei", 14, (24, 32, 51)),
    )
    defaults.update(kw)
    return TextLayer(**defaults)


def test_property_panel_no_selection(qtbot) -> None:
    app = QApplication.instance() or QApplication(["imgtrans-test"])
    panel = PropertyPanel()
    qtbot.addWidget(panel)
    panel.show()

    assert panel.selected_region_id is None
    assert not panel.text_edit.isEnabled()


def test_property_panel_set_layer_block_signals(qtbot) -> None:
    """set_layer 应正确设置字段值而不发射 layer_property_changed。"""
    app = QApplication.instance() or QApplication(["imgtrans-test"])
    panel = PropertyPanel()
    qtbot.addWidget(panel)
    panel.show()

    signals_received = []

    def on_changed(region_id, field, value):
        signals_received.append((region_id, field, value))

    panel.layer_property_changed.connect(on_changed)
    layer = _make_layer()
    panel.set_layer(layer)

    # 字段应被填充
    assert panel.selected_region_id == "l1"
    assert panel.x_spin.value() == 100.0
    assert panel.y_spin.value() == 50.0
    assert panel.text_edit.isEnabled()

    # 不应发射 signal（blockSignals + debounce）
    assert signals_received == []


def test_property_panel_exposes_text_color_control(qtbot) -> None:
    """文字属性应明确提供文字颜色控件，并回显当前填充色。"""
    app = QApplication.instance() or QApplication(["imgtrans-color-test"])
    panel = PropertyPanel()
    qtbot.addWidget(panel)
    panel.show()

    panel.set_layer(_make_layer(style=TextStyle("Microsoft YaHei", 14, (12, 34, 56))))

    assert panel.color_button.toolTip()
    assert panel.color_button.text() == "#0C2238"


def test_property_panel_field_change_debounce(qtbot) -> None:
    """字段变更应在 300ms 后通过 debounce 触发 signal。"""
    app = QApplication.instance() or QApplication(["imgtrans-test"])
    panel = PropertyPanel()
    qtbot.addWidget(panel)
    panel.show()

    layer = _make_layer()
    panel.set_layer(layer)

    signals_received = []

    def on_changed(region_id, field, value):
        signals_received.append((region_id, field, value))

    panel.layer_property_changed.connect(on_changed)

    # 修改字段
    panel.x_spin.setValue(200.0)
    assert signals_received == []  # 还没到 300ms

    # 等待 debounce
    qtbot.wait(400)
    assert len(signals_received) == 1
    assert signals_received[0] == ("l1", "center_x", 200.0)


def test_property_panel_clear() -> None:
    """set_layer(None) 应禁用所有字段。"""
    app = QApplication.instance() or QApplication(["imgtrans-test"])
    panel = PropertyPanel()

    layer = _make_layer()
    panel.set_layer(layer)
    assert panel.text_edit.isEnabled()

    panel.set_layer(None)
    assert panel.selected_region_id is None
    assert not panel.text_edit.isEnabled()


def test_property_panel_translation_edit_shows_translation(qtbot) -> None:
    """set_layer 带翻译单元时译文框应显示译文，而非图层文字。"""
    app = QApplication.instance() or QApplication(["imgtrans-test"])
    panel = PropertyPanel()
    qtbot.addWidget(panel)
    panel.show()

    layer = _make_layer(text="Hello")
    unit = TranslationUnit(
        "l1", "Hello", "en", "zh-Hans", "你好",
        TranslationStatus.TRANSLATED,
    )
    panel.set_layer(layer, translation_unit=unit)

    assert panel.translated_text_edit.toPlainText() == "你好"
    assert panel.apply_translated_text_btn.isEnabled()


def test_property_panel_translation_edit_empty_without_unit(qtbot) -> None:
    """无翻译单元（如自建文字图层）时译文框为空、应用按钮禁用。"""
    app = QApplication.instance() or QApplication(["imgtrans-test"])
    panel = PropertyPanel()
    qtbot.addWidget(panel)
    panel.show()

    layer = _make_layer(text="Hello")
    panel.set_layer(layer)

    assert panel.translated_text_edit.toPlainText() == ""
    assert not panel.apply_translated_text_btn.isEnabled()


def test_property_panel_manual_text_shows_translation_controls(qtbot) -> None:
    app = QApplication.instance() or QApplication(["imgtrans-manual-text-test"])
    panel = PropertyPanel()
    qtbot.addWidget(panel)
    panel.show()

    layer = _make_layer(region_id="manual-new", text="Hello")
    panel.set_layer(layer)

    assert panel.source_text_edit.toPlainText() == "Hello"
    assert panel.translated_text_edit.toPlainText() == "Hello"
    assert panel.manual_translate_btn.isEnabled()
    assert panel.manual_source_language.count() > 1
    assert panel.manual_target_language.findData("en") >= 0

    emitted = []
    panel.manual_translate_requested.connect(
        lambda *values: emitted.append(values)
    )
    panel.manual_source_language.setCurrentIndex(
        panel.manual_source_language.findData("en")
    )
    panel.manual_translate_btn.click()
    assert emitted == [("manual-new", "Hello", "en", "en")]


def test_property_panel_apply_translation_emits_signal(qtbot) -> None:
    """点击“应用译文”应发射 translated_text_changed。"""
    app = QApplication.instance() or QApplication(["imgtrans-test"])
    panel = PropertyPanel()
    qtbot.addWidget(panel)
    panel.show()

    layer = _make_layer(text="Hello")
    unit = TranslationUnit(
        "l1", "Hello", "en", "zh-Hans", "你好",
        TranslationStatus.TRANSLATED,
    )
    panel.set_layer(layer, translation_unit=unit)
    assert panel.apply_translated_text_btn.isEnabled()

    signals_received = []

    def on_changed(region_id, text):
        signals_received.append((region_id, text))

    panel.translated_text_changed.connect(on_changed)

    panel.translated_text_edit.setPlainText("  你好世界  ")
    panel.apply_translated_text_btn.click()

    assert signals_received == [("l1", "你好世界")]


def test_property_panel_apply_translation_ignores_empty(qtbot) -> None:
    """空译文不发射信号。"""
    app = QApplication.instance() or QApplication(["imgtrans-test"])
    panel = PropertyPanel()
    qtbot.addWidget(panel)
    panel.show()

    layer = _make_layer(text="Hello")
    unit = TranslationUnit(
        "l1", "Hello", "en", "zh-Hans", "你好",
        TranslationStatus.TRANSLATED,
    )
    panel.set_layer(layer, translation_unit=unit)

    signals_received = []
    panel.translated_text_changed.connect(
        lambda region_id, text: signals_received.append(text)
    )

    panel.translated_text_edit.setPlainText("   ")
    panel.apply_translated_text_btn.click()

    assert signals_received == []


def test_property_panel_spin_buttons_moved_outside(qtbot) -> None:
    """数值输入框的 ▲▼ 按钮应移到输入框外部（NoButtons）。"""
    app = QApplication.instance() or QApplication(["imgtrans-test"])
    panel = PropertyPanel()
    qtbot.addWidget(panel)
    panel.show()

    for spin in (
        panel.x_spin, panel.y_spin, panel.width_spin, panel.height_spin,
        panel.rotation_spin, panel.font_size_spin, panel.font_stretch_spin,
        panel.line_height_spin, panel.letter_spacing_spin,
        panel.text_opacity_spin, panel.background_opacity_spin,
        panel.stroke_width_spin, panel.shadow_x_spin, panel.shadow_y_spin,
        panel.shadow_opacity_spin,
    ):
        assert (
            spin.buttonSymbols()
            == QAbstractSpinBox.ButtonSymbols.NoButtons
        ), spin

    # 按钮移出后输入框与 stepUp/stepDown 仍正常工作
    panel.x_spin.setValue(100.0)
    panel.x_spin.stepUp()
    assert panel.x_spin.value() == 101.0
    panel.x_spin.stepDown()
    assert panel.x_spin.value() == 100.0


def test_manual_font_size_disables_auto_fit_and_emits_exact_size(qtbot) -> None:
    panel = PropertyPanel()
    qtbot.addWidget(panel)
    panel.show()
    panel.set_layer(_make_layer())
    assert panel.auto_fit_check.isChecked()

    emitted = []
    panel.layer_property_changed.connect(
        lambda region_id, field, value: emitted.append((region_id, field, value))
    )
    panel.font_size_spin.setValue(28)
    qtbot.wait(400)

    assert not panel.auto_fit_check.isChecked()
    assert emitted[-1] == ("l1", "font_size", 28.0)


def test_path_controls_only_show_for_selected_path_type(qtbot) -> None:
    panel = PropertyPanel()
    qtbot.addWidget(panel)
    panel.show()
    panel.set_layer(_make_layer())

    assert not panel.arc_bend_row.isVisible()
    assert not panel.circle_radius_row.isVisible()

    panel.path_mode.setCurrentIndex(panel.path_mode.findData("arc"))
    assert panel.arc_bend_row.isVisible()
    assert not panel.circle_radius_row.isVisible()

    panel.path_mode.setCurrentIndex(panel.path_mode.findData("circle"))
    assert not panel.arc_bend_row.isVisible()
    assert panel.circle_radius_row.isVisible()
    assert panel.circle_center_x.value() == 100
    assert panel.circle_center_y.value() == 50
    assert panel.circle_radius.value() == 40


def test_existing_arc_path_round_trips_its_bend(qtbot) -> None:
    panel = PropertyPanel()
    qtbot.addWidget(panel)
    panel.show()
    layer = _make_layer(
        path=ArcTextPath(
            PathPoint(60, 50),
            PathPoint(100, 38),
            PathPoint(140, 50),
        )
    )

    panel.set_layer(layer)

    assert panel.path_mode.currentData() == "arc"
    assert panel.arc_bend.value() == 0.5


def test_arc_bend_direct_input_commits_exact_path_value(qtbot) -> None:
    panel = PropertyPanel()
    qtbot.addWidget(panel)
    panel.show()
    panel.set_layer(_make_layer(path=ArcTextPath(
        PathPoint(60, 50),
        PathPoint(100, 42.8),
        PathPoint(140, 50),
    )))
    changes = []
    panel.layer_property_changed.connect(
        lambda region_id, field, value: changes.append((region_id, field, value))
    )

    panel.arc_bend.lineEdit().setText("0.65")
    panel.arc_bend.interpretText()
    panel.arc_bend.editingFinished.emit()

    assert panel.arc_bend.value() == 0.65
    assert changes[-1][0:2] == ("l1", "text_path")
    assert changes[-1][2]["bend"] == 0.65


def test_selected_text_box_draws_outline_without_covering_canvas(qtbot) -> None:
    item = TextLayerItem(_make_layer())
    item.setSelected(True)
    image = QImage(240, 140, QImage.Format.Format_ARGB32)
    image.fill(0)
    painter = QPainter(image)
    painter.translate(QPointF(120, 70))
    item.paint(painter, QStyleOptionGraphicsItem())
    painter.end()

    assert image.pixelColor(120, 70).alpha() == 0


def _arm_brush(panel: PropertyPanel, source: TextLayer) -> None:
    panel.set_layer(source)
    panel.format_brush_btn.click()
    assert panel.format_brush_btn.isChecked()


def _test_font_family() -> str:
    """offscreen 环境字体库为空，注册一个系统字体保证 family 可解析。"""
    from PySide6.QtGui import QFont, QFontDatabase

    for candidate in (r"C:\Windows\Fonts\arial.ttf", r"C:\Windows\Fonts\msyh.ttc"):
        if os.path.exists(candidate):
            QFontDatabase.addApplicationFont(candidate)
    for family in ("Arial", "Microsoft YaHei"):
        if QFont(family).exactMatch():
            return family
    return QFont("Arial").family()


def test_format_brush_captures_style_and_applies_on_new_selection(qtbot) -> None:
    family = _test_font_family()
    panel = PropertyPanel()
    qtbot.addWidget(panel)
    panel.show()

    source = _make_layer(
        region_id="src",
        style=TextStyle(family, 20, (255, 0, 0), line_height=1.4, letter_spacing=2.0),
    )
    _arm_brush(panel, source)

    applied = []
    panel.style_brush_applied.connect(lambda *a: applied.append(a))

    # 选中其他图层 → 发射快照
    panel.set_layer(_make_layer(region_id="tgt"))
    assert len(applied) == 1
    region_id, source_id, snapshot = applied[0]
    assert region_id == "tgt"
    assert source_id == "src"
    assert snapshot["font_family"] == family
    assert snapshot["font_size"] == 20.0
    assert snapshot["fill_rgb"] == (255, 0, 0)
    assert snapshot["line_height"] == 1.4
    assert snapshot["letter_spacing"] == 2.0
    assert "center_x" not in snapshot and "text" not in snapshot

    # 保持 armed：继续刷下一层
    panel.set_layer(_make_layer(region_id="tgt2"))
    assert len(applied) == 2
    assert applied[1][0] == "tgt2"


def test_format_brush_does_not_apply_to_source_layer(qtbot) -> None:
    panel = PropertyPanel()
    qtbot.addWidget(panel)
    panel.show()

    _arm_brush(
        panel,
        _make_layer(region_id="src", style=TextStyle("Arial", 20, (255, 0, 0))),
    )
    applied = []
    panel.style_brush_applied.connect(lambda *a: applied.append(a))

    # 先选目标层，再切回来源层 → 不重复刷来源
    panel.set_layer(_make_layer(region_id="tgt"))
    panel.set_layer(_make_layer(region_id="src"))
    assert [item[0] for item in applied] == ["tgt"]


def _send_esc(receiver) -> None:
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent

    QApplication.sendEvent(
        receiver,
        QKeyEvent(
            QEvent.Type.KeyPress,
            Qt.Key.Key_Escape,
            Qt.KeyboardModifier.NoModifier,
        ),
    )


def test_format_brush_esc_disarms_from_panel_focus(qtbot) -> None:
    panel = PropertyPanel()
    qtbot.addWidget(panel)
    panel.show()

    _arm_brush(panel, _make_layer(region_id="src"))
    # 焦点在面板子控件（字号输入框）上按 Esc 应取消
    panel.font_size_spin.setFocus()
    _send_esc(panel.font_size_spin)
    assert not panel.format_brush_btn.isChecked()


def test_format_brush_esc_disarms_from_outside_focus(qtbot) -> None:
    """点选画布后焦点不在面板上，Esc 也应退出格式刷（应用级过滤器）。"""
    panel = PropertyPanel()
    qtbot.addWidget(panel)
    panel.show()

    _arm_brush(panel, _make_layer(region_id="src"))
    # 模拟焦点在面板外（如画布视图）
    canvas_like = QWidget()
    qtbot.addWidget(canvas_like)
    canvas_like.setFocus()
    _send_esc(canvas_like)
    assert not panel.format_brush_btn.isChecked()

    applied = []
    panel.style_brush_applied.connect(lambda *a: applied.append(a))
    panel.set_layer(_make_layer(region_id="tgt"))
    assert applied == []


def test_format_brush_reclick_disarms(qtbot) -> None:
    panel = PropertyPanel()
    qtbot.addWidget(panel)
    panel.show()

    _arm_brush(panel, _make_layer(region_id="src"))
    panel.format_brush_btn.click()
    assert not panel.format_brush_btn.isChecked()

    applied = []
    panel.style_brush_applied.connect(lambda *a: applied.append(a))
    panel.set_layer(_make_layer(region_id="tgt"))
    assert applied == []


def test_format_brush_disabled_without_selection(qtbot) -> None:
    panel = PropertyPanel()
    qtbot.addWidget(panel)
    panel.show()

    assert not panel.format_brush_btn.isEnabled()
    panel.format_brush_btn.click()
    assert not panel.format_brush_btn.isChecked()


def test_style_brush_snapshot_merges_into_target_layer(qtbot) -> None:
    """EditorPage 接收 style_brush_applied 后整体合并样式并单次 emit edit_requested。"""
    from types import SimpleNamespace

    from PySide6.QtGui import QUndoStack

    from src.domain.layout import TextLayout
    from src.ui.editor.editor_page import EditorPage

    family = _test_font_family()
    page = EditorPage(QUndoStack())
    qtbot.addWidget(page)
    page.show()

    source_style = TextStyle(family, 20, (255, 0, 0), line_height=1.4, letter_spacing=2.0)
    source = TextLayer("src", "A", TextBox(100, 50, 80, 24), source_style)
    target = TextLayer(
        "tgt", "B", TextBox(300, 150, 200, 60), TextStyle("Microsoft YaHei", 14, (24, 32, 51))
    )
    page._model = SimpleNamespace(text_layout=TextLayout((source, target)))

    edits = []
    page.edit_requested.connect(lambda *a: edits.append(a))

    panel = page.property_panel
    panel.set_layer(source)
    panel.format_brush_btn.click()
    panel.set_layer(target)

    assert len(edits) == 1
    region_id, kind, after, before = edits[0]
    assert region_id == "tgt"
    assert kind == "style"
    assert before is target
    assert after.style.font_family == family
    assert after.style.font_size == 20.0
    assert after.style.fill_rgb == (255, 0, 0)
    assert after.style.line_height == 1.4
    assert after.style.letter_spacing == 2.0
    assert after.box == target.box  # 位置不变
    assert after.text == "B"


def test_property_panel_narrow_allows_horizontal_scroll(qtbot) -> None:
    """面板窄于表单最小宽时应出现横向滚动条，而不是静默截断右侧内容。"""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QScrollArea

    app = QApplication.instance() or QApplication(["imgtrans-test"])
    panel = PropertyPanel()
    qtbot.addWidget(panel)
    panel.resize(300, 700)
    panel.show()

    scroll = panel.findChildren(QScrollArea)[0]
    assert (
        scroll.horizontalScrollBarPolicy()
        == Qt.ScrollBarPolicy.ScrollBarAsNeeded
    )
    qtbot.waitUntil(
        lambda: scroll.horizontalScrollBar().maximum() > 0,
        timeout=2000,
    )
