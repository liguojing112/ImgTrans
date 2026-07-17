from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from enum import Enum
from math import cos, hypot, isfinite, radians, sin


class LayoutError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class TextAlignment(str, Enum):
    LEFT = "left"
    CENTER = "center"
    RIGHT = "right"


class VerticalAlignment(str, Enum):
    TOP = "top"
    CENTER = "center"
    BOTTOM = "bottom"


class ArtisticPreset(str, Enum):
    CUSTOM = "custom"
    OUTLINE = "outline"
    POSTER = "poster"
    SHADOW = "shadow"


class FontStyleHint(str, Enum):
    SANS = "sans"
    SERIF = "serif"
    DISPLAY = "display"
    HANDWRITTEN = "handwritten"


@dataclass(frozen=True, slots=True)
class TextBox:
    center_x: float
    center_y: float
    width: float
    height: float
    rotation_degrees: float = 0

    def __post_init__(self) -> None:
        values = (self.center_x, self.center_y, self.width, self.height, self.rotation_degrees)
        if not all(isfinite(value) for value in values):
            raise ValueError("Text box values must be finite")
        if self.width <= 0 or self.height <= 0:
            raise ValueError("Text box dimensions must be positive")


@dataclass(frozen=True, slots=True)
class PathPoint:
    x: float
    y: float

    def __post_init__(self) -> None:
        if not isfinite(self.x) or not isfinite(self.y):
            raise ValueError("Text path point values must be finite")


@dataclass(frozen=True, slots=True)
class ArcTextPath:
    start: PathPoint
    control: PathPoint
    end: PathPoint
    reverse: bool = False

    def __post_init__(self) -> None:
        if self.start == self.end:
            raise ValueError("Text path start and end must differ")

    def point_at(self, position: float) -> PathPoint:
        if not 0 <= position <= 1:
            raise ValueError("Text path position must be between zero and one")
        remaining = 1 - position
        return PathPoint(
            remaining * remaining * self.start.x
            + 2 * remaining * position * self.control.x
            + position * position * self.end.x,
            remaining * remaining * self.start.y
            + 2 * remaining * position * self.control.y
            + position * position * self.end.y,
        )

    def tangent_at(self, position: float) -> PathPoint:
        if not 0 <= position <= 1:
            raise ValueError("Text path position must be between zero and one")
        return PathPoint(
            2
            * ((1 - position) * (self.control.x - self.start.x)
               + position * (self.end.x - self.control.x)),
            2
            * ((1 - position) * (self.control.y - self.start.y)
               + position * (self.end.y - self.control.y)),
        )

    def approximate_length(self, segments: int = 96) -> float:
        if segments <= 0:
            raise ValueError("Text path segments must be positive")
        previous = self.start
        length = 0.0
        for index in range(1, segments + 1):
            point = self.point_at(index / segments)
            length += hypot(point.x - previous.x, point.y - previous.y)
            previous = point
        return length


@dataclass(frozen=True, slots=True)
class TextStyle:
    font_family: str
    font_size: float
    fill_rgb: tuple[int, int, int]
    alignment: TextAlignment = TextAlignment.CENTER
    vertical_alignment: VerticalAlignment = VerticalAlignment.CENTER
    wrap: bool = True
    auto_fit: bool = True
    stroke_rgb: tuple[int, int, int] = (255, 255, 255)
    stroke_width: float = 0
    shadow_rgb: tuple[int, int, int] = (0, 0, 0)
    shadow_opacity: float = 0
    shadow_offset_x: float = 2
    shadow_offset_y: float = 2
    effect_preset: ArtisticPreset = ArtisticPreset.CUSTOM
    font_degraded: bool = False
    font_fallback_reason: str | None = None

    def __post_init__(self) -> None:
        if not self.font_family or self.font_size <= 0:
            raise ValueError("Text style requires a font family and positive size")
        for color in (self.fill_rgb, self.stroke_rgb, self.shadow_rgb):
            if len(color) != 3 or any(not 0 <= value <= 255 for value in color):
                raise ValueError("Text colors must be RGB values")
        if self.stroke_width < 0:
            raise ValueError("Text stroke width cannot be negative")
        if not 0 <= self.shadow_opacity <= 1:
            raise ValueError("Shadow opacity must be between zero and one")
        if self.font_fallback_reason is not None and not self.font_degraded:
            raise ValueError("Font fallback reason requires a degraded font")


@dataclass(frozen=True, slots=True)
class TextLayer:
    region_id: str
    text: str
    box: TextBox
    style: TextStyle
    overflow: bool = False
    path: ArcTextPath | None = None

    def __post_init__(self) -> None:
        if not self.region_id:
            raise ValueError("Text layer region ID cannot be empty")


@dataclass(frozen=True, slots=True)
class TextLayout:
    layers: tuple[TextLayer, ...]

    def __post_init__(self) -> None:
        region_ids = tuple(layer.region_id for layer in self.layers)
        if len(region_ids) != len(set(region_ids)):
            raise ValueError("Text layout region IDs must be unique")

    def layer_by_id(self, region_id: str) -> TextLayer:
        for layer in self.layers:
            if layer.region_id == region_id:
                return layer
        raise KeyError(region_id)

    def replace_layer(self, replacement: TextLayer) -> "TextLayout":
        self.layer_by_id(replacement.region_id)
        return replace(
            self,
            layers=tuple(
                replacement if layer.region_id == replacement.region_id else layer
                for layer in self.layers
            ),
        )

    def add_layer(self, layer: TextLayer, index: int | None = None) -> "TextLayout":
        if any(existing.region_id == layer.region_id for existing in self.layers):
            raise ValueError("Text layer region ID already exists")
        values = list(self.layers)
        values.insert(len(values) if index is None else index, layer)
        return replace(self, layers=tuple(values))

    def remove_layer(self, region_id: str) -> tuple["TextLayout", TextLayer, int]:
        layer = self.layer_by_id(region_id)
        index = self.layers.index(layer)
        return replace(self, layers=self.layers[:index] + self.layers[index + 1 :]), layer, index


def fit_font_size(
    minimum: float,
    maximum: float,
    fits: Callable[[float], bool],
    iterations: int = 10,
) -> tuple[float, bool]:
    if minimum <= 0 or maximum < minimum:
        raise ValueError("Invalid font-size range")
    if not fits(minimum):
        return minimum, True
    low, high = minimum, maximum
    for _ in range(iterations):
        middle = (low + high) / 2
        if fits(middle):
            low = middle
        else:
            high = middle
    return low, False


def default_arc_path(box: TextBox, bend: float = 0.35) -> ArcTextPath:
    if not -1 <= bend <= 1:
        raise ValueError("Default arc bend must be between minus one and one")
    angle = radians(box.rotation_degrees)

    def mapped(local_x: float, local_y: float) -> PathPoint:
        return PathPoint(
            box.center_x + local_x * cos(angle) - local_y * sin(angle),
            box.center_y + local_x * sin(angle) + local_y * cos(angle),
        )

    return ArcTextPath(
        mapped(-box.width / 2, 0),
        mapped(0, -box.height * bend),
        mapped(box.width / 2, 0),
    )


def transform_arc_path(
    path: ArcTextPath,
    source_box: TextBox,
    target_box: TextBox,
) -> ArcTextPath:
    source_angle = radians(source_box.rotation_degrees)
    target_angle = radians(target_box.rotation_degrees)

    def transformed(point: PathPoint) -> PathPoint:
        dx = point.x - source_box.center_x
        dy = point.y - source_box.center_y
        local_x = dx * cos(source_angle) + dy * sin(source_angle)
        local_y = -dx * sin(source_angle) + dy * cos(source_angle)
        scaled_x = local_x * target_box.width / source_box.width
        scaled_y = local_y * target_box.height / source_box.height
        return PathPoint(
            target_box.center_x
            + scaled_x * cos(target_angle)
            - scaled_y * sin(target_angle),
            target_box.center_y
            + scaled_x * sin(target_angle)
            + scaled_y * cos(target_angle),
        )

    return ArcTextPath(
        transformed(path.start),
        transformed(path.control),
        transformed(path.end),
        path.reverse,
    )
