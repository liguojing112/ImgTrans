"""第3步：文案生成页 — 设置面板 + 文案内容区。

使用专用编辑器组件（TagEditor / KeywordEditor / TitleEditor / SellingPointEditor）
替换原始 QListWidget，并集成 CopywritingSettingsPanel。
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from src.domain.copywriting import (
    CopywritingResult,
    CopywritingSettings,
    ProductIntro,
)
from src.ui.product.widgets.copywriting_editors import (
    KeywordEditor,
    SellingPointEditor,
    TagEditor,
    TitleEditor,
)
from src.ui.product.widgets.copywriting_settings import CopywritingSettingsPanel


class StepCopywriting(QFrame):
    """第3步：文案生成。"""

    generate_all_requested = Signal()
    generate_tags_requested = Signal()
    generate_keywords_requested = Signal()
    generate_titles_requested = Signal()
    generate_selling_points_requested = Signal()
    generate_intro_requested = Signal()
    generate_detail_requested = Signal(str)  # section
    regenerate_item_requested = Signal(str, str)  # item_type, item_id
    export_txt_requested = Signal(str)
    export_json_requested = Signal(str)
    export_csv_requested = Signal(str)
    prev_requested = Signal()
    finish_requested = Signal()
    settings_changed = Signal(object)  # CopywritingSettings
    # 编辑器交互信号
    tag_added = Signal(str)           # text
    keyword_added = Signal(str, str)  # keyword, meaning
    title_added = Signal(str)         # title text
    item_changed = Signal(str, str, str)  # item_type, item_id, new_value

    def __init__(self) -> None:
        super().__init__()
        self.setProperty("editorStyle", True)
        self._result: CopywritingResult | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 16, 24, 16)
        layout.setSpacing(16)

        # 标题行
        header = QHBoxLayout()
        title = QLabel("第 3 步：文案生成")
        title.setStyleSheet("color: #212733; font-size: 18px; font-weight: 650;")
        header.addWidget(title)
        header.addStretch()

        self._generate_btn = QPushButton(" 生成全部文案")
        self._generate_btn.setObjectName("primaryButton")
        self._generate_btn.setStyleSheet(
            "QPushButton#primaryButton {"
            "  background: qlineargradient(x1:0, y1:0, x2:0, y2:1,"
            "  stop:0 #4a8af4, stop:1 #3973db);"
            "  color: #ffffff; border: 1px solid #5a9af4;"
            "  border-radius: 8px; padding: 8px 20px;"
            "  font-size: 13px; font-weight: 600;"
            "}"
            "QPushButton#primaryButton:hover {"
            "  background: qlineargradient(x1:0, y1:0, x2:0, y2:1,"
            "  stop:0 #5a9af4, stop:1 #4a8af4);"
            "  border-color: #6aaaf4;"
            "}"
            "QPushButton#primaryButton:disabled { background: #ffffff; color: #98a0ad;"
            "  border-color: #d5d9e0; }"
        )
        self._generate_btn.clicked.connect(self.generate_all_requested.emit)
        header.addWidget(self._generate_btn)
        layout.addLayout(header)

        # 内容区 — 左：文案内容 | 中：详情文案 | 右：设置面板
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setStyleSheet(
            "QSplitter::handle { background: #ffffff; width: 2px; }"
        )

        # ── 左侧：文案内容 ──
        left = QScrollArea()
        left.setWidgetResizable(True)
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 8, 0)
        left_layout.setSpacing(8)

        self._tab_group = QGroupBox("文案内容")
        tab_layout = QVBoxLayout(self._tab_group)
        self._content_tabs = QTabWidget()
        self._content_tabs.setObjectName("copywritingTabs")

        self._tag_editor = TagEditor()
        self._content_tabs.addTab(self._tag_editor, "图片标签")

        self._kw_editor = KeywordEditor()
        self._content_tabs.addTab(self._kw_editor, "长尾场景词")

        self._title_editor = TitleEditor()
        self._content_tabs.addTab(self._title_editor, "产品标题")

        self._sp_editor = SellingPointEditor()
        self._content_tabs.addTab(self._sp_editor, "商品卖点")

        tab_layout.addWidget(self._content_tabs)
        left_layout.addWidget(self._tab_group, stretch=2)

        # 简介
        intro_group = QGroupBox("商品简介")
        intro_layout = QVBoxLayout(intro_group)
        # 简介按钮栏
        intro_btns = QHBoxLayout()
        intro_copy = QPushButton("复制简介")
        intro_copy.clicked.connect(self._copy_intro)
        intro_regen = QPushButton("重新生成简介")
        self._intro_regen_btn = intro_regen
        intro_regen.clicked.connect(self.generate_intro_requested.emit)
        intro_btns.addStretch()
        intro_btns.addWidget(intro_copy)
        intro_btns.addWidget(intro_regen)
        intro_layout.addLayout(intro_btns)
        self._intro_tabs = QTabWidget()
        self._one_liner = QPlainTextEdit()
        self._one_liner.setPlaceholderText("一句话简介...")
        self._intro_tabs.addTab(self._one_liner, "一句话简介")
        self._short_desc = QPlainTextEdit()
        self._short_desc.setPlaceholderText("短描述...")
        self._intro_tabs.addTab(self._short_desc, "短描述")
        self._standard = QPlainTextEdit()
        self._standard.setPlaceholderText("标准简介...")
        self._intro_tabs.addTab(self._standard, "标准简介")
        intro_layout.addWidget(self._intro_tabs)
        left_layout.addWidget(intro_group, stretch=1)

        left.setWidget(left_widget)
        splitter.addWidget(left)

        # ── 中间：详情文案 ──
        mid = QScrollArea()
        mid.setWidgetResizable(True)
        mid_widget = QWidget()
        mid_layout = QVBoxLayout(mid_widget)
        mid_layout.setContentsMargins(8, 0, 8, 0)
        mid_layout.setSpacing(8)

        self._detail_group = QGroupBox("详情文案")
        detail_layout = QVBoxLayout(self._detail_group)
        self._detail_tabs = QTabWidget()
        self._detail_editors: dict[str, QPlainTextEdit] = {}
        self._detail_copy_btns: dict[str, QPushButton] = {}
        self._detail_regen_btns: dict[str, QPushButton] = {}
        sections = [
            ("overview", "产品概述"),
            ("advantages", "核心优势"),
            ("functions", "功能介绍"),
            ("scenes", "使用场景"),
            ("specs", "规格参数"),
            ("packing", "包装清单"),
            ("instructions", "使用说明"),
            ("notes", "注意事项"),
        ]
        for sec, label in sections:
            sec_widget = QWidget()
            sec_layout = QVBoxLayout(sec_widget)
            sec_layout.setContentsMargins(0, 0, 0, 0)
            sec_layout.setSpacing(4)

            sec_btns = QHBoxLayout()
            copy_btn = QPushButton("复制此节")
            copy_btn.setFixedSize(72, 22)
            copy_btn.setStyleSheet(
                "QPushButton { background: #eef0f4; color: #a0a0c0; font-size: 11px;"
                "  border: 1px solid #d5d9e0; border-radius: 3px; }"
                "QPushButton:hover { background: #4d4d6e; }"
            )
            copy_btn.clicked.connect(lambda checked=False, s=sec: self._copy_section(s))
            self._detail_copy_btns[sec] = copy_btn

            regen_btn = QPushButton("重新生成此节")
            regen_btn.setFixedSize(88, 22)
            regen_btn.setStyleSheet(
                "QPushButton { background: #eef0f4; color: #a0a0c0; font-size: 11px;"
                "  border: 1px solid #d5d9e0; border-radius: 3px; }"
                "QPushButton:hover { background: #4d4d6e; }"
            )
            regen_btn.clicked.connect(
                lambda checked=False, s=sec: self.generate_detail_requested.emit(s)
            )
            self._detail_regen_btns[sec] = regen_btn

            sec_btns.addStretch()
            sec_btns.addWidget(copy_btn)
            sec_btns.addWidget(regen_btn)
            sec_layout.addLayout(sec_btns)

            editor = QPlainTextEdit()
            editor.setPlaceholderText(f"生成 {label}...")
            sec_layout.addWidget(editor)
            self._detail_tabs.addTab(sec_widget, label)
            self._detail_editors[sec] = editor

        detail_layout.addWidget(self._detail_tabs)
        mid_layout.addWidget(self._detail_group, stretch=1)

        # 导出
        export_group = QGroupBox("导出")
        export_layout = QHBoxLayout(export_group)
        txt_btn = QPushButton("导出 TXT")
        txt_btn.clicked.connect(lambda: self.export_txt_requested.emit(""))
        json_btn = QPushButton("导出 JSON")
        json_btn.clicked.connect(lambda: self.export_json_requested.emit(""))
        csv_btn = QPushButton("导出 CSV")
        csv_btn.clicked.connect(lambda: self.export_csv_requested.emit(""))
        export_layout.addWidget(txt_btn)
        export_layout.addWidget(json_btn)
        export_layout.addWidget(csv_btn)
        mid_layout.addWidget(export_group)

        mid.setWidget(mid_widget)
        splitter.addWidget(mid)

        # ── 右侧：设置面板 ──
        self._settings_panel = CopywritingSettingsPanel()
        self._settings_panel.settings_changed.connect(self.settings_changed.emit)
        splitter.addWidget(self._settings_panel)

        splitter.setSizes([400, 300, 250])
        layout.addWidget(splitter, stretch=1)

        # 底部按钮
        btn_layout = QHBoxLayout()
        prev_btn = QPushButton("← 上一步")
        prev_btn.clicked.connect(self.prev_requested.emit)
        btn_layout.addWidget(prev_btn)
        btn_layout.addStretch()
        finish_btn = QPushButton("完成")
        finish_btn.setStyleSheet(
            "QPushButton {"
            "  background: qlineargradient(x1:0, y1:0, x2:0, y2:1,"
            "  stop:0 #4a8af4, stop:1 #3973db);"
            "  color: #ffffff; border: 1px solid #5a9af4;"
            "  border-radius: 8px; padding: 10px 24px;"
            "  font-size: 14px; font-weight: 600;"
            "}"
            "QPushButton:hover {"
            "  background: qlineargradient(x1:0, y1:0, x2:0, y2:1,"
            "  stop:0 #5a9af4, stop:1 #4a8af4);"
            "  border-color: #6aaaf4;"
            "}"
        )
        finish_btn.clicked.connect(self.finish_requested.emit)
        btn_layout.addWidget(finish_btn)
        layout.addLayout(btn_layout)

        self._connect_editor_signals()

    # —— 编辑器信号接线 ——

    def _connect_editor_signals(self) -> None:
        self._tag_editor.regenerate_requested.connect(self.generate_tags_requested.emit)
        self._kw_editor.regenerate_requested.connect(self.generate_keywords_requested.emit)
        self._title_editor.regenerate_requested.connect(self.generate_titles_requested.emit)
        self._sp_editor.regenerate_requested.connect(self.generate_selling_points_requested.emit)

        self._tag_editor.item_edited.connect(
            lambda tid, t: self.item_changed.emit("tag", tid, t))
        self._kw_editor.item_edited.connect(
            lambda kid, k, m: self.item_changed.emit("keyword", kid, k))
        self._title_editor.item_edited.connect(
            lambda tid, t: self.item_changed.emit("title", tid, t))
        self._sp_editor.item_edited.connect(
            lambda sid, t: self.item_changed.emit("selling_point", sid, t))

        self._tag_editor.item_deleted.connect(
            lambda tid: self.item_changed.emit("tag_delete", tid, ""))
        self._kw_editor.item_deleted.connect(
            lambda kid: self.item_changed.emit("keyword_delete", kid, ""))
        self._title_editor.item_deleted.connect(
            lambda tid: self.item_changed.emit("title_delete", tid, ""))
        self._sp_editor.item_deleted.connect(
            lambda sid: self.item_changed.emit("selling_point_delete", sid, ""))

        self._sp_editor.item_locked.connect(
            lambda sid: self.item_changed.emit("selling_point_lock", sid, ""))

    # —— 公开接口 ——

    def settings(self) -> CopywritingSettings:
        return self._settings_panel.get_settings()

    def set_generating(self, active: bool) -> None:
        self._generate_btn.setEnabled(not active)
        self._generate_btn.setText("⏳ 生成中..." if active else "⚡ 生成全部文案")

    def set_regeneration_active(self, item_type: str, active: bool) -> None:
        """Disable the button that owns an in-flight API request."""
        if item_type == "intro":
            self._intro_regen_btn.setEnabled(not active)
        elif item_type.startswith("detail:"):
            section = item_type.split(":", 1)[1]
            button = self._detail_regen_btns.get(section)
            if button is not None:
                button.setEnabled(not active)

    def set_result(self, result: CopywritingResult) -> None:
        self._result = result

        self._tag_editor.set_tags(result.tags)
        self._kw_editor.set_keywords(result.keywords)
        self._title_editor.set_titles(result.titles)
        self._sp_editor.set_selling_points(result.selling_points)

        if result.intro:
            self._one_liner.setPlainText(result.intro.one_liner)
            self._short_desc.setPlainText(result.intro.short_description)
            self._standard.setPlainText(result.intro.standard_intro)

        for mod in result.detail_modules:
            editor = self._detail_editors.get(mod.section)
            if editor:
                editor.setPlainText(mod.content)

    def set_error(self, message: str) -> None:
        pass

    def collect_result(self, result: CopywritingResult) -> CopywritingResult:
        result.intro = ProductIntro(
            one_liner=self._one_liner.toPlainText().strip() or (
                result.intro.one_liner if result.intro else ""
            ),
            short_description=self._short_desc.toPlainText().strip() or (
                result.intro.short_description if result.intro else ""
            ),
            standard_intro=self._standard.toPlainText().strip() or (
                result.intro.standard_intro if result.intro else ""
            ),
        )
        for sec, editor in self._detail_editors.items():
            text = editor.toPlainText().strip()
            if text:
                for mod in result.detail_modules:
                    if mod.section == sec:
                        mod.content = text
                        break
        return result

    # —— 内部操作 ——

    def _copy_intro(self) -> None:
        parts = []
        for label, editor in [
            ("一句话简介", self._one_liner),
            ("短描述", self._short_desc),
            ("标准简介", self._standard),
        ]:
            text = editor.toPlainText().strip()
            if text:
                parts.append(f"{label}: {text}")
        if parts:
            QApplication.clipboard().setText("\n\n".join(parts))

    def _copy_section(self, section: str) -> None:
        editor = self._detail_editors.get(section)
        if editor:
            text = editor.toPlainText().strip()
            if text:
                QApplication.clipboard().setText(text)
