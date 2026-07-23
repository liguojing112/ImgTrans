import json
import pytest

from src.domain.terminology import (
    TerminologyCatalog,
    TerminologyEntry,
    normalize_terminology_entries,
    normalize_terminology_text,
)
from src.infrastructure.user_preferences import (
    JsonBrandTermsPreferences,
    JsonTerminologyPreferences,
    UserPreferencesError,
)


def test_terminology_normalizes_unicode_whitespace_and_last_duplicate_wins() -> None:
    assert normalize_terminology_text("  Ａ\t  B  ") == "A B"
    entries = normalize_terminology_entries(
        [
            TerminologyEntry("en", "zh-Hans", " Ａ  B ", "first"),
            TerminologyEntry("en", "zh-Hans", "A B", " second "),
        ]
    )
    assert entries == (
        TerminologyEntry("en", "zh-Hans", "A B", "second"),
    )


def test_terminology_catalog_isolates_language_pairs_and_ignores_disabled() -> None:
    catalog = TerminologyCatalog(
        (
            TerminologyEntry("en", "zh-Hans", "Clamp", "卡箍"),
            TerminologyEntry("en", "ja", "Clamp", "クランプ"),
            TerminologyEntry("en", "ko", "Clamp", "클램프", enabled=False),
        )
    )
    assert catalog.lookup("en", "zh-Hans", "Clamp") == "卡箍"
    assert catalog.lookup("en", "ja", "Clamp") == "クランプ"
    assert catalog.lookup("en", "ko", "Clamp") is None
    assert catalog.lookup("en", "zh-Hans", "Clamp set") is None


def test_terminology_preferences_share_file_with_brand_terms_and_reload(tmp_path) -> None:
    path = tmp_path / "config" / "preferences.json"
    brands = JsonBrandTermsPreferences(path)
    terminology = JsonTerminologyPreferences(path)
    brands.save(("Alpha",))
    terminology.save(
        (
            TerminologyEntry("en", "zh-Hans", "Clamp", "卡箍"),
            TerminologyEntry(
                "zh-Hans",
                "en",
                "卡箍",
                "Clamp",
                enabled=False,
            ),
        )
    )

    assert JsonBrandTermsPreferences(path).load() == ("Alpha",)
    assert JsonTerminologyPreferences(path).load() == (
        TerminologyEntry("en", "zh-Hans", "Clamp", "卡箍"),
        TerminologyEntry("zh-Hans", "en", "卡箍", "Clamp", enabled=False),
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["brand_terms"] == ["Alpha"]
    assert payload["terminology_entries"][1]["enabled"] is False


def test_empty_terminology_preferences_preserve_existing_behavior(tmp_path) -> None:
    path = tmp_path / "preferences.json"
    terminology = JsonTerminologyPreferences(path)
    assert terminology.load() == ()
    terminology.save(())
    assert terminology.load() == ()


def test_corrupt_preferences_are_backed_up_and_recovered(tmp_path) -> None:
    path = tmp_path / "config" / "preferences.json"
    path.parent.mkdir(parents=True)
    path.write_text("{not-json", encoding="utf-8")

    brands = JsonBrandTermsPreferences(path)
    assert brands.load() == ()
    backups = tuple(path.parent.glob("preferences.json.corrupt-*.bak"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == "{not-json"
    assert json.loads(path.read_text(encoding="utf-8")) == {"schema_version": 1}

    brands.save(("Recovered",))
    assert JsonBrandTermsPreferences(path).load() == ("Recovered",)


def test_legacy_preferences_are_migrated_without_losing_values(tmp_path) -> None:
    path = tmp_path / "preferences.json"
    path.write_text(
        json.dumps(
            {
                "brand_terms": ["Alpha"],
                "terminology_entries": [
                    {
                        "source_language": "en",
                        "target_language": "zh-Hans",
                        "source_text": "Clamp",
                        "target_text": "卡箍",
                        "enabled": True,
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    assert JsonBrandTermsPreferences(path).load() == ("Alpha",)
    assert JsonTerminologyPreferences(path).load() == (
        TerminologyEntry("en", "zh-Hans", "Clamp", "卡箍"),
    )
    assert json.loads(path.read_text(encoding="utf-8"))["schema_version"] == 1
    assert tuple(path.parent.glob("preferences.json.corrupt-*.bak")) == ()


def test_newer_preferences_schema_is_not_overwritten(tmp_path) -> None:
    path = tmp_path / "preferences.json"
    original = '{"schema_version":2,"future":true}'
    path.write_text(original, encoding="utf-8")

    with pytest.raises(UserPreferencesError, match="newer"):
        JsonBrandTermsPreferences(path).load()

    assert path.read_text(encoding="utf-8") == original
    assert tuple(path.parent.glob("preferences.json.corrupt-*.bak")) == ()
