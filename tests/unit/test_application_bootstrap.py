from pathlib import Path

from src.application.bootstrap import BootstrapApplication
from src.domain.product import ProductInfo


class StubDirectories:
    def __init__(self, root: Path) -> None:
        self.data_dir = root / "data"
        self.cache_dir = root / "cache"
        self.ensure_called = False

    def ensure(self) -> None:
        self.ensure_called = True


def test_bootstrap_uses_directory_port_and_returns_snapshot(tmp_path: Path) -> None:
    directories = StubDirectories(tmp_path)
    product = ProductInfo("图片翻译", "0.1.0", "M1")
    snapshot = BootstrapApplication(product, directories).execute()
    assert directories.ensure_called
    assert snapshot.product is product
    assert snapshot.data_dir == tmp_path / "data"
    assert snapshot.cache_dir == tmp_path / "cache"
