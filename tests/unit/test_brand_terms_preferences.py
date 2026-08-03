import json

from src.domain.protection import normalize_brand_terms
from src.infrastructure.user_preferences import (
    JsonBrandTermsPreferences,
    JsonModelTermsPreferences,
)


def test_brand_terms_normalize_chinese_commas_and_preserve_first_occurrence() -> None:
    assert normalize_brand_terms(
        " Alpha，Beta, alpha , Gamma，Beta "
    ) == ("Alpha", "Beta", "Gamma")


def test_brand_terms_preferences_save_and_reload(tmp_path) -> None:
    path = tmp_path / "config" / "preferences.json"
    first = JsonBrandTermsPreferences(path)
    assert first.load() == ()

    first.save((" Alpha ", "Beta", "alpha"))

    second = JsonBrandTermsPreferences(path)
    assert second.load() == ("Alpha", "Beta")
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload == {
        "schema_version": 1,
        "brand_terms": ["Alpha", "Beta"],
    }


def test_empty_brand_terms_preferences_preserve_existing_behavior(tmp_path) -> None:
    preferences = JsonBrandTermsPreferences(tmp_path / "preferences.json")
    preferences.save(())
    assert preferences.load() == ()


def test_model_terms_are_persisted_separately_from_brand_terms(tmp_path) -> None:
    path = tmp_path / "preferences.json"
    JsonBrandTermsPreferences(path).save(("品牌",))
    JsonModelTermsPreferences(path).save(("AB-100", "SKU-2"))
    assert JsonBrandTermsPreferences(path).load() == ("品牌",)
    assert JsonModelTermsPreferences(path).load() == ("AB-100", "SKU-2")
