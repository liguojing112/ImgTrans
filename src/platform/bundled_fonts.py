"""exe 内置字体 — 随包分发的客户字体，启动时自动注册到应用字体库。

打包时字体放入 `bundled_fonts/`；启动注册后直接出现在「译文字体」、
「自动匹配首选」和属性面板的字体下拉里，客户无需手动「载入字体」。
"""

from __future__ import annotations

from pathlib import Path

_FONT_SUFFIXES = {".ttf", ".otf", ".ttc", ".otc"}


def bundled_fonts_root() -> Path | None:
    """frozen exe 返回 _MEIPASS/bundled_fonts；开发环境返回仓库内目录。"""
    import sys

    if getattr(sys, "frozen", False):
        root = Path(getattr(sys, "_MEIPASS", "")) / "bundled_fonts"
    else:
        root = Path(__file__).resolve().parents[2] / "packaging" / "bundled_fonts"
    return root if root.is_dir() else None


def register_bundled_fonts() -> tuple[str, ...]:
    """把内置字体注册到应用字体库，返回成功载入的文件名。

    需在 QApplication 创建之后调用。
    """
    root = bundled_fonts_root()
    if root is None:
        return ()
    from PySide6.QtGui import QFontDatabase

    registered: list[str] = []
    for path in sorted(root.iterdir()):
        if not path.is_file() or path.suffix.lower() not in _FONT_SUFFIXES:
            continue
        if QFontDatabase.addApplicationFont(str(path)) >= 0:
            registered.append(path.name)
    return tuple(registered)
