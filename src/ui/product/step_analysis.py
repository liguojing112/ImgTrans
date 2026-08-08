"""第2步：AI 商品分析页 — OCR 结果 + 图片理解 + 事实编辑器。"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from src.domain.product_info import (
    ImageUnderstanding,
    ProductAnalysisResult,
    ProductFact,
)


class StepAnalysis(QFrame):
    """第2步：AI 商品分析。"""

    analyze_requested = Signal()
    fact_changed = Signal(str, str)  # field_name, value
    fact_confirmed = Signal(str)
    fact_uncertain = Signal(str)
    next_requested = Signal()
    prev_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setProperty("editorStyle", True)
        self._fact: ProductFact | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 16, 24, 16)
        layout.setSpacing(16)

        # 标题行
        header = QHBoxLayout()
        title = QLabel("第 2 步：AI 商品分析")
        title.setObjectName("sectionTitle")
        header.addWidget(title)
        header.addStretch()

        self._analyze_btn = QPushButton("⚡ 开始分析")
        self._analyze_btn.setObjectName("primaryButton")
        self._analyze_btn.setStyleSheet(
            "QPushButton#primaryButton {"
            "  background: qlineargradient(x1:0, y1:0, x2:0, y2:1,"
            "  stop:0 #4a8af4, stop:1 #3973db);"
            "  color: #ffffff; border: 1px solid #5a9af4;"
            "  border-radius: 8px; padding: 8px 20px;"
            " font-weight: 600;"
            "}"
            "QPushButton#primaryButton:hover {"
            "  background: qlineargradient(x1:0, y1:0, x2:0, y2:1,"
            "  stop:0 #5a9af4, stop:1 #4a8af4);"
            "  border-color: #6aaaf4;"
            "}"
            "QPushButton#primaryButton:disabled { background: #ffffff; color: #98a0ad;"
            "  border-color: #d5d9e0; }"
        )
        self._analyze_btn.clicked.connect(self.analyze_requested.emit)
        header.addWidget(self._analyze_btn)
        layout.addLayout(header)

        # 内容区
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # 左侧：OCR + 图片理解
        left = QScrollArea()
        left.setWidgetResizable(True)
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setSpacing(12)

        self._ocr_group = QGroupBox("OCR 文字识别")
        ocr_layout = QVBoxLayout(self._ocr_group)
        self._ocr_text = QPlainTextEdit()
        self._ocr_text.setPlaceholderText("分析后将显示图片中识别的文字...")
        self._ocr_text.setMaximumHeight(200)
        ocr_layout.addWidget(self._ocr_text)
        left_layout.addWidget(self._ocr_group)

        self._vision_group = QGroupBox("图片内容理解")
        vision_layout = QVBoxLayout(self._vision_group)
        self._vision_content = QLabel("分析后将显示图片内容理解结果...")
        self._vision_content.setWordWrap(True)
        self._vision_content.setStyleSheet("color: #626b7a;")
        vision_layout.addWidget(self._vision_content)
        left_layout.addWidget(self._vision_group)

        left_layout.addStretch()
        left.setWidget(left_widget)
        splitter.addWidget(left)

        # 右侧：事实编辑器
        right = QFrame()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(8, 0, 0, 0)
        right_layout.addWidget(QLabel("商品事实信息 — 逐项确认"))
        from src.ui.product.widgets.fact_editor import FactEditor
        self._fact_editor = FactEditor()
        self._fact_editor.fact_changed.connect(self.fact_changed.emit)
        self._fact_editor.fact_confirmed.connect(self.fact_confirmed.emit)
        self._fact_editor.fact_uncertain.connect(self.fact_uncertain.emit)
        right_layout.addWidget(self._fact_editor, stretch=1)
        splitter.addWidget(right)

        splitter.setSizes([350, 500])
        layout.addWidget(splitter, stretch=1)

        # 底部按钮
        btn_layout = QHBoxLayout()
        prev_btn = QPushButton("← 上一步")
        prev_btn.clicked.connect(self.prev_requested.emit)
        btn_layout.addWidget(prev_btn)
        btn_layout.addStretch()
        self._next_btn = QPushButton("下一步：生成文案 →")
        self._next_btn.setStyleSheet(
            "QPushButton {"
            "  background: qlineargradient(x1:0, y1:0, x2:0, y2:1,"
            "  stop:0 #4a8af4, stop:1 #3973db);"
            "  color: #ffffff; border: 1px solid #5a9af4;"
            "  border-radius: 8px; padding: 10px 24px;"
            " font-weight: 600;"
            "}"
            "QPushButton:hover {"
            "  background: qlineargradient(x1:0, y1:0, x2:0, y2:1,"
            "  stop:0 #5a9af4, stop:1 #4a8af4);"
            "  border-color: #6aaaf4;"
            "}"
        )
        self._next_btn.clicked.connect(self.next_requested.emit)
        btn_layout.addWidget(self._next_btn)
        layout.addLayout(btn_layout)

    # —— 公开接口 ——

    def set_analyzing(self, active: bool) -> None:
        self._analyze_btn.setEnabled(not active)
        self._analyze_btn.setText("⏳ 分析中..." if active else "⚡ 开始分析")

    def set_result(self, result: ProductAnalysisResult) -> None:
        self._ocr_text.setPlainText(result.ocr_text or "(未识别到文字)")

        # 图片理解
        u = result.image_understanding
        if u and (u.category or u.appearance or u.main_colors or u.packaging or u.usage_scene):
            lines = []
            if u.category:
                lines.append(f"类别: {u.category}")
            if u.appearance:
                lines.append(f"外观: {u.appearance}")
            if u.main_colors:
                lines.append(f"主要颜色: {'、'.join(u.main_colors)}")
            if u.packaging:
                lines.append(f"包装: {u.packaging}")
            if u.visible_accessories:
                lines.append(f"可见配件: {'、'.join(u.visible_accessories)}")
            if u.usage_scene:
                lines.append(f"使用场景: {u.usage_scene}")
            if u.visual_style:
                lines.append(f"视觉风格: {u.visual_style}")
            if u.background:
                lines.append(f"背景: {u.background}")
            self._vision_content.setText("\n".join(lines))
            self._vision_content.setStyleSheet("color: #626b7a;")
        else:
            self._vision_content.setText(
                "暂无图片理解结果\n\n"
                "提示: 请检查 LLM 提供商设置是否正确。\n"
                "当前使用的提供商和模型可能不支持 Vision 功能或 API Key 无效。"
            )
            self._vision_content.setStyleSheet("color: #d97706;")

        # 事实编辑
        if result.product_fact:
            self._fact = result.product_fact
            self._fact_editor.set_fact(result.product_fact)

    def set_error(self, message: str) -> None:
        self._ocr_text.setPlainText("")
        self._vision_content.setText(f"分析失败:\n{message}")
        self._vision_content.setStyleSheet("color: #dc2626;")

    def current_fact(self) -> ProductFact | None:
        return self._fact
