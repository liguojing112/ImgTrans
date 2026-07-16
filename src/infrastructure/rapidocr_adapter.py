from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from time import perf_counter
from typing import Any

import numpy as np

from src.domain.image import ImageDocument
from src.domain.ocr import (
    OcrError,
    OcrResult,
    TextRegion,
    TextRegionStatus,
    normalize_ocr_text,
    order_quad,
)
from src.infrastructure.ocr_profiles import LANGUAGE_PROFILES, OcrProfile


@dataclass(frozen=True, slots=True)
class RapidOcrModelFiles:
    detection: Path
    classification: Path
    recognition: Path


class RapidOcrAdapter:
    def __init__(
        self,
        confidence_threshold: float = 0.5,
        engine_factory: Callable[[OcrProfile], Any] | None = None,
        model_resolver: Callable[[OcrProfile], RapidOcrModelFiles] | None = None,
    ) -> None:
        if not 0 <= confidence_threshold <= 1:
            raise ValueError("OCR confidence threshold must be between zero and one")
        self._confidence_threshold = confidence_threshold
        self._model_resolver = model_resolver
        self._engine_factory = engine_factory or self._create_engine
        self._engines: dict[str, Any] = {}
        self._lock = Lock()
        self.engine_load_ms: dict[str, float] = {}

    @property
    def language_codes(self) -> tuple[str, ...]:
        return tuple(LANGUAGE_PROFILES)

    def recognize(self, document: ImageDocument, language_code: str) -> OcrResult:
        try:
            profile = LANGUAGE_PROFILES[language_code]
        except KeyError as error:
            raise OcrError("unsupported_language", f"OCR 不支持语言代码：{language_code}") from error
        if profile is None:
            raise OcrError(
                "model_unavailable",
                "RapidOCR 当前没有明确的孟加拉语识别模型，请选择其他语言或安装后续替代模型",
            )
        image = self._to_bgr(document)
        with self._lock:
            engine = self._get_engine(profile)
            started = perf_counter()
            try:
                output = engine(image, use_det=True, use_cls=True, use_rec=True)
            except Exception as error:
                raise OcrError("runtime_failed", f"RapidOCR 识别失败：{error}") from error
            elapsed_ms = (perf_counter() - started) * 1000
        boxes = getattr(output, "boxes", None)
        texts = getattr(output, "txts", None)
        scores = getattr(output, "scores", None)
        if boxes is None:
            return OcrResult((), language_code, profile.profile_id, elapsed_ms)
        if texts is None or scores is None or not (len(boxes) == len(texts) == len(scores)):
            raise OcrError("invalid_runtime_result", "RapidOCR 返回的文字框、文本和分数数量不一致")
        regions = []
        for index, (box, raw_text, raw_score) in enumerate(
            zip(boxes, texts, scores, strict=True), start=1
        ):
            text = normalize_ocr_text(str(raw_text))
            if not text:
                continue
            confidence = min(1.0, max(0.0, float(raw_score)))
            status = (
                TextRegionStatus.OK
                if confidence >= self._confidence_threshold
                else TextRegionStatus.LOW_CONFIDENCE
            )
            regions.append(
                TextRegion(
                    region_id=f"region-{index:04d}",
                    polygon=order_quad(box),
                    text=text,
                    confidence=confidence,
                    language_code=language_code,
                    model_id=profile.profile_id,
                    status=status,
                )
            )
        return OcrResult(tuple(regions), language_code, profile.profile_id, elapsed_ms)

    def _get_engine(self, profile: OcrProfile) -> Any:
        engine = self._engines.get(profile.profile_id)
        if engine is not None:
            return engine
        started = perf_counter()
        try:
            engine = self._engine_factory(profile)
        except OcrError:
            raise
        except Exception as error:
            raise OcrError("model_load_failed", f"OCR 模型加载失败：{error}") from error
        self._engines[profile.profile_id] = engine
        self.engine_load_ms[profile.profile_id] = (perf_counter() - started) * 1000
        return engine

    @staticmethod
    def _to_bgr(document: ImageDocument) -> np.ndarray:
        channels = 4 if document.mode == "RGBA" else 3
        image = np.frombuffer(document.pixels, dtype=np.uint8).reshape(
            document.asset.height, document.asset.width, channels
        )
        return np.ascontiguousarray(image[..., :3][..., ::-1])

    def _create_engine(self, profile: OcrProfile) -> Any:
        try:
            from rapidocr import EngineType, LangDet, LangRec, ModelType, OCRVersion, RapidOCR
        except ImportError as error:
            raise OcrError("runtime_missing", "RapidOCR 运行时未安装") from error
        params = {
            "Global.log_level": "critical",
            "Det.engine_type": EngineType("onnxruntime"),
            "Det.lang_type": LangDet("ch"),
            "Det.model_type": ModelType("small"),
            "Det.ocr_version": OCRVersion("PP-OCRv6"),
            "Rec.engine_type": EngineType("onnxruntime"),
            "Rec.lang_type": LangRec(profile.recognition_language),
            "Rec.model_type": ModelType(profile.model_type),
            "Rec.ocr_version": OCRVersion(profile.ocr_version),
        }
        if self._model_resolver is not None:
            models = self._model_resolver(profile)
            params.update(
                {
                    "Det.model_path": str(models.detection),
                    "Cls.model_path": str(models.classification),
                    "Rec.model_path": str(models.recognition),
                }
            )
        return RapidOCR(params=params)
