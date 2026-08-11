from __future__ import annotations

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from src.domain.image import ImageDocument
from src.domain.inpainting import EraseMask


class PillowMaskRasterizer:
    def rasterize(
        self,
        width: int,
        height: int,
        polygons: tuple[tuple[tuple[float, float], ...], ...],
        expansion: int,
    ) -> EraseMask:
        image = Image.new("L", (width, height), 0)
        draw = ImageDraw.Draw(image)
        for polygon in polygons:
            draw.polygon(polygon, fill=255)
        if expansion:
            image = image.filter(ImageFilter.MaxFilter(expansion * 2 + 1))
        return EraseMask(width, height, image.tobytes())

    def rasterize_text(
        self,
        document: ImageDocument,
        polygons: tuple[tuple[tuple[float, float], ...], ...],
        expansion: int,
    ) -> EraseMask:
        channels = 4 if document.mode == "RGBA" else 3
        source_pixels = np.frombuffer(document.pixels, dtype=np.uint8).reshape(
            document.asset.height,
            document.asset.width,
            channels,
        )
        pixels = source_pixels[:, :, :3]
        alpha = source_pixels[:, :, 3] if document.mode == "RGBA" else None
        result = Image.new(
            "L",
            (document.asset.width, document.asset.height),
            0,
        )
        for polygon in polygons:
            geometry = Image.new("L", result.size, 0)
            ImageDraw.Draw(geometry).polygon(polygon, fill=255)
            transparent_text = (
                _transparent_text_mask(alpha, geometry)
                if alpha is not None
                else None
            )
            refined = (
                transparent_text
                if transparent_text is not None
                else _high_contrast_text_mask(pixels, geometry)
            )
            refined_image = Image.fromarray(refined, mode="L")
            if expansion:
                xs = tuple(point[0] for point in polygon)
                ys = tuple(point[1] for point in polygon)
                short_edge = min(max(xs) - min(xs), max(ys) - min(ys))
                is_refined = not np.array_equal(
                    refined,
                    np.asarray(geometry, dtype=np.uint8),
                )
                refined_ratio = float(np.count_nonzero(refined)) / float(
                    max(1, np.count_nonzero(np.asarray(geometry, dtype=np.uint8)))
                )
                xs_span = max(xs) - min(xs)
                ys_span = max(ys) - min(ys)
                narrow_label = (
                    is_refined
                    and ys_span >= xs_span * 1.8
                    and refined_ratio <= 0.35
                )
                if narrow_label:
                    refined_expansion = max(1, expansion // 2)
                elif is_refined and short_edge >= 18 and refined_ratio <= 0.3:
                    refined_expansion = expansion * 2
                else:
                    refined_expansion = expansion
                refined_image = refined_image.filter(
                    ImageFilter.MaxFilter(refined_expansion * 2 + 1)
                )
            result = Image.fromarray(
                np.maximum(
                    np.asarray(result, dtype=np.uint8),
                    np.asarray(refined_image, dtype=np.uint8),
                ),
                mode="L",
            )
        return EraseMask(
            document.asset.width,
            document.asset.height,
            result.tobytes(),
        )

    def rasterize_mapped_text(
        self,
        document: ImageDocument,
        polygons: tuple[tuple[tuple[float, float], ...], ...],
        expansion: int,
    ) -> EraseMask:
        return self._rasterize_mapped_text(
            document,
            polygons,
            expansion,
            fill_smooth_polygon=False,
        )

    def rasterize_high_recall_text(
        self,
        document: ImageDocument,
        polygons: tuple[tuple[tuple[float, float], ...], ...],
        expansion: int,
    ) -> EraseMask:
        return self._rasterize_mapped_text(
            document,
            polygons,
            expansion,
            fill_smooth_polygon=True,
        )

    def _rasterize_mapped_text(
        self,
        document: ImageDocument,
        polygons: tuple[tuple[tuple[float, float], ...], ...],
        expansion: int,
        *,
        fill_smooth_polygon: bool,
    ) -> EraseMask:
        channels = 4 if document.mode == "RGBA" else 3
        source = np.frombuffer(document.pixels, dtype=np.uint8).reshape(
            document.asset.height,
            document.asset.width,
            channels,
        )
        pixels = source[:, :, :3]
        result = np.zeros(
            (document.asset.height, document.asset.width),
            dtype=np.uint8,
        )
        for polygon in polygons:
            geometry = np.zeros(result.shape, dtype=np.uint8)
            points = np.asarray(
                tuple((round(x), round(y)) for x, y in polygon),
                dtype=np.int32,
            )
            points[:, 0] = np.clip(points[:, 0], 0, document.asset.width - 1)
            points[:, 1] = np.clip(points[:, 1], 0, document.asset.height - 1)
            cv2.fillPoly(geometry, (points,), 1)
            search_geometry = cv2.dilate(
                geometry,
                np.ones((3, 3), dtype=np.uint8),
            )
            candidate = _mapped_text_color_difference_mask(
                pixels,
                search_geometry,
                fill_smooth_polygon,
            )
            if expansion and np.any(candidate):
                size = expansion * 2 + 1
                candidate = cv2.dilate(
                    candidate,
                    np.ones((size, size), dtype=np.uint8),
                )
            result = np.maximum(result, candidate * 255)
        return EraseMask(
            document.asset.width,
            document.asset.height,
            result.tobytes(),
        )


def _transparent_text_mask(
    alpha: np.ndarray,
    geometry: Image.Image,
) -> np.ndarray | None:
    polygon = np.asarray(geometry, dtype=np.uint8) > 0
    polygon_pixels = int(np.count_nonzero(polygon))
    if not polygon_pixels:
        return None
    transparent_ratio = float(np.count_nonzero((alpha <= 8) & polygon)) / float(
        polygon_pixels
    )
    candidate = polygon & (alpha > 8)
    candidate_ratio = float(np.count_nonzero(candidate)) / float(polygon_pixels)
    if transparent_ratio < 0.15 or not 0.01 <= candidate_ratio <= 0.85:
        return None
    return candidate.astype(np.uint8) * 255


def _mapped_text_color_difference_mask(
    pixels: np.ndarray,
    geometry: np.ndarray,
    fill_smooth_polygon: bool = False,
) -> np.ndarray:
    inside = geometry > 0
    if np.count_nonzero(inside) < 3:
        return geometry
    outside = (cv2.dilate(geometry, np.ones((5, 5), dtype=np.uint8)) > 0) & ~inside
    inside_pixels = pixels[inside].astype(np.float32)
    outside_pixels = pixels[outside].astype(np.float32)
    background = np.median(
        outside_pixels if len(outside_pixels) else inside_pixels,
        axis=0,
    )
    if fill_smooth_polygon:
        return geometry.copy()
    distances = np.linalg.norm(
        pixels.astype(np.float32) - background,
        axis=2,
    )
    inside_distances = distances[inside]
    threshold = max(18.0, float(np.percentile(inside_distances, 65)))
    candidate = inside & (distances >= threshold)
    ratio = float(np.count_nonzero(candidate)) / float(np.count_nonzero(inside))
    if ratio > 0.6:
        threshold = max(threshold, float(np.percentile(inside_distances, 82)))
        candidate = inside & (distances >= threshold)
    return candidate.astype(np.uint8)


def _high_contrast_text_mask(
    pixels: np.ndarray,
    geometry: Image.Image,
) -> np.ndarray:
    polygon = np.asarray(geometry, dtype=np.uint8) > 0
    colored_label = _colored_label_text_mask(pixels, polygon)
    if colored_label is not None:
        return colored_label
    samples = pixels[polygon].astype(np.float32)
    if not len(samples):
        return np.asarray(geometry, dtype=np.uint8)
    luminance = samples @ np.asarray((0.2126, 0.7152, 0.0722), dtype=np.float32)
    low_limit, high_limit = np.percentile(luminance, (3.0, 97.0))
    dark = np.median(samples[luminance <= low_limit], axis=0)
    bright = np.median(samples[luminance >= high_limit], axis=0)
    edge_width = 5 if min(geometry.size) >= 20 else 3
    inner = np.asarray(
        geometry.filter(ImageFilter.MinFilter(edge_width)),
        dtype=np.uint8,
    )
    border = polygon & (inner == 0)
    background_samples = pixels[border].astype(np.float32)
    background = np.median(
        background_samples if len(background_samples) else samples,
        axis=0,
    )
    dark_distance = float(np.linalg.norm(dark - background))
    bright_distance = float(np.linalg.norm(bright - background))
    dark_chroma = float(dark.max() - dark.min())
    bright_chroma = float(bright.max() - bright.min())
    background_chroma = float(background.max() - background.min())
    neutral_candidates = tuple(
        (distance, color)
        for distance, chroma, color in (
            (dark_distance, dark_chroma, dark),
            (bright_distance, bright_chroma, bright),
        )
        if chroma <= 45 and distance >= 80
    )
    distance_to_background = np.linalg.norm(
        pixels.astype(np.float32) - background,
        axis=2,
    )
    if neutral_candidates:
        contrast, foreground = max(
            neutral_candidates,
            key=lambda candidate: candidate[0],
        )
        foreground_chroma = float(foreground.max() - foreground.min())
        if (
            contrast < 80
            or (foreground_chroma > 45 and background_chroma > 35)
        ):
            return np.asarray(geometry, dtype=np.uint8)
        # 文字 = 距前景色近 且 距背景色远：既排除浅色/渐变背景（离背景近），
        # 又排除多色背景里的其它色块（离前景色远）。
        distance_to_foreground = np.linalg.norm(
            pixels.astype(np.float32) - foreground,
            axis=2,
        )
        foreground_limit = max(72.0, min(180.0, contrast * 0.65))
        background_minimum = max(72.0, contrast * 0.5)
        candidate = polygon & (
            distance_to_foreground <= foreground_limit
        ) & (
            distance_to_background >= background_minimum
        )
    elif background_chroma <= 35:
        contrast, foreground = max(
            (
                (dark_distance, dark),
                (bright_distance, bright),
            ),
            key=lambda candidate: candidate[0],
        )
        distance_to_foreground = np.linalg.norm(
            pixels.astype(np.float32) - foreground,
            axis=2,
        )
        foreground_limit = max(72.0, min(180.0, contrast * 0.65))
        background_minimum = max(72.0, contrast * 0.5)
        candidate = polygon & (
            distance_to_foreground <= foreground_limit
        ) & (
            distance_to_background >= background_minimum
        )
    else:
        # 彩色背景上的彩色/深色文字（无中性前景）：按「与背景的差异」提取文字
        candidate = polygon & (distance_to_background >= 48.0)
    candidate_ratio = (
        float(np.count_nonzero(candidate)) / float(np.count_nonzero(polygon))
        if np.any(candidate)
        else 1.0
    )
    if candidate_ratio > 0.9:
        return np.asarray(geometry, dtype=np.uint8)
    # 不再因候选占框比例过低而退回整框蒙版：纯色背景上的文字即使紧贴文字框，
    # 也应当只擦除文字笔画，保留背景颜色与形状，避免整框走修复破坏背景。
    return candidate.astype(np.uint8) * 255


def _colored_label_text_mask(
    pixels: np.ndarray,
    polygon: np.ndarray,
) -> np.ndarray | None:
    polygon_area = int(np.count_nonzero(polygon))
    if not polygon_area:
        return None
    rows, columns = np.where(polygon)
    polygon_width = int(columns.max() - columns.min() + 1)
    polygon_height = int(rows.max() - rows.min() + 1)
    if polygon_height < polygon_width * 1.8:
        return None
    chroma = pixels.max(axis=2).astype(np.int16) - pixels.min(axis=2).astype(
        np.int16
    )
    colored = polygon & (chroma > 45)
    colored_area = int(np.count_nonzero(colored))
    if colored_area / polygon_area < 0.25:
        return None
    component_count, labels, stats, _ = cv2.connectedComponentsWithStats(
        colored.astype(np.uint8),
        8,
    )
    if component_count <= 1:
        return None
    component_areas = stats[1:, cv2.CC_STAT_AREA]
    largest_id = int(np.argmax(component_areas)) + 1
    largest = labels == largest_id
    if np.count_nonzero(largest) / colored_area < 0.75:
        return None
    coordinates = np.column_stack(np.where(largest))[:, ::-1].astype(np.int32)
    support = np.zeros(polygon.shape, dtype=np.uint8)
    cv2.fillConvexPoly(support, cv2.convexHull(coordinates), 1)
    support_mask = polygon & (support > 0)
    background = np.median(pixels[largest].astype(np.float32), axis=0)
    luminance = pixels @ np.asarray(
        (0.2126, 0.7152, 0.0722),
        dtype=np.float32,
    )
    neutral = chroma < 35
    candidates = (
        support_mask & neutral & (luminance >= 180),
        support_mask & neutral & (luminance <= 120),
    )
    ranked = []
    for candidate in candidates:
        count = int(np.count_nonzero(candidate))
        ratio = count / polygon_area
        if not 0.01 <= ratio <= 0.35:
            continue
        foreground = np.median(pixels[candidate].astype(np.float32), axis=0)
        contrast = float(np.linalg.norm(foreground - background))
        if contrast >= 65:
            ranked.append((contrast, candidate))
    if not ranked:
        return None
    return max(ranked, key=lambda item: item[0])[1].astype(np.uint8) * 255
