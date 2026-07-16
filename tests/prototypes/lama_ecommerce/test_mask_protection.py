import numpy as np

from prototypes.lama_ecommerce.contracts import RepairRequest
from prototypes.lama_ecommerce.mask_variants import (
    composite_candidate,
    make_mask_variant,
)
from prototypes.lama_ecommerce.opencv_baseline import OpenCVInpaintAdapter


def test_protection_area_is_removed_from_inference_and_blend_masks() -> None:
    mask = np.zeros((32, 32), np.uint8)
    mask[10:22, 10:22] = 255
    protect = np.zeros_like(mask)
    protect[14:18, 14:18] = 255
    variant = make_mask_variant(mask, protect, 2, 3)
    assert not np.any(variant.inference_mask[14:18, 14:18])
    assert not np.any(variant.blend_alpha[14:18, 14:18])


def test_composite_is_exact_outside_allowed_area() -> None:
    original = np.full((20, 20, 3), 50, np.uint8)
    candidate = np.full_like(original, 220)
    alpha = np.zeros((20, 20), np.float32)
    alpha[5:15, 7:12] = 1
    result = composite_candidate(original, candidate, alpha)
    assert np.array_equal(result[alpha == 0], original[alpha == 0])
    assert np.all(result[alpha == 1] == 220)


def test_opencv_baseline_preserves_alpha_and_outside_pixels() -> None:
    image = np.full((64, 64, 4), 100, np.uint8)
    image[..., 3] = np.arange(64, dtype=np.uint8)[:, None]
    mask = np.zeros((64, 64), np.uint8)
    mask[25:40, 20:45] = 255
    request = RepairRequest(image, mask, mode="local", expand_px=1, feather_px=0)
    variant = make_mask_variant(mask, None, 1, 0)
    result = OpenCVInpaintAdapter().inpaint(request).image
    assert np.array_equal(result[..., 3], image[..., 3])
    assert np.array_equal(result[~variant.allowed_mask], image[~variant.allowed_mask])

