"""编辑器模型测试。"""

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Signal

from src.domain.layout import (
    TextBox,
    TextLayer,
    TextLayout,
    TextStyle,
)
from src.ui.editor.editor_model import EditorModel


def _make_layer(
    region_id: str = "layer-1",
    text: str = "Hello",
    x: float = 100,
    y: float = 50,
    w: float = 80,
    h: float = 24,
) -> TextLayer:
    return TextLayer(
        region_id=region_id,
        text=text,
        box=TextBox(x, y, w, h),
        style=TextStyle("Microsoft YaHei", 14, (24, 32, 51)),
    )


def test_model_initial_state() -> None:
    app = QApplication.instance() or QApplication(["imgtrans-test"])
    model = EditorModel()
    assert model.document is None
    assert model.text_layout.layers == ()
    assert model.selected_layer_id is None
    assert model.selected_layer is None


def test_model_document_set() -> None:
    app = QApplication.instance() or QApplication(["imgtrans-test"])
    model = EditorModel()

    captured = []

    def on_doc_changed(value):
        captured.append(value)

    model.document_changed.connect(on_doc_changed)
    model.document = None  # same value, no signal
    assert captured == []


def test_model_layout_operations() -> None:
    app = QApplication.instance() or QApplication(["imgtrans-test"])
    model = EditorModel()

    layer1 = _make_layer("r1", "Text 1")
    layer2 = _make_layer("r2", "Text 2")

    model.text_layout = TextLayout((layer1, layer2))
    assert len(model.text_layout.layers) == 2
    assert model.text_layout.layer_by_id("r1") == layer1

    # 选中
    model.selected_layer_id = "r1"
    assert model.selected_layer is not None
    assert model.selected_layer.region_id == "r1"

    # 替换
    after = _make_layer("r1", "Updated")
    model.replace_layer(layer1, after)
    assert model.text_layout.layer_by_id("r1").text == "Updated"

    # 添加
    layer3 = _make_layer("r3", "New")
    model.add_layer(layer3)
    assert len(model.text_layout.layers) == 3

    # 删除
    model.remove_layer("r3")
    assert len(model.text_layout.layers) == 2


def test_model_selection_cleared_on_remove() -> None:
    app = QApplication.instance() or QApplication(["imgtrans-test"])
    model = EditorModel()

    layer1 = _make_layer("r1", "Text")
    model.text_layout = TextLayout((layer1,))
    model.selected_layer_id = "r1"
    assert model.selected_layer_id == "r1"

    model.remove_layer("r1")
    assert model.selected_layer_id is None
    assert model.selected_layer is None
