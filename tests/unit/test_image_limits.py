import pytest

from src.domain.image import ImageFileFormat, ImageLimits, ImageValidationError


def test_builtin_limits_match_decision_baseline() -> None:
    limits = ImageLimits()
    assert (limits.min_width, limits.min_height) == (64, 64)
    assert (limits.max_width, limits.max_height) == (12_000, 12_000)
    assert limits.max_bytes == 50 * 1024 * 1024
    assert limits.max_pixels == 80_000_000
    assert limits.source == "builtin"


def test_limits_reject_small_large_and_excessive_pixel_images() -> None:
    limits = ImageLimits(max_width=1_000, max_height=1_000, max_pixels=500_000)
    with pytest.raises(ImageValidationError) as small:
        limits.validate_dimensions(63, 100)
    assert small.value.code == "dimensions_too_small"
    with pytest.raises(ImageValidationError) as large:
        limits.validate_dimensions(1_001, 100)
    assert large.value.code == "dimensions_too_large"
    with pytest.raises(ImageValidationError) as pixels:
        limits.validate_dimensions(800, 800)
    assert pixels.value.code == "pixel_count_too_large"


def test_file_size_limit_and_format_suffixes_are_explicit() -> None:
    limits = ImageLimits(max_bytes=100)
    with pytest.raises(ImageValidationError) as error:
        limits.validate_file_size(101)
    assert error.value.code == "file_too_large"
    assert ImageFileFormat.from_input_suffix(".JPEG") is ImageFileFormat.JPEG
    assert ImageFileFormat.from_output_suffix(".tiff") is ImageFileFormat.TIFF
    with pytest.raises(ImageValidationError, match="JPG"):
        ImageFileFormat.from_input_suffix(".gif")
