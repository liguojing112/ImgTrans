import json

from src.infrastructure.user_preferences import (
    JsonBrandTermsPreferences,
    JsonFontPreferences,
)


def test_font_preferences_default_is_auto(tmp_path) -> None:
    preferences = JsonFontPreferences(tmp_path / "preferences.json")
    assert preferences.load() is None


def test_font_preferences_save_and_reload(tmp_path) -> None:
    path = tmp_path / "config" / "preferences.json"
    JsonFontPreferences(path).save("  Segoe UI  ")

    assert JsonFontPreferences(path).load() == "Segoe UI"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["translation_font"] == "Segoe UI"


def test_font_preferences_save_auto_removes_key(tmp_path) -> None:
    path = tmp_path / "preferences.json"
    preferences = JsonFontPreferences(path)
    preferences.save("Arial")
    preferences.save(None)

    assert preferences.load() is None
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert "translation_font" not in payload


def test_font_preferences_ignores_blank_value(tmp_path) -> None:
    path = tmp_path / "preferences.json"
    preferences = JsonFontPreferences(path)
    preferences.save("   ")
    assert preferences.load() is None


def test_font_preferences_preserve_other_fields(tmp_path) -> None:
    path = tmp_path / "preferences.json"
    JsonBrandTermsPreferences(path).save(("品牌",))
    JsonFontPreferences(path).save("Microsoft YaHei")

    assert JsonBrandTermsPreferences(path).load() == ("品牌",)
    assert JsonFontPreferences(path).load() == "Microsoft YaHei"
