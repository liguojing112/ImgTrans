"""第3步：文案生成页 — 设置面板 + 文案内容区。

使用专用编辑器组件（TagEditor / KeywordEditor / TitleEditor / SellingPointEditor）
替换原始 QListWidget，并集成 CopywritingSettingsPanel。
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
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
        title.setObjectName("sectionTitle")
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

        # 商品图片列表（商品来源同款长条样式，固定预留 4 行，无竖直滚动条）
        self._source_list = QListWidget()
        self._source_list.setObjectName("copywritingSourceList")
        self._source_list.setIconSize(QSize(44, 44))
        self._source_list.setFixedHeight(140)
        self._source_list.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._source_list.currentRowChanged.connect(self._on_source_row_changed)
        intro_layout.addWidget(self._source_list)
        left_layout.addWidget(intro_group, stretch=1)
        # 每图独立文案结果
        self._copywriting_results: dict = {}
        self._current_result_index = 0

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
        self._detail_sections = [
            ("overview", "产品概述"),
            ("advantages", "核心优势"),
            ("functions", "功能介绍"),
            ("scenes", "使用场景"),
            ("specs", "规格参数"),
            ("packing", "包装清单"),
            ("instructions", "使用说明"),
            ("notes", "注意事项"),
        ]
        # 标签：两行横排（4 x 2），点击切换共用内容区
        self._detail_contents: dict[str, str] = {}
        self._detail_buttons: dict[str, QPushButton] = {}
        self._detail_btn_group = QButtonGroup(self)
        self._detail_btn_group.setExclusive(True)
        tag_grid = QGridLayout()
        tag_grid.setSpacing(4)
        tag_style = (
            "QPushButton { background: #eef0f4; color: #212733;"
            "  border: 1px solid #d5d9e0; border-radius: 4px;"
            "  padding: 4px 8px; }"
            "QPushButton:hover { background: #e0e4ec; }"
            "QPushButton:checked { background: #3973db; color: #ffffff;"
            "  border-color: #3973db; }"
        )
        for index, (sec, label) in enumerate(self._detail_sections):
            button = QPushButton(label)
            button.setCheckable(True)
            button.setStyleSheet(tag_style)
            button.clicked.connect(
                lambda checked=False, s=sec: self._switch_detail_section(s)
            )
            self._detail_buttons[sec] = button
            self._detail_btn_group.addButton(button)
            tag_grid.addWidget(button, index // 4, index % 4)
        detail_layout.addLayout(tag_grid)

        # 操作按钮（针对当前选中区块）
        detail_ops = QHBoxLayout()
        detail_ops.setSpacing(6)
        self._detail_copy_btn = QPushButton("复制此节")
        self._detail_copy_btn.setFixedSize(90, 30)
        self._detail_copy_btn.setStyleSheet(
            "QPushButton { background: #eef0f4; color: #212733;"
            "  border: 1px solid #d5d9e0; border-radius: 4px; }"
            "QPushButton:hover { background: #e0e4ec; }"
        )
        self._detail_copy_btn.clicked.connect(self._copy_current_section)
        self._detail_regen_btn = QPushButton("重新生成此节")
        self._detail_regen_btn.setFixedSize(110, 30)
        self._detail_regen_btn.setStyleSheet(
            "QPushButton { background: #eef0f4; color: #212733;"
            "  border: 1px solid #d5d9e0; border-radius: 4px; }"
            "QPushButton:hover { background: #e0e4ec; }"
        )
        self._detail_regen_btn.clicked.connect(self._regen_current_section)
        detail_ops.addWidget(self._detail_copy_btn)
        detail_ops.addWidget(self._detail_regen_btn)
        detail_ops.addStretch()
        detail_layout.addLayout(detail_ops)

        # 共用内容区
        self._detail_editor = QPlainTextEdit()
        self._detail_editor.setPlaceholderText("生成详情文案...")
        detail_layout.addWidget(self._detail_editor, stretch=1)

        self._current_detail_section = "overview"
        self._detail_buttons["overview"].setChecked(True)
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

        # ── 右侧：设置面板（习惯设置持久化到用户配置） ──
        from src.platform.paths import PlatformPaths

        prefs_path = (
            PlatformPaths.discover().data_dir
            / "config"
            / "copywriting-preferences.json"
        )
        self._settings_panel = CopywritingSettingsPanel(prefs_path)
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
            " font-weight: 600;"
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

    def set_source_images(self, paths: list, image_info: list | None = None) -> None:
        """显示商品图片列表（商品简介下方，长条列表样式）。

        多图独立文案时：点击图片切换显示该图的文案结果。
        """
        del image_info
        from PySide6.QtGui import QIcon, QPixmap

        self._source_list.blockSignals(True)
        self._source_list.clear()
        for path in paths[:3]:
            name = str(path)
            item = QListWidgetItem(name.rsplit("/", 1)[-1])
            pixmap = QPixmap(name)
            if not pixmap.isNull():
                item.setIcon(
                    QIcon(
                        pixmap.scaled(
                            40, 40,
                            Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation,
                        )
                    )
                )
            item.setToolTip(name)
            self._source_list.addItem(item)
        self._source_list.blockSignals(False)
        if self._source_list.count():
            self._source_list.setCurrentRow(0)

    @property
    def current_result_index(self) -> int:
        return getattr(self, "_current_result_index", 0)

    def set_results(self, results: dict) -> None:
        """设置每图独立文案结果；点击图片列表切换显示对应图的那套。"""
        self._copywriting_results = results
        if not results:
            return
        self._current_result_index = 0
        self.set_result(results.get(0))
        if self._source_list.count() == 0:
            return
        self._source_list.setCurrentRow(0)
        if self._source_list.count() > 1:
            self._source_list.setToolTip("点击切换查看每张图片的文案")

    def _on_source_row_changed(self, row: int) -> None:
        """点击图片 → 切换显示该图的独立文案。"""
        if not getattr(self, "_copywriting_results", None) or row < 0:
            return
        if row >= len(self._copywriting_results):
            return
        self._save_current_edits()
        self._current_result_index = row
        self.set_result(self._copywriting_results.get(row))

    def _save_current_edits(self) -> None:
        """把当前编辑中的文案写回对应图片的结果。"""
        if not getattr(self, "_copywriting_results", None):
            return
        index = getattr(self, "_current_result_index", 0)
        current = self._copywriting_results.get(index)
        if current is not None:
            self._copywriting_results[index] = self.collect_result(current)

    def set_regeneration_active(self, item_type: str, active: bool) -> None:
        """Disable the button that owns an in-flight API request."""
        if item_type == "intro":
            self._intro_regen_btn.setEnabled(not active)
        elif item_type.startswith("detail:"):
            self._detail_regen_btn.setEnabled(not active)

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
            self._detail_contents[mod.section] = mod.content
        # 刷新当前选中的区块内容
        self._detail_editor.setPlainText(
            self._detail_contents.get(self._current_detail_section, "")
        )

    def set_error(self, message: str) -> None:
        pass

    def collect_result(self, result: CopywritingResult) -> CopywritingResult:
        # 保存当前编辑中的内容，避免切换区块时丢失
        self._detail_contents[self._current_detail_section] = (
            self._detail_editor.toPlainText()
        )
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
        for sec, text in self._detail_contents.items():
            text = text.strip()
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

    def _switch_detail_section(self, section: str) -> None:
        """切换详情区块：保存当前编辑内容，加载目标区块内容。"""
        self._detail_contents[self._current_detail_section] = (
            self._detail_editor.toPlainText()
        )
        self._current_detail_section = section
        self._detail_editor.setPlainText(
            self._detail_contents.get(section, "")
        )

    def _copy_current_section(self) -> None:
        text = self._detail_editor.toPlainText().strip()
        if text:
            QApplication.clipboard().setText(text)

    def _regen_current_section(self) -> None:
        self.generate_detail_requested.emit(self._current_detail_section)
