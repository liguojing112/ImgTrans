from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
from io import BytesIO
import json
from pathlib import Path

import pytest

from src.domain.models import ModelDeliveryError, ModelManifestEntry
from src.infrastructure.model_delivery import HttpRangeModelDownloader


class Response:
    def __init__(self, content: bytes, status: int, headers: dict[str, str]):
        self._stream = BytesIO(content)
        self.status = status
        self.headers = headers

    def read(self, size=-1):
        return self._stream.read(size)

    def getcode(self):
        return self.status

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class InterruptedResponse(Response):
    def __init__(self, content: bytes, headers: dict[str, str]):
        super().__init__(content, 200, headers)
        self._reads = 0

    def read(self, size=-1):
        self._reads += 1
        if self._reads == 1:
            return self._stream.read(4)
        raise OSError("connection dropped")


def _entry(content: bytes, object_version: str = "object-v1") -> ModelManifestEntry:
    return ModelManifestEntry(
        "lama-inpainting", "1.0", "windows", "x86_64", "lama.onnx",
        object_version, len(content), hashlib.sha256(content).hexdigest(),
        "https://objects.example.invalid/signed?signature=secret",
        datetime.now(timezone.utc) + timedelta(minutes=10),
    )


def test_range_resume_appends_from_trusted_offset(tmp_path: Path, monkeypatch) -> None:
    content = b"0123456789"
    entry = _entry(content)
    part = tmp_path / "model.part"
    state = tmp_path / "model.json"
    part.write_bytes(content[:4])
    state.write_text(json.dumps({
        "schema_version": 1,
        "model_id": entry.model_id,
        "version": entry.version,
        "platform": entry.platform,
        "architecture": entry.architecture,
        "object_version": entry.object_version,
        "size_bytes": entry.size_bytes,
        "sha256": entry.sha256,
        "etag": '"etag-v1"',
    }), encoding="utf-8")
    requests = []

    def open_response(request, timeout):
        requests.append(request)
        return Response(content[4:], 206, {"ETag": '"etag-v1"', "Content-Range": "bytes 4-9/10"})

    monkeypatch.setattr("src.infrastructure.model_delivery.urlopen", open_response)
    result = HttpRangeModelDownloader().download(entry, part, state, lambda: False)
    assert result.read_bytes() == content
    assert requests[0].get_header("Range") == "bytes=4-"
    assert requests[0].get_header("If-range") == '"etag-v1"'


def test_changed_object_or_ignored_range_restarts_without_duplicate_bytes(
    tmp_path: Path, monkeypatch
) -> None:
    content = b"new-object"
    entry = _entry(content, "object-v2")
    part = tmp_path / "model.part"
    state = tmp_path / "model.json"
    part.write_bytes(b"old-")
    state.write_text(json.dumps({
        "schema_version": 1,
        "model_id": entry.model_id,
        "version": entry.version,
        "platform": entry.platform,
        "architecture": entry.architecture,
        "object_version": "object-v1",
        "size_bytes": len(content),
        "sha256": entry.sha256,
    }), encoding="utf-8")

    monkeypatch.setattr(
        "src.infrastructure.model_delivery.urlopen",
        lambda request, timeout: Response(content, 200, {"ETag": '"etag-v2"'}),
    )
    HttpRangeModelDownloader().download(entry, part, state, lambda: False)
    assert part.read_bytes() == content
    saved = json.loads(state.read_text(encoding="utf-8"))
    assert saved["object_version"] == "object-v2"
    assert "download_url" not in saved


def test_interrupted_download_is_resumed_on_next_attempt(tmp_path: Path, monkeypatch) -> None:
    content = b"resume-this-model"
    entry = _entry(content)
    part = tmp_path / "model.part"
    state = tmp_path / "model.json"
    responses = iter(
        [
            InterruptedResponse(content, {"ETag": '"stable"'}),
            Response(
                content[4:],
                206,
                {"ETag": '"stable"', "Content-Range": f"bytes 4-{len(content)-1}/{len(content)}"},
            ),
        ]
    )
    monkeypatch.setattr(
        "src.infrastructure.model_delivery.urlopen",
        lambda request, timeout: next(responses),
    )
    downloader = HttpRangeModelDownloader()
    with pytest.raises(ModelDeliveryError):
        downloader.download(entry, part, state, lambda: False)
    assert part.read_bytes() == content[:4]
    downloader.download(entry, part, state, lambda: False)
    assert part.read_bytes() == content


def test_missing_resume_identity_discards_untrusted_partial(tmp_path: Path, monkeypatch) -> None:
    content = b"trusted-content"
    entry = _entry(content)
    part = tmp_path / "model.part"
    state = tmp_path / "missing.json"
    part.write_bytes(b"untrusted-")
    requests = []

    def open_response(request, timeout):
        requests.append(request)
        return Response(content, 200, {"ETag": '"fresh"'})

    monkeypatch.setattr("src.infrastructure.model_delivery.urlopen", open_response)
    HttpRangeModelDownloader().download(entry, part, state, lambda: False)
    assert part.read_bytes() == content
    assert requests[0].get_header("Range") is None
