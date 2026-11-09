"""商店页 — 按套餐类型分类展示可购买套餐（时长包 / 次数包 / 组合套餐）。"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

# 分类顺序、标题与说明；plan_type 来自服务端套餐定义
_CATEGORIES = (
    ("duration", "时长包", "图片翻译等基础功能的使用时长"),
    ("quota", "次数包", "商品详情生成的次数（需先激活时长包）"),
    ("combo", "组合套餐", "时长 + 次数一起购买"),
)
_CATEGORY_LABELS = {key: title for key, title, _ in _CATEGORIES}


class StorePage(QFrame):
    back_requested = Signal()
    purchase_requested = Signal(object)

    def __init__(self, payment_client=None, task_runner=None) -> None:
        super().__init__()
        self.setProperty("editorStyle", True)
        self._payment_client = payment_client
        self._task_runner = task_runner
        self._plans: list = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 16, 24, 16)
        outer.setSpacing(8)

        header = QHBoxLayout()
        title = QLabel("商店")
        title.setObjectName("homeTitle")
        self._back_button = QPushButton("← 返回首页")
        self._back_button.clicked.connect(self.back_requested.emit)
        header.addWidget(title)
        header.addStretch()
        header.addWidget(self._back_button)
        outer.addLayout(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        self._content_layout = QVBoxLayout(content)
        self._content_layout.setContentsMargins(24, 12, 24, 24)
        self._content_layout.setSpacing(18)
        self._content_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll.setWidget(content)
        outer.addWidget(scroll, 1)

        # 每类一个卡片行；无该类套餐时整块隐藏
        self._sections: dict[str, tuple[QWidget, QHBoxLayout]] = {}
        for key, name, description in _CATEGORIES:
            section = QWidget()
            section_layout = QVBoxLayout(section)
            section_layout.setContentsMargins(0, 0, 0, 0)
            section_layout.setSpacing(8)
            caption = QLabel(name)
            caption.setObjectName("homeSubtitle")
            hint = QLabel(description)
            hint.setObjectName("homeCardDesc")
            cards_row = QHBoxLayout()
            cards_row.setSpacing(12)
            cards_row.setAlignment(Qt.AlignmentFlag.AlignLeft)
            section_layout.addWidget(caption)
            section_layout.addWidget(hint)
            section_layout.addLayout(cards_row)
            self._content_layout.addWidget(section)
            self._sections[key] = (section, cards_row)

        self._status_label = QLabel("")
        self._status_label.setObjectName("homeCardDesc")
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._content_layout.addWidget(self._status_label)

        if self._payment_client is not None:
            QTimer.singleShot(0, self.reload_plans)

    # —— 数据 ——

    def reload_plans(self) -> None:
        if self._payment_client is None:
            self._status_label.setText("暂无可购买套餐")
            return
        if self._task_runner is not None:
            self._task_runner.submit(
                self._payment_client.list_plans,
                self.set_plans,
                self._plans_failed,
            )
            return
        try:
            self.set_plans(self._payment_client.list_plans())
        except Exception as error:  # noqa: BLE001 - 展示失败信息
            self._plans_failed(error)

    def set_plans(self, plans) -> None:
        self._plans = list(plans or [])
        for section, row in self._sections.values():
            _clear_layout(row)
            section.setVisible(False)
        grouped = {key: [] for key in _CATEGORY_LABELS}
        for plan in self._plans:
            plan_type = str(getattr(plan, "plan_type", "duration"))
            grouped.setdefault(plan_type, []).append(plan)
        unknown = [
            plan
            for plan in self._plans
            if str(getattr(plan, "plan_type", "duration")) not in _CATEGORY_LABELS
        ]
        for key, plans_in_group in grouped.items():
            if not plans_in_group:
                continue
            section, row = self._sections.get(key, (None, None))
            if section is None:
                continue
            section.setVisible(True)
            for plan in plans_in_group:
                row.addWidget(self._make_plan_card(plan))
        if unknown:
            self._append_other_section(unknown)
        self._status_label.setText(
            "" if self._plans else "暂无可购买套餐"
        )

    def _append_other_section(self, plans) -> None:
        # 未知类型（服务端以后新增的套餐种类）：单独一组兜底展示
        if "other" not in self._sections:
            section = QWidget()
            section_layout = QVBoxLayout(section)
            section_layout.setContentsMargins(0, 0, 0, 0)
            section_layout.setSpacing(8)
            caption = QLabel("其他套餐")
            caption.setObjectName("homeSubtitle")
            cards_row = QHBoxLayout()
            cards_row.setSpacing(12)
            section_layout.addWidget(caption)
            section_layout.addLayout(cards_row)
            self._content_layout.insertWidget(
                self._content_layout.count() - 1, section
            )
            self._sections["other"] = (section, cards_row)
        section, row = self._sections["other"]
        _clear_layout(row)
        section.setVisible(True)
        for plan in plans:
            row.addWidget(self._make_plan_card(plan))

    def _plans_failed(self, error) -> None:
        self._status_label.setText(f"套餐加载失败：{error}")

    # —— 卡片 ——

    def _make_plan_card(self, plan) -> QFrame:
        if plan.plan_type == "combo":
            spec = f"{plan.duration_hours} 小时 + {plan.quota} 次"
        elif plan.plan_type == "quota":
            spec = f"{plan.quota} 次"
        else:
            spec = f"{plan.duration_hours} 小时"
        price = (
            plan.sale_amount_minor
            if plan.is_on_sale and plan.sale_amount_minor
            else plan.amount_minor
        )
        card = QFrame()
        card.setObjectName("homeCard")
        card.setProperty("editorStyle", True)
        card.setFixedSize(200, 130)
        card.setCursor(Qt.CursorShape.PointingHandCursor)

        inner = QVBoxLayout(card)
        inner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        inner.setSpacing(8)

        name = QLabel(plan.name)
        name.setObjectName("homeCardTitle")
        name.setAlignment(Qt.AlignmentFlag.AlignCenter)

        price_label = QLabel(f"¥{price / 100:.2f}")
        price_label.setObjectName("homeCardTitle")
        price_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        spec_label = QLabel(spec)
        spec_label.setObjectName("homeCardDesc")
        spec_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        inner.addWidget(name)
        inner.addWidget(price_label)
        inner.addWidget(spec_label)
        card.mousePressEvent = lambda e, p=plan: self.purchase_requested.emit(p)
        return card


def _clear_layout(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.deleteLater()
