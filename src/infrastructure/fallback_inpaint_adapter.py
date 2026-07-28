from __future__ import annotations

from time import perf_counter
from threading import Event

import cv2
import numpy as np

from src.application.ports import InpaintingAdapter
from src.domain.image import ImageDocument
from src.domain.inpainting import InpaintingRequest, InpaintingResult


_MAX_EDGE_FALLBACK_AREA_RATIO = 0.2
_MAX_GLOBAL_FALLBACK_AREA_RATIO = 0.35


class FallbackInpaintAdapter:
    adapter_id = "lama-with-opencv-fallback"

    def __init__(
        self,
        primary: InpaintingAdapter,
        fallback: InpaintingAdapter,
    ) -> None:
        self._primary = primary
        self._fallback = fallback
        self._cancelled = Event()

    def inpaint(self, request: InpaintingRequest) -> InpaintingResult:
        started = perf_counter()
        if self._cancelled.is_set():
            raise RuntimeError("修复任务已取消")
        if _has_transparent_background(request):
            return InpaintingResult(
                _clear_transparent_text(request),
                "transparent-text-clear",
                (perf_counter() - started) * 1000,
            )
        if (
            _has_light_neutral_mask_background(request)
            or _is_text_shaped_mask(request)
        ):
            return InpaintingResult(
                _fill_text_mask(request),
                "opencv-text-fill",
                (perf_counter() - started) * 1000,
            )
        try:
            result = self._primary.inpaint(request)
        except Exception as error:
            if self._cancelled.is_set():
                raise RuntimeError("修复任务已取消") from error
            result = self._fallback.inpaint(request)
            return InpaintingResult(
                result.document,
                result.backend_id,
                (perf_counter() - started) * 1000,
                f"LaMa 不可用，已使用 OpenCV 快速修复：{error}",
            )
        artifact_mask = _smooth_background_artifact_mask(request, result)
        if not np.any(artifact_mask):
            return result
        fallback = self._fallback.inpaint(request)
        effective_mask = _effective_mask(request)
        if np.array_equal(artifact_mask, effective_mask):
            return InpaintingResult(
                fallback.document,
                fallback.backend_id,
                (perf_counter() - started) * 1000,
                "LaMa 修复与平滑背景边界不一致，已使用 OpenCV 快速修复",
            )
        document = _composite_artifact_regions(
            result.document,
            fallback.document,
            artifact_mask,
        )
        return InpaintingResult(
            document,
            f"{result.backend_id}+{fallback.backend_id}",
            (perf_counter() - started) * 1000,
            "LaMa 局部修复与平滑背景边界不一致，异常区域已使用 OpenCV 修复",
        )

    def close(self) -> None:
        close = getattr(self._primary, "close", None)
        if close is not None:
            close()

    def reset_cancel(self) -> None:
        self._cancelled.clear()

    def cancel(self) -> None:
        self._cancelled.set()
        cancel = getattr(self._primary, "cancel", None)
        if cancel is not None:
            cancel()
        else:
            self.close()


def _has_smooth_background_artifact(
    request: InpaintingRequest,
    result: InpaintingResult,
) -> bool:
    return bool(np.any(_smooth_background_artifact_mask(request, result)))


def _effective_mask(request: InpaintingRequest) -> np.ndarray:
    height = request.document.asset.height
    width = request.document.asset.width
    mask = np.frombuffer(request.erase_mask.pixels, dtype=np.uint8).reshape(
        height, width
    ) > 0
    if request.protect_mask is not None:
        protected = np.frombuffer(
            request.protect_mask.pixels,
            dtype=np.uint8,
        ).reshape(height, width) > 0
        mask &= ~protected
    return mask


def _is_text_shaped_mask(request: InpaintingRequest) -> bool:
    mask = _effective_mask(request)
    area = int(np.count_nonzero(mask))
    if not area or area / mask.size > 0.25:
        return False
    component_count, _, stats, _ = cv2.connectedComponentsWithStats(
        mask.astype(np.uint8),
        8,
    )
    if component_count <= 3:
        return False
    extents = tuple(
        float(row[cv2.CC_STAT_AREA])
        / float(row[cv2.CC_STAT_WIDTH] * row[cv2.CC_STAT_HEIGHT])
        for row in stats[1:]
        if row[cv2.CC_STAT_WIDTH] and row[cv2.CC_STAT_HEIGHT]
    )
    return bool(extents) and float(np.median(extents)) < 0.93


def _has_transparent_background(request: InpaintingRequest) -> bool:
    if request.document.mode != "RGBA":
        return False
    alpha = np.frombuffer(request.document.pixels, dtype=np.uint8).reshape(
        request.document.asset.height,
        request.document.asset.width,
        4,
    )[:, :, 3]
    return float(np.count_nonzero(alpha <= 8)) / float(alpha.size) >= 0.15


def _has_light_neutral_mask_background(
    request: InpaintingRequest,
) -> bool:
    mask = _effective_mask(request)
    area_ratio = float(np.count_nonzero(mask)) / float(mask.size)
    if not 0 < area_ratio <= _MAX_GLOBAL_FALLBACK_AREA_RATIO:
        return False
    document = request.document
    channels = 4 if document.mode == "RGBA" else 3
    pixels = np.frombuffer(document.pixels, dtype=np.uint8).reshape(
        document.asset.height,
        document.asset.width,
        channels,
    )[:, :, :3]
    border = (
        cv2.dilate(
            mask.astype(np.uint8),
            np.ones((9, 9), dtype=np.uint8),
        )
        > 0
    ) & ~mask
    samples = pixels[border]
    if len(samples) < 32:
        return False
    minimum = samples.min(axis=1)
    chroma = (
        samples.max(axis=1).astype(np.int16)
        - minimum.astype(np.int16)
    )
    light_neutral = (minimum >= 210) & (chroma <= 30)
    return (
        float(np.count_nonzero(light_neutral)) / float(len(samples))
        >= 0.65
    )


def _clear_transparent_text(request: InpaintingRequest) -> ImageDocument:
    document = request.document
    pixels = np.frombuffer(document.pixels, dtype=np.uint8).reshape(
        document.asset.height,
        document.asset.width,
        4,
    ).copy()
    pixels[_effective_mask(request)] = 0
    return ImageDocument(document.asset, document.mode, pixels.tobytes())


def _fill_text_mask(request: InpaintingRequest) -> ImageDocument:
    document = request.document
    height = document.asset.height
    width = document.asset.width
    channels = 4 if document.mode == "RGBA" else 3
    source = np.frombuffer(document.pixels, dtype=np.uint8).reshape(
        height,
        width,
        channels,
    )
    mask = _effective_mask(request)
    _, labels = cv2.distanceTransformWithLabels(
        mask.astype(np.uint8),
        cv2.DIST_L2,
        5,
        labelType=cv2.DIST_LABEL_PIXEL,
    )
    background_positions = np.argwhere(~mask)
    nearest = background_positions[labels[mask] - 1]
    output = source.copy()
    output[mask, :3] = source[nearest[:, 0], nearest[:, 1], :3]
    solid_fill = np.zeros(mask.shape, dtype=bool)
    component_count, component_labels = cv2.connectedComponents(
        mask.astype(np.uint8),
        8,
    )
    for component_id in range(1, component_count):
        component = component_labels == component_id
        ring = (
            cv2.dilate(
                component.astype(np.uint8),
                np.ones((7, 7), dtype=np.uint8),
            )
            > 0
        ) & ~mask
        background = _dominant_background_color(source[:, :, :3][ring])
        if background is None:
            continue
        output[component, :3] = background
        solid_fill |= component
    for _ in range(4):
        smoothed = cv2.GaussianBlur(output[:, :, :3], (0, 0), 2.0)
        smooth_mask = mask & ~solid_fill
        output[smooth_mask, :3] = smoothed[smooth_mask]
    return ImageDocument(document.asset, document.mode, output.tobytes())


def _dominant_background_color(
    samples: np.ndarray,
) -> np.ndarray | None:
    if len(samples) < 8:
        return None
    values = samples.astype(np.uint8)
    quantized = values // 16
    bins, counts = np.unique(quantized, axis=0, return_counts=True)
    best = bins[int(np.argmax(counts))]
    selected = np.all(quantized == best, axis=1)
    if np.count_nonzero(selected) / len(values) < 0.28:
        return None
    return np.median(values[selected], axis=0).astype(np.uint8)


def _smooth_background_artifact_mask(
    request: InpaintingRequest,
    result: InpaintingResult,
) -> np.ndarray:
    source = request.document
    output = result.document
    height, width = source.asset.height, source.asset.width
    if (
        source.asset.width != output.asset.width
        or source.asset.height != output.asset.height
        or source.mode != output.mode
    ):
        return np.ones((height, width), dtype=bool)
    channels = 4 if source.mode == "RGBA" else 3
    source_pixels = np.frombuffer(source.pixels, dtype=np.uint8).reshape(
        height, width, channels
    )[..., :3]
    output_pixels = np.frombuffer(output.pixels, dtype=np.uint8).reshape(
        height, width, channels
    )[..., :3]
    mask = _effective_mask(request)
    if not np.any(mask):
        return np.zeros((height, width), dtype=bool)
    artifacts = np.zeros((height, width), dtype=bool)
    edge_component_count, edge_labels = cv2.connectedComponents(
        mask.astype(np.uint8),
        8,
    )
    for component_id in range(1, edge_component_count):
        component = edge_labels == component_id
        rows, columns = np.where(component)
        if (
            rows.min() == 0
            or rows.max() == height - 1
            or columns.min() == 0
            or columns.max() == width - 1
        ) and np.count_nonzero(component) / (height * width) <= (
            _MAX_EDGE_FALLBACK_AREA_RATIO
        ):
            artifacts |= component
    if np.count_nonzero(mask) / (height * width) > _MAX_GLOBAL_FALLBACK_AREA_RATIO:
        return artifacts
    ring = cv2.dilate(
        mask.astype(np.uint8),
        np.ones((9, 9), dtype=np.uint8),
        iterations=1,
    ).astype(bool) & ~mask
    if np.count_nonzero(ring) < 32:
        return artifacts
    boundary = source_pixels[ring].astype(np.float32)
    boundary_color = np.median(boundary, axis=0)
    boundary_distance = np.linalg.norm(boundary - boundary_color, axis=1)
    if float(np.percentile(boundary_distance, 90)) > 18.0:
        return artifacts
    repaired = output_pixels[mask].astype(np.float32)
    repaired_distance = np.linalg.norm(repaired - boundary_color, axis=1)
    if float(np.percentile(repaired_distance, 85)) > 60.0:
        return mask
    return artifacts


def _composite_artifact_regions(
    primary: ImageDocument,
    fallback: ImageDocument,
    artifact_mask: np.ndarray,
) -> ImageDocument:
    channels = 4 if primary.mode == "RGBA" else 3
    height = primary.asset.height
    width = primary.asset.width
    primary_pixels = np.frombuffer(primary.pixels, dtype=np.uint8).reshape(
        height, width, channels
    ).copy()
    fallback_pixels = np.frombuffer(fallback.pixels, dtype=np.uint8).reshape(
        height, width, channels
    )
    primary_pixels[artifact_mask] = fallback_pixels[artifact_mask]
    return ImageDocument(primary.asset, primary.mode, primary_pixels.tobytes())
