from __future__ import annotations

from pathlib import Path
from time import perf_counter

import cv2
import numpy as np
import onnxruntime as ort

from prototypes.lama_ecommerce.contracts import RepairRequest, RepairResult
from prototypes.lama_ecommerce.mask_variants import (
    composite_candidate,
    make_mask_variant,
    mask_crop,
)
from prototypes.lama_ecommerce.runtime import PeakRssSampler


class LaMaOnnxAdapter:
    name = "lama-onnxruntime"

    def __init__(self, model_path: Path, threads: int = 2) -> None:
        if not model_path.is_file():
            raise FileNotFoundError(model_path)
        options = ort.SessionOptions()
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
        options.log_severity_level = 3
        started = perf_counter()
        self._session = ort.InferenceSession(
            str(model_path), sess_options=options, providers=["CPUExecutionProvider"]
        )
        self.load_ms = (perf_counter() - started) * 1000
        self.model_path = model_path
        self.inference_count = 0
        warmup_image = np.zeros((1, 3, 512, 512), np.float32)
        warmup_mask = np.zeros((1, 1, 512, 512), np.float32)
        started = perf_counter()
        self._session.run(None, {"image": warmup_image, "mask": warmup_mask})
        self.warmup_ms = (perf_counter() - started) * 1000

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
        if not np.any(variant.inference_mask):
            return RepairResult(
                request.image.copy(), self.name, "empty-mask", 0, 0, crop
            )
        with PeakRssSampler() as rss:
            started = perf_counter()
            candidate_crop = self._infer(
                request.image[y0:y1, x0:x1, :3],
                variant.inference_mask[y0:y1, x0:x1],
            )
            elapsed = (perf_counter() - started) * 1000
        self.inference_count += 1
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

    def _infer(self, image: np.ndarray, mask: np.ndarray) -> np.ndarray:
        target_size = (512, 512)
        resized_image = cv2.resize(image, target_size, interpolation=cv2.INTER_AREA)
        resized_mask = cv2.resize(mask, target_size, interpolation=cv2.INTER_NEAREST)
        image_tensor = (
            resized_image.astype(np.float32).transpose(2, 0, 1)[None, ...] / 255.0
        )
        mask_tensor = (resized_mask > 0).astype(np.float32)[None, None, ...]
        output = self._session.run(
            None, {"image": image_tensor, "mask": mask_tensor}
        )[0][0]
        rgb = np.clip(output.transpose(1, 2, 0), 0, 255).astype(np.uint8)
        return cv2.resize(rgb, (image.shape[1], image.shape[0]), interpolation=cv2.INTER_CUBIC)
