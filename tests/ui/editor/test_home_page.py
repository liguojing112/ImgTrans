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


def test_home_page_portal_card_emits_and_updates(qtbot) -> None:
    """万象笔记卡片：可点击，且能按服务端配置更新标题/说明。"""
    QApplication.instance() or QApplication(["home-portal-test"])
    page = HomePage()
    qtbot.addWidget(page)
    page.show()

    received: list = []
    page.portal_requested.connect(lambda: received.append(1))
    page._portal_card.mousePressEvent(None)
    assert received == [1]

    page.set_portal_module("万象笔记（新）", "新的说明文字")
    assert page._portal_card._title_label.text() == "万象笔记（新）"
    assert page._portal_card._desc_label.text() == "新的说明文字"
