from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal
import json


Direction = Literal["auto", "ltr", "rtl"]
Alignment = Literal["left", "center", "right"]


class LayoutContractError(ValueError):
    pass


@dataclass(frozen=True)
class LayoutRequest:
    case_id: str
    text: str
    language_code: str
    font_path: Path
    direction: Direction
    width: int
    height: int
    font_size: float
    alignment: Alignment = "left"

    def __post_init__(self) -> None:
        if not self.case_id or not self.text:
            raise LayoutContractError("case_id and text are required")
        if self.direction not in {"auto", "ltr", "rtl"}:
            raise LayoutContractError(f"Unsupported direction: {self.direction}")
        if self.alignment not in {"left", "center", "right"}:
            raise LayoutContractError(f"Unsupported alignment: {self.alignment}")
        if self.width <= 0 or self.height <= 0 or self.font_size <= 0:
            raise LayoutContractError("Layout dimensions and font size must be positive")

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["font_path"] = str(self.font_path)
        return value


@dataclass(frozen=True)
class GlyphCluster:
    text_start: int
    text_end: int
    text: str
    font_file: str
    glyph_ids: tuple[int, ...]
    positions: tuple[tuple[float, float], ...]
    bounds: tuple[float, float, float, float]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class LayoutLine:
    text_start: int
    text_end: int
    direction: Literal["ltr", "rtl"]
    position: tuple[float, float]
    size: tuple[float, float]
    clusters: tuple[GlyphCluster, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "clusters": [cluster.to_dict() for cluster in self.clusters],
        }


@dataclass(frozen=True)
class LayoutResult:
    backend: str
    request: LayoutRequest
    lines: tuple[LayoutLine, ...]
    ink_bounds: tuple[float, float, float, float]
    warnings: tuple[str, ...] = ()

    @property
    def cluster_sequence(self) -> tuple[tuple[int, int], ...]:
        return tuple(
            (cluster.text_start, cluster.text_end)
            for line in self.lines
            for cluster in line.clusters
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "request": self.request.to_dict(),
            "lines": [line.to_dict() for line in self.lines],
            "ink_bounds": self.ink_bounds,
            "warnings": self.warnings,
            "cluster_sequence": self.cluster_sequence,
        }


def load_requests(path: Path, fonts_dir: Path) -> tuple[LayoutRequest, ...]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    requests: list[LayoutRequest] = []
    for language in raw.get("languages", []):
        defaults = {
            "language_code": str(language["language_code"]),
            "font_path": fonts_dir / str(language["font_file"]),
            "direction": str(language.get("direction", "auto")),
            "width": int(language.get("width", 520)),
            "height": int(language.get("height", 180)),
            "font_size": float(language.get("font_size", 40)),
            "alignment": str(language.get("alignment", "left")),
        }
        for case in language.get("cases", []):
            requests.append(
                LayoutRequest(
                    case_id=str(case["id"]),
                    text=str(case["text"]),
                    language_code=defaults["language_code"],
                    font_path=defaults["font_path"],
                    direction=case.get("direction", defaults["direction"]),
                    width=int(case.get("width", defaults["width"])),
                    height=int(case.get("height", defaults["height"])),
                    font_size=float(case.get("font_size", defaults["font_size"])),
                    alignment=case.get("alignment", defaults["alignment"]),
                )
            )
    ids = [request.case_id for request in requests]
    if len(ids) != len(set(ids)):
        raise LayoutContractError("Case IDs must be unique")
    return tuple(requests)
