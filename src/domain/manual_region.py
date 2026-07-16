from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import cos, radians, sin

from src.domain.inpainting import EraseMask, InpaintingResult
from src.domain.layout import TextBox, TextLayer
from src.domain.ocr import Quad, order_quad


class ManualRegionError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class ManualInputMode(str, Enum):
    AUTO = "auto"
    SOURCE_TEXT = "source_text"
    TRANSLATED_TEXT = "translated_text"


@dataclass(frozen=True, slots=True)
class ManualRegionSpec:
    mode: ManualInputMode
    selection_box: TextBox
    erase_box: TextBox
    text_box: TextBox
    source_text: str = ""
    translated_text: str = ""

    def __post_init__(self) -> None:
        if self.mode is ManualInputMode.SOURCE_TEXT and not self.source_text.strip():
            raise ValueError("Direct source-text mode requires source text")
        if self.mode is ManualInputMode.TRANSLATED_TEXT and not self.translated_text.strip():
            raise ValueError("Direct translated-text mode requires translated text")


@dataclass(frozen=True, slots=True)
class ManualRegionResult:
    region_id: str
    source_text: str
    translated_text: str
    erase_mask: EraseMask
    repaired_background: InpaintingResult
    layer: TextLayer


def box_to_quad(box: TextBox) -> Quad:
    angle = radians(box.rotation_degrees)
    points = []
    for x, y in (
        (-box.width / 2, -box.height / 2),
        (box.width / 2, -box.height / 2),
        (box.width / 2, box.height / 2),
        (-box.width / 2, box.height / 2),
    ):
        points.append(
            (
                box.center_x + x * cos(angle) - y * sin(angle),
                box.center_y + x * sin(angle) + y * cos(angle),
            )
        )
    return order_quad(points)
