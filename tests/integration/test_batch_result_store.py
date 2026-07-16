from pathlib import Path

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
