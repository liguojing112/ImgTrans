from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class ImageFileFormat(str, Enum):
    JPEG = "JPEG"
    PNG = "PNG"
    WEBP = "WEBP"
    GIF = "GIF"
    TIFF = "TIFF"

    @classmethod
    def from_input_suffix(cls, suffix: str) -> "ImageFileFormat":
        mapping = {
            ".jpg": cls.JPEG,
            ".jpeg": cls.JPEG,
            ".png": cls.PNG,
            ".webp": cls.WEBP,
        }
        try:
            return mapping[suffix.lower()]
        except KeyError as error:
            raise ImageValidationError("unsupported_input_format", "仅支持 JPG、PNG 和 WebP") from error

    @classmethod
    def from_output_suffix(cls, suffix: str) -> "ImageFileFormat":
        mapping = {
            ".jpg": cls.JPEG,
            ".jpeg": cls.JPEG,
            ".png": cls.PNG,
            ".webp": cls.WEBP,
            ".gif": cls.GIF,
            ".tif": cls.TIFF,
            ".tiff": cls.TIFF,
        }
        try:
            return mapping[suffix.lower()]
        except KeyError as error:
            raise ImageValidationError(
                "unsupported_output_format", "仅支持 JPG、PNG、WebP、GIF 和 TIFF"
            ) from error


class ImageValidationError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class ImageLimits:
    min_width: int = 64
    min_height: int = 64
    max_width: int = 12_000
    max_height: int = 12_000
    max_bytes: int = 50 * 1024 * 1024
    max_pixels: int = 80_000_000
    source: str = "builtin"
    config_version: int | None = None

    def __post_init__(self) -> None:
        values = (
            self.min_width,
            self.min_height,
            self.max_width,
            self.max_height,
            self.max_bytes,
            self.max_pixels,
        )
        if any(value <= 0 for value in values):
            raise ValueError("Image limits must be positive")
        if self.min_width > self.max_width or self.min_height > self.max_height:
            raise ValueError("Minimum image dimensions cannot exceed maximum dimensions")

    def validate_file_size(self, size: int) -> None:
        if size > self.max_bytes:
            raise ImageValidationError(
                "file_too_large", f"图片文件超过当前限制 {self.max_bytes // 1024 // 1024} MiB"
            )

    def validate_dimensions(self, width: int, height: int) -> None:
        if width < self.min_width or height < self.min_height:
            raise ImageValidationError(
                "dimensions_too_small",
                f"图片宽高不得小于 {self.min_width}×{self.min_height} px",
            )
        if width > self.max_width or height > self.max_height:
            raise ImageValidationError(
                "dimensions_too_large",
                f"图片宽高不得超过 {self.max_width}×{self.max_height} px",
            )
        if width * height > self.max_pixels:
            raise ImageValidationError(
                "pixel_count_too_large", f"图片解码像素不得超过 {self.max_pixels:,}"
            )


@dataclass(frozen=True, slots=True)
class ImageAsset:
    source_path: Path
    width: int
    height: int
    file_size: int
    file_format: ImageFileFormat
    has_alpha: bool
    orientation_applied: bool


@dataclass(frozen=True, slots=True)
class ImageDocument:
    asset: ImageAsset
    mode: str
    pixels: bytes

    def __post_init__(self) -> None:
        channels = {"RGB": 3, "RGBA": 4}.get(self.mode)
        if channels is None:
            raise ValueError("Working image mode must be RGB or RGBA")
        expected = self.asset.width * self.asset.height * channels
        if len(self.pixels) != expected:
            raise ValueError("Pixel buffer size does not match image dimensions")
