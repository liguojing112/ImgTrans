from math import nan

import pytest

from src.domain.ocr import (
    OcrResult,
    Point,
    TextRegion,
    TextRegionStatus,
    normalize_ocr_text,
    order_quad,
)


def test_order_quad_normalizes_shuffled_points() -> None:
    polygon = order_quad(((100, 50), (10, 50), (100, 10), (10, 10)))
    assert polygon[0] == Point(10, 10)
    assert set(polygon) == {Point(10, 10), Point(100, 10), Point(100, 50), Point(10, 50)}


def test_region_validates_geometry_confidence_and_language() -> None:
    polygon = order_quad(((0, 0), (20, 0), (20, 10), (0, 10)))
    region = TextRegion("region-0001", polygon, "Text", 0.8, "en", "model")
    assert region.status is TextRegionStatus.OK
    with pytest.raises(ValueError, match="confidence"):
        TextRegion("bad", polygon, "Text", 1.1, "en", "model")
    with pytest.raises(ValueError, match="finite"):
        Point(nan, 1)


def test_text_normalization_and_empty_result_are_valid() -> None:
    assert normalize_ocr_text("  café\n product  ") == "café product"
    result = OcrResult((), "en", "common", 0)
    assert result.regions == ()
