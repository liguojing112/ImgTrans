from pathlib import Path

from src.platform.paths import PlatformPaths


def test_windows_paths_use_local_app_data(tmp_path: Path) -> None:
    paths = PlatformPaths.discover(
        system="Windows", environ={"LOCALAPPDATA": str(tmp_path)}, home=tmp_path
    )
    assert paths.data_dir == tmp_path / "ImgTrans"
    assert paths.cache_dir == tmp_path / "ImgTrans" / "Cache"


def test_macos_paths_use_application_support_and_caches(tmp_path: Path) -> None:
    paths = PlatformPaths.discover(system="Darwin", environ={}, home=tmp_path)
    assert paths.data_dir == tmp_path / "Library" / "Application Support" / "ImgTrans"
    assert paths.cache_dir == tmp_path / "Library" / "Caches" / "ImgTrans"


def test_ensure_creates_product_directories(tmp_path: Path) -> None:
    paths = PlatformPaths(tmp_path / "data", tmp_path / "cache")
    paths.ensure()
    assert paths.data_dir.is_dir()
    assert paths.cache_dir.is_dir()
