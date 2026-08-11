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
        # 仅文字形小蒙版走快速填充；水印/杂物等区域一律走 LaMa
        # 脑补背景（避免浅色背景被误判后直接填白，失去纹理/环境填充）
        if _should_fill_with_background(request):
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


def _should_fill_with_background(request: InpaintingRequest) -> bool:
    """判断蒙版是否适合用背景色直接填充，而不是交给 LaMa 生成。

    两种情况走背景色填充：
    1. 文字形小蒙版（多个/少数薄笔画连通分量）；
    2. 整框蒙版内含文字、且周边为纯色背景（短标签/按钮上的文字）。
    实心色块/水印等仍走 LaMa，避免把整块区域直接填成周边颜色。
    """
    mask = _effective_mask(request)
    area = int(np.count_nonzero(mask))
    if not area or area / mask.size > 0.50:
        return False
    if _is_text_shaped_mask(request):
        return True
    return _text_on_solid_background_mask(request)


def _is_text_shaped_mask(request: InpaintingRequest) -> bool:
    mask = _effective_mask(request)
    area = int(np.count_nonzero(mask))
    if not area or area / mask.size > 0.25:
        return False
    component_count, _, stats, _ = cv2.connectedComponentsWithStats(
        mask.astype(np.uint8),
        8,
    )
    if component_count <= 1:
        return False
    extents = tuple(
        float(row[cv2.CC_STAT_AREA])
        / float(row[cv2.CC_STAT_WIDTH] * row[cv2.CC_STAT_HEIGHT])
        for row in stats[1:]
        if row[cv2.CC_STAT_WIDTH] and row[cv2.CC_STAT_HEIGHT]
    )
    return bool(extents) and float(np.median(extents)) < 0.93


def _text_on_solid_background_mask(request: InpaintingRequest) -> bool:
    """整框蒙版内含文字（背景+文字混合）且周边为纯色背景时返回 True。

    例如粉色标签/按钮上的白色短词：OCR 框紧贴文字，蒙版退化为整框时，
    只要框内同时存在背景色与文字色、且框外一圈颜色一致，就用背景色填充，
    保留标签本身的颜色、圆角与形状。
    """
    mask = _effective_mask(request)
    ring = cv2.dilate(
        mask.astype(np.uint8),
        np.ones((7, 7), dtype=np.uint8),
    ).astype(bool) & ~mask
    if np.count_nonzero(ring) < 32:
        return False
    height = request.document.asset.height
    width = request.document.asset.width
    channels = 4 if request.document.mode == "RGBA" else 3
    source = np.frombuffer(request.document.pixels, dtype=np.uint8).reshape(
        height,
        width,
        channels,
    )
    ring_colors = source[ring][:, :3].astype(np.float32)
    background = np.median(ring_colors, axis=0)
    ring_distance = np.linalg.norm(ring_colors - background, axis=1)
    if float(np.percentile(ring_distance, 90)) > 18.0:
        return False
    interior = source[mask][:, :3].astype(np.float32)
    if len(interior) < 16:
        return False
    interior_distance = np.linalg.norm(interior - background, axis=1)
    background_ratio = float(
        np.count_nonzero(interior_distance <= 40.0)
    ) / float(len(interior))
    text_ratio = float(
        np.count_nonzero(interior_distance > 40.0)
    ) / float(len(interior))
    # 只有蒙版内确实有较多与周边同色的背景像素（如浅色底上的文字框），
    # 才用周边颜色填充；若蒙版覆盖的是整个彩色标签（内部几乎没有周边色），
    # 不适用，交给 LaMa，避免把标签整体涂成周边颜色。
    return (
        0.25 <= background_ratio <= 0.9
        and text_ratio >= 0.05
    )


def _has_transparent_background(request: InpaintingRequest) -> bool:
    if request.document.mode != "RGBA":
        return False
    alpha = np.frombuffer(request.document.pixels, dtype=np.uint8).reshape(
        request.document.asset.height,
        request.document.asset.width,
        4,
    )[:, :, 3]
    return float(np.count_nonzero(alpha <= 8)) / float(alpha.size) >= 0.15


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
    """文字笔画蒙版填充，优先保留原始背景效果。

    掩码周边主体为纯色时用逐像素就近取色（精确、抗紧贴干扰色）；周边存在
    渐变/纹理时用 OpenCV TELEA 从周围扩散，保持纹理连续性（避免纯色填充
    造成渐变/图案断裂，尤其对带渐变、花纹的彩色标签）。
    """
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
    if not np.any(mask):
        return document
    rgb = source[:, :, :3]
    ring = (
        cv2.dilate(mask.astype(np.uint8), np.ones((5, 5), dtype=np.uint8))
        > 0
    ) & ~mask
    dominant, ratio = _dominant_background_color(rgb[ring])
    output = (
        _fill_flat_background(source, mask, rgb, dominant)
        if dominant is not None and ratio >= 0.6
        else _fill_textured_background(source, mask, rgb)
    )
    return ImageDocument(document.asset, document.mode, output.tobytes())


def _fill_flat_background(
    source: np.ndarray,
    mask: np.ndarray,
    rgb: np.ndarray,
    dominant: np.ndarray,
) -> np.ndarray:
    """纯色主体背景：逐像素就近取最近背景色，并校准偏离主体色的像素。"""
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
    component_count, component_labels = cv2.connectedComponents(
        mask.astype(np.uint8),
        8,
    )
    mask_area = int(np.count_nonzero(mask))
    for component_id in range(1, component_count):
        component = component_labels == component_id
        # 大面积分量（如误入蒙版的标签外背景块）保持逐像素就近取色，不做校准
        if np.count_nonzero(component) > max(400, mask_area * 0.5):
            continue
        indices = np.flatnonzero(component & mask)
        if not len(indices):
            continue
        ys, xs = np.unravel_index(indices, mask.shape)
        filled = output[ys, xs, :3].astype(np.float32)
        distances = np.linalg.norm(
            filled - dominant.astype(np.float32),
            axis=1,
        )
        outliers = distances > 90
        if np.any(outliers):
            output[ys[outliers], xs[outliers], :3] = dominant
    return output


def _fill_textured_background(
    source: np.ndarray,
    mask: np.ndarray,
    rgb: np.ndarray,
) -> np.ndarray:
    """渐变/纹理主体背景：用 OpenCV TELEA 从周围扩散，保持纹理连续性。"""
    try:
        repaired = cv2.cvtColor(
            cv2.inpaint(
                cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR),
                mask.astype(np.uint8),
                3.0,
                cv2.INPAINT_TELEA,
            ),
            cv2.COLOR_BGR2RGB,
        )
    except cv2.error:
        repaired = rgb
    output = source.copy()
    output[mask > 0, :3] = repaired[mask > 0]
    return output


def _dominant_background_color(
    samples: np.ndarray,
) -> tuple[np.ndarray | None, float]:
    """返回样本中占多数且颜色均匀的主体色及其占比。"""
    if len(samples) < 8:
        return None, 0.0
    values = samples.astype(np.uint8)
    quantized = values // 16
    bins, counts = np.unique(quantized, axis=0, return_counts=True)
    best = bins[int(np.argmax(counts))]
    selected = np.all(quantized == best, axis=1)
    ratio = float(np.count_nonzero(selected)) / float(len(values))
    if ratio < 0.28:
        return None, ratio
    return np.median(values[selected], axis=0).astype(np.uint8), ratio


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
