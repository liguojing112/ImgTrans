from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path

from PIL import Image
import pytest

from src.domain.image import ImageFileFormat, ImageLimits, ImageValidationError
from src.domain.models import ModelDeliveryError, ModelManifestEntry
from src.infrastructure.model_delivery import FileModelRepository
from src.infrastructure.pillow_image_codec import PillowImageCodec
from src.platform.storage import StorageUnavailableError


class _UnavailableStorage:
    def ensure_available(self, directory, required_bytes, reserve_bytes=0):
        del directory, required_bytes, reserve_bytes
        raise StorageUnavailableError("disk_full", "可用磁盘空间不足，请释放空间后重试")


def _entry(content: bytes) -> ModelManifestEntry:
    return ModelManifestEntry(
        "fixture-model",
        "1.0",
        "windows",
        "x86_64",
        "fixture.onnx",
        "object-1",
        len(content),
        hashlib.sha256(content).hexdigest(),
        "https://objects.example.test/model",
        datetime.now(timezone.utc) + timedelta(minutes=10),
    )


def test_export_disk_preflight_preserves_existing_target_and_sanitizes_error(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.png"
    target = tmp_path / "existing.png"
    Image.new("RGB", (80, 80), "blue").save(source)
    target.write_bytes(b"existing-safe-content")
    loader = PillowImageCodec()
    document = loader.load(source, ImageLimits())
    codec = PillowImageCodec(storage_guard=_UnavailableStorage())

    with pytest.raises(ImageValidationError) as error:
        codec.save(document, target, ImageFileFormat.PNG)
    assert error.value.code == "output_disk_full"
    assert target.read_bytes() == b"existing-safe-content"
    assert str(tmp_path) not in str(error.value)


def test_model_install_disk_preflight_preserves_previous_active_version(
    tmp_path: Path,
) -> None:
    stable = b"stable-model"
    stable_entry = _entry(stable)
    source = tmp_path / "stable.part"
    source.write_bytes(stable)
    root = tmp_path / "models"
    repository = FileModelRepository(root)
    installed = repository.install(stable_entry, source)

    replacement = b"replacement-model"
    replacement_entry = ModelManifestEntry(
        stable_entry.model_id,
        "2.0",
        stable_entry.platform,
        stable_entry.architecture,
        stable_entry.filename,
        "object-2",
        len(replacement),
        hashlib.sha256(replacement).hexdigest(),
        stable_entry.download_url,
        stable_entry.download_url_expires_at,
    )
    replacement_source = tmp_path / "replacement.part"
    replacement_source.write_bytes(replacement)
    blocked = FileModelRepository(root, storage_guard=_UnavailableStorage())

    with pytest.raises(ModelDeliveryError, match="模型安装失败"):
        blocked.install(replacement_entry, replacement_source)
    active = repository.active(stable_entry.model_id)
    assert active == installed
    assert Path(active.path).read_bytes() == stable
