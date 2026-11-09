"""商店页测试 — 套餐分类展示与购买/返回信号。"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from src.infrastructure.payment_client import PayablePlan
from src.ui.editor.home_page import HomePage
from src.ui.editor.store_page import StorePage


def _plan(plan_id, name, plan_type="duration", hours=0, quota=0, amount=1000):
    return PayablePlan(
        plan_id=plan_id,
        name=name,
        amount_minor=amount,
        currency="CNY",
        duration_hours=hours,
        plan_type=plan_type,
        quota=quota,
    )


def test_store_groups_plans_by_category(qtbot) -> None:
    QApplication.instance() or QApplication(["store-test"])
    store = StorePage()
    qtbot.addWidget(store)
    store.show()

    store.set_plans(
        [
            _plan(1, "时长 A", "duration", hours=24),
            _plan(2, "次数 B", "quota", quota=100),
            _plan(3, "组合 C", "combo", hours=24, quota=50),
        ]
    )

    duration_section, duration_row = store._sections["duration"]
    quota_section, quota_row = store._sections["quota"]
    combo_section, combo_row = store._sections["combo"]
    assert duration_section.isVisible()
    assert quota_section.isVisible()
    assert combo_section.isVisible()
    assert duration_row.count() == 1
    assert quota_row.count() == 1
    assert combo_row.count() == 1


def test_store_hides_empty_categories(qtbot) -> None:
    QApplication.instance() or QApplication(["store-empty-test"])
    store = StorePage()
    qtbot.addWidget(store)
    store.show()

    store.set_plans([_plan(1, "时长 A", "duration", hours=24)])

    assert store._sections["duration"][0].isVisible()
    assert not store._sections["quota"][0].isVisible()
    assert not store._sections["combo"][0].isVisible()


def test_store_card_click_emits_purchase(qtbot) -> None:
    QApplication.instance() or QApplication(["store-click-test"])
    store = StorePage()
    qtbot.addWidget(store)
    store.show()
    store.set_plans([_plan(1, "时长 A", "duration", hours=24)])

    received: list = []
    store.purchase_requested.connect(received.append)
    _section, row = store._sections["duration"]
    card = row.itemAt(0).widget()
    card.mousePressEvent(None)

    assert received and received[0].plan_id == 1


def test_store_back_button_emits(qtbot) -> None:
    QApplication.instance() or QApplication(["store-back-test"])
    store = StorePage()
    qtbot.addWidget(store)
    store.show()

    received: list = []
    store.back_requested.connect(lambda: received.append(1))
    store._back_button.click()

    assert received == [1]


def test_home_page_store_card_emits(qtbot) -> None:
    QApplication.instance() or QApplication(["home-store-test"])
    page = HomePage()
    qtbot.addWidget(page)
    page.show()

    received: list = []
    page.store_requested.connect(lambda: received.append(1))
    page._store_card.mousePressEvent(None)

    assert received == [1]
