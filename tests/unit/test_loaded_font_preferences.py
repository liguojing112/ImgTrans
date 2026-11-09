from __future__ import annotations

from pathlib import Path

from src.infrastructure.user_preferences import JsonLoadedFontPreferences


def test_loaded_font_preferences_round_trip(tmp_path: Path) -> None:
    preferences = JsonLoadedFontPreferences(tmp_path / "preferences.json")
    assert preferences.load() == ()

    paths = (Path("C:/Fonts/a.ttf"), Path("D:/Fonts/b.otf"))
    preferences.save(paths)
    assert preferences.load() == paths

    preferences.save(())
    assert preferences.load() == ()
