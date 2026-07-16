import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel, QPushButton

from src.application.bootstrap import StartupSnapshot
from src.domain.product import ProductInfo
from src.ui.main_window import MainWindow


def test_main_window_shows_product_empty_state(tmp_path: Path) -> None:
    application = QApplication.instance() or QApplication(["imgtrans-test"])
    startup = StartupSnapshot(
        ProductInfo("图片翻译", "0.1.0", "M1"), tmp_path / "data", tmp_path / "cache"
    )
    window = MainWindow(startup)
    window.show()
    application.processEvents()
    assert window.windowTitle() == "图片翻译"
    assert window.findChild(QLabel, "emptyStateTitle").text() == "尚未导入图片"
    assert not window.findChild(QPushButton, "importButton").isEnabled()
    assert window.statusBar().currentMessage() == "应用已就绪"
    window.close()
