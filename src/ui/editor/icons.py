"""Qt 标准图标工具 — 通过 QStyle.StandardPixmap 获取原生图标。"""

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QStyle


def standard_icon(pixmap: QStyle.StandardPixmap) -> QIcon:
    """返回当前平台风格对应的标准图标。"""
    return QApplication.style().standardIcon(pixmap)
