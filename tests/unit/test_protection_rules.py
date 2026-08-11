import pytest

from src.domain.protection import ProtectionEngine, ProtectionError, ProtectionKind


def test_default_rules_and_brand_terms_protect_expected_fragments() -> None:
    value = ProtectionEngine().protect(
        "ACME X100 SKU-AB12 visit https://example.com/p/99 save 25%",
        ("ACME",),
    )
    protected = {(span.kind, span.text) for span in value.spans}
    assert (ProtectionKind.BRAND, "ACME") in protected
    assert (ProtectionKind.MODEL, "X100") in protected
    assert (ProtectionKind.SKU, "SKU-AB12") in protected
    assert (ProtectionKind.URL, "https://example.com/p/99") in protected
    assert (ProtectionKind.NUMBER, "25%") in protected
    assert value.restore(value.masked) == value.original
    assert all(
        not any(character.isascii() and character.isalpha() for character in span.placeholder)
        for span in value.spans
    )


def test_overlapping_rules_keep_whole_sku_and_url() -> None:
    value = ProtectionEngine().protect("SKU-X100 https://shop.example.com/X200")
    assert [(span.kind, span.text) for span in value.spans] == [
        (ProtectionKind.SKU, "SKU-X100"),
        (ProtectionKind.URL, "https://shop.example.com/X200"),
    ]


def test_fully_protected_and_placeholder_damage_are_detected() -> None:
    value = ProtectionEngine().protect("SKU-AB12 25%")
    assert value.fully_protected
    with pytest.raises(ProtectionError, match="占位符"):
        value.restore("占位符已丢失")


def test_restore_accepts_standard_placeholder() -> None:
    value = ProtectionEngine().protect("堵头*2")
    assert value.restore("Plug * ⟦0⟧") == "Plug * 2"


def test_restore_rejects_whitespace_inside_placeholder() -> None:
    value = ProtectionEngine().protect("堵头*2")
    with pytest.raises(ProtectionError, match="占位符"):
        value.restore("Plug * ⟦ 0⟧")
    with pytest.raises(ProtectionError, match="占位符"):
        value.restore("Plug * ⟦0 ⟧")


def test_restore_preserves_ordinary_sentence_spacing() -> None:
    value = ProtectionEngine().protect("堵头*2")
    translated = "Use  plug <b>count</b>:  ⟦0⟧  today"
    assert value.restore(translated) == "Use  plug <b>count</b>:  2  today"


def test_restore_matches_multiple_placeholders_by_id() -> None:
    value = ProtectionEngine().protect("X100 saves 25%")
    translated = "Save ⟦1⟧ with ⟦0⟧"
    assert value.restore(translated) == "Save 25% with X100"


def test_restore_rejects_missing_placeholder() -> None:
    value = ProtectionEngine().protect("堵头*2")
    with pytest.raises(ProtectionError, match="占位符"):
        value.restore("Plug * 2")


def test_restore_rejects_duplicate_placeholder_id() -> None:
    value = ProtectionEngine().protect("堵头*2")
    with pytest.raises(ProtectionError, match="占位符"):
        value.restore("⟦0⟧ and ⟦0⟧")


def test_restore_rejects_unknown_placeholder_id() -> None:
    value = ProtectionEngine().protect("堵头*2")
    with pytest.raises(ProtectionError, match="占位符"):
        value.restore("⟦0⟧ and ⟦9⟧")


def test_restore_rejects_changed_placeholder_id() -> None:
    value = ProtectionEngine().protect("堵头*2")
    with pytest.raises(ProtectionError, match="占位符"):
        value.restore("⟦1⟧")


@pytest.mark.parametrize(
    "translated",
    (
        "⟦⟧",
        "⟦a⟧",
        "⟦0⟧ and ⟦⟧",
        "⟦0⟧ and ⟦01⟧",
    ),
)
def test_restore_rejects_malformed_or_unknown_placeholders(translated: str) -> None:
    value = ProtectionEngine().protect("堵头*2")
    with pytest.raises(ProtectionError, match="占位符"):
        value.restore(translated)


def test_complete_ocr_region_fragment_of_configured_brand_is_protected() -> None:
    engine = ProtectionEngine()
    chinese = engine.protect("轴心", ("杰克森轴心",))
    english = engine.protect("AXIS", ("JACKSON AXIS",))
    mixed_script = engine.protect("EKSEN", ("杰克森EKSEN",))
    assert [(span.kind, span.text) for span in chinese.spans] == [
        (ProtectionKind.BRAND, "轴心")
    ]
    assert [(span.kind, span.text) for span in english.spans] == [
        (ProtectionKind.BRAND, "AXIS")
    ]
    assert [(span.kind, span.text) for span in mixed_script.spans] == [
        (ProtectionKind.BRAND, "EKSEN")
    ]


def test_short_or_embedded_brand_fragment_is_not_guessed() -> None:
    engine = ProtectionEngine()
    assert not engine.protect("森", ("杰克森轴心",)).spans
    assert not engine.protect("new AXIS product", ("JACKSON AXIS",)).spans


def test_number_protection_can_be_disabled_without_disabling_other_rules() -> None:
    value = ProtectionEngine().protect(
        "ACME X100 SKU-AB12 https://example.com 25%",
        ("ACME",),
        preserve_numbers=False,
    )
    protected = {(span.kind, span.text) for span in value.spans}
    assert (ProtectionKind.NUMBER, "25%") not in protected
    assert (ProtectionKind.BRAND, "ACME") in protected
    assert (ProtectionKind.MODEL, "X100") in protected
    assert (ProtectionKind.SKU, "SKU-AB12") in protected
    assert (ProtectionKind.URL, "https://example.com") in protected
