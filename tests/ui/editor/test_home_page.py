"""首页测试。"""

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from src.ui.editor.home_page import HomePage


def test_home_page_creates(qtbot) -> None:
    app = QApplication.instance() or QApplication(["imgtrans-test"])
    page = HomePage()
    qtbot.addWidget(page)
    page.show()

    assert page is not None
    # 应该能找到两张卡片（QFrame#homeCard）
    cards = page.findChildren(type(page), "homeCard")
    assert len(cards) == 0  # objectName 不在 children 中搜索


def test_home_page_signals(qtbot) -> None:
    app = QApplication.instance() or QApplication(["imgtrans-test"])
    page = HomePage()
    qtbot.addWidget(page)
    page.show()

    clicked = []
    page.image_translation_requested.connect(lambda: clicked.append("translate"))
    page.product_detail_requested.connect(lambda: clicked.append("detail"))

    # 发射信号确认连接正常
    page.image_translation_requested.emit()
    assert clicked == ["translate"]

    page.product_detail_requested.emit()
    assert clicked == ["translate", "detail"]
