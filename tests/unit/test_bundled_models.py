from __future__ import annotations

from pathlib import Path

from src.infrastructure.bundled_models import BundledModelRepository, bundled_models_root


class _FakePrimary:
    def __init__(self, active_result=None):
        self._active_result = active_result

    def active(self, model_id):
        del model_id
        return self._active_result


def test_falls_back_to_bundled_model(tmp_path: Path) -> None:
    bundled = tmp_path / "bundled_models" / "lama-inpainting"
    bundled.mkdir(parents=True)
    model = bundled / "inpainting_lama_2025jan.onnx"
    model.write_bytes(b"bundled-model-bytes")
    repo = BundledModelRepository(_FakePrimary(None), tmp_path / "bundled_models")
    installed = repo.active("lama-inpainting")
    assert installed is not None
    assert installed.model_id == "lama-inpainting"
    assert installed.version == "bundled"
    assert Path(installed.path) == model


def test_prefers_installed_over_bundled(tmp_path: Path) -> None:
    bundled = tmp_path / "bundled_models" / "lama-inpainting"
    bundled.mkdir(parents=True)
    (bundled / "inpainting_lama_2025jan.onnx").write_bytes(b"bundled")

    primary_model = object()

    class _WithInstalled:
        def active(self, model_id):
            del model_id
            return primary_model

    repo = BundledModelRepository(_WithInstalled(), tmp_path / "bundled_models")
    assert repo.active("lama-inpainting") is primary_model


def test_returns_none_when_model_not_bundled(tmp_path: Path) -> None:
    repo = BundledModelRepository(_FakePrimary(None), tmp_path / "bundled_models")
    assert repo.active("missing-model") is None


def test_returns_none_without_bundled_root() -> None:
    repo = BundledModelRepository(_FakePrimary(None), None)
    assert repo.active("anything") is None


def test_bundled_root_is_none_in_development() -> None:
    assert bundled_models_root() is None
