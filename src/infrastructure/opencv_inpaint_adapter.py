from __future__ import annotations

from time import perf_counter

import cv2
import numpy as np

from src.domain.image import ImageDocument
from src.domain.inpainting import InpaintingError, InpaintingRequest, InpaintingResult


class OpenCvInpaintAdapter:
    adapter_id = "opencv-telea"

    def __init__(self, radius: float = 3.0) -> None:
        self._radius = radius

    def inpaint(self, request: InpaintingRequest) -> InpaintingResult:
        started = perf_counter()
        document = request.document
        channels = 4 if document.mode == "RGBA" else 3
        source = np.frombuffer(document.pixels, dtype=np.uint8).reshape(
            document.asset.height, document.asset.width, channels
        )
        mask = np.frombuffer(request.erase_mask.pixels, dtype=np.uint8).reshape(
            request.erase_mask.height, request.erase_mask.width
        )
        if request.protect_mask is not None:
            protected = np.frombuffer(request.protect_mask.pixels, dtype=np.uint8).reshape(
                request.protect_mask.height, request.protect_mask.width
            )
            mask = np.where(protected > 0, 0, mask).astype(np.uint8)
        if not np.any(mask):
            raise InpaintingError("empty_erase_mask", "擦除蒙版为空")
        rgb = source[:, :, :3]
        try:
            repaired = cv2.cvtColor(
                cv2.inpaint(cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR), mask, self._radius, cv2.INPAINT_TELEA),
                cv2.COLOR_BGR2RGB,
            )
        except cv2.error as error:
            raise InpaintingError("opencv_failed", f"OpenCV 修复失败：{error}") from error
        output_rgb = rgb.copy()
        selected = mask > 0
        output_rgb[selected] = repaired[selected]
        if document.mode == "RGBA":
            output = np.dstack((output_rgb, source[:, :, 3]))
        else:
            output = output_rgb
        result_document = ImageDocument(document.asset, document.mode, output.tobytes())
        return InpaintingResult(
            result_document,
            self.adapter_id,
            (perf_counter() - started) * 1000,
        )
