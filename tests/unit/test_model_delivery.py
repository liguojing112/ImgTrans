from __future__ import annotations

from datetime import datetime, timedelta, timezone
from dataclasses import replace
import hashlib
import json
from pathlib import Path

import pytest

from src.application.model_delivery import EnsureModels
from src.domain.models import ModelDeliveryError, ModelManifestEntry
import src.infrastructure.model_delivery as model_delivery_module
from src.infrastructure.model_delivery import FileModelRepository, HttpModelManifestClient
from src.platform.paths import discover_model_target


def _entry(content: bytes, version: str = "1.0", object_version: str | None = None):
    return ModelManifestEntry(
        model_id="lama-inpainting",
        version=version,
        platform="windows",
        architecture="x86_64",
        filename="lama.onnx",
        object_version=object_version or f"object-{version}",
        size_bytes=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
        download_url="https://objects.example.invalid/signed?secret=hidden",
        download_url_expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
    )


class Remote:
    def __init__(self, entries):
        self.entries = tuple(entries)

    def fetch(self, platform, architecture):
        assert (platform, architecture) == ("windows", "x86_64")
        return self.entries


class Downloader:
    def __init__(self, content: bytes):
        self.content = content
        self.calls = 0

    def download(self, entry, part_path, state_path, cancelled):
        self.calls += 1
        part_path.parent.mkdir(parents=True, exist_ok=True)
        part_path.write_bytes(self.content)
        return part_path


def test_verified_model_is_atomically_activated_and_reused(tmp_path: Path) -> None:
    content = b"verified-model"
    entry = _entry(content)
    repository = FileModelRepository(tmp_path / "models")
    downloader = Downloader(content)
    use_case = EnsureModels(
        Remote([entry]), downloader, repository, tmp_path / "downloads", "windows", "x86_64"
    )
    first = use_case.execute()
    second = use_case.execute()
    active = repository.active(entry.model_id)
    assert first.installed_count == 1
    assert second.installed_count == 0
    assert downloader.calls == 1
    assert active is not None
    assert Path(active.path).read_bytes() == content
    Path(active.path).write_bytes(b"corrupt-model?")
    recovered = use_case.execute()
    assert recovered.installed_count == 1
    assert downloader.calls == 2
    assert Path(repository.active(entry.model_id).path).read_bytes() == content


@pytest.mark.parametrize("invalid_content", [b"short", b"wrong-content!!"])
def test_bad_size_or_hash_never_replaces_previous_version(
    tmp_path: Path, invalid_content: bytes
) -> None:
    repository = FileModelRepository(tmp_path / "models")
    v1_content = b"stable-version"
    v1 = _entry(v1_content, "1.0")
    source = tmp_path / "v1.part"
    source.write_bytes(v1_content)
    repository.install(v1, source)

    v2_expected = b"expected-model!"
    v2 = _entry(v2_expected, "2.0")
    result = EnsureModels(
        Remote([v2]), Downloader(invalid_content), repository,
        tmp_path / "downloads", "windows", "x86_64",
    ).execute()
    active = repository.active(v1.model_id)
    assert result.failed_count == 1
    assert active is not None and active.version == "1.0"
    assert Path(active.path).read_bytes() == v1_content
    assert not any((tmp_path / "downloads").glob("*.part"))


def test_install_failure_preserves_previous_pointer(tmp_path: Path, monkeypatch) -> None:
    content = b"model-one"
    repository = FileModelRepository(tmp_path / "models")
    v1 = _entry(content, "1.0")
    source = tmp_path / "source.part"
    source.write_bytes(content)
    repository.install(v1, source)

    def fail_replace(source, target):
        raise OSError("disk full")

    monkeypatch.setattr("src.infrastructure.model_delivery.os.replace", fail_replace)
    v2_content = b"model-two"
    result = EnsureModels(
        Remote([_entry(v2_content, "2.0")]), Downloader(v2_content), repository,
        tmp_path / "downloads", "windows", "x86_64",
    ).execute()
    assert result.failed_count == 1
    assert repository.active(v1.model_id).version == "1.0"


def test_manifest_rejects_path_traversal_and_unsupported_platform() -> None:
    valid = _entry(b"content")
    with pytest.raises(ModelDeliveryError):
        replace(valid, filename="../model.onnx")
    with pytest.raises(ModelDeliveryError):
        replace(valid, architecture="arm64")
    with pytest.raises(ModelDeliveryError):
        replace(valid, download_url="file:///etc/passwd")


def test_wrong_target_is_not_downloaded(tmp_path: Path) -> None:
    content = b"mac-model"
    mac_entry = replace(
        _entry(content),
        platform="macos",
        architecture="arm64",
    )
    downloader = Downloader(content)
    result = EnsureModels(
        Remote([mac_entry]), downloader, FileModelRepository(tmp_path / "models"),
        tmp_path / "downloads", "windows", "x86_64",
    ).execute()
    assert result.failed_count == 1
    assert downloader.calls == 0


def test_only_supported_product_targets_are_discovered() -> None:
    assert discover_model_target("Windows", "AMD64") == ("windows", "x86_64")
    assert discover_model_target("Darwin", "arm64") == ("macos", "arm64")
    with pytest.raises(RuntimeError):
        discover_model_target("Darwin", "x86_64")


def test_manifest_client_uses_device_token_available_after_construction(monkeypatch) -> None:
    token = {"value": None}
    client = HttpModelManifestClient(
        "https://api.example.test",
        lambda: token["value"],
    )
    with pytest.raises(ModelDeliveryError, match="请先激活"):
        client.fetch("windows", "x86_64")

    captured = {}

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self, size):
            assert size == 256 * 1024 + 1
            return json.dumps({"schema_version": 1, "models": []}).encode()

    def open_request(request, timeout):
        del timeout
        captured["authorization"] = dict(request.header_items())["Authorization"]
        return _Response()

    monkeypatch.setattr(model_delivery_module, "urlopen", open_request)
    token["value"] = "itd_live_device_token_123456"
    assert client.fetch("windows", "x86_64") == ()
    assert captured["authorization"] == "Bearer itd_live_device_token_123456"
