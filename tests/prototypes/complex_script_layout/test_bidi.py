from prototypes.complex_script_layout.shaping_backend import _bidi_visual_runs


def test_rtl_mixed_text_keeps_latin_and_digits_ltr() -> None:
    text = "مرحبا SKU-123 (NEW)"
    runs, direction = _bidi_visual_runs(text, "rtl")
    assert direction == "rtl"
    latin_runs = ["".join(run.chars) for run in runs if run.direction == "ltr"]
    assert any("SKU-123" in run for run in latin_runs)
    assert any("NEW" in run for run in latin_runs)


def test_auto_direction_detects_rtl_and_ltr() -> None:
    assert _bidi_visual_runs("فارسی ۲۰۲۶", "auto")[1] == "rtl"
    assert _bidi_visual_runs("हिंदी 2026", "auto")[1] == "ltr"

