from __future__ import annotations

from dataclasses import dataclass, replace

from src.domain.composition import CropViewport, ImageTransform
from src.domain.layout import PathPoint, TextBox
from src.domain.ocr import OcrObservation, OcrResult, Point


@dataclass(frozen=True, slots=True)
class CoordinateTransform:
    viewport: CropViewport
    view_scale: float = 1.0
    view_offset_x: float = 0.0
    view_offset_y: float = 0.0

    def __post_init__(self) -> None:
        if self.view_scale <= 0:
            raise ValueError("View scale must be positive")

    def original_to_canvas(self, point: PathPoint) -> PathPoint:
        return PathPoint(
            point.x - self.viewport.x,
            point.y - self.viewport.y,
        )

    def canvas_to_original(self, point: PathPoint) -> PathPoint:
        return PathPoint(
            point.x + self.viewport.x,
            point.y + self.viewport.y,
        )

    def canvas_to_view(self, point: PathPoint) -> PathPoint:
        return PathPoint(
            point.x * self.view_scale + self.view_offset_x,
            point.y * self.view_scale + self.view_offset_y,
        )

    def view_to_canvas(self, point: PathPoint) -> PathPoint:
        return PathPoint(
            (point.x - self.view_offset_x) / self.view_scale,
            (point.y - self.view_offset_y) / self.view_scale,
        )

    def original_box_to_canvas(self, box: TextBox) -> TextBox:
        return TextBox(
            box.center_x - self.viewport.x,
            box.center_y - self.viewport.y,
            box.width,
            box.height,
            box.rotation_degrees,
        )

    def canvas_box_to_original(self, box: TextBox) -> TextBox:
        return TextBox(
            box.center_x + self.viewport.x,
            box.center_y + self.viewport.y,
            box.width,
            box.height,
            box.rotation_degrees,
        )


def transform_ocr_result(
    result: OcrResult,
    operation: ImageTransform,
    width: int,
    height: int,
) -> OcrResult:
    def polygon(values):
        return tuple(
            transform_ocr_point(point, operation, width, height)
            for point in values
        )

    def observation(value: OcrObservation) -> OcrObservation:
        return replace(
            value,
            polygon=polygon(value.polygon),
            angle_degrees=_transform_angle(value.angle_degrees, operation),
        )

    regions = tuple(
        replace(
            region,
            polygon=polygon(region.polygon),
            observations=tuple(observation(item) for item in region.observations),
        )
        for region in result.regions
    )
    return replace(
        result,
        regions=regions,
        raw_observations=tuple(
            observation(item) for item in result.raw_observations
        ),
        preview_strips=(),
    )


def crop_ocr_result(
    result: OcrResult,
    left: int,
    top: int,
    width: int,
    height: int,
) -> OcrResult:
    if min(left, top) < 0 or min(width, height) <= 0:
        raise ValueError("OCR crop geometry is invalid")

    def intersects(values: tuple[Point, ...]) -> bool:
        min_x = min(point.x for point in values)
        max_x = max(point.x for point in values)
        min_y = min(point.y for point in values)
        max_y = max(point.y for point in values)
        return (
            max_x > left
            and max_y > top
            and min_x < left + width
            and min_y < top + height
        )

    def polygon(values: tuple[Point, ...]) -> tuple[Point, ...]:
        return tuple(
            Point(
                min(float(width), max(0.0, point.x - left)),
                min(float(height), max(0.0, point.y - top)),
            )
            for point in values
        )

    def observation(value: OcrObservation) -> OcrObservation:
        return replace(value, polygon=polygon(value.polygon))

    return replace(
        result,
        regions=tuple(
            replace(
                region,
                polygon=polygon(region.polygon),
                observations=tuple(
                    observation(item)
                    for item in region.observations
                    if intersects(item.polygon)
                ),
            )
            for region in result.regions
            if intersects(region.polygon)
        ),
        raw_observations=tuple(
            observation(item)
            for item in result.raw_observations
            if intersects(item.polygon)
        ),
        preview_strips=(),
    )


def transform_ocr_point(
    point: Point,
    operation: ImageTransform,
    width: int,
    height: int,
) -> Point:
    if operation is ImageTransform.ROTATE_90_CW:
        return Point(height - point.y, point.x)
    if operation is ImageTransform.ROTATE_90_CCW:
        return Point(point.y, width - point.x)
    if operation is ImageTransform.ROTATE_180:
        return Point(width - point.x, height - point.y)
    if operation is ImageTransform.FLIP_HORIZONTAL:
        return Point(width - point.x, point.y)
    return Point(point.x, height - point.y)


def _transform_angle(angle: float, operation: ImageTransform) -> float:
    if operation is ImageTransform.ROTATE_90_CW:
        value = angle + 90
    elif operation is ImageTransform.ROTATE_90_CCW:
        value = angle - 90
    elif operation is ImageTransform.ROTATE_180:
        value = angle + 180
    elif operation is ImageTransform.FLIP_HORIZONTAL:
        value = 180 - angle
    else:
        value = -angle
    return (value + 180) % 360 - 180
