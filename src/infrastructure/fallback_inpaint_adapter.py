from __future__ import annotations

from time import perf_counter
from threading import Event

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
            return self._primary.inpaint(request)
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
