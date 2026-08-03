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
