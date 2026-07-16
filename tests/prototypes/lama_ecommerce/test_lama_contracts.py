from pathlib import Path

import numpy as np
import pytest

from prototypes.lama_ecommerce.contracts import (
    DatasetManifest,
    RepairContractError,
    RepairRequest,
)
from prototypes.lama_ecommerce.generate_dataset import sample_specs


MANIFEST = Path("tests/prototypes/lama_ecommerce/fixtures/manifest.json")


def test_manifest_defines_five_samples_for_seven_categories(tmp_path: Path) -> None:
    manifest = DatasetManifest.load(MANIFEST)
    specs = sample_specs(manifest, tmp_path)
    assert len(specs) == 35
    assert len({spec.category for spec in specs}) == 7


def test_request_accepts_rgb_and_rgba() -> None:
    mask = np.zeros((16, 20), np.uint8)
    RepairRequest(np.zeros((16, 20, 3), np.uint8), mask)
    RepairRequest(np.zeros((16, 20, 4), np.uint8), mask)


def test_request_rejects_size_mismatch() -> None:
    with pytest.raises(RepairContractError, match="same-size"):
        RepairRequest(np.zeros((16, 20, 3), np.uint8), np.zeros((15, 20), np.uint8))
