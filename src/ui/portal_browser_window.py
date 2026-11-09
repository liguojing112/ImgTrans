"""万象笔记浏览器窗口 — 内嵌网页，首页卡片与编辑器工具栏入口共用。"""

from __future__ import annotations

import os

from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QLabel, QMainWindow


class PortalBrowserWindow(QMainWindow):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("万象笔记")
        self.resize(1200, 800)
        self._view = None
        if os.environ.get("QT_QPA_PLATFORM") == "offscreen":
            self.setCentralWidget(self._placeholder("万象笔记网页（当前测试环境不可用）"))
            return
        try:
            from PySide6.QtWebEngineWidgets import QWebEngineView
        except Exception as error:  # noqa: BLE001 - 缺组件时降级提示
            self.setCentralWidget(
                self._placeholder(f"本机缺少浏览器组件，无法打开万象笔记：{error}")
            )
            return
        self._view = QWebEngineView(self)
        self.setCentralWidget(self._view)

    def load_url(self, url: str) -> bool:
        """加载入口链接；无浏览器组件（测试环境）时返回 False。"""
        if self._view is None:
            return False
        self._view.setUrl(QUrl(url))
        return True

    @staticmethod
    def _placeholder(text: str) -> QLabel:
        from PySide6.QtCore import Qt

        label = QLabel(text)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setWordWrap(True)
        return label
