from __future__ import annotations

from time import perf_counter

import cv2

from prototypes.lama_ecommerce.contracts import RepairRequest, RepairResult
from prototypes.lama_ecommerce.mask_variants import (
    composite_candidate,
    make_mask_variant,
    mask_crop,
)
from prototypes.lama_ecommerce.runtime import PeakRssSampler


class OpenCVInpaintAdapter:
    name = "opencv-telea"

    def inpaint(self, request: RepairRequest) -> RepairResult:
        variant = make_mask_variant(
            request.mask, request.protect_mask, request.expand_px, request.feather_px
        )
        crop = (
            mask_crop(variant.inference_mask, request.context_px)
            if request.mode == "local"
            else (0, 0, request.image.shape[1], request.image.shape[0])
        )
        x0, y0, x1, y1 = crop
        source = request.image[y0:y1, x0:x1, :3]
        mask = variant.inference_mask[y0:y1, x0:x1]
        with PeakRssSampler() as rss:
            started = perf_counter()
            candidate_crop = cv2.cvtColor(
                cv2.inpaint(cv2.cvtColor(source, cv2.COLOR_RGB2BGR), mask, 3, cv2.INPAINT_TELEA),
                cv2.COLOR_BGR2RGB,
            )
            elapsed = (perf_counter() - started) * 1000
        candidate = request.image.copy()
        candidate[y0:y1, x0:x1, :3] = candidate_crop
        result = composite_candidate(request.image, candidate, variant.blend_alpha)
        return RepairResult(
            image=result,
            backend=self.name,
            strategy=f"{request.mode}-e{request.expand_px}-f{request.feather_px}",
            inference_ms=elapsed,
            peak_rss_bytes=rss.peak,
            crop=crop,
        )

