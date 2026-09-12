from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from difflib import SequenceMatcher
from math import atan2, cos, degrees, pi, sin
from pathlib import Path
from threading import Lock
from time import perf_counter
from typing import Any

import cv2
import numpy as np

from src.domain.image import ImageDocument
from src.domain.ocr import (
    HighRecallOcrOptions,
    OcrCleanupSummary,
    OcrError,
    OcrMode,
    OcrObservation,
    OcrPreviewStrip,
    OcrResult,
    Point,
    RingBand,
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
        return tuple(
            code for code, profile in LANGUAGE_PROFILES.items() if profile is not None
        )

    def recognize(
        self,
        document: ImageDocument,
        language_code: str,
        fast: bool = False,
    ) -> OcrResult:
        """识别图片文字。

        fast=True 时跳过瓦片恢复、密集重复修复与逐区域精修，
        只做一次标准识别（适合快速预览，翻译流程保持完整路径）。
        """
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
        if not fast:
            boxes, texts, scores = _recover_high_resolution_regions(
                engine,
                image,
                boxes,
                texts,
                scores,
                self._confidence_threshold,
            )
            boxes, texts, scores = _recover_dense_repeated_regions(
                engine,
                image,
                boxes,
                texts,
                scores,
                self._confidence_threshold,
            )
        polygons = tuple(_engine_text_quad(box) for box in boxes)
        regions = []
        for index, (polygon, raw_text, raw_score) in enumerate(
            zip(polygons, texts, scores, strict=True), start=1
        ):
            text = normalize_ocr_text(str(raw_text))
            if not text:
                continue
            confidence = min(1.0, max(0.0, float(raw_score)))
            if not fast and _should_refine_region(text):
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
                    language_code=_detect_region_language(text, language_code),
                    model_id=profile.profile_id,
                    status=status,
                )
            )
        elapsed_ms = (perf_counter() - started) * 1000
        return OcrResult(tuple(regions), language_code, profile.profile_id, elapsed_ms)

    def recognize_high_recall(
        self,
        document: ImageDocument,
        language_code: str,
        options: HighRecallOcrOptions,
    ) -> OcrResult:
        started = perf_counter()
        standard = self.recognize(document, language_code)
        profile = LANGUAGE_PROFILES.get(language_code)
        if profile is None:
            raise OcrError("model_unavailable", "当前语言没有可用的高召回 OCR 模型")
        image = self._to_bgr(document)
        with self._lock:
            engine = self._get_engine(profile)

        observations = _rotation_observations(
            engine,
            image,
            options.rotation_angles,
            self._confidence_threshold,
        )
        polar_observations, preview_strips = _polar_observations(
            engine,
            image,
            options,
            self._confidence_threshold,
        )
        observations.extend(polar_observations)
        regions = _merge_high_recall_regions(
            standard.regions,
            observations,
            language_code,
            profile.profile_id,
            self._confidence_threshold,
            options.consensus_confidence,
            (
                options.center.x,
                options.center.y,
            )
            if options.center is not None
            else (image.shape[1] / 2, image.shape[0] / 2),
            (image.shape[1], image.shape[0]),
        )
        raw_candidate_count = len(standard.regions) + len(observations)
        cleanup_summary = OcrCleanupSummary(
            raw_candidate_count=raw_candidate_count,
            unique_candidate_count=len(regions),
            auto_confirmed_count=sum(
                region.auto_process_eligible for region in regions
            ),
            review_required_count=sum(
                not region.auto_process_eligible for region in regions
            ),
            deleted_candidate_count=max(0, raw_candidate_count - len(regions)),
        )
        return OcrResult(
            regions,
            language_code,
            profile.profile_id,
            (perf_counter() - started) * 1000,
            OcrMode.HIGH_RECALL,
            preview_strips,
            cleanup_summary,
            tuple(sorted(observations, key=_observation_sort_key)),
        )

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


def _rotation_observations(
    engine: Any,
    image: np.ndarray,
    angles: tuple[int, ...],
    confidence_threshold: float,
) -> list[OcrObservation]:
    image_height, image_width = image.shape[:2]
    observations: list[OcrObservation] = []
    for angle in angles:
        rotated, matrix = _rotate_image_expand(image, float(angle))
        output = engine(rotated, use_det=True, use_cls=True, use_rec=True)
        boxes = getattr(output, "boxes", None)
        texts = getattr(output, "txts", None)
        scores = getattr(output, "scores", None)
        if boxes is None or texts is None or scores is None:
            continue
        if not (len(boxes) == len(texts) == len(scores)):
            continue
        inverse = cv2.invertAffineTransform(matrix)
        for box, raw_text, raw_score in zip(boxes, texts, scores, strict=True):
            text = normalize_ocr_text(str(raw_text))
            confidence = min(1.0, max(0.0, float(raw_score)))
            if not text or confidence < confidence_threshold:
                continue
            mapped = _map_affine_polygon(np.asarray(box, dtype=float), inverse)
            mapped[:, 0] = np.clip(mapped[:, 0], 0, image_width - 1)
            mapped[:, 1] = np.clip(mapped[:, 1], 0, image_height - 1)
            try:
                polygon = _engine_text_quad(mapped)
            except ValueError:
                continue
            observations.append(
                OcrObservation(
                    source="rotation",
                    angle_degrees=float(angle % 360),
                    scale=1.0,
                    confidence=confidence,
                    polygon=polygon,
                    text=text,
                    view_id=f"rotation:{angle % 360}",
                )
            )
    return observations


def _polar_observations(
    engine: Any,
    image: np.ndarray,
    options: HighRecallOcrOptions,
    confidence_threshold: float,
) -> tuple[list[OcrObservation], tuple[OcrPreviewStrip, ...]]:
    image_height, image_width = image.shape[:2]
    center = (
        (options.center.x, options.center.y)
        if options.center is not None
        else (image_width / 2, image_height / 2)
    )
    maximum_radius = min(
        center[0],
        center[1],
        image_width - center[0],
        image_height - center[1],
    )
    if maximum_radius < 12:
        return [], ()
    angle_steps = max(360, round(2 * pi * maximum_radius))
    polar = cv2.warpPolar(
        image,
        (round(maximum_radius), angle_steps),
        center,
        maximum_radius,
        cv2.WARP_POLAR_LINEAR | cv2.WARP_FILL_OUTLIERS,
    )
    unwrapped = cv2.rotate(polar, cv2.ROTATE_90_COUNTERCLOCKWISE)
    bands = options.ring_bands or _detected_ring_bands(unwrapped, maximum_radius)
    observations: list[OcrObservation] = []
    previews: list[OcrPreviewStrip] = []
    for band_index, band in enumerate(bands):
        inner = max(0.0, min(maximum_radius, band.inner_radius))
        outer = max(0.0, min(maximum_radius, band.outer_radius))
        if outer <= inner:
            continue
        y0 = max(0, int(round(maximum_radius - outer)))
        y1 = min(unwrapped.shape[0], int(round(maximum_radius - inner)))
        if y1 - y0 < 4:
            continue
        strip = np.ascontiguousarray(unwrapped[y0:y1])
        rgb = np.ascontiguousarray(strip[..., ::-1])
        normalized_band = RingBand(inner, outer)
        previews.append(
            OcrPreviewStrip(
                name=f"ring-{band_index + 1:02d}-{inner:.0f}-{outer:.0f}",
                width=strip.shape[1],
                height=strip.shape[0],
                pixels=rgb.tobytes(),
                center=Point(*center),
                ring_band=normalized_band,
            )
        )
        for scale in options.scales:
            view_id = f"polar:{band_index}:scale:{scale}"
            observations.extend(
                _detect_polar_strip(
                    engine,
                    strip,
                    scale,
                    view_id,
                    y0,
                    center,
                    maximum_radius,
                    angle_steps,
                    confidence_threshold,
                )
            )
            observations.extend(
                _recognize_polar_intervals(
                    engine,
                    strip,
                    scale,
                    band_index,
                    y0,
                    center,
                    maximum_radius,
                    angle_steps,
                    confidence_threshold,
                )
            )
    return observations, tuple(previews)


def _detect_polar_strip(
    engine: Any,
    strip: np.ndarray,
    scale: int,
    view_id: str,
    full_y0: int,
    center: tuple[float, float],
    maximum_radius: float,
    angle_steps: int,
    confidence_threshold: float,
) -> list[OcrObservation]:
    observations: list[OcrObservation] = []
    chunk_width = min(720, strip.shape[1])
    starts = _tile_starts(strip.shape[1], chunk_width)
    vertical_padding = max(0, (24 - strip.shape[0] + 1) // 2)
    for chunk_x in starts:
        chunk = strip[:, chunk_x : chunk_x + chunk_width]
        padded = cv2.copyMakeBorder(
            chunk,
            vertical_padding,
            vertical_padding,
            0,
            0,
            cv2.BORDER_CONSTANT,
            value=(255, 255, 255),
        )
        scaled = cv2.resize(
            padded,
            None,
            fx=scale,
            fy=scale,
            interpolation=cv2.INTER_CUBIC,
        )
        try:
            output = engine(scaled, use_det=True, use_cls=True, use_rec=True)
        except Exception:
            continue
        boxes = getattr(output, "boxes", None)
        texts = getattr(output, "txts", None)
        scores = getattr(output, "scores", None)
        if (
            boxes is None
            or texts is None
            or scores is None
            or not (len(boxes) == len(texts) == len(scores))
        ):
            continue
        for box, raw_text, raw_score in zip(boxes, texts, scores, strict=True):
            text = normalize_ocr_text(str(raw_text))
            confidence = min(1.0, max(0.0, float(raw_score)))
            if not text or confidence < confidence_threshold:
                continue
            local = np.asarray(box, dtype=float) / scale
            local[:, 0] += chunk_x
            local[:, 1] -= vertical_padding
            local[:, 1] = np.clip(local[:, 1], 0, strip.shape[0])
            if abs(float(cv2.contourArea(local.astype(np.float32)))) < 1:
                continue
            mapped = _map_polar_strip_polygon(
                local,
                full_y0,
                center,
                maximum_radius,
                angle_steps,
            )
            observation = _make_observation(
                text,
                confidence,
                mapped,
                "polar",
                scale,
                view_id,
            )
            if observation is not None:
                observations.append(observation)
    return observations


def _recognize_polar_intervals(
    engine: Any,
    strip: np.ndarray,
    scale: int,
    band_index: int,
    full_y0: int,
    center: tuple[float, float],
    maximum_radius: float,
    angle_steps: int,
    confidence_threshold: float,
) -> list[OcrObservation]:
    observations: list[OcrObservation] = []
    for x0, x1 in _polar_word_intervals(strip):
        padded_x0 = max(0, x0 - 2)
        padded_x1 = min(strip.shape[1], x1 + 2)
        crop = cv2.resize(
            strip[:, padded_x0:padded_x1],
            None,
            fx=scale,
            fy=scale,
            interpolation=cv2.INTER_CUBIC,
        )
        try:
            output = engine(crop, use_det=False, use_cls=True, use_rec=True)
        except Exception:
            continue
        texts = getattr(output, "txts", None)
        scores = getattr(output, "scores", None)
        if texts is None or scores is None or len(texts) != 1 or len(scores) != 1:
            continue
        recognized = normalize_ocr_text(str(texts[0]))
        confidence = min(1.0, max(0.0, float(scores[0])))
        if not recognized or confidence < confidence_threshold:
            continue
        tokens = _alphabetic_token_spans(recognized) or (
            (recognized, 0, len(recognized)),
        )
        for token, start, end in tokens:
            token_x0 = padded_x0 + (
                (padded_x1 - padded_x0) * start / max(1, len(recognized))
            )
            token_x1 = padded_x0 + (
                (padded_x1 - padded_x0) * end / max(1, len(recognized))
            )
            local = np.asarray(
                (
                    (token_x0, 0),
                    (token_x1, 0),
                    (token_x1, strip.shape[0]),
                    (token_x0, strip.shape[0]),
                ),
                dtype=float,
            )
            mapped = _map_polar_strip_polygon(
                local,
                full_y0,
                center,
                maximum_radius,
                angle_steps,
            )
            observation = _make_observation(
                token,
                confidence,
                mapped,
                "polar-segment",
                scale,
                f"polar:{band_index}:scale:{scale}",
            )
            if observation is not None:
                observations.append(observation)
    return observations


def _detected_ring_bands(
    unwrapped: np.ndarray,
    maximum_radius: float,
) -> tuple[RingBand, ...]:
    bands: list[RingBand] = []
    half_width = max(8.0, min(24.0, maximum_radius * 0.04))
    for center_y in _polar_ring_centers(unwrapped):
        radial_center = maximum_radius - center_y
        inner = max(0.0, radial_center - half_width)
        outer = min(maximum_radius, radial_center + half_width)
        if outer > inner:
            bands.append(RingBand(inner, outer))
    return tuple(sorted(bands, key=lambda item: (item.inner_radius, item.outer_radius)))


def _rotate_image_expand(
    image: np.ndarray,
    angle_degrees: float,
) -> tuple[np.ndarray, np.ndarray]:
    height, width = image.shape[:2]
    center = (width / 2, height / 2)
    matrix = cv2.getRotationMatrix2D(center, angle_degrees, 1.0)
    cosine = abs(matrix[0, 0])
    sine = abs(matrix[0, 1])
    expanded_width = max(1, int(round(height * sine + width * cosine)))
    expanded_height = max(1, int(round(height * cosine + width * sine)))
    matrix[0, 2] += expanded_width / 2 - center[0]
    matrix[1, 2] += expanded_height / 2 - center[1]
    rotated = cv2.warpAffine(
        image,
        matrix,
        (expanded_width, expanded_height),
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(255, 255, 255),
    )
    return rotated, matrix


def _map_affine_polygon(points: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    return np.column_stack(
        (
            points[:, 0] * matrix[0, 0]
            + points[:, 1] * matrix[0, 1]
            + matrix[0, 2],
            points[:, 0] * matrix[1, 0]
            + points[:, 1] * matrix[1, 1]
            + matrix[1, 2],
        )
    )


def _map_polar_strip_polygon(
    points: np.ndarray,
    full_y0: float,
    center: tuple[float, float],
    maximum_radius: float,
    angle_steps: int,
) -> np.ndarray:
    mapped = []
    for x, local_y in points:
        angle = float(x) / angle_steps * 2 * pi
        radius = max(0.0, maximum_radius - (full_y0 + float(local_y)))
        mapped.append(
            (
                center[0] + radius * cos(angle),
                center[1] + radius * sin(angle),
            )
        )
    return np.asarray(mapped, dtype=float)


def _map_cartesian_polygon_to_polar_strip(
    points: np.ndarray,
    full_y0: float,
    center: tuple[float, float],
    maximum_radius: float,
    angle_steps: int,
) -> np.ndarray:
    mapped = []
    for x, y in points:
        delta_x = float(x) - center[0]
        delta_y = float(y) - center[1]
        angle = atan2(delta_y, delta_x) % (2 * pi)
        radius = (delta_x**2 + delta_y**2) ** 0.5
        mapped.append(
            (
                angle / (2 * pi) * angle_steps,
                maximum_radius - radius - full_y0,
            )
        )
    return np.asarray(mapped, dtype=float)


def _make_observation(
    text: str,
    confidence: float,
    mapped: np.ndarray,
    source: str,
    scale: float,
    view_id: str,
) -> OcrObservation | None:
    try:
        polygon = _engine_text_quad(mapped)
    except ValueError:
        return None
    delta = mapped[1] - mapped[0]
    angle = degrees(atan2(float(delta[1]), float(delta[0])))
    return OcrObservation(
        source=source,
        angle_degrees=angle,
        scale=float(scale),
        confidence=confidence,
        polygon=polygon,
        text=text,
        view_id=view_id,
    )


def _merge_high_recall_regions(
    standard_regions: tuple[TextRegion, ...],
    enhanced_observations: list[OcrObservation],
    language_code: str,
    model_id: str,
    confidence_threshold: float,
    consensus_confidence: float,
    center: tuple[float, float] = (0.0, 0.0),
    image_size: tuple[int, int] | None = None,
) -> tuple[TextRegion, ...]:
    standard_with_evidence = [
        TextRegion(
            region.region_id,
            region.polygon,
            region.text,
            region.confidence,
            region.language_code,
            region.model_id,
            region.status,
            (
                OcrObservation(
                    "standard",
                    _quad_rotation(region.polygon),
                    1.0,
                    region.confidence,
                    region.polygon,
                    region.text,
                    "standard",
                ),
            ),
            False,
            True,
        )
        for region in standard_regions
    ]
    unmatched: list[OcrObservation] = []
    valid_observations = tuple(
        observation
        for observation in enhanced_observations
        if _valid_enhanced_observation(
            observation,
            center,
            image_size,
        )
    )
    ring_groups = _cluster_observations_by_ring(valid_observations, center)
    ring_by_observation = {
        id(observation): ring_index
        for ring_index, group in enumerate(ring_groups)
        for observation in group
    }
    ring_band_limits = _ring_band_limits(ring_groups, center)
    for observation in sorted(valid_observations, key=_observation_sort_key):
        match_index = next(
            (
                index
                for index, region in enumerate(standard_with_evidence)
                if _observation_matches_region(
                    observation,
                    region,
                    center,
                )
            ),
            None,
        )
        if match_index is None:
            unmatched.append(observation)
            continue
        region = standard_with_evidence[match_index]
        standard_with_evidence[match_index] = TextRegion(
            region.region_id,
            region.polygon,
            region.text,
            max(region.confidence, observation.confidence),
            region.language_code,
            region.model_id,
            region.status,
            (*region.observations, observation),
            False,
            True,
        )

    standard_with_evidence = [
        TextRegion(
            region.region_id,
            region.polygon,
            region.text,
            region.confidence,
            region.language_code,
            region.model_id,
            region.status,
            region.observations,
            False,
            True,
        )
        for region in standard_with_evidence
    ]

    clusters: list[list[OcrObservation]] = []
    for ring_index, ring in enumerate(ring_groups):
        ring_observations = tuple(
            observation
            for observation in unmatched
            if ring_by_observation[id(observation)] == ring_index
        )
        for observation in ring_observations:
            cluster = next(
                (
                    candidate
                    for candidate in clusters
                    if ring_by_observation[id(candidate[0])] == ring_index
                    and any(
                        _observations_match(
                            observation,
                            item,
                            center,
                        )
                        for item in candidate
                    )
                ),
                None,
            )
            if cluster is None:
                clusters.append([observation])
            else:
                cluster.append(observation)

    enhanced_regions: list[TextRegion] = []
    for cluster_index, cluster in enumerate(clusters, start=1):
        ordered = tuple(sorted(cluster, key=_observation_sort_key))
        representative = max(
            ordered,
            key=lambda item: (
                sum(_text_similarity(item.text, other.text) >= 0.82 for other in ordered),
                item.confidence,
                len(item.text),
                item.text,
            ),
        )
        supported = tuple(
            item
            for item in ordered
            if item.confidence >= 0.8
            and _text_similarity(item.text, representative.text) >= 0.82
        )
        if len({item.view_id for item in supported}) < 2:
            continue
        agreeing = tuple(
            item
            for item in ordered
            if item.confidence >= consensus_confidence
            and _text_similarity(item.text, representative.text) >= 0.82
        )
        evidence = agreeing or supported
        stable = _mapping_is_stable(agreeing, center) if agreeing else False
        independent_agreement = _independent_view_agreement(
            agreeing,
            representative.text,
        )
        eligible = (
            independent_agreement >= 2
            and stable
        )
        confidence = float(
            np.mean(
                tuple(
                    item.confidence
                    for item in (agreeing or supported)
                )
            )
        )
        mapping_representative = _mapping_medoid(
            agreeing or supported,
            center,
        )
        ring_index = ring_by_observation[id(cluster[0])]
        polygon = _limit_polygon_to_ring(
            mapping_representative.polygon,
            center,
            ring_band_limits[ring_index],
        )
        enhanced_regions.append(
            TextRegion(
                f"enhanced-pending-{cluster_index:04d}",
                polygon,
                representative.text,
                confidence,
                _detect_region_language(representative.text, language_code),
                model_id,
                (
                    TextRegionStatus.OK
                    if confidence >= confidence_threshold
                    else TextRegionStatus.LOW_CONFIDENCE
                ),
                ordered,
                True,
                eligible,
            )
        )

    enhanced_regions = _prune_conflicting_regions(
        enhanced_regions,
        center,
    )
    combined = [*standard_with_evidence, *enhanced_regions]
    combined.sort(key=_region_sort_key)
    return tuple(
        TextRegion(
            f"region-{index:04d}",
            region.polygon,
            region.text,
            region.confidence,
            region.language_code,
            region.model_id,
            region.status,
            region.observations,
            region.enhanced_only,
            region.auto_process_eligible,
        )
        for index, region in enumerate(combined, start=1)
    )


def _observation_matches_region(
    observation: OcrObservation,
    region: TextRegion,
    center: tuple[float, float] | None = None,
) -> bool:
    if center is not None:
        observation_geometry = _polar_geometry(observation.polygon, center)
        region_geometry = _polar_geometry(region.polygon, center)
        if (
            _radial_overlap_ratio(
                observation_geometry,
                region_geometry,
            )
            < 0.25
            or _angular_overlap_ratio(
                observation_geometry,
                region_geometry,
            )
            < 0.2
        ):
            return False
    return (
        _quad_iou(observation.polygon, region.polygon) >= 0.2
        or (
            _quad_center_distance(observation.polygon, region.polygon)
            <= 0.65 * max(_quad_extent(observation.polygon), _quad_extent(region.polygon))
            and _box_overlap_over_smaller(
                _quad_array(observation.polygon),
                _quad_array(region.polygon),
            )
            >= 0.35
        )
    ) and _text_similarity(observation.text, region.text) >= 0.68


def _observations_match(
    first: OcrObservation,
    second: OcrObservation,
    center: tuple[float, float] | None = None,
) -> bool:
    if _text_similarity(first.text, second.text) < 0.72:
        return False
    if center is not None:
        first_geometry = _polar_geometry(first.polygon, center)
        second_geometry = _polar_geometry(second.polygon, center)
        if (
            _angular_overlap_ratio(first_geometry, second_geometry) < 0.3
            or _radial_overlap_ratio(first_geometry, second_geometry) < 0.35
        ):
            return False
    iou = _quad_iou(first.polygon, second.polygon)
    center_distance = _quad_center_distance(first.polygon, second.polygon)
    extent = max(_quad_extent(first.polygon), _quad_extent(second.polygon))
    overlap = _box_overlap_over_smaller(
        _quad_array(first.polygon),
        _quad_array(second.polygon),
    )
    return iou >= 0.18 or (center_distance <= extent * 0.65 and overlap >= 0.28)


@dataclass(frozen=True, slots=True)
class _PolarGeometry:
    mean_radius: float
    radial_start: float
    radial_end: float
    angle_start: float
    angle_end: float
    center_angle: float
    band_width: float
    tangent_degrees: float
    center_x: float
    center_y: float

    @property
    def angular_span(self) -> float:
        return self.angle_end - self.angle_start


def _polar_geometry(
    polygon,
    center: tuple[float, float],
) -> _PolarGeometry:
    points = _quad_array(polygon).astype(float)
    deltas = points - np.asarray(center, dtype=float)
    radii = np.linalg.norm(deltas, axis=1)
    polygon_center = points.mean(axis=0)
    center_delta = polygon_center - np.asarray(center, dtype=float)
    center_angle = atan2(float(center_delta[1]), float(center_delta[0]))
    raw_angles = np.arctan2(deltas[:, 1], deltas[:, 0])
    unwrapped = np.asarray(
        tuple(
            center_angle + _normalized_radians(float(angle) - center_angle)
            for angle in raw_angles
        ),
        dtype=float,
    )
    mean_radius = float(radii.mean())
    tangent = degrees(center_angle + pi / 2)
    return _PolarGeometry(
        mean_radius=mean_radius,
        radial_start=float(radii.min()),
        radial_end=float(radii.max()),
        angle_start=float(unwrapped.min()),
        angle_end=float(unwrapped.max()),
        center_angle=center_angle,
        band_width=float(radii.max() - radii.min()),
        tangent_degrees=_normalized_degrees(tangent),
        center_x=float(polygon_center[0]),
        center_y=float(polygon_center[1]),
    )


def _cluster_observations_by_ring(
    observations: tuple[OcrObservation, ...],
    center: tuple[float, float],
) -> tuple[tuple[OcrObservation, ...], ...]:
    if not observations:
        return ()
    geometries = {
        id(observation): _polar_geometry(observation.polygon, center)
        for observation in observations
    }
    band_widths = tuple(
        geometry.band_width for geometry in geometries.values()
    )
    radius_tolerance = max(
        3.0,
        min(7.0, float(np.median(band_widths)) * 0.4),
    )
    groups: list[list[OcrObservation]] = []
    means: list[float] = []
    for observation in sorted(
        observations,
        key=lambda item: (
            geometries[id(item)].mean_radius,
            *_observation_sort_key(item),
        ),
    ):
        radius = geometries[id(observation)].mean_radius
        nearest = min(
            range(len(means)),
            key=lambda index: abs(means[index] - radius),
            default=None,
        )
        if nearest is None or abs(means[nearest] - radius) > radius_tolerance:
            groups.append([observation])
            means.append(radius)
            continue
        groups[nearest].append(observation)
        means[nearest] = float(
            np.mean(
                tuple(
                    geometries[id(item)].mean_radius
                    for item in groups[nearest]
                )
            )
        )
    return tuple(
        tuple(sorted(group, key=_observation_sort_key))
        for _, group in sorted(
            zip(means, groups, strict=True),
            key=lambda item: item[0],
        )
    )


def _ring_band_limits(
    groups: tuple[tuple[OcrObservation, ...], ...],
    center: tuple[float, float],
) -> tuple[float, ...]:
    means = tuple(
        float(
            np.median(
                tuple(
                    _polar_geometry(observation.polygon, center).mean_radius
                    for observation in group
                )
            )
        )
        for group in groups
    )
    limits: list[float] = []
    for index, group in enumerate(groups):
        original_width = float(
            np.median(
                tuple(
                    _polar_geometry(observation.polygon, center).band_width
                    for observation in group
                )
            )
        )
        neighbor_gaps = tuple(
            abs(means[index] - means[neighbor])
            for neighbor in (index - 1, index + 1)
            if 0 <= neighbor < len(means)
        )
        if not neighbor_gaps:
            limits.append(original_width)
            continue
        limits.append(
            min(
                original_width,
                max(4.0, min(neighbor_gaps) * 0.7),
            )
        )
    return tuple(limits)


def _limit_polygon_to_ring(
    polygon,
    center: tuple[float, float],
    maximum_band_width: float,
):
    geometry = _polar_geometry(polygon, center)
    band_width = min(geometry.band_width, maximum_band_width)
    radial_start = max(0.0, geometry.mean_radius - band_width / 2)
    radial_end = geometry.mean_radius + band_width / 2
    points = (
        (
            center[0] + radial_start * cos(geometry.angle_start),
            center[1] + radial_start * sin(geometry.angle_start),
        ),
        (
            center[0] + radial_end * cos(geometry.angle_start),
            center[1] + radial_end * sin(geometry.angle_start),
        ),
        (
            center[0] + radial_end * cos(geometry.angle_end),
            center[1] + radial_end * sin(geometry.angle_end),
        ),
        (
            center[0] + radial_start * cos(geometry.angle_end),
            center[1] + radial_start * sin(geometry.angle_end),
        ),
    )
    return order_quad(points)


def _valid_enhanced_observation(
    observation: OcrObservation,
    center: tuple[float, float],
    image_size: tuple[int, int] | None,
) -> bool:
    normalized = "".join(
        character for character in observation.text if character.isalnum()
    )
    if len(normalized) < 2 or "\ufffd" in observation.text:
        return False
    points = _quad_array(observation.polygon).astype(float)
    area = abs(float(cv2.contourArea(points.astype(np.float32))))
    if area < 3:
        return False
    if image_size is not None:
        width, height = image_size
        if (
            np.any(points[:, 0] < 0)
            or np.any(points[:, 1] < 0)
            or np.any(points[:, 0] > width - 1)
            or np.any(points[:, 1] > height - 1)
            or area > width * height * 0.035
        ):
            return False
    geometry = _polar_geometry(observation.polygon, center)
    if (
        geometry.mean_radius <= 1
        or geometry.band_width > max(20.0, geometry.mean_radius * 0.12)
        or geometry.angular_span <= 0
        or geometry.angular_span > pi * 0.45
    ):
        return False
    tangent_error = abs(
        _normalized_axis_degrees(
            observation.angle_degrees - geometry.tangent_degrees
        )
    )
    if tangent_error > 32:
        return False
    arc_width = geometry.mean_radius * geometry.angular_span
    width_per_character = arc_width / max(1, len(normalized))
    return 1.0 <= width_per_character <= 42.0


def _independent_view_key(observation: OcrObservation) -> str:
    if observation.source in {"polar", "polar-segment"}:
        return observation.view_id
    if observation.source == "rotation" and observation.angle_degrees % 360 == 0:
        return "standard"
    return observation.view_id


def _normalized_candidate_text(value: str) -> str:
    return "".join(character.casefold() for character in value if character.isalnum())


def _independent_view_agreement(
    observations: tuple[OcrObservation, ...],
    representative_text: str,
) -> int:
    expected = _normalized_candidate_text(representative_text)
    return len(
        {
            _independent_view_key(observation)
            for observation in observations
            if _normalized_candidate_text(observation.text) == expected
        }
    )


def _candidate_is_auto_confirmed(
    observations: tuple[OcrObservation, ...],
    representative_text: str,
    confidence_threshold: float,
    center: tuple[float, float],
) -> bool:
    agreeing = tuple(
        observation
        for observation in observations
        if observation.confidence >= confidence_threshold
        and _normalized_candidate_text(observation.text)
        == _normalized_candidate_text(representative_text)
    )
    return (
        _independent_view_agreement(agreeing, representative_text) >= 2
        and _mapping_is_stable(agreeing, center)
    )


def _mapping_medoid(
    observations: tuple[OcrObservation, ...],
    center: tuple[float, float],
) -> OcrObservation:
    geometries = {
        id(observation): _polar_geometry(observation.polygon, center)
        for observation in observations
    }

    def distance(first: OcrObservation, second: OcrObservation) -> float:
        first_geometry = geometries[id(first)]
        second_geometry = geometries[id(second)]
        mean_radius = max(
            1.0,
            (first_geometry.mean_radius + second_geometry.mean_radius) / 2,
        )
        return (
            abs(first_geometry.mean_radius - second_geometry.mean_radius)
            + abs(
                _normalized_radians(
                    first_geometry.center_angle - second_geometry.center_angle
                )
            )
            * mean_radius
            + abs(first_geometry.band_width - second_geometry.band_width) * 0.25
        )

    return min(
        observations,
        key=lambda candidate: (
            sum(distance(candidate, other) for other in observations),
            -candidate.confidence,
            _observation_sort_key(candidate),
        ),
    )


def _mapping_is_stable(
    observations: tuple[OcrObservation, ...],
    center: tuple[float, float],
) -> bool:
    if len({observation.view_id for observation in observations}) < 2:
        return False
    geometries = tuple(
        _polar_geometry(observation.polygon, center)
        for observation in observations
    )
    radii = tuple(geometry.mean_radius for geometry in geometries)
    band_width = max(
        1.0,
        float(np.median(tuple(geometry.band_width for geometry in geometries))),
    )
    if max(radii) - min(radii) > max(3.0, band_width * 0.35):
        return False
    reference_angle = geometries[0].center_angle
    angular_offsets = tuple(
        _normalized_radians(geometry.center_angle - reference_angle)
        for geometry in geometries
    )
    mean_radius = float(np.mean(radii))
    if (max(angular_offsets) - min(angular_offsets)) * mean_radius > 8.0:
        return False
    tangent_offsets = tuple(
        _normalized_axis_degrees(
            geometry.tangent_degrees - geometries[0].tangent_degrees
        )
        for geometry in geometries
    )
    if max(tangent_offsets) - min(tangent_offsets) > 12:
        return False
    centers = np.asarray(
        tuple((geometry.center_x, geometry.center_y) for geometry in geometries),
        dtype=float,
    )
    center_spread = max(
        float(np.linalg.norm(first - second))
        for first in centers
        for second in centers
    )
    return center_spread <= max(
        8.0,
        float(np.median(tuple(_quad_extent(item.polygon) for item in observations)))
        * 0.3,
    )


def _prune_conflicting_regions(
    regions: list[TextRegion],
    center: tuple[float, float],
) -> list[TextRegion]:
    ordered = sorted(
        regions,
        key=lambda region: (
            -_region_consensus_score(region, center),
            *_region_sort_key(region),
        ),
    )
    selected: list[TextRegion] = []
    for region in ordered:
        geometry = _polar_geometry(region.polygon, center)
        conflict = any(
            _candidate_conflict(
                geometry,
                _polar_geometry(existing.polygon, center),
                region,
                existing,
            )
            for existing in selected
        )
        if not conflict:
            selected.append(region)
    return sorted(selected, key=_region_sort_key)


def _candidate_conflict(
    first_geometry: _PolarGeometry,
    second_geometry: _PolarGeometry,
    first: TextRegion,
    second: TextRegion,
) -> bool:
    if abs(first_geometry.mean_radius - second_geometry.mean_radius) > 7:
        return False
    angular_overlap = _angular_overlap_ratio(first_geometry, second_geometry)
    radial_overlap = _radial_overlap_ratio(first_geometry, second_geometry)
    if angular_overlap < 0.68 or radial_overlap < 0.55:
        return False
    distance = _quad_center_distance(first.polygon, second.polygon)
    return distance <= 0.55 * max(
        _quad_extent(first.polygon),
        _quad_extent(second.polygon),
    )


def _region_consensus_score(
    region: TextRegion,
    center: tuple[float, float],
) -> float:
    observations = region.observations
    view_count = len({item.view_id for item in observations})
    average_confidence = float(
        np.mean(tuple(item.confidence for item in observations))
    )
    representative = region.text
    agreement = float(
        np.mean(
            tuple(
                _text_similarity(representative, item.text)
                for item in observations
            )
        )
    )
    stability = 1.0 if _mapping_is_stable(observations, center) else 0.0
    return view_count * 2 + average_confidence + agreement + stability


def _angular_overlap_ratio(
    first: _PolarGeometry,
    second: _PolarGeometry,
) -> float:
    overlap = 0.0
    for shift in (-2 * pi, 0.0, 2 * pi):
        start = max(first.angle_start, second.angle_start + shift)
        end = min(first.angle_end, second.angle_end + shift)
        overlap = max(overlap, max(0.0, end - start))
    return overlap / max(
        1e-6,
        min(first.angular_span, second.angular_span),
    )


def _radial_overlap_ratio(
    first: _PolarGeometry,
    second: _PolarGeometry,
) -> float:
    overlap = max(
        0.0,
        min(first.radial_end, second.radial_end)
        - max(first.radial_start, second.radial_start),
    )
    return overlap / max(1e-6, min(first.band_width, second.band_width))


def _normalized_radians(value: float) -> float:
    return (value + pi) % (2 * pi) - pi


def _normalized_degrees(value: float) -> float:
    return (value + 180) % 360 - 180


def _normalized_axis_degrees(value: float) -> float:
    normalized = _normalized_degrees(value)
    if normalized > 90:
        normalized -= 180
    elif normalized < -90:
        normalized += 180
    return normalized


def _text_similarity(first: str, second: str) -> float:
    first_normalized = "".join(character.casefold() for character in first if character.isalnum())
    second_normalized = "".join(character.casefold() for character in second if character.isalnum())
    if not first_normalized or not second_normalized:
        return 0.0
    return SequenceMatcher(None, first_normalized, second_normalized).ratio()


def _quad_array(polygon) -> np.ndarray:
    return np.asarray(tuple((point.x, point.y) for point in polygon), dtype=np.float32)


def _quad_iou(first, second) -> float:
    first_array = cv2.convexHull(_quad_array(first))
    second_array = cv2.convexHull(_quad_array(second))
    first_area = abs(float(cv2.contourArea(first_array)))
    second_area = abs(float(cv2.contourArea(second_array)))
    if first_area <= 0 or second_area <= 0:
        return 0.0
    intersection, _ = cv2.intersectConvexConvex(first_array, second_array)
    union = first_area + second_area - float(intersection)
    return float(intersection) / union if union > 0 else 0.0


def _quad_center_distance(first, second) -> float:
    first_center = np.mean(_quad_array(first), axis=0)
    second_center = np.mean(_quad_array(second), axis=0)
    return float(np.linalg.norm(first_center - second_center))


def _quad_extent(polygon) -> float:
    points = _quad_array(polygon)
    return max(
        1.0,
        float(points[:, 0].max() - points[:, 0].min()),
        float(points[:, 1].max() - points[:, 1].min()),
    )


def _quad_rotation(polygon) -> float:
    delta_x = polygon[1].x - polygon[0].x
    delta_y = polygon[1].y - polygon[0].y
    return degrees(atan2(delta_y, delta_x))


def _observation_sort_key(observation: OcrObservation) -> tuple[float, float, str, str]:
    center = np.mean(_quad_array(observation.polygon), axis=0)
    return (
        round(float(center[1]), 4),
        round(float(center[0]), 4),
        observation.text.casefold(),
        observation.view_id,
    )


def _region_sort_key(region: TextRegion) -> tuple[float, float, str]:
    center = np.mean(_quad_array(region.polygon), axis=0)
    return (
        round(float(center[1]), 4),
        round(float(center[0]), 4),
        region.text.casefold(),
    )


def _recover_high_resolution_regions(
    engine: Any,
    image: np.ndarray,
    boxes,
    texts,
    scores,
    confidence_threshold: float,
):
    image_height, image_width = image.shape[:2]
    tile_size = 704
    if max(image_width, image_height) <= 960:
        return tuple(boxes), tuple(texts), tuple(scores)

    recovered_boxes = [np.asarray(box, dtype=float) for box in boxes]
    recovered_texts = [str(text) for text in texts]
    recovered_scores = [float(score) for score in scores]
    for y in _tile_starts(image_height, tile_size):
        tile_height = min(tile_size, image_height - y)
        for x in _tile_starts(image_width, tile_size):
            tile_width = min(tile_size, image_width - x)
            tile = np.ascontiguousarray(
                image[y : y + tile_height, x : x + tile_width]
            )
            output = engine(tile, use_det=True, use_cls=True, use_rec=True)
            tile_boxes = getattr(output, "boxes", None)
            tile_texts = getattr(output, "txts", None)
            tile_scores = getattr(output, "scores", None)
            if tile_boxes is None:
                continue
            if (
                tile_texts is None
                or tile_scores is None
                or not (len(tile_boxes) == len(tile_texts) == len(tile_scores))
            ):
                continue
            for box, text, score in zip(
                tile_boxes,
                tile_texts,
                tile_scores,
                strict=True,
            ):
                confidence = min(1.0, max(0.0, float(score)))
                if confidence < confidence_threshold:
                    continue
                local_box = np.asarray(box, dtype=float)
                if _touches_internal_tile_edge(
                    local_box,
                    x,
                    y,
                    tile_width,
                    tile_height,
                    image_width,
                    image_height,
                ):
                    continue
                mapped_box = local_box + np.array((x, y), dtype=float)
                if any(
                    _box_overlap_over_smaller(mapped_box, existing) > 0.55
                    for existing in recovered_boxes
                ):
                    continue
                recovered_boxes.append(mapped_box)
                recovered_texts.append(str(text))
                recovered_scores.append(confidence)
    return tuple(recovered_boxes), tuple(recovered_texts), tuple(recovered_scores)


def _tile_starts(length: int, tile_size: int) -> tuple[int, ...]:
    if length <= tile_size:
        return (0,)
    last = length - tile_size
    if last <= tile_size:
        return (0, last)
    return (0, last // 2, last)


def _recover_dense_repeated_regions(
    engine: Any,
    image: np.ndarray,
    boxes,
    texts,
    scores,
    confidence_threshold: float,
):
    if len(boxes) < 40:
        return tuple(boxes), tuple(texts), tuple(scores)
    reliable_threshold = max(0.75, confidence_threshold)
    normalized_texts = [normalize_ocr_text(str(text)) for text in texts]
    repeated = Counter(
        text
        for text, score in zip(normalized_texts, scores, strict=True)
        if (
            float(score) >= reliable_threshold
            and 2 <= len(text) <= 4
            and all(_is_cjk_character(character) for character in text)
        )
    )
    canonical = {text for text, count in repeated.items() if count >= 5}
    suspicious = tuple(
        index
        for index, text in enumerate(normalized_texts)
        if 1 <= len(text) <= 2 and not any(_is_cjk_character(character) for character in text)
    )
    if not canonical:
        return tuple(boxes), tuple(texts), tuple(scores)

    observations: dict[int, list[tuple[np.ndarray, str, float]]] = {}
    for scale in (2, 3):
        enlarged = cv2.resize(
            image,
            None,
            fx=scale,
            fy=scale,
            interpolation=cv2.INTER_CUBIC,
        )
        output = engine(enlarged, use_det=True, use_cls=True, use_rec=True)
        enlarged_boxes = getattr(output, "boxes", None)
        enlarged_texts = getattr(output, "txts", None)
        enlarged_scores = getattr(output, "scores", None)
        if (
            enlarged_boxes is None
            or enlarged_texts is None
            or enlarged_scores is None
            or not (
                len(enlarged_boxes) == len(enlarged_texts) == len(enlarged_scores)
            )
        ):
            observations[scale] = []
            continue
        observations[scale] = [
            (
                np.asarray(box, dtype=float) / scale,
                normalize_ocr_text(str(raw_text)),
                min(1.0, max(0.0, float(raw_score))),
            )
            for box, raw_text, raw_score in zip(
                enlarged_boxes,
                enlarged_texts,
                enlarged_scores,
                strict=True,
            )
        ]

    recovered_boxes = [np.asarray(box, dtype=float) for box in boxes]
    recovered_texts = list(texts)
    recovered_scores = [float(score) for score in scores]
    replaced: set[int] = set()
    for mapped, text, confidence in (
        item for values in observations.values() for item in values
    ):
        if text not in canonical or confidence < max(0.85, reliable_threshold):
            continue
        candidates = tuple(
            (
                _box_overlap_over_smaller(mapped, recovered_boxes[index]),
                index,
            )
            for index in suspicious
            if index not in replaced
        )
        if not candidates:
            continue
        overlap, index = max(candidates)
        if overlap < 0.8:
            continue
        recovered_texts[index] = text
        recovered_scores[index] = confidence
        replaced.add(index)

    for box_2x, text_2x, score_2x in observations.get(2, ()):
        if text_2x not in canonical:
            continue
        for box_3x, text_3x, score_3x in observations.get(3, ()):
            if (
                text_3x != text_2x
                or min(score_2x, score_3x) < confidence_threshold
                or _box_overlap_over_smaller(box_2x, box_3x) < 0.7
            ):
                continue
            consensus_box = (box_2x + box_3x) / 2
            if any(
                _box_overlap_over_smaller(consensus_box, existing) > 0.55
                for existing in recovered_boxes
            ):
                break
            recovered_boxes.append(consensus_box)
            recovered_texts.append(text_2x)
            recovered_scores.append(min(score_2x, score_3x))
            break
    return (
        tuple(recovered_boxes),
        tuple(recovered_texts),
        tuple(recovered_scores),
    )


def _recover_multi_angle_regions(
    engine: Any,
    image: np.ndarray,
    boxes,
    texts,
    scores,
    confidence_threshold: float,
):
    recovered_boxes = [np.asarray(box, dtype=float) for box in boxes]
    recovered_texts = [str(text) for text in texts]
    recovered_scores = [float(score) for score in scores]
    if len(recovered_boxes) > 8 or sum(
        abs(_box_rotation_degrees(box)) >= 15 for box in recovered_boxes
    ) < 2:
        return tuple(recovered_boxes), tuple(recovered_texts), tuple(recovered_scores)

    image_height, image_width = image.shape[:2]
    center = (image_width / 2, image_height / 2)
    for angle in range(10, 360, 10):
        matrix = cv2.getRotationMatrix2D(center, angle, 1)
        rotated = cv2.warpAffine(
            image,
            matrix,
            (image_width, image_height),
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=(255, 255, 255),
        )
        output = engine(rotated, use_det=True, use_cls=True, use_rec=True)
        angle_boxes = getattr(output, "boxes", None)
        angle_texts = getattr(output, "txts", None)
        angle_scores = getattr(output, "scores", None)
        if angle_boxes is None:
            continue
        if (
            angle_texts is None
            or angle_scores is None
            or not (len(angle_boxes) == len(angle_texts) == len(angle_scores))
        ):
            continue
        inverse = cv2.invertAffineTransform(matrix)
        for box, text, score in zip(
            angle_boxes,
            angle_texts,
            angle_scores,
            strict=True,
        ):
            confidence = min(1.0, max(0.0, float(score)))
            if confidence < confidence_threshold:
                continue
            points = np.asarray(box, dtype=float)
            mapped = np.column_stack(
                (
                    points[:, 0] * inverse[0, 0]
                    + points[:, 1] * inverse[0, 1]
                    + inverse[0, 2],
                    points[:, 0] * inverse[1, 0]
                    + points[:, 1] * inverse[1, 1]
                    + inverse[1, 2],
                )
            )
            mapped[:, 0] = np.clip(mapped[:, 0], 0, image_width - 1)
            mapped[:, 1] = np.clip(mapped[:, 1], 0, image_height - 1)
            if any(
                _box_overlap_over_smaller(mapped, existing) > 0.55
                for existing in recovered_boxes
            ):
                continue
            recovered_boxes.append(mapped)
            recovered_texts.append(str(text))
            recovered_scores.append(confidence)
    return tuple(recovered_boxes), tuple(recovered_texts), tuple(recovered_scores)


def _recover_polar_text_regions(
    engine: Any,
    image: np.ndarray,
    boxes,
    texts,
    scores,
    confidence_threshold: float,
):
    image_height, image_width = image.shape[:2]
    if not 0.85 <= image_width / max(1, image_height) <= 1.15:
        return tuple(boxes), tuple(texts), tuple(scores)
    center = (image_width / 2, image_height / 2)
    radius = min(center)
    angle_steps = max(360, round(2 * pi * radius))
    polar = cv2.warpPolar(
        image,
        (round(radius), angle_steps),
        center,
        radius,
        cv2.WARP_POLAR_LINEAR | cv2.WARP_FILL_OUTLIERS,
    )
    unwrapped = cv2.rotate(polar, cv2.ROTATE_90_COUNTERCLOCKWISE)
    ring_centers = _polar_ring_centers(unwrapped)
    if len(ring_centers) < 5:
        return tuple(boxes), tuple(texts), tuple(scores)

    recovered_boxes = [np.asarray(box, dtype=float) for box in boxes]
    recovered_texts = [str(text) for text in texts]
    recovered_scores = [float(score) for score in scores]
    for ring_center in ring_centers:
        y0 = max(0, ring_center - 7)
        y1 = min(unwrapped.shape[0], ring_center + 7)
        for x0, x1 in _polar_word_intervals(unwrapped[y0:y1]):
            padded_x0 = max(0, x0 - 2)
            padded_x1 = min(unwrapped.shape[1], x1 + 2)
            crop = cv2.resize(
                unwrapped[y0:y1, padded_x0:padded_x1],
                None,
                fx=3,
                fy=3,
                interpolation=cv2.INTER_CUBIC,
            )
            output = engine(crop, use_det=False, use_cls=True, use_rec=True)
            candidate_texts = getattr(output, "txts", None)
            candidate_scores = getattr(output, "scores", None)
            if (
                candidate_texts is None
                or candidate_scores is None
                or len(candidate_texts) != 1
                or len(candidate_scores) != 1
            ):
                continue
            recognized = normalize_ocr_text(str(candidate_texts[0]))
            confidence = min(1.0, max(0.0, float(candidate_scores[0])))
            if confidence < confidence_threshold:
                continue
            tokens = _alphabetic_token_spans(recognized)
            for token, start, end in tokens:
                token_x0 = padded_x0 + (
                    (padded_x1 - padded_x0) * start / max(1, len(recognized))
                )
                token_x1 = padded_x0 + (
                    (padded_x1 - padded_x0) * end / max(1, len(recognized))
                )
                mapped = _polar_token_quad(
                    token_x0,
                    token_x1,
                    y0,
                    y1,
                    center,
                    radius,
                    angle_steps,
                )
                overlaps = tuple(
                    _box_overlap_over_smaller(mapped, existing)
                    for existing in recovered_boxes
                )
                best_overlap = max(overlaps, default=0.0)
                if best_overlap > 0.55:
                    index = overlaps.index(best_overlap)
                    if (
                        confidence >= recovered_scores[index] + 0.05
                        and len(token) >= len(
                            normalize_ocr_text(recovered_texts[index])
                        )
                    ):
                        recovered_texts[index] = token
                        recovered_scores[index] = confidence
                    continue
                recovered_boxes.append(mapped)
                recovered_texts.append(token)
                recovered_scores.append(confidence)
    return (
        tuple(recovered_boxes),
        tuple(recovered_texts),
        tuple(recovered_scores),
    )


def _polar_ring_centers(unwrapped: np.ndarray) -> tuple[int, ...]:
    gray = cv2.cvtColor(unwrapped, cv2.COLOR_BGR2GRAY)
    ink = np.clip((235 - gray.astype(float)) / 235, 0, 1)
    profile = ink.mean(axis=1)
    smooth = np.convolve(profile, np.ones(5) / 5, mode="same")
    limit = min(len(smooth) - 4, round(unwrapped.shape[0] * 0.68))
    peaks: list[int] = []
    for y in range(4, limit):
        if smooth[y] < 0.035 or smooth[y] < max(smooth[y - 4 : y + 5]):
            continue
        if not peaks or y - peaks[-1] >= 7:
            peaks.append(y)
        elif smooth[y] > smooth[peaks[-1]]:
            peaks[-1] = y
    return tuple(peaks)


def _polar_word_intervals(band: np.ndarray) -> tuple[tuple[int, int], ...]:
    gray = cv2.cvtColor(band, cv2.COLOR_BGR2GRAY)
    foreground = (gray < 210).astype(np.uint8) * 255
    foreground = cv2.morphologyEx(
        foreground,
        cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_RECT, (5, 3)),
    )
    active = (foreground > 0).sum(axis=0) >= 2
    intervals: list[tuple[int, int]] = []
    start: int | None = None
    for x, value in enumerate(active):
        if value and start is None:
            start = x
        elif not value and start is not None:
            if x - start >= 8:
                intervals.append((start, x))
            start = None
    if start is not None and len(active) - start >= 8:
        intervals.append((start, len(active)))
    return tuple(intervals)


def _alphabetic_token_spans(text: str) -> tuple[tuple[str, int, int], ...]:
    tokens: list[tuple[str, int, int]] = []
    start: int | None = None
    for index, character in enumerate((*text, " ")):
        if character.isalpha() and start is None:
            start = index
        elif not character.isalpha() and start is not None:
            if index - start >= 3:
                tokens.append((text[start:index], start, index))
            start = None
    return tuple(tokens)


def _polar_token_quad(
    x0: float,
    x1: float,
    y0: float,
    y1: float,
    center: tuple[float, float],
    radius: float,
    angle_steps: int,
) -> np.ndarray:
    def point(x: float, y: float) -> tuple[float, float]:
        angle = x / angle_steps * 2 * pi
        distance = max(0.0, radius - y)
        return (
            center[0] + distance * cos(angle),
            center[1] + distance * sin(angle),
        )

    return np.asarray(
        (
            point(x0, y0),
            point(x1, y0),
            point(x1, y1),
            point(x0, y1),
        ),
        dtype=float,
    )


def _box_rotation_degrees(box: np.ndarray) -> float:
    points = np.asarray(box, dtype=float)
    delta = points[1] - points[0]
    angle = degrees(atan2(float(delta[1]), float(delta[0])))
    while angle > 90:
        angle -= 180
    while angle < -90:
        angle += 180
    return angle


def _engine_text_quad(values) -> tuple[Point, Point, Point, Point]:
    points = tuple(Point(float(value[0]), float(value[1])) for value in values)
    if len(points) != 4 or len(set(points)) != 4:
        return order_quad(values)
    area = sum(
        points[index].x * points[(index + 1) % 4].y
        - points[(index + 1) % 4].x * points[index].y
        for index in range(4)
    ) / 2
    if abs(area) < 1e-6:
        return order_quad(values)
    if area < 0:
        return (points[0], points[3], points[2], points[1])
    return points  # type: ignore[return-value]


def _touches_internal_tile_edge(
    box: np.ndarray,
    x: int,
    y: int,
    tile_width: int,
    tile_height: int,
    image_width: int,
    image_height: int,
) -> bool:
    margin = 3.0
    xs = box[:, 0]
    ys = box[:, 1]
    return (
        (x > 0 and float(xs.min()) <= margin)
        or (x + tile_width < image_width and float(xs.max()) >= tile_width - 1 - margin)
        or (y > 0 and float(ys.min()) <= margin)
        or (y + tile_height < image_height and float(ys.max()) >= tile_height - 1 - margin)
    )


def _box_overlap_over_smaller(first: np.ndarray, second: np.ndarray) -> float:
    first_x = first[:, 0]
    first_y = first[:, 1]
    second_x = second[:, 0]
    second_y = second[:, 1]
    intersection_width = max(
        0.0,
        min(float(first_x.max()), float(second_x.max()))
        - max(float(first_x.min()), float(second_x.min())),
    )
    intersection_height = max(
        0.0,
        min(float(first_y.max()), float(second_y.max()))
        - max(float(first_y.min()), float(second_y.min())),
    )
    intersection = intersection_width * intersection_height
    first_area = max(
        1.0,
        (float(first_x.max()) - float(first_x.min()))
        * (float(first_y.max()) - float(first_y.min())),
    )
    second_area = max(
        1.0,
        (float(second_x.max()) - float(second_x.min()))
        * (float(second_y.max()) - float(second_y.min())),
    )
    return intersection / min(first_area, second_area)


def _should_refine_region(text: str) -> bool:
    return len(text) <= 12 and any(_is_cjk_character(character) for character in text)


def _is_cjk_character(character: str) -> bool:
    return (
        "\u3400" <= character <= "\u9fff"
        or "\uf900" <= character <= "\ufaff"
    )


# 各书写的支持语言（脚本无法唯一确定语言时回退用）
_LATIN_SCRIPT_LANGUAGES = frozenset(
    {"en", "fr", "de", "es", "it", "pt-PT", "pt-BR", "pl", "tr", "id", "ms", "fil", "vi", "sw"}
)
_ARABIC_SCRIPT_LANGUAGES = frozenset({"ar", "fa", "ur"})
_CJK_LANGUAGES = frozenset({"zh-Hans", "zh-Hant", "ja", "ko"})


def _detect_region_language(text: str, ocr_language: str) -> str:
    """按 Unicode 书写字形推断区域语言，修正 OCR 所选语言的统一打标。

    RapidOCR 每次只跑单一语言模型，所有区域都会被打上所选语言；
    但商品图常混合多语言（如中文主体 + 英文参数），「只翻译指定语言」
    依赖 region.language_code 过滤，必须逐区域修正。
    纯拉丁文本无法区分具体语言时：OCR 所选为拉丁语言则沿用，否则按 en。
    """
    if any("\u3040" <= c <= "\u30ff" or "\u31f0" <= c <= "\u31ff" for c in text):
        return "ja"
    if any("\uac00" <= c <= "\ud7a3" or "\u1100" <= c <= "\u11ff" for c in text):
        return "ko"
    if any(_is_cjk_character(c) or "\u3000" <= c <= "\u303f" for c in text):
        return ocr_language if ocr_language in _CJK_LANGUAGES else "zh-Hans"
    if any("\u0400" <= c <= "\u04ff" for c in text):
        return "ru"
    if any("\u0e00" <= c <= "\u0e7f" for c in text):
        return "th"
    if any("\u0600" <= c <= "\u06ff" for c in text):
        return ocr_language if ocr_language in _ARABIC_SCRIPT_LANGUAGES else "ar"
    if any("\u0900" <= c <= "\u097f" for c in text):
        return "hi"
    if any("\u0980" <= c <= "\u09ff" for c in text):
        return "bn"
    return ocr_language if ocr_language in _LATIN_SCRIPT_LANGUAGES else "en"


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
