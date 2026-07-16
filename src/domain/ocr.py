from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import atan2, isfinite
from typing import Iterable
import unicodedata


class OcrError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class Point:
    x: float
    y: float

    def __post_init__(self) -> None:
        if not isfinite(self.x) or not isfinite(self.y):
            raise ValueError("OCR coordinates must be finite")


Quad = tuple[Point, Point, Point, Point]


class TextRegionStatus(str, Enum):
    OK = "ok"
    LOW_CONFIDENCE = "low_confidence"


@dataclass(frozen=True, slots=True)
class TextRegion:
    region_id: str
    polygon: Quad
    text: str
    confidence: float
    language_code: str
    model_id: str
    status: TextRegionStatus = TextRegionStatus.OK

    def __post_init__(self) -> None:
        if not self.region_id:
            raise ValueError("OCR region ID cannot be empty")
        if len(self.polygon) != 4:
            raise ValueError("OCR polygon must contain four points")
        if abs(_signed_area(self.polygon)) < 1e-6:
            raise ValueError("OCR polygon must have a positive area")
        if not 0 <= self.confidence <= 1:
            raise ValueError("OCR confidence must be between zero and one")
        if not self.language_code:
            raise ValueError("OCR language code cannot be empty")


@dataclass(frozen=True, slots=True)
class OcrResult:
    regions: tuple[TextRegion, ...]
    language_code: str
    model_id: str
    elapsed_ms: float

    def __post_init__(self) -> None:
        if self.elapsed_ms < 0:
            raise ValueError("OCR elapsed time cannot be negative")


def normalize_ocr_text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFC", value).split())


def order_quad(values: Iterable[Iterable[float]]) -> Quad:
    points = tuple(Point(float(value[0]), float(value[1])) for value in values)
    if len(points) != 4 or len(set(points)) != 4:
        raise ValueError("OCR polygon must contain four unique points")
    center_x = sum(point.x for point in points) / 4
    center_y = sum(point.y for point in points) / 4
    ordered = sorted(points, key=lambda point: atan2(point.y - center_y, point.x - center_x))
    start = min(range(4), key=lambda index: (ordered[index].x + ordered[index].y, ordered[index].y))
    ordered = ordered[start:] + ordered[:start]
    if _signed_area(ordered) < 0:
        ordered = [ordered[0], ordered[3], ordered[2], ordered[1]]
    if abs(_signed_area(ordered)) < 1e-6:
        raise ValueError("OCR polygon must have a positive area")
    return tuple(ordered)  # type: ignore[return-value]


def _signed_area(points: Iterable[Point]) -> float:
    values = tuple(points)
    return sum(
        values[index].x * values[(index + 1) % 4].y
        - values[(index + 1) % 4].x * values[index].y
        for index in range(4)
    ) / 2
