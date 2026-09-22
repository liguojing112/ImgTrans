"""工作台图片列表面板测试。"""

import os
from pathlib import Path
from types import SimpleNamespace
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from src.domain.image import ImageAsset, ImageDocument, ImageFileFormat
from src.ui.editor.widgets.image_list_panel import ImageListPanel


def _ref(doc_id: str, name: str = "a.png"):
    asset = ImageAsset(
        Path(name), 10, 10, 1, ImageFileFormat.PNG, False, False
    )
    return SimpleNamespace(
        doc_id=doc_id,
        name=name,
        source_path=Path(name),
        source_document=ImageDocument(asset, "RGB", bytes(10 * 10 * 3)),
    )


def test_remove_button_disabled_without_selection(qtbot) -> None:
    app = QApplication.instance() or QApplication(["imglist-test"])
    panel = ImageListPanel()
    qtbot.addWidget(panel)
    panel.show()

    panel.set_documents([_ref("d1"), _ref("d2", "b.png")])

    assert panel._list.count() == 2
    assert not panel._remove_btn.isEnabled()


def test_remove_button_enabled_when_item_selected(qtbot) -> None:
    app = QApplication.instance() or QApplication(["imglist-test"])
    panel = ImageListPanel()
    qtbot.addWidget(panel)
    panel.show()

    panel.set_documents([_ref("d1"), _ref("d2", "b.png")])
    panel.set_active("d2")

    assert panel._remove_btn.isEnabled()


def test_remove_button_emits_requested_doc_id(qtbot) -> None:
    app = QApplication.instance() or QApplication(["imglist-test"])
    panel = ImageListPanel()
    qtbot.addWidget(panel)
    panel.show()

    panel.set_documents([_ref("d1"), _ref("d2", "b.png")])
    panel.set_active("d1")

    removed = []
    panel.remove_requested.connect(removed.append)
    panel._remove_btn.click()

    assert removed == ["d1"]


def test_reclick_active_document_reactivates(qtbot) -> None:
    """重复点击当前已激活图片也要发 document_activated。

    currentItemChanged 只在切换时触发，强化翻译需靠重复点击重新上传。
    """
    app = QApplication.instance() or QApplication(["imglist-test"])
    panel = ImageListPanel()
    qtbot.addWidget(panel)
    panel.show()

    panel.set_documents([_ref("d1")])
    panel.set_active("d1")

    received = []
    panel.document_activated.connect(received.append)
    # 模拟点击当前项：itemPressed → itemClicked（currentItemChanged 不发）
    panel._on_item_pressed(panel._items["d1"])
    panel._on_item_clicked(panel._items["d1"])

    assert received == ["d1"]


def test_switch_document_emits_once(qtbot) -> None:
    """切换到另一张图只发一次 document_activated（切换与点击不重复）。"""
    app = QApplication.instance() or QApplication(["imglist-test"])
    panel = ImageListPanel()
    qtbot.addWidget(panel)
    panel.show()

    panel.set_documents([_ref("d1"), _ref("d2", "b.png")])
    panel.set_active("d1")

    received = []
    panel.document_activated.connect(received.append)
    # 模拟点击 d2：itemPressed → currentItemChanged → itemClicked
    panel._on_item_pressed(panel._items["d2"])
    panel._list.setCurrentItem(panel._items["d2"])
    panel._on_item_clicked(panel._items["d2"])

    assert received == ["d2"]


def test_set_active_does_not_emit_document_activated(qtbot) -> None:
    """程序化同步选中项不算用户点击：导入后激活新文档不能再发激活信号。

    否则强化翻译会把刚导入的解析结果当成「点了左侧图片」重新上传给豆包。
    """
    app = QApplication.instance() or QApplication(["imglist-test"])
    panel = ImageListPanel()
    qtbot.addWidget(panel)
    panel.show()

    panel.set_documents([_ref("d1"), _ref("d2", "b.png")])

    received = []
    panel.document_activated.connect(received.append)
    panel.set_active("d2")

    assert received == []
    assert panel._list.currentItem() is panel._items["d2"]
    assert panel._remove_btn.isEnabled()


def test_remove_button_disabled_after_clear(qtbot) -> None:
    app = QApplication.instance() or QApplication(["imglist-test"])
    panel = ImageListPanel()
    qtbot.addWidget(panel)
    panel.show()

    panel.set_documents([_ref("d1")])
    panel.set_active("d1")
    assert panel._remove_btn.isEnabled()

    panel.set_documents([])
    assert panel._list.count() == 0
    assert not panel._remove_btn.isEnabled()
    assert panel._count_label.text() == "0 张图片"


def test_rapid_same_doc_activation_collapses(qtbot) -> None:
    """一次点击连发两次同文档激活（currentItemChanged+itemClicked）只算一次。

    日志实测同 doc 两次 enhance_activate 间隔约 190ms，强化翻译会各传一轮图。
    """
    app = QApplication.instance() or QApplication(["imglist-test"])
    panel = ImageListPanel()
    qtbot.addWidget(panel)
    panel.show()

    panel.set_documents([_ref("d1")])
    panel.set_active("d1")

    received = []
    panel.document_activated.connect(received.append)
    # 模拟一次点击内的连发
    panel._on_item_pressed(panel._items["d1"])
    panel._on_item_clicked(panel._items["d1"])
    panel._on_item_pressed(panel._items["d1"])
    panel._on_item_clicked(panel._items["d1"])

    assert received == ["d1"]


def test_reclick_after_debounce_window_emits_again(qtbot) -> None:
    """合并窗口之外的再次点击仍要发激活（强化翻译需要重传）。"""
    app = QApplication.instance() or QApplication(["imglist-test"])
    panel = ImageListPanel()
    qtbot.addWidget(panel)
    panel.show()

    panel.set_documents([_ref("d1")])
    panel.set_active("d1")

    received = []
    panel.document_activated.connect(received.append)
    panel._on_item_pressed(panel._items["d1"])
    panel._on_item_clicked(panel._items["d1"])
    # 把上次发射时间拨回窗口外，等价于用户稍后再次点击
    panel._last_emit_at -= 1.0
    panel._on_item_pressed(panel._items["d1"])
    panel._on_item_clicked(panel._items["d1"])

    assert received == ["d1", "d1"]
