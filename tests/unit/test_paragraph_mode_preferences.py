import json

from src.infrastructure.user_preferences import (
    JsonBrandTermsPreferences,
    JsonParagraphModePreferences,
)


def test_paragraph_mode_preferences_default_is_long(tmp_path) -> None:
    preferences = JsonParagraphModePreferences(tmp_path / "preferences.json")
    assert preferences.load() == "long"


def test_paragraph_mode_preferences_save_and_reload(tmp_path) -> None:
    path = tmp_path / "config" / "preferences.json"
    JsonParagraphModePreferences(path).save("short")

    assert JsonParagraphModePreferences(path).load() == "short"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["translation_paragraph_mode"] == "short"


def test_paragraph_mode_preferences_ignores_invalid_value(tmp_path) -> None:
    path = tmp_path / "preferences.json"
    preferences = JsonParagraphModePreferences(path)
    preferences.save("not-a-mode")
    assert preferences.load() == "long"


def test_paragraph_mode_preferences_load_invalid_stored_value(tmp_path) -> None:
    path = tmp_path / "preferences.json"
    JsonParagraphModePreferences(path).save("long")
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["translation_paragraph_mode"] = "weird"
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert JsonParagraphModePreferences(path).load() == "long"


def test_paragraph_mode_preferences_preserve_other_fields(tmp_path) -> None:
    path = tmp_path / "preferences.json"
    JsonBrandTermsPreferences(path).save(("品牌",))
    JsonParagraphModePreferences(path).save("short")

    assert JsonBrandTermsPreferences(path).load() == ("品牌",)
    assert JsonParagraphModePreferences(path).load() == "short"
