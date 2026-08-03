"""首页 — 三个入口卡片（倒品字形布局）。"""

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
    """首页，提供"图片翻译"、"商品详情生成"和"图片工具箱"三个入口。"""

    image_translation_requested = Signal()
    product_detail_requested = Signal()
    toolbox_requested = Signal()

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
