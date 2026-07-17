from __future__ import annotations

from pathlib import Path

import pytest

from prototypes.rapidocr_multilingual.generate_synthetic_dataset import (
    load_configuration,
    rotate_polygon,
)


def test_synthetic_configuration_covers_25_languages_and_500_regions() -> None:
    texts, fonts = load_configuration(Path("prototypes/rapidocr_multilingual"))
    assert len(texts) == 25
    assert sum(len(phrases) for phrases in texts.values()) * 4 == 500
    assert set(texts) == set(fonts["languages"]) == set(fonts["scripts"])


def test_rotated_polygon_preserves_four_distinct_ordered_points() -> None:
    polygon = rotate_polygon(
        ((10, 10), (110, 10), (110, 40), (10, 40)),
        source_size=(120, 50),
        rotated_size=(126, 66),
        angle=8,
        offset=(20, 30),
    )
    assert len(set(polygon)) == 4
    assert polygon[0] == min(polygon, key=lambda point: (sum(point), point[1], point[0]))


def test_missing_font_directory_fails_before_generation(tmp_path: Path) -> None:
    from prototypes.rapidocr_multilingual.generate_synthetic_dataset import generate_dataset

    with pytest.raises(FileNotFoundError, match="Required font is missing"):
        generate_dataset(tmp_path, tmp_path / "output")


def test_current_pillow_shaping_capability_is_explicit() -> None:
    from PIL import features

    assert isinstance(features.check_feature("raqm"), bool)
