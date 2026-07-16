from pathlib import Path

import pytest

from src.application.image_limits import (
    ImageLimitsCacheError,
    ImageLimitsCoordinator,
    ImageLimitsRemoteError,
    ImageLimitsSnapshot,
)
from src.application.image_io import ImportImage
from src.domain.image import ImageLimits
from src.infrastructure.image_limits_config import JsonImageLimitsCache
from src.infrastructure.image_limits_config import HttpImageLimitsClient


def _snapshot(version: int = 3) -> ImageLimitsSnapshot:
    return ImageLimitsSnapshot(
        ImageLimits(
            min_width=100,
            min_height=110,
            max_width=7000,
            max_height=8000,
            max_bytes=30 * 1024 * 1024,
            source="remote",
            config_version=version,
        ),
        600,
    )


class _Remote:
    def __init__(self, result=None, error: Exception | None = None) -> None:
        self.result = result
        self.error = error

    def fetch(self):
        if self.error is not None:
            raise self.error
        return self.result


def test_remote_config_is_atomically_cached_and_loaded_on_next_start(tmp_path: Path) -> None:
    cache_path = tmp_path / "config" / "image-limits.json"
    coordinator = ImageLimitsCoordinator(
        JsonImageLimitsCache(cache_path),
        ImageLimits(),
        _Remote(_snapshot()),
    )
    result = coordinator.refresh()
    assert result.remote_applied
    assert result.limits.source == "remote"
    assert result.limits.config_version == 3
    assert cache_path.is_file()
    assert not tuple(cache_path.parent.glob("*.tmp"))

    restarted = ImageLimitsCoordinator(JsonImageLimitsCache(cache_path))
    assert restarted.current_limits.source == "cache"
    assert restarted.current_limits.config_version == 3
    assert restarted.current_limits.max_pixels == 80_000_000


def test_remote_failure_keeps_recent_cache_and_does_not_poison_it(tmp_path: Path) -> None:
    cache = JsonImageLimitsCache(tmp_path / "limits.json")
    cache.save(_snapshot(4))
    before = (tmp_path / "limits.json").read_bytes()
    coordinator = ImageLimitsCoordinator(
        cache,
        ImageLimits(),
        _Remote(error=ImageLimitsRemoteError("offline")),
    )
    result = coordinator.refresh()
    assert not result.remote_applied
    assert result.limits.source == "cache"
    assert result.limits.config_version == 4
    assert (tmp_path / "limits.json").read_bytes() == before


def test_corrupt_cache_falls_back_to_builtin_limits(tmp_path: Path) -> None:
    cache_path = tmp_path / "limits.json"
    cache_path.write_text('{"schema_version":1,"config_version":"bad"}', encoding="utf-8")
    coordinator = ImageLimitsCoordinator(JsonImageLimitsCache(cache_path))
    assert coordinator.current_limits == ImageLimits()


def test_dynamic_provider_is_read_for_each_import() -> None:
    class Codec:
        def __init__(self) -> None:
            self.seen = []

        def load(self, source, limits):
            self.seen.append(limits)
            return source

    class Cache:
        def load(self):
            return None

        def save(self, snapshot):
            pass

    codec = Codec()
    coordinator = ImageLimitsCoordinator(Cache(), remote=_Remote(_snapshot(8)))
    importer = ImportImage(codec, coordinator)
    assert importer.execute(Path("first.png")) == Path("first.png")
    coordinator.refresh()
    assert importer.execute(Path("second.png")) == Path("second.png")
    assert codec.seen[0].source == "builtin"
    assert codec.seen[1].source == "remote"
    assert codec.seen[1].config_version == 8


def test_snapshot_rejects_missing_or_nonpositive_version() -> None:
    with pytest.raises(ValueError):
        ImageLimitsSnapshot(ImageLimits(), 600)


def test_http_client_validates_contract_and_does_not_accept_extra_fields(
    monkeypatch,
) -> None:
    import json
    import src.infrastructure.image_limits_config as module

    payload = {
        "schema_version": 1,
        "config_version": 12,
        "cache_ttl_seconds": 900,
        "image_limits": {
            "min_width": 64,
            "min_height": 64,
            "max_width": 12000,
            "max_height": 12000,
            "max_bytes": 50 * 1024 * 1024,
        },
    }

    class Response:
        headers = {"Content-Length": "256"}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self, size):
            assert size == 64 * 1024 + 1
            return json.dumps(payload).encode("utf-8")

    captured = {}

    def open_request(request, timeout):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr(module, "urlopen", open_request)
    client = HttpImageLimitsClient("https://api.example.test/root", 2.5)
    snapshot = client.fetch()
    assert captured == {
        "url": "https://api.example.test/root/v1/client-config",
        "timeout": 2.5,
    }
    assert snapshot.limits.config_version == 12
    assert snapshot.limits.source == "remote"

    payload["unexpected"] = True
    with pytest.raises(ImageLimitsRemoteError):
        client.fetch()


def test_cache_write_failure_preserves_last_valid_file(tmp_path: Path, monkeypatch) -> None:
    import src.infrastructure.image_limits_config as module

    path = tmp_path / "limits.json"
    cache = JsonImageLimitsCache(path)
    cache.save(_snapshot(2))
    before = path.read_bytes()

    def fail_replace(source, target):
        raise OSError("disk failure")

    monkeypatch.setattr(module.os, "replace", fail_replace)
    with pytest.raises(ImageLimitsCacheError):
        cache.save(_snapshot(3))
    assert path.read_bytes() == before
    assert not tuple(tmp_path.glob("*.tmp"))
