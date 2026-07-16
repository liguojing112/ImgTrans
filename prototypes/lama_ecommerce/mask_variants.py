from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass(frozen=True)
class MaskVariant:
    inference_mask: np.ndarray
    blend_alpha: np.ndarray
    allowed_mask: np.ndarray


def make_mask_variant(
    mask: np.ndarray,
    protect_mask: np.ndarray | None,
    expand_px: int,
    feather_px: int,
) -> MaskVariant:
    binary = (mask > 0).astype(np.uint8)
    if expand_px:
        size = expand_px * 2 + 1
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (size, size))
        binary = cv2.dilate(binary, kernel)
    protected = (
        np.zeros_like(binary, dtype=bool)
        if protect_mask is None
        else protect_mask.astype(bool)
    )
    binary[protected] = 0
    alpha = binary.astype(np.float32)
    if feather_px:
        kernel_size = feather_px * 6 + 1
        if kernel_size % 2 == 0:
            kernel_size += 1
        alpha = cv2.GaussianBlur(alpha, (kernel_size, kernel_size), feather_px)
        alpha[protected] = 0
    alpha = np.clip(alpha, 0, 1)
    allowed = alpha > 0
    return MaskVariant(binary * 255, alpha, allowed)


def mask_crop(mask: np.ndarray, context_px: int) -> tuple[int, int, int, int]:
    ys, xs = np.where(mask > 0)
    height, width = mask.shape
    if not len(xs):
        return (0, 0, width, height)
    x0 = max(0, int(xs.min()) - context_px)
    y0 = max(0, int(ys.min()) - context_px)
    x1 = min(width, int(xs.max()) + 1 + context_px)
    y1 = min(height, int(ys.max()) + 1 + context_px)
    side = max(x1 - x0, y1 - y0)
    center_x = (x0 + x1) // 2
    center_y = (y0 + y1) // 2
    x0 = max(0, min(width - side, center_x - side // 2))
    y0 = max(0, min(height - side, center_y - side // 2))
    x1 = min(width, x0 + side)
    y1 = min(height, y0 + side)
    return (x0, y0, x1, y1)


def composite_candidate(
    original: np.ndarray,
    candidate: np.ndarray,
    blend_alpha: np.ndarray,
) -> np.ndarray:
    result = original.copy()
    alpha = blend_alpha[..., None]
    rgb = np.rint(original[..., :3] * (1 - alpha) + candidate[..., :3] * alpha)
    changed = blend_alpha > 0
    result[..., :3][changed] = np.clip(rgb, 0, 255).astype(np.uint8)[changed]
    return result

