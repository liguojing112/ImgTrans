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
        polygons = tuple(order_quad(box) for box in boxes)
        regions = []
        for index, (polygon, raw_text, raw_score) in enumerate(
            zip(polygons, texts, scores, strict=True), start=1
        ):
            text = normalize_ocr_text(str(raw_text))
            if not text:
                continue
            confidence = min(1.0, max(0.0, float(raw_score)))
            if _should_refine_region(text):
                try:
                    with self._lock:
                        text, confidence, polygon = _refine_region(
                            engine,
                            image,
                            text,
                            confidence,
                            polygon,
                            polygons[: index - 1] + polygons[index:],
                        )
                except Exception:
                    pass
            status = (
                TextRegionStatus.OK
                if confidence >= self._confidence_threshold
                else TextRegionStatus.LOW_CONFIDENCE
            )
            regions.append(
                TextRegion(
                    region_id=f"region-{index:04d}",
                    polygon=polygon,
                    text=text,
                    confidence=confidence,
                    language_code=language_code,
                    model_id=profile.profile_id,
                    status=status,
                )
            )
        elapsed_ms = (perf_counter() - started) * 1000
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


def _should_refine_region(text: str) -> bool:
    return len(text) <= 12 and any(
        "\u3400" <= character <= "\u9fff"
        or "\uf900" <= character <= "\ufaff"
        for character in text
    )


def _refine_region(
    engine: Any,
    image: np.ndarray,
    text: str,
    confidence: float,
    polygon,
    occupied_polygons=(),
):
    xs = tuple(point.x for point in polygon)
    ys = tuple(point.y for point in polygon)
    height = max(1.0, max(ys) - min(ys))
    horizontal_padding = max(4, round(height * 0.8))
    vertical_padding = max(2, round(height * 0.2))
    image_height, image_width = image.shape[:2]
    x0 = max(0, int(min(xs)) - horizontal_padding)
    x1 = min(image_width, int(max(xs)) + horizontal_padding + 1)
    y0 = max(0, int(min(ys)) - vertical_padding)
    y1 = min(image_height, int(max(ys)) + vertical_padding + 1)
    crop = np.ascontiguousarray(image[y0:y1, x0:x1])
    output = engine(crop, use_det=False, use_cls=True, use_rec=True)
    texts = getattr(output, "txts", None)
    scores = getattr(output, "scores", None)
    if texts is None or scores is None or len(texts) != 1 or len(scores) != 1:
        return text, confidence, polygon
    candidate = normalize_ocr_text(str(texts[0]))
    candidate_confidence = min(1.0, max(0.0, float(scores[0])))
    position = candidate.find(text)
    extra = len(candidate) - len(text)
    if (
        not candidate
        or position < 0
        or not 1 <= extra <= 2
        or candidate_confidence + 0.005 < confidence
    ):
        return text, confidence, polygon
    prefix = position
    suffix = extra - prefix
    expanded_polygon = _extend_polygon(
        polygon,
        prefix,
        suffix,
        max(1, len(text)),
        image_width,
        image_height,
    )
    if any(
        _overlap_area(expanded_polygon, occupied)
        > _overlap_area(polygon, occupied) + 1
        for occupied in occupied_polygons
    ):
        return text, confidence, polygon
    return candidate, candidate_confidence, expanded_polygon


def _extend_polygon(
    polygon,
    prefix_characters: int,
    suffix_characters: int,
    original_characters: int,
    image_width: int,
    image_height: int,
):
    p0, p1, p2, p3 = polygon
    width = max(1.0, ((p1.x - p0.x) ** 2 + (p1.y - p0.y) ** 2) ** 0.5)
    unit_x = (p1.x - p0.x) / width
    unit_y = (p1.y - p0.y) / width
    character_width = width / original_characters
    left = character_width * prefix_characters * 1.1
    right = character_width * suffix_characters * 1.1

    def clamp(value: float, maximum: int) -> float:
        return min(float(maximum - 1), max(0.0, value))

    return order_quad(
        (
            (clamp(p0.x - unit_x * left, image_width), clamp(p0.y - unit_y * left, image_height)),
            (clamp(p1.x + unit_x * right, image_width), clamp(p1.y + unit_y * right, image_height)),
            (clamp(p2.x + unit_x * right, image_width), clamp(p2.y + unit_y * right, image_height)),
            (clamp(p3.x - unit_x * left, image_width), clamp(p3.y - unit_y * left, image_height)),
        )
    )


def _overlap_area(first, second) -> float:
    first_x = tuple(point.x for point in first)
    first_y = tuple(point.y for point in first)
    second_x = tuple(point.x for point in second)
    second_y = tuple(point.y for point in second)
    width = max(
        0.0,
        min(max(first_x), max(second_x)) - max(min(first_x), min(second_x)),
    )
    height = max(
        0.0,
        min(max(first_y), max(second_y)) - max(min(first_y), min(second_y)),
    )
    return width * height
