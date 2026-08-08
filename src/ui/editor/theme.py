"""图片翻译编辑器 — 深色主题 QSS 样式表。

使用属性选择器 [editorStyle="true"] 与生产 UI 的 _STYLE 隔离，
避免 QSS 级联冲突。
"""

# === 首页卡片样式 ===
HOME_CARD_STYLE = """
QFrame#homeCard {
    background: #ffffff;
    border: 1px solid #d5d9e0;
    border-radius: 16px;
    padding: 24px;
}
QFrame#homeCard:hover {
    border-color: #3973db;
    background: #eef2f8;
}
QFrame#homeCard:disabled {
    background: #f8f9fb;
    border-color: #2e2e48;
}
QFrame#homeCard:disabled:hover {
    border-color: #2e2e48;
}
QLabel#homeCardTitle {
    color: #212733;
    font-size: 18px;
    font-weight: 600;
}
QLabel#homeCardDesc {
    color: #000000;
    font-size: 12px;
}
QLabel#homeCardDisabled {
    color: #98a0ad;
    font-size: 12px;
}
"""

# === 深色编辑器主题 ===
EDITOR_DARK_THEME = """
/* 根背景 */
QMainWindow[editorStyle="true"], QWidget[editorStyle="true"] {
    background: #f4f5f7;
    color: #212733;
    font-family: "Segoe UI", "Microsoft YaHei", sans-serif;
}

/* === Typography tokens（统一字体层级） === */
QLabel#pageTitle {
    color: #212733;
    font-size: 22px;
    font-weight: 700;
}
QLabel#sectionTitle {
    color: #212733;
    font-size: 18px;
    font-weight: 600;
}
QLabel#groupTitle {
    color: #212733;
    font-size: 15px;
    font-weight: 600;
}
QLabel#fieldLabel {
    color: #212733;
    font-size: 14px;
    font-weight: 500;
}
QLabel#captionLabel {
    color: #000000;
    font-size: 12px;
    font-weight: 400;
}
QGroupBox {
    font-size: 15px;
    font-weight: 600;
}
/* 默认字体（Body）— 控件未显式分级时统一 14px */
QLabel[editorStyle="true"] {
    font-size: 14px;
    font-weight: 500;
}
QPushButton[editorStyle="true"] {
    font-size: 14px;
}

/* 首页标题 */
QLabel#homeTitle {
    color: #212733;
    font-size: 22px;
    font-weight: 700;
}
QLabel#homeSubtitle {
    color: #000000;
    font-size: 12px;
}

/* 首页卡片 */
QFrame[editorStyle="true"]#homeCard {
    background: #ffffff;
    border: 1px solid #d5d9e0;
    border-radius: 16px;
}
QFrame[editorStyle="true"]#homeCard:hover {
    border-color: #3973db;
    background: #eef2f8;
}
QLabel#homeCardTitle {
    color: #212733;
    font-size: 18px;
    font-weight: 600;
}
QLabel#homeCardDesc {
    color: #000000;
    font-size: 12px;
}

/* 工具栏 */
QFrame#editorToolBar {
    background: #ffffff;
    border-right: 1px solid #d5d9e0;
}
QFrame#textListPanel {
    background: #f8f9fb;
    border-right: 1px solid #d5d9e0;
}
QFrame#editorRightPanel {
    background: #ffffff;
    border-left: 1px solid #d5d9e0;
}
QSplitter::handle {
    background: #d5d9e0;
    width: 2px;
}
QSplitter::handle:hover {
    background: #3973db;
}
QPushButton#toolButton {
    background: transparent;
    color: #000000;
    border: none;
    border-radius: 8px;
    padding: 4px;
    min-width: 36px;
    min-height: 36px;
}
QPushButton#toolButton:hover {
    background: #eef0f4;
    color: #212733;
}
QPushButton#toolButton:checked {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 #4a8af4, stop:1 #3973db);
    color: #ffffff;
    border: 1px solid #5a9af4;
}

/* 画布区域 */
QGraphicsView#editorCanvas {
    background: #e6e8ec;
    border: none;
}

QTabWidget#editorRightTabs::pane {
    border: none;
    border-top: 1px solid #d5d9e0;
    background: #ffffff;
}
QTabWidget#editorRightTabs QTabBar::tab {
    background: #f8f9fb;
    color: #000000;
    border: none;
    padding: 9px 8px;
    min-width: 58px;
}
QTabWidget#editorRightTabs QTabBar::tab:selected {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 #4a8af4, stop:1 #3973db);
    color: #ffffff;
    border: 1px solid #5a9af4;
    border-bottom: none;
    font-weight: 600;
}
QTabWidget#editorRightTabs QTabBar::tab:hover:!selected {
    background: #eef0f4;
    color: #212733;
}

/* 属性面板 */
QFrame#propertyPanel {
    background: #ffffff;
    border-left: 1px solid #d5d9e0;
}
QLabel#propertyTitle {
    color: #212733;
    font-size: 18px;
    font-weight: 600;
}
QLabel#propertyFieldLabel {
    color: #212733;
    font-size: 14px;
    font-weight: 500;
}
QLabel#propertyNoSelection {
    color: #98a0ad;
    font-size: 12px;
}
QDoubleSpinBox, QSpinBox, QComboBox, QPlainTextEdit {
    background: #eef0f4;
    color: #212733;
    border: 1px solid #d5d9e0;
    border-radius: 6px;
    padding: 6px;
}
QDoubleSpinBox:focus, QSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus {
    border-color: #3973db;
}
QComboBox::drop-down {
    border: none;
    background: #ffffff;
    border-radius: 0 6px 6px 0;
    width: 20px;
}
QComboBox QAbstractItemView {
    background: #eef0f4;
    color: #212733;
    border: 1px solid #d5d9e0;
    selection-background-color: #3973db;
}

/* 颜色按钮 */
QPushButton#colorButton {
    border: 1px solid #d5d9e0;
    border-radius: 6px;
    padding: 5px;
    min-height: 24px;
}

/* 操作按钮 - 现代渐变风格 */
QPushButton#applyPropertyButton {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 #4a8af4, stop:1 #3973db);
    color: #ffffff;
    border: 1px solid #5a9af4;
    border-radius: 8px;
    padding: 8px 16px;
    font-weight: 600;
}
QPushButton#applyPropertyButton:hover {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 #5a9af4, stop:1 #4a8af4);
    border-color: #6aaaf4;
}
QPushButton#applyPropertyButton:pressed {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 #2a6ad4, stop:1 #1a5ac4);
    border-color: #3a7ae4;
}
QPushButton#applyPropertyButton:disabled {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 #eef0f4, stop:1 #e6e9ee);
    border-color: #c5cbd4;
    color: #9aa3b0;
}

/* 首页按钮 - 更大的渐变按钮 */
QPushButton#enterEditorButton {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 #4a8af4, stop:1 #3973db);
    color: #ffffff;
    border: 1px solid #5a9af4;
    border-radius: 10px;
    padding: 12px 28px;
    font-weight: 600;
}
QPushButton#enterEditorButton:hover {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 #5a9af4, stop:1 #4a8af4);
    border-color: #6aaaf4;
}
QPushButton#enterEditorButton:pressed {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 #2a6ad4, stop:1 #1a5ac4);
    border-color: #3a7ae4;
}

/* 返回按钮 */
QPushButton#backButton {
    background: transparent;
    color: #000000;
    border: 1px solid #d5d9e0;
    border-radius: 6px;
    padding: 6px 14px;
}
QPushButton#backButton:hover {
    background: #eef0f4;
    color: #212733;
}

/* 菜单栏 */
QMenuBar[editorStyle="true"] {
    background: #f4f5f7;
    color: #212733;
    border-bottom: 1px solid #d5d9e0;
    padding: 4px;
}
QMenuBar[editorStyle="true"]::item:selected {
    background: #eef0f4;
    border-radius: 4px;
}
QMenu {
    background: #ffffff;
    color: #212733;
    border: 1px solid #d5d9e0;
    border-radius: 8px;
    padding: 4px;
}
QMenu::item:selected {
    background: #3973db;
    border-radius: 4px;
}

/* 滚动条 */
QScrollBar:vertical {
    background: #f4f5f7;
    width: 8px;
    border-radius: 4px;
}
QScrollBar::handle:vertical {
    background: #d5d9e0;
    border-radius: 4px;
    min-height: 30px;
}
QScrollBar::handle:vertical:hover {
    background: #5085e8;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
QScrollBar:horizontal {
    background: #f4f5f7;
    height: 8px;
    border-radius: 4px;
}
QScrollBar::handle:horizontal {
    background: #d5d9e0;
    border-radius: 4px;
    min-width: 30px;
}
QScrollBar::handle:horizontal:hover {
    background: #5085e8;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0;
}

/* QSplitter 手柄 */
QSplitter::handle {
    background: #d5d9e0;
}
QSplitter::handle:horizontal {
    width: 4px;
}

/* 状态栏 */
QStatusBar[editorStyle="true"] {
    background: #f4f5f7;
    color: #000000;
    border-top: 1px solid #d5d9e0;
}

/* 禁用态通用 */
QPushButton:disabled {
    color: #98a0ad;
}

/* 通用禁用控件 */
QDoubleSpinBox:disabled, QSpinBox:disabled, QComboBox:disabled, QPlainTextEdit:disabled {
    background: #eef0f4;
    color: #98a0ad;
}
QPushButton:disabled {
    color: #98a0ad;
}

/* 统一圆角 */
QPushButton { border-radius: 8px; }
QDoubleSpinBox, QSpinBox, QComboBox, QPlainTextEdit, QLineEdit { border-radius: 6px; }

/* QLabel disabled 可读 */
QLabel:disabled { color: #000000; }

/* 通用主要按钮样式 - 现代渐变 */
QPushButton.primary, QPushButton[primary="true"] {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 #4a8af4, stop:1 #3973db);
    color: #ffffff;
    border: 1px solid #5a9af4;
    border-radius: 8px;
    padding: 8px 16px;
    font-weight: 600;
}
QPushButton.primary:hover, QPushButton[primary="true"]:hover {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 #5a9af4, stop:1 #4a8af4);
    border-color: #6aaaf4;
}
QPushButton.primary:pressed, QPushButton[primary="true"]:pressed {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 #2a6ad4, stop:1 #1a5ac4);
    border-color: #3a7ae4;
}
QPushButton.primary:disabled, QPushButton[primary="true"]:disabled {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 #eef0f4, stop:1 #e6e9ee);
    border-color: #c5cbd4;
    color: #9aa3b0;
}
"""
