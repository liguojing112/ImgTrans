from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ProductInfo:
    name: str
    version: str
    milestone: str

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("Product name cannot be empty")
        if not self.version.strip():
            raise ValueError("Product version cannot be empty")
        if not self.milestone.strip():
            raise ValueError("Product milestone cannot be empty")
