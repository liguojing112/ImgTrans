"""首页 — 三个入口卡片（倒品字形布局）。"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from src.ui.editor.icons import standard_icon


class HomePage(QFrame):
    """首页，提供"图片翻译"、"商品详情生成"和"图片工具箱"三个入口。"""

    image_translation_requested = Signal()
    product_detail_requested = Signal()
    toolbox_requested = Signal()
    purchase_requested = Signal(object)

    def __init__(self, payment_client=None, task_runner=None) -> None:
        super().__init__()
        self.setProperty("editorStyle", True)
        self._payment_client = payment_client
        self._task_runner = task_runner

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(32)

        # 标题区域
        title_group = QVBoxLayout()
        title_group.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_group.setSpacing(8)

        title = QLabel("优译图AI 图片翻译")
        title.setObjectName("homeTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        subtitle = QLabel("高效本地化您的产品图片")
        subtitle.setObjectName("homeSubtitle")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)

        title_group.addWidget(title)
        title_group.addWidget(subtitle)
        layout.addLayout(title_group)

        # 第一行：主营功能卡片
        cards_top = QHBoxLayout()
        cards_top.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cards_top.setSpacing(24)

        translate_card = self._make_card(
            "图片翻译",
            "识别 / 翻译 / 渲染\n将图片中文字翻译为多语言并回填",
            enabled=True,
        )
        translate_card.mousePressEvent = lambda _: self.image_translation_requested.emit()

        detail_card = self._make_card(
            "商品详情生成",
            "上传商品图片 / AI 商品分析\n生成多语言标题、标签、卖点与详情文案",
            enabled=True,
        )
        detail_card.mousePressEvent = lambda e: self.product_detail_requested.emit()

        cards_top.addWidget(translate_card)
        cards_top.addWidget(detail_card)
        layout.addLayout(cards_top)

        # 第二行：辅助功能卡片（稍小，居中）
        cards_bottom = QHBoxLayout()
        cards_bottom.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cards_bottom.setSpacing(24)
        cards_bottom.addStretch()

        toolbox_card = self._make_card(
            "图片工具箱",
            "裁剪 / 旋转 / 翻转\n水印 / 压缩 / 格式转换",
            enabled=True,
            width=220,
            height=170,
            icon_pix=QStyle.StandardPixmap.SP_DialogSaveButton,
        )
        toolbox_card.mousePressEvent = lambda e: self.toolbox_requested.emit()

        cards_bottom.addWidget(toolbox_card)
        cards_bottom.addStretch()
        layout.addLayout(cards_bottom)

        # 套餐区
        plans_title = QLabel("购买套餐")
        plans_title.setObjectName("homeSubtitle")
        plans_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(plans_title)
        self._plans_row = QHBoxLayout()
        self._plans_row.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._plans_row.setSpacing(12)
        layout.addLayout(self._plans_row)

        if self._payment_client is not None:
            QTimer.singleShot(0, self._load_plans)

    def _load_plans(self) -> None:
        if self._task_runner is not None:
            self._task_runner.submit(
                self._payment_client.list_plans,
                self._plans_loaded,
                self._plans_failed,
            )
            return
        try:
            self.set_plans(self._payment_client.list_plans())
        except Exception:
            pass

    def _plans_loaded(self, result) -> None:
        if isinstance(result, list):
            self.set_plans(result)

    def _plans_failed(self, error) -> None:
        while self._plans_row.count():
            item = self._plans_row.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        note = QLabel(f"套餐加载失败：{error}")
        note.setObjectName("homeCardDesc")
        note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._plans_row.addWidget(note)

    def set_plans(self, plans) -> None:
        while self._plans_row.count():
            item = self._plans_row.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        for plan in plans:
            self._plans_row.addWidget(self._make_plan_card(plan))
        if not plans:
            note = QLabel("暂无可购买套餐")
            note.setObjectName("homeCardDesc")
            note.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._plans_row.addWidget(note)

    def _make_plan_card(self, plan):
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

    def _make_card(
        self,
        title_text: str,
        desc: str,
        enabled: bool,
        width: int = 260,
        height: int = 200,
        icon_pix: QStyle.StandardPixmap | None = None,
    ) -> QFrame:
        card = QFrame()
        card.setObjectName("homeCard")
        card.setProperty("editorStyle", True)
        card.setFixedSize(width, height)
        card.setCursor(
            Qt.CursorShape.PointingHandCursor
            if enabled
            else Qt.CursorShape.ForbiddenCursor
        )
        card.setEnabled(enabled)

        inner = QVBoxLayout(card)
        inner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        inner.setSpacing(16)

        if icon_pix is None:
            icon_pix = (
                QStyle.StandardPixmap.SP_FileDialogContentsView
                if enabled
                else QStyle.StandardPixmap.SP_ComputerIcon
            )
        icon_label = QLabel()
        icon_label.setPixmap(standard_icon(icon_pix).pixmap(36, 36))
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        t = QLabel(title_text)
        t.setObjectName("homeCardTitle")
        t.setAlignment(Qt.AlignmentFlag.AlignCenter)

        d = QLabel(desc)
        d.setObjectName("homeCardDesc" if enabled else "homeCardDisabled")
        d.setAlignment(Qt.AlignmentFlag.AlignCenter)
        d.setWordWrap(True)

        inner.addWidget(icon_label)
        inner.addWidget(t)
        inner.addWidget(d)

        return card
