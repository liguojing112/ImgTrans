"""编辑器模型测试。"""

import os
from pathlib import Path
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Signal

from src.domain.image import ImageAsset, ImageDocument, ImageFileFormat
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


def _doc(w: int = 10, h: int = 10, name: str = "a.png") -> ImageDocument:
    asset = ImageAsset(
        Path(name), w, h, 1, ImageFileFormat.PNG, False, False
    )
    return ImageDocument(asset, "RGB", bytes(w * h * 3))


def test_model_document_state_snapshot_and_restore() -> None:
    """切换活动文档应保存并恢复各自的编辑状态。"""
    app = QApplication.instance() or QApplication(["imgtrans-test"])
    model = EditorModel()
    layout_a = TextLayout((_make_layer("r1", "译文A"),))

    id_a = model.add_document(Path("a.png"), _doc(), name="a.png")
    model.ocr_result = "ocr-A"
    model.translation_result = "result-A"
    model.text_layout = layout_a
    model.rendered_document = "rendered-A"
    model.is_dirty = True

    id_b = model.add_document(Path("b.png"), _doc(name="b.png"), name="b.png")
    # 新文档以干净状态激活，A 的状态已保存
    assert model.active_document_id == id_b
    assert model.ocr_result is None
    assert model.translation_result is None
    assert model.text_layout.layers == ()

    # 切回 A → 恢复 A 的状态
    model.set_active_document(id_a)
    assert model.ocr_result == "ocr-A"
    assert model.translation_result == "result-A"
    assert model.text_layout is layout_a
    assert model.rendered_document == "rendered-A"
    assert model.is_dirty is True
    assert model.selected_layer_id is None

    # 切回 B → B 的干净状态恢复
    model.set_active_document(id_b)
    assert model.translation_result is None
    assert model.text_layout.layers == ()

    # 再次切回 A → 状态仍在（多次往返不丢失）
    model.set_active_document(id_a)
    assert model.translation_result == "result-A"
    assert model.text_layout is layout_a


def test_model_remove_active_document_restores_next_state() -> None:
    """删除活动文档后自动恢复剩余文档的状态。"""
    app = QApplication.instance() or QApplication(["imgtrans-test"])
    model = EditorModel()
    layout_a = TextLayout((_make_layer("r1", "译文A"),))

    id_a = model.add_document(Path("a.png"), _doc(), name="a.png")
    model.translation_result = "result-A"
    model.text_layout = layout_a
    id_b = model.add_document(Path("b.png"), _doc(name="b.png"), name="b.png")

    model.set_active_document(id_a)
    model.remove_document(id_a)

    assert model.active_document_id == id_b
    assert model.translation_result is None  # B 干净状态
    assert model.text_layout.layers == ()
