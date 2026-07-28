"""属性面板测试。"""

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from src.domain.layout import TextBox, TextLayer, TextStyle
from src.ui.editor.property_panel import PropertyPanel


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
