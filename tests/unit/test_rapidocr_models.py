from __future__ import annotations

from pathlib import Path

import pytest

from src.domain.models import InstalledModel
from src.domain.ocr import OcrError
from src.infrastructure.ocr_profiles import ARABIC, COMMON
from src.infrastructure.rapidocr_models import (
    CLASSIFICATION_MODEL_ID,
    DETECTION_MODEL_ID,
    InstalledRapidOcrModels,
    RECOGNITION_MODEL_IDS,
)


class _Repository:
    def __init__(self, models: dict[str, InstalledModel]) -> None:
        self.models = models

    def active(self, model_id: str) -> InstalledModel | None:
        return self.models.get(model_id)


def _installed(model_id: str, path: Path) -> InstalledModel:
    return InstalledModel(model_id, "1.0", "object-1", "a" * 64, path.stat().st_size, str(path))


def test_installed_model_resolver_selects_shared_and_profile_models(tmp_path: Path) -> None:
    paths = {}
    model_ids = {
        DETECTION_MODEL_ID,
        CLASSIFICATION_MODEL_ID,
        RECOGNITION_MODEL_IDS[COMMON.profile_id],
        RECOGNITION_MODEL_IDS[ARABIC.profile_id],
    }
    for model_id in model_ids:
        path = tmp_path / f"{model_id}.onnx"
        path.write_bytes(b"model")
        paths[model_id] = _installed(model_id, path)
    resolver = InstalledRapidOcrModels(_Repository(paths))

    common = resolver.resolve(COMMON)
    arabic = resolver.resolve(ARABIC)
    assert common.detection == arabic.detection
    assert common.classification == arabic.classification
    assert common.recognition != arabic.recognition


def test_installed_model_resolver_rejects_missing_or_non_onnx_model(tmp_path: Path) -> None:
    resolver = InstalledRapidOcrModels(_Repository({}))
    with pytest.raises(OcrError) as missing:
        resolver.resolve(COMMON)
    assert missing.value.code == "model_unavailable"

    invalid = tmp_path / "model.txt"
    invalid.write_text("not an onnx model", encoding="utf-8")
    repository = _Repository(
        {DETECTION_MODEL_ID: _installed(DETECTION_MODEL_ID, invalid)}
    )
    with pytest.raises(OcrError, match="OCR 模型不可用"):
        InstalledRapidOcrModels(repository).resolve(COMMON)

