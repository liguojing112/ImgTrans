import pytest

from src.domain.layout import (
    ArcTextPath,
    PathPoint,
    TextBox,
    default_arc_path,
    transform_arc_path,
)


def test_quadratic_path_points_tangents_and_length() -> None:
    path = ArcTextPath(PathPoint(0, 20), PathPoint(50, -20), PathPoint(100, 20))
    middle = path.point_at(0.5)
    tangent = path.tangent_at(0.5)
    assert middle == PathPoint(50, 0)
    assert tangent.x == pytest.approx(100)
    assert tangent.y == pytest.approx(0)
    assert path.approximate_length() > 100


def test_default_path_and_box_transform_preserve_relative_control_geometry() -> None:
    source = TextBox(50, 40, 80, 30)
    path = default_arc_path(source, 0.5)
    target = TextBox(120, 80, 160, 60, 90)
    transformed = transform_arc_path(path, source, target)
    assert transformed.start.x == pytest.approx(120)
    assert transformed.start.y == pytest.approx(0)
    assert transformed.end.x == pytest.approx(120)
    assert transformed.end.y == pytest.approx(160)
    assert transformed.control.x == pytest.approx(150)
    assert transformed.control.y == pytest.approx(80)


def test_path_rejects_identical_endpoints_and_invalid_positions() -> None:
    with pytest.raises(ValueError):
        ArcTextPath(PathPoint(1, 1), PathPoint(2, 2), PathPoint(1, 1))
    path = ArcTextPath(PathPoint(0, 0), PathPoint(1, 1), PathPoint(2, 0))
    with pytest.raises(ValueError):
        path.point_at(1.1)
