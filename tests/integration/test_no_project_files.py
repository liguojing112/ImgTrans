from pathlib import Path

from src.domain.image import ImageAsset, ImageDocument, ImageFileFormat
from src.infrastructure.batch_result_store import PngBatchResultStore


def test_session_cache_contains_only_flat_images_not_reopenable_projects(
    tmp_path: Path,
) -> None:
    asset = ImageAsset(Path("source.png"), 10, 8, 1, ImageFileFormat.PNG, False, False)
    document = ImageDocument(asset, "RGB", bytes((10, 20, 30)) * 10 * 8)
    store = PngBatchResultStore(tmp_path / "cache")
    store.save("batch-session", "item-one", document)
    files = tuple(path for path in tmp_path.rglob("*") if path.is_file())
    assert files
    assert {path.suffix for path in files} == {".png"}
    assert not any(
        path.suffix in {".project", ".imgtrans", ".json", ".sqlite"}
        for path in files
    )
