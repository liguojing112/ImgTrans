from __future__ import annotations

from dataclasses import dataclass
from math import atan2, isfinite
from pathlib import Path
from typing import Any, Iterable
import json
import unicodedata


Point = tuple[float, float]
Quad = tuple[Point, Point, Point, Point]


class ContractError(ValueError):
    pass


def order_quad(points: Iterable[Iterable[float]]) -> Quad:
    parsed = tuple((float(point[0]), float(point[1])) for point in points)
    if len(parsed) != 4:
        raise ContractError("A text polygon must contain exactly four points")
    if any(not isfinite(value) for point in parsed for value in point):
        raise ContractError("Text polygon coordinates must be finite")
    if len(set(parsed)) != 4:
        raise ContractError("Text polygon points must be unique")

    center_x = sum(point[0] for point in parsed) / 4
    center_y = sum(point[1] for point in parsed) / 4
    ordered = sorted(parsed, key=lambda point: atan2(point[1] - center_y, point[0] - center_x))
    start = min(range(4), key=lambda index: (sum(ordered[index]), ordered[index][1], ordered[index][0]))
    ordered = ordered[start:] + ordered[:start]
    if _signed_area(ordered) < 0:
        ordered = [ordered[0], ordered[3], ordered[2], ordered[1]]
    if abs(_signed_area(ordered)) < 1e-6:
        raise ContractError("Text polygon area must be greater than zero")
    return tuple(ordered)  # type: ignore[return-value]


def _signed_area(points: Iterable[Point]) -> float:
    values = tuple(points)
    return sum(
        values[index][0] * values[(index + 1) % 4][1]
        - values[(index + 1) % 4][0] * values[index][1]
        for index in range(4)
    ) / 2


def normalize_text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFC", value).split())


@dataclass(frozen=True)
class ExpectedRegion:
    polygon: Quad
    text: str
    difficulty: str = "clear_print"

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ExpectedRegion":
        return cls(
            polygon=order_quad(value["polygon"]),
            text=str(value["text"]),
            difficulty=str(value.get("difficulty", "clear_print")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "polygon": [list(point) for point in self.polygon],
            "text": self.text,
            "difficulty": self.difficulty,
        }


@dataclass(frozen=True)
class OCRRegion:
    polygon: Quad
    text: str
    confidence: float
    language_code: str
    language_confidence: float
    model_id: str
    status: str = "ok"

    def __post_init__(self) -> None:
        if not 0 <= self.confidence <= 1:
            raise ContractError("OCR confidence must be between zero and one")
        if not 0 <= self.language_confidence <= 1:
            raise ContractError("Language confidence must be between zero and one")

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "OCRRegion":
        return cls(
            polygon=order_quad(value["polygon"]),
            text=str(value["text"]),
            confidence=float(value["confidence"]),
            language_code=str(value["language_code"]),
            language_confidence=float(value.get("language_confidence", 1.0)),
            model_id=str(value["model_id"]),
            status=str(value.get("status", "ok")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "polygon": [list(point) for point in self.polygon],
            "text": self.text,
            "confidence": self.confidence,
            "language_code": self.language_code,
            "language_confidence": self.language_confidence,
            "model_id": self.model_id,
            "status": self.status,
        }


@dataclass(frozen=True)
class ManifestSample:
    sample_id: str
    image: str | None
    language_code: str
    script: str
    license: str
    expected_regions: tuple[ExpectedRegion, ...]
    fixture_regions: tuple[OCRRegion, ...] = ()

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ManifestSample":
        return cls(
            sample_id=str(value["id"]),
            image=str(value["image"]) if value.get("image") else None,
            language_code=str(value["language_code"]),
            script=str(value["script"]),
            license=str(value["license"]),
            expected_regions=tuple(
                ExpectedRegion.from_dict(region) for region in value.get("expected_regions", [])
            ),
            fixture_regions=tuple(
                OCRRegion.from_dict(region) for region in value.get("fixture_regions", [])
            ),
        )


@dataclass(frozen=True)
class Manifest:
    dataset_kind: str
    adapter: str
    samples: tuple[ManifestSample, ...]

    @classmethod
    def load(cls, path: Path) -> "Manifest":
        value = json.loads(path.read_text(encoding="utf-8"))
        samples = tuple(ManifestSample.from_dict(sample) for sample in value.get("samples", []))
        ids = [sample.sample_id for sample in samples]
        if len(ids) != len(set(ids)):
            raise ContractError("Manifest sample IDs must be unique")
        return cls(
            dataset_kind=str(value.get("dataset_kind", "unclassified")),
            adapter=str(value.get("adapter", "rapidocr")),
            samples=samples,
        )

