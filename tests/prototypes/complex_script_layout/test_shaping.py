from pathlib import Path

import pytest

from prototypes.complex_script_layout.contracts import LayoutRequest, load_requests
from prototypes.complex_script_layout.qt_backend import QtLayoutBackend
from prototypes.complex_script_layout.shaping_backend import HarfBuzzLayoutBackend


CASES = Path("tests/prototypes/complex_script_layout/fixtures/cases.json")


def request(font_dir: Path, case_id: str, text: str, language: str, font: str, direction: str):
    return LayoutRequest(case_id, text, language, font_dir / font, direction, 520, 220, 40)


def test_fixture_contains_twenty_cases_per_language(font_dir: Path) -> None:
    requests = load_requests(CASES, font_dir)
    assert len(requests) == 120
    counts = {}
    for item in requests:
        counts[item.language_code] = counts.get(item.language_code, 0) + 1
    assert counts == {"ar": 20, "ur": 20, "fa": 20, "hi": 20, "bn": 20, "th": 20}


@pytest.mark.parametrize("backend_type", [HarfBuzzLayoutBackend, QtLayoutBackend])
def test_arabic_shaping_and_latin_fallback(font_dir: Path, backend_type) -> None:
    item = request(
        font_dir,
        "mixed",
        "مرحبا SKU-123",
        "ar",
        "NotoNaskhArabic-Regular.ttf",
        "rtl",
    )
    result = backend_type().layout(item)
    clusters = [cluster for line in result.lines for cluster in line.clusters]
    assert clusters
    assert all(0 not in cluster.glyph_ids for cluster in clusters)
    assert any(cluster.font_file == "NotoSans-Regular.ttf" for cluster in clusters)
    assert result.lines[0].direction == "rtl"


@pytest.mark.parametrize(
    ("language", "text", "font"),
    [
        ("hi", "क्षेत्र त्रिकोण", "NotoSansDevanagari-Regular.ttf"),
        ("bn", "ক্ষেত্র শ্রদ্ধা", "NotoSansBengali-Regular.ttf"),
        ("th", "น้ำกำลังเดินทาง", "NotoSansThai-Regular.ttf"),
    ],
)
@pytest.mark.parametrize("backend_type", [HarfBuzzLayoutBackend, QtLayoutBackend])
def test_complex_clusters_have_no_missing_glyphs(
    font_dir: Path, backend_type, language: str, text: str, font: str
) -> None:
    result = backend_type().layout(request(font_dir, language, text, language, font, "ltr"))
    clusters = [cluster for line in result.lines for cluster in line.clusters]
    assert clusters
    assert all(0 not in cluster.glyph_ids for cluster in clusters)

