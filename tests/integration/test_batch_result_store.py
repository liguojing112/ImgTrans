from pathlib import Path

import pytest

from src.domain.image import ImageAsset, ImageDocument, ImageFileFormat
from src.infrastructure.batch_result_store import PngBatchResultStore


def test_png_batch_result_store_round_trips_alpha_and_clears_batch(tmp_path: Path) -> None:
    asset = ImageAsset(tmp_path / "source.png", 8, 6, 1, ImageFileFormat.PNG, True, False)
    pixels = bytes((20, 40, 60, 128)) * 8 * 6
    document = ImageDocument(asset, "RGBA", pixels)
    store = PngBatchResultStore(tmp_path / "results")
    result_ref = store.save("batch-fixture", "item-1", document)
    restored = store.load(result_ref)
    assert restored.mode == "RGBA"
    assert restored.pixels == pixels
    store.clear("batch-fixture")
    assert not Path(result_ref).exists()


def test_edit_state_round_trips_and_missing_state_returns_none(tmp_path: Path) -> None:
    asset = ImageAsset(tmp_path / "source.png", 8, 6, 1, ImageFileFormat.PNG, False, False)
    document = ImageDocument(asset, "RGB", bytes((1, 2, 3)) * 8 * 6)
    store = PngBatchResultStore(tmp_path / "results")
    result_ref = store.save("batch-fixture", "item-1", document)

    # 旧批次没有可编辑状态时，读回 None 而不是报错
    assert store.load_editable(result_ref) is None

    state = {"layout": [1, 2, 3], "text": "译文"}
    store.save_editable("batch-fixture", "item-1", state)
    assert store.load_editable(result_ref) == state

    store.clear("batch-fixture")
    assert store.load_editable(result_ref) is None


def test_edit_state_rejects_reference_outside_cache(tmp_path: Path) -> None:
    store = PngBatchResultStore(tmp_path / "results")
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"")

    with pytest.raises(ValueError):
        store.load_editable(str(outside))
