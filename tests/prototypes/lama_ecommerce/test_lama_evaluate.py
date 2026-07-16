import numpy as np

from prototypes.lama_ecommerce.evaluate import quality_metrics


def test_identical_reference_has_perfect_metrics_and_no_external_changes() -> None:
    image = np.full((48, 48, 3), 127, np.uint8)
    mask = np.zeros((48, 48), bool)
    mask[12:30, 15:34] = True
    metrics = quality_metrics(image, image, image, mask, mask)
    assert metrics["psnr_db"] == 100
    assert metrics["ssim"] == 1
    assert metrics["gmsd"] == 0
    assert metrics["outside_changed_pixels"] == 0
