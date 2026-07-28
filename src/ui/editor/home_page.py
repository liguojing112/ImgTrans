"""首页 — 两个入口卡片。"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
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
    """首页，提供"图片翻译"和"商品详情生成"两个入口。"""

    image_translation_requested = Signal()
    product_detail_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setProperty("editorStyle", True)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(32)

        # 标题区域
        title_group = QVBoxLayout()
        title_group.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_group.setSpacing(8)

        title = QLabel("ImgTrans 图片翻译")
        title.setObjectName("homeTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        subtitle = QLabel("高效本地化您的产品图片")
        subtitle.setObjectName("homeSubtitle")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)

        title_group.addWidget(title)
        title_group.addWidget(subtitle)
        layout.addLayout(title_group)

        # 两张入口卡片
        cards = QHBoxLayout()
        cards.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cards.setSpacing(24)

        translate_card = self._make_card(
            "图片翻译",
            "识别 / 翻译 / 渲染\n将图片中文字翻译为多语言并回填",
            enabled=True,
        )
        translate_card.mousePressEvent = lambda _: self.image_translation_requested.emit()

        detail_card = self._make_card(
            "商品详情生成",
            "敬请期待",
            enabled=False,
        )

        cards.addWidget(translate_card)
        cards.addWidget(detail_card)
        layout.addLayout(cards)

    def _make_card(self, title_text: str, desc: str, enabled: bool) -> QFrame:
        card = QFrame()
        card.setObjectName("homeCard")
        card.setProperty("editorStyle", True)
        card.setFixedSize(260, 200)
        card.setCursor(
            Qt.CursorShape.PointingHandCursor
            if enabled
            else Qt.CursorShape.ForbiddenCursor
        )
        card.setEnabled(enabled)

        inner = QVBoxLayout(card)
        inner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        inner.setSpacing(16)

        icon_pix = QStyle.StandardPixmap.SP_FileDialogContentsView if enabled else QStyle.StandardPixmap.SP_ComputerIcon
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
