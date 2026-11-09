"""载入外部字体：注册、持久化并出现在译文字体下拉里。"""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication, QFileDialog

from src.infrastructure.user_preferences import JsonLoadedFontPreferences
from src.ui.editor.main_window import EditorMainWindow


def _system_font_file() -> Path:
    for candidate in (
        Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "arial.ttf",
        Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "segoeui.ttf",
        Path("/System/Library/Fonts/Helvetica.ttc"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ):
        if candidate.is_file():
            return candidate
    pytest.skip("本机没有可用于测试的字体文件")


def test_load_fonts_registers_persists_and_shows_in_combo(
    tmp_path: Path, monkeypatch
) -> None:
    QApplication.instance() or QApplication(["load-fonts-test"])
    font_path = _system_font_file()
    preferences = JsonLoadedFontPreferences(tmp_path / "preferences.json")
    window = EditorMainWindow(
        import_image=object(),
        loaded_font_preferences=preferences,
    )
    try:
        monkeypatch.setattr(
            QFileDialog,
            "getOpenFileNames",
            lambda *args, **kwargs: ([str(font_path)], ""),
        )
        window._on_load_fonts()

        assert preferences.load() == (font_path,)
        combo = window._editor_page.translate_controls.translation_font
        assert combo.count() > 1
    finally:
        window.close()


def test_font_button_emits_request(monkeypatch) -> None:
    QApplication.instance() or QApplication(["load-fonts-signal-test"])
    # 避免真的弹出文件选择框（无界面环境会卡住）
    monkeypatch.setattr(
        QFileDialog, "getOpenFileNames", lambda *args, **kwargs: ([], "")
    )
    window = EditorMainWindow(import_image=object())
    try:
        controls = window._editor_page.translate_controls
        emitted: list[int] = []
        controls.load_fonts_requested.connect(lambda: emitted.append(1))
        controls.load_fonts_btn.click()
        assert emitted == [1]
    finally:
        window.close()


def test_help_documents_font_loading() -> None:
    """使用说明里要写清「载入字体」的用法。"""
    from src.ui.help_dialog import _HELP_HTML

    assert "载入字体…" in _HELP_HTML
    assert ".ttf" in _HELP_HTML
    assert "下次启动软件自动重新加载" in _HELP_HTML
