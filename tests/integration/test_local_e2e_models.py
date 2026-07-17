from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from scripts.install_local_e2e_models import (
    LAMA_MODEL_ID,
    _RAPIDOCR_FILES,
    discover_sources,
    install_local_models,
)
from src.domain.models import ModelDeliveryError
from src.infrastructure.model_delivery import FileModelRepository


def _model_file(path: Path, value: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value)
    return path


def test_local_assets_are_hashed_copied_and_activated(tmp_path: Path) -> None:
    rapidocr_root = tmp_path / "rapidocr"
    for index, filename in enumerate(_RAPIDOCR_FILES.values()):
        _model_file(rapidocr_root / "models" / filename, f"ocr-{index}".encode())
    lama = _model_file(tmp_path / "lama.onnx", b"verified-lama")
    lama_sha256 = hashlib.sha256(lama.read_bytes()).hexdigest()
    sources = discover_sources(rapidocr_root, lama)
    repository = FileModelRepository(tmp_path / "installed")

    result = install_local_models(
        repository,
        sources,
        "windows",
        "x86_64",
        expected_lama_sha256=lama_sha256,
    )

    assert len(result) == 9
    for model_id, source in sources.items():
        active = repository.active(model_id)
        assert active is not None
        installed_path = Path(active.path)
        assert installed_path.read_bytes() == source.read_bytes()
        assert installed_path.resolve() != source.resolve()
        assert active.version.startswith("local-e2e-")


def test_local_import_fails_before_install_when_a_model_is_missing(
    tmp_path: Path,
) -> None:
    rapidocr_root = tmp_path / "rapidocr"
    for filename in tuple(_RAPIDOCR_FILES.values())[1:]:
        _model_file(rapidocr_root / filename, b"model")
    lama = _model_file(tmp_path / "lama.onnx", b"lama")

    with pytest.raises(ModelDeliveryError, match="本地联调模型不完整"):
        discover_sources(rapidocr_root, lama)


def test_local_import_rejects_unverified_lama(tmp_path: Path) -> None:
    source = _model_file(tmp_path / "lama.onnx", b"wrong-lama")
    with pytest.raises(ModelDeliveryError, match="SHA-256"):
        install_local_models(
            FileModelRepository(tmp_path / "installed"),
            {LAMA_MODEL_ID: source},
            "windows",
            "x86_64",
        )
