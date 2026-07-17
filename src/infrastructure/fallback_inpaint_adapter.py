from __future__ import annotations

from time import perf_counter
from threading import Event

import cv2
import numpy as np

from src.application.ports import InpaintingAdapter
from src.domain.inpainting import InpaintingRequest, InpaintingResult


class FallbackInpaintAdapter:
    adapter_id = "lama-with-opencv-fallback"

    def __init__(
        self,
        primary: InpaintingAdapter,
        fallback: InpaintingAdapter,
    ) -> None:
        self._primary = primary
        self._fallback = fallback
        self._cancelled = Event()

    def inpaint(self, request: InpaintingRequest) -> InpaintingResult:
        started = perf_counter()
        if self._cancelled.is_set():
            raise RuntimeError("修复任务已取消")
        try:
            result = self._primary.inpaint(request)
        except Exception as error:
            if self._cancelled.is_set():
                raise RuntimeError("修复任务已取消") from error
            result = self._fallback.inpaint(request)
            return InpaintingResult(
                result.document,
                result.backend_id,
                (perf_counter() - started) * 1000,
                f"LaMa 不可用，已使用 OpenCV 快速修复：{error}",
            )
        if not _has_smooth_background_artifact(request, result):
            return result
        fallback = self._fallback.inpaint(request)
        return InpaintingResult(
            fallback.document,
            fallback.backend_id,
            (perf_counter() - started) * 1000,
            "LaMa 修复与平滑背景边界不一致，已使用 OpenCV 快速修复",
        )

    def close(self) -> None:
        close = getattr(self._primary, "close", None)
        if close is not None:
            close()

    def reset_cancel(self) -> None:
        self._cancelled.clear()

    def cancel(self) -> None:
        self._cancelled.set()
        cancel = getattr(self._primary, "cancel", None)
        if cancel is not None:
            cancel()
        else:
            self.close()


def _has_smooth_background_artifact(
    request: InpaintingRequest,
    result: InpaintingResult,
) -> bool:
    source = request.document
    output = result.document
    if (
        source.asset.width != output.asset.width
        or source.asset.height != output.asset.height
        or source.mode != output.mode
    ):
        return True
    height, width = source.asset.height, source.asset.width
    channels = 4 if source.mode == "RGBA" else 3
    source_pixels = np.frombuffer(source.pixels, dtype=np.uint8).reshape(
        height, width, channels
    )[..., :3]
    output_pixels = np.frombuffer(output.pixels, dtype=np.uint8).reshape(
        height, width, channels
    )[..., :3]
    mask = np.frombuffer(request.erase_mask.pixels, dtype=np.uint8).reshape(
        height, width
    ) > 0
    if request.protect_mask is not None:
        protected = np.frombuffer(
            request.protect_mask.pixels,
            dtype=np.uint8,
        ).reshape(height, width) > 0
        mask &= ~protected
    if not np.any(mask):
        return False
    ring = cv2.dilate(
        mask.astype(np.uint8),
        np.ones((9, 9), dtype=np.uint8),
        iterations=1,
    ).astype(bool) & ~mask
    if np.count_nonzero(ring) < 32:
        return False
    boundary = source_pixels[ring].astype(np.float32)
    boundary_color = np.median(boundary, axis=0)
    boundary_distance = np.linalg.norm(boundary - boundary_color, axis=1)
    if float(np.percentile(boundary_distance, 90)) > 18.0:
        return False
    repaired = output_pixels[mask].astype(np.float32)
    repaired_distance = np.linalg.norm(repaired - boundary_color, axis=1)
    return float(np.percentile(repaired_distance, 85)) > 60.0
