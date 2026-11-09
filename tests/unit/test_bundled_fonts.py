"""随包分发字体（客户字体）注册测试。"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from src.platform.bundled_fonts import bundled_fonts_root, register_bundled_fonts


def test_bundled_fonts_root_points_to_packaging_fonts() -> None:
    root = bundled_fonts_root()
    assert root is not None
    assert root.name == "bundled_fonts"
    files = [path for path in root.iterdir() if path.suffix.lower() == ".ttf"]
    assert len(files) == 5, "打包目录应包含 5 个客户字体"


def test_each_bundled_font_file_registers_valid_family() -> None:
    """每个字体文件都能被 Qt 识别出至少一个字体族。"""
    QApplication.instance() or QApplication(["bundled-fonts-test"])
    from PySide6.QtGui import QFontDatabase

    root = bundled_fonts_root()
    assert root is not None
    for path in sorted(root.glob("*.TTF")):
        font_id = QFontDatabase.addApplicationFont(str(path))
        assert font_id >= 0, f"字体载入失败：{path.name}"
        families = QFontDatabase.applicationFontFamilies(font_id)
        assert families, f"字体无字体族：{path.name}"


def test_register_bundled_fonts_returns_all_files() -> None:
    QApplication.instance() or QApplication(["bundled-fonts-test"])
    registered = register_bundled_fonts()
    assert len(registered) == 5
