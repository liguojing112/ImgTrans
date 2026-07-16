from __future__ import annotations

from dataclasses import dataclass

from src.domain.image import ImageDocument


class InpaintingError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class EraseMask:
    width: int
    height: int
    pixels: bytes

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError("Mask dimensions must be positive")
        if len(self.pixels) != self.width * self.height:
            raise ValueError("Mask buffer size does not match its dimensions")

    @property
    def is_empty(self) -> bool:
        return not any(self.pixels)


@dataclass(frozen=True, slots=True)
class InpaintingRequest:
    document: ImageDocument
    erase_mask: EraseMask
    context_pixels: int = 96
    protect_mask: EraseMask | None = None

    def __post_init__(self) -> None:
        size = (self.document.asset.width, self.document.asset.height)
        if size != (self.erase_mask.width, self.erase_mask.height):
            raise ValueError("Image and erase mask dimensions must match")
        if self.context_pixels < 0:
            raise ValueError("Inpainting context cannot be negative")
        if self.protect_mask is not None and size != (
            self.protect_mask.width,
            self.protect_mask.height,
        ):
            raise ValueError("Image and protection mask dimensions must match")

@dataclass(frozen=True, slots=True)
class InpaintingResult:
    document: ImageDocument
    backend_id: str
    elapsed_ms: float
    warning: str | None = None

    def __post_init__(self) -> None:
        if not self.backend_id:
            raise ValueError("Inpainting backend ID cannot be empty")
        if self.elapsed_ms < 0:
            raise ValueError("Inpainting elapsed time cannot be negative")


@dataclass(frozen=True, slots=True)
class RepairOutcome:
    erase_mask: EraseMask
    result: InpaintingResult
