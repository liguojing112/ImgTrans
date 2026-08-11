import json

from src.infrastructure.user_preferences import (
    JsonBrandTermsPreferences,
    JsonEcommercePreferences,
)


def test_ecommerce_preferences_default_is_empty(tmp_path) -> None:
    preferences = JsonEcommercePreferences(tmp_path / "preferences.json")
    assert preferences.load() == ({}, None)


def test_ecommerce_preferences_save_and_reload(tmp_path) -> None:
    path = tmp_path / "config" / "preferences.json"
    JsonEcommercePreferences(path).save(
        {"柔软细腻": "Soft & Smooth", " 零添加 ": " No Additives "},
        "自定义提示词",
    )

    assert JsonEcommercePreferences(path).load() == (
        {"柔软细腻": "Soft & Smooth", "零添加": "No Additives"},
        "自定义提示词",
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["ecommerce_terms"] == {
        "柔软细腻": "Soft & Smooth",
        "零添加": "No Additives",
    }
    assert payload["ecommerce_llm_prompt"] == "自定义提示词"


def test_ecommerce_preferences_ignore_blank_terms_and_prompt(tmp_path) -> None:
    path = tmp_path / "preferences.json"
    preferences = JsonEcommercePreferences(path)
    preferences.save({"": "X", "有效": "Valid", "   ": "  "}, "   ")

    assert preferences.load() == ({"有效": "Valid"}, None)


def test_ecommerce_preferences_preserve_other_fields(tmp_path) -> None:
    path = tmp_path / "preferences.json"
    JsonBrandTermsPreferences(path).save(("品牌",))
    JsonEcommercePreferences(path).save({"新品": "New Arrival"}, "提示词")

    assert JsonBrandTermsPreferences(path).load() == ("品牌",)
    assert JsonEcommercePreferences(path).load() == ({"新品": "New Arrival"}, "提示词")
