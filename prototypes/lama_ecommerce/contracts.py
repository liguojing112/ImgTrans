from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal
import json

import numpy as np


RepairMode = Literal["full", "local"]


class RepairContractError(ValueError):
    pass


@dataclass(frozen=True)
class DatasetManifest:
    width: int
    height: int
    samples_per_category: int
    categories: tuple[str, ...]
    seed: int
    license: str

    @classmethod
    def load(cls, path: Path) -> "DatasetManifest":
        value = json.loads(path.read_text(encoding="utf-8"))
        manifest = cls(
            width=int(value["width"]),
            height=int(value["height"]),
            samples_per_category=int(value["samples_per_category"]),
            categories=tuple(str(item) for item in value["categories"]),
            seed=int(value["seed"]),
            license=str(value["license"]),
        )
        if manifest.width <= 0 or manifest.height <= 0:
            raise RepairContractError("Dataset dimensions must be positive")
        if manifest.samples_per_category < 1 or len(set(manifest.categories)) != len(
            manifest.categories
        ):
            raise RepairContractError("Dataset categories and counts must be valid")
        return manifest


@dataclass(frozen=True)
class SamplePaths:
    sample_id: str
    category: str
    input_path: Path
    reference_path: Path
    mask_path: Path
    protect_path: Path


@dataclass(frozen=True)
class RepairRequest:
    image: np.ndarray
    mask: np.ndarray
    protect_mask: np.ndarray | None = None
    mode: RepairMode = "local"
    expand_px: int = 2
    feather_px: int = 2
    context_px: int = 96

    def __post_init__(self) -> None:
        if self.image.dtype != np.uint8 or self.image.ndim != 3:
            raise RepairContractError("Image must be an HxWxC uint8 array")
        if self.image.shape[2] not in {3, 4}:
            raise RepairContractError("Image must be RGB or RGBA")
        if self.mask.dtype != np.uint8 or self.mask.shape != self.image.shape[:2]:
            raise RepairContractError("Mask must be a same-size HxW uint8 array")
        if self.protect_mask is not None and (
            self.protect_mask.dtype != np.uint8
            or self.protect_mask.shape != self.image.shape[:2]
        ):
            raise RepairContractError("Protection mask must be a same-size HxW uint8 array")
        if self.mode not in {"full", "local"}:
            raise RepairContractError(f"Unsupported repair mode: {self.mode}")
        if min(self.expand_px, self.feather_px, self.context_px) < 0:
            raise RepairContractError("Mask and context parameters cannot be negative")


@dataclass(frozen=True)
class RepairResult:
    image: np.ndarray
    backend: str
    strategy: str
    inference_ms: float
    peak_rss_bytes: int
    crop: tuple[int, int, int, int]

