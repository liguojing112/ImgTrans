"""图片翻译编辑器 — 深色主题 QSS 样式表。

使用属性选择器 [editorStyle="true"] 与生产 UI 的 _STYLE 隔离，
避免 QSS 级联冲突。
"""

# === 首页卡片样式 ===
HOME_CARD_STYLE = """
QFrame#homeCard {
    background: #2a2a3e;
    border: 1px solid #3d3d5c;
    border-radius: 16px;
    padding: 24px;
}
QFrame#homeCard:hover {
    border-color: #3973db;
    background: #32324a;
}
QFrame#homeCard:disabled {
    background: #252538;
    border-color: #2e2e48;
}
QFrame#homeCard:disabled:hover {
    border-color: #2e2e48;
}
QLabel#homeCardTitle {
    color: #e0e0f0;
    font-size: 20px;
    font-weight: 650;
}
QLabel#homeCardDesc {
    color: #9898b0;
    font-size: 13px;
}
QLabel#homeCardDisabled {
    color: #686878;
    font-size: 13px;
}
"""

# === 深色编辑器主题 ===
EDITOR_DARK_THEME = """
/* 根背景 */
QMainWindow[editorStyle="true"], QWidget[editorStyle="true"] {
    background: #1e1e2e;
    color: #e0e0f0;
    font-family: "Segoe UI", "Microsoft YaHei", sans-serif;
}

/* 首页标题 */
QLabel#homeTitle {
    color: #e0e0f0;
    font-size: 28px;
    font-weight: 700;
}
QLabel#homeSubtitle {
    color: #9898b0;
    font-size: 14px;
}

/* 首页卡片 */
QFrame[editorStyle="true"]#homeCard {
    background: #2a2a3e;
    border: 1px solid #3d3d5c;
    border-radius: 16px;
}
QFrame[editorStyle="true"]#homeCard:hover {
    border-color: #3973db;
    background: #32324a;
}
QLabel#homeCardTitle {
    color: #e0e0f0;
    font-size: 18px;
    font-weight: 650;
}
QLabel#homeCardDesc {
    color: #9898b0;
    font-size: 12px;
}

/* 工具栏 */
QFrame#editorToolBar {
    background: #232336;
    border-right: 1px solid #3d3d5c;
}
QFrame#textListPanel {
    background: #252538;
    border-right: 1px solid #3d3d5c;
}
QFrame#editorRightPanel {
    background: #2a2a3e;
    border-left: 1px solid #3d3d5c;
}
QSplitter::handle {
    background: #3d3d5c;
    width: 2px;
}
QSplitter::handle:hover {
    background: #3973db;
}
QPushButton#toolButton {
    background: transparent;
    color: #9898b0;
    border: none;
    border-radius: 8px;
    padding: 4px;
    font-size: 12px;
    min-width: 36px;
    min-height: 36px;
}
QPushButton#toolButton:hover {
    background: #363650;
    color: #e0e0f0;
}
QPushButton#toolButton:checked {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 #4a8af4, stop:1 #3973db);
    color: #ffffff;
    border: 1px solid #5a9af4;
}

/* 画布区域 */
QGraphicsView#editorCanvas {
    background: #1a1a2e;
    border: none;
}

QTabWidget#editorRightTabs::pane {
    border: none;
    border-top: 1px solid #3d3d5c;
    background: #2a2a3e;
}
QTabWidget#editorRightTabs QTabBar::tab {
    background: #252538;
    color: #9898b0;
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
    background: #363650;
    color: #e0e0f0;
}

/* 属性面板 */
QFrame#propertyPanel {
    background: #2a2a3e;
    border-left: 1px solid #3d3d5c;
}
QLabel#propertyTitle {
    color: #e0e0f0;
    font-size: 16px;
    font-weight: 650;
}
QLabel#propertyFieldLabel {
    color: #9898b0;
    font-size: 12px;
}
QLabel#propertyNoSelection {
    color: #686878;
    font-size: 13px;
}
QDoubleSpinBox, QSpinBox, QComboBox, QPlainTextEdit {
    background: #363650;
    color: #e0e0f0;
    border: 1px solid #3d3d5c;
    border-radius: 6px;
    padding: 6px;
}
QDoubleSpinBox:focus, QSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus {
    border-color: #3973db;
}
QComboBox::drop-down {
    border: none;
    background: #2a2a3e;
    border-radius: 0 6px 6px 0;
    width: 20px;
}
QComboBox QAbstractItemView {
    background: #363650;
    color: #e0e0f0;
    border: 1px solid #3d3d5c;
    selection-background-color: #3973db;
}

/* 颜色按钮 */
QPushButton#colorButton {
    border: 1px solid #3d3d5c;
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
    font-size: 13px;
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
                                stop:0 #3a4a5e, stop:1 #2e3e4e);
    border-color: #4a5a6e;
    color: #8898a8;
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
    font-size: 15px;
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
    color: #9898b0;
    border: 1px solid #3d3d5c;
    border-radius: 6px;
    padding: 6px 14px;
    font-size: 13px;
}
QPushButton#backButton:hover {
    background: #363650;
    color: #e0e0f0;
}

/* 菜单栏 */
QMenuBar[editorStyle="true"] {
    background: #1e1e2e;
    color: #e0e0f0;
    border-bottom: 1px solid #3d3d5c;
    padding: 4px;
}
QMenuBar[editorStyle="true"]::item:selected {
    background: #363650;
    border-radius: 4px;
}
QMenu {
    background: #2a2a3e;
    color: #e0e0f0;
    border: 1px solid #3d3d5c;
    border-radius: 8px;
    padding: 4px;
}
QMenu::item:selected {
    background: #3973db;
    border-radius: 4px;
}

/* 滚动条 */
QScrollBar:vertical {
    background: #1e1e2e;
    width: 8px;
    border-radius: 4px;
}
QScrollBar::handle:vertical {
    background: #3d3d5c;
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
    background: #1e1e2e;
    height: 8px;
    border-radius: 4px;
}
QScrollBar::handle:horizontal {
    background: #3d3d5c;
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
    background: #3d3d5c;
}
QSplitter::handle:horizontal {
    width: 4px;
}

/* 状态栏 */
QStatusBar[editorStyle="true"] {
    background: #1e1e2e;
    color: #9898b0;
    border-top: 1px solid #3d3d5c;
}

/* 禁用态通用 */
QPushButton:disabled {
    color: #686878;
}

/* 通用禁用控件 */
QDoubleSpinBox:disabled, QSpinBox:disabled, QComboBox:disabled, QPlainTextEdit:disabled {
    background: #252536;
    color: #686878;
}
QPushButton:disabled {
    color: #686878;
}

/* 统一圆角 */
QPushButton { border-radius: 8px; }
QDoubleSpinBox, QSpinBox, QComboBox, QPlainTextEdit, QLineEdit { border-radius: 6px; }

/* QLabel disabled 可读 */
QLabel:disabled { color: #9898b0; }

/* 通用主要按钮样式 - 现代渐变 */
QPushButton.primary, QPushButton[primary="true"] {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 #4a8af4, stop:1 #3973db);
    color: #ffffff;
    border: 1px solid #5a9af4;
    border-radius: 8px;
    padding: 8px 16px;
    font-weight: 600;
    font-size: 13px;
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
                                stop:0 #3a4a5e, stop:1 #2e3e4e);
    border-color: #4a5a6e;
    color: #8898a8;
}
"""
