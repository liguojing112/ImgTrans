from __future__ import annotations

from pathlib import Path
from typing import Protocol

from src.domain.models import InstalledModel
from src.domain.ocr import OcrError
from src.infrastructure.ocr_profiles import OcrProfile
from src.infrastructure.rapidocr_adapter import RapidOcrModelFiles


DETECTION_MODEL_ID = "rapidocr-det-ppocrv6-small"
CLASSIFICATION_MODEL_ID = "rapidocr-cls-angle-mobile"
RECOGNITION_MODEL_IDS = {
    "ppocrv6-common-small": "rapidocr-rec-ppocrv6-common-small",
    "ppocrv5-cyrillic-mobile": "rapidocr-rec-ppocrv5-cyrillic-mobile",
    "ppocrv5-korean-mobile": "rapidocr-rec-ppocrv5-korean-mobile",
    "ppocrv5-thai-mobile": "rapidocr-rec-ppocrv5-thai-mobile",
    "ppocrv5-arabic-mobile": "rapidocr-rec-ppocrv5-arabic-mobile",
    "ppocrv5-devanagari-mobile": "rapidocr-rec-ppocrv5-devanagari-mobile",
}


class ModelRepository(Protocol):
    def active(self, model_id: str) -> InstalledModel | None: ...


class InstalledRapidOcrModels:
    def __init__(self, repository: ModelRepository) -> None:
        self._repository = repository

    def resolve(self, profile: OcrProfile) -> RapidOcrModelFiles:
        try:
            recognition_id = RECOGNITION_MODEL_IDS[profile.profile_id]
        except KeyError as error:
            raise OcrError(
                "model_unavailable",
                f"OCR 识别配置缺少模型映射：{profile.profile_id}",
            ) from error
        return RapidOcrModelFiles(
            self._path(DETECTION_MODEL_ID),
            self._path(CLASSIFICATION_MODEL_ID),
            self._path(recognition_id),
        )

    def _path(self, model_id: str) -> Path:
        installed = self._repository.active(model_id)
        if installed is None:
            raise OcrError(
                "model_unavailable",
                "OCR 模型尚未安装，请先完成设备激活并检查模型更新",
            )
        path = Path(installed.path)
        if path.suffix.lower() != ".onnx" or not path.is_file():
            raise OcrError(
                "model_unavailable",
                f"OCR 模型不可用：{model_id}",
            )
        return path

