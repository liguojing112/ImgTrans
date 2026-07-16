from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class ImageLimitError(ValueError):
    pass


class ImageLimitNotFound(ImageLimitError):
    pass


class ImageLimitConflict(ImageLimitError):
    pass


class ImageLimitStatus(str, Enum):
    DRAFT = "draft"
    PUBLISHED = "published"
    SUPERSEDED = "superseded"


@dataclass(frozen=True, slots=True)
class ImageLimitValues:
    min_width: int
    min_height: int
    max_width: int
    max_height: int
    max_bytes: int

    def __post_init__(self) -> None:
        values = (
            self.min_width,
            self.min_height,
            self.max_width,
            self.max_height,
            self.max_bytes,
        )
        if any(value <= 0 for value in values):
            raise ImageLimitError("Image limits must be positive")
        if self.min_width > self.max_width:
            raise ImageLimitError("Minimum width cannot exceed maximum width")
        if self.min_height > self.max_height:
            raise ImageLimitError("Minimum height cannot exceed maximum height")


@dataclass(frozen=True, slots=True)
class ImageLimitVersion:
    version: int
    values: ImageLimitValues
    status: ImageLimitStatus
    created_at: datetime
    published_at: datetime | None = None
    source_version: int | None = None
