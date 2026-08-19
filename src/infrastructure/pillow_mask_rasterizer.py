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


_BACKGROUND_MINIMUM_SHARE = 0.35
_BACKGROUND_SEED_TOLERANCE = 50.0
_BACKGROUND_MIN_SEED_SHARE = 0.30
_BACKGROUND_MIN_SHIFT = 60.0
_BACKGROUND_MIN_LARGEST_SHARE = 0.75


def _corrected_background(
    pixels: np.ndarray,
    polygon: np.ndarray,
    background: np.ndarray,
) -> np.ndarray:
    """边缘环被框外内容污染时，把背景色纠正回框内真正的底色。

    背景估计取多边形最外一圈的中位色，前提是「框边缘属于背景」。彩色横幅、圆角胶囊、
    表格单元格上的文字让这个前提失效：OCR 框比色块本体大一圈，边缘环采到的是框外的
    颜色，中位数被整个带走。后果是框内真正的底色被判成「距背景最远」，于是当成文字
    擦掉——实测橙色圆角胶囊条覆盖率高达 98%，底色连圆角一起被抹平。

    三道门槛，缺一不可：

    1. 环中位色在框内的占比低于 35%。背景色按定义必须在框内大量出现（文字只占少数），
       占比极低说明环被污染。实测被擦毁的橙条只有 2.7%，正常区域普遍在 60% 以上。
    2. 候选底色与环中位色相距 60 以上。渐变、纹理背景同样会让占比偏低，但它们的主色
       与环中位色本就接近，替换没有意义还会扰动下游判据。
    3. 候选底色必须汇成单一连通块。这一道是关键：大号标题的笔画本身就能占满框内两成
       以上像素，仅按占比取主色会把文字误当背景（实测深蓝标题「无需洗马桶」框内蓝色
       占 21%，正是最大色簇）。底色是一整片，文字是彼此分离的字符，主连通域占比把两者
       分得很开——橙色胶囊底 0.92/0.97，深蓝标题笔画 0.24。

    注意不要改用 _looks_like_strokes 做这一道：胶囊底色被白字切得很碎，最大内切半径
    只有框短边的 12.6%（深蓝笔画是 7.7%），落在同一侧，其连通域填充率判据也把底色一
    并判成笔画。形态粗细在这里区分不开，连通性才行。
    """
    samples = pixels[polygon].astype(np.float32)
    total = len(samples)
    if not total:
        return background
    share = (
        float(np.count_nonzero(np.linalg.norm(samples - background, axis=1) <= 30.0))
        / total
    )
    if share >= _BACKGROUND_MINIMUM_SHARE:
        return background
    # 粗量化到 24 级色桶取最大桶作为种子，再按颜色距离把渐变/抗锯齿造成的邻近桶并回
    # 来——胶囊底色带渐变，单个色桶只剩 23.8%，不聚合就会被占比门槛挡掉。
    quantized = (samples // 24).astype(np.int32)
    keys = quantized[:, 0] * 121 + quantized[:, 1] * 11 + quantized[:, 2]
    values, counts = np.unique(keys, return_counts=True)
    seed = np.median(samples[keys == values[int(np.argmax(counts))]], axis=0)
    if float(np.linalg.norm(seed - background)) < _BACKGROUND_MIN_SHIFT:
        return background
    region = polygon & (
        np.linalg.norm(pixels.astype(np.float32) - seed, axis=2)
        <= _BACKGROUND_SEED_TOLERANCE
    )
    if float(np.count_nonzero(region)) / total < _BACKGROUND_MIN_SEED_SHARE:
        return background
    count, labels, stats, _ = cv2.connectedComponentsWithStats(
        region.astype(np.uint8),
        8,
    )
    if count <= 1:
        return background
    areas = stats[1:, cv2.CC_STAT_AREA]
    largest = int(np.argmax(areas))
    if float(areas[largest]) / float(areas.sum()) < _BACKGROUND_MIN_LARGEST_SHARE:
        return background
    # 只取主连通域取色，零散噪点不参与，避免中位色被抗锯齿边缘拉偏。
    return np.median(pixels[labels == largest + 1].astype(np.float32), axis=0)


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
    background = _corrected_background(pixels, polygon, background)
    # 已知未解决：彩色横幅/圆角标签/表格单元格上的文字，其底色会被当成文字擦掉
    # （实测圆角胶囊条覆盖率 98%）。曾尝试两种判别均在语料上净负、已撤回，详见
    # TASK-M5-001 §14/§15：(a) 框内主色+形态判别；(b) 同色连通域溢出文字框判别。
    # 二者都会让蒙版转向整框膨胀。该问题需要像素级文字分割模型，颜色/几何统计不足。
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
        contrast, foreground = None, None
        candidate = polygon & (distance_to_background >= 48.0)
    # 描边/双色艺术字：字身与描边是两个不同的前景色（例如蓝色字身 + 白色描边），
    # 上面只会选中其中一个，另一个会被判为「非文字」而残留。这里对补充前景色
    # 同样做「距前景近 且 距背景远」的筛选后并入，避免只擦掉描边、字身原样留下。
    if foreground is not None:
        companion = _companion_foreground_mask(
            pixels,
            polygon,
            candidate,
            primary=foreground,
            dark=dark,
            bright=bright,
            background=background,
            distance_to_background=distance_to_background,
        )
        if np.any(companion):
            candidate = _merge_if_not_whole_box(polygon, candidate, companion)
    # 同一行内混排第三种颜色的文字（例如白字标题里夹一段红字）：dark/bright 只覆盖
    # 亮度两极，中间色调的文字既不是最暗也不是最亮，会被整段漏掉。
    # 仅当框内仍存在「离背景很远却没被现有蒙版覆盖」的成片内容时才补测颜色簇：
    # 单色文字擦完后不会有这种残留，跳过可避免无谓改变蒙版面积——上游 rasterize_text
    # 会按 refined_ratio 是否 <= 0.3 决定膨胀量是否翻倍，面积被抬高会导致膨胀量下降、
    # 最终蒙版反而变小（实测单色区域覆盖率由 71% 掉到 58%）。
    unexplained = polygon & (distance_to_background >= 80.0) & ~candidate
    polygon_area = float(np.count_nonzero(polygon))
    if polygon_area and float(np.count_nonzero(unexplained)) / polygon_area >= 0.05:
        for extra in _extra_colour_text_masks(
            pixels,
            polygon,
            background=background,
            distance_to_background=distance_to_background,
            known=tuple(
                colour for colour in (foreground, dark, bright) if colour is not None
            ),
        ):
            candidate = _merge_if_not_whole_box(polygon, candidate, extra)
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


_COMPANION_MIN_BACKGROUND_DISTANCE = 80.0
_COMPANION_MIN_PRIMARY_DISTANCE = 60.0
_COMPANION_MAX_RATIO = 0.65
_COMPANION_MIN_ADJACENCY = 0.6


def _companion_foreground_mask(
    pixels: np.ndarray,
    polygon: np.ndarray,
    primary_mask: np.ndarray,
    *,
    primary: np.ndarray,
    dark: np.ndarray,
    bright: np.ndarray,
    background: np.ndarray,
    distance_to_background: np.ndarray,
) -> np.ndarray:
    """取「另一个前景色」对应的文字像素，用于描边/双色文字。

    仅在补充色同时满足以下条件时生效，避免把背景或相邻色块误判为文字：
      1. 距背景足够远（>= 80），确认它是前景而不是背景的一部分；
      2. 与已选前景色差异足够大（>= 60），否则说明两者本就是同一种颜色；
      3. 产生的补充蒙版不超过框内 65%，防止整框被吞掉；
      4. 补充像素大部分落在已选前景所围成的孔洞内（>= 60%）。描边字的字身正是被
         描边圈住的那块区域，因此天然满足包含关系；而框内不相干的同色图形/色块
         位于描边之外，不满足。缺少这条判别时，实测会把彩色图标、渐变色块误当
         字身擦除（残留由 73 升到 212、由 8 升到 87）。
         注意不能退化成「相邻」判断：字身笔画很厚，只有紧贴描边的一薄层算相邻，
         内部像素都会被漏掉，导致描边字本身也被拒。
    """
    companion = (
        bright
        if float(np.linalg.norm(primary - dark))
        <= float(np.linalg.norm(primary - bright))
        else dark
    )
    if (
        float(np.linalg.norm(companion - background))
        < _COMPANION_MIN_BACKGROUND_DISTANCE
        or float(np.linalg.norm(companion - primary))
        < _COMPANION_MIN_PRIMARY_DISTANCE
    ):
        return np.zeros_like(polygon)
    contrast = float(np.linalg.norm(companion - background))
    distance_to_companion = np.linalg.norm(
        pixels.astype(np.float32) - companion,
        axis=2,
    )
    foreground_limit = max(72.0, min(180.0, contrast * 0.65))
    background_minimum = max(72.0, contrast * 0.5)
    extra = polygon & (
        distance_to_companion <= foreground_limit
    ) & (
        distance_to_background >= background_minimum
    )
    extra_area = float(np.count_nonzero(extra))
    if not extra_area:
        return np.zeros_like(polygon)
    polygon_area = float(np.count_nonzero(polygon))
    if polygon_area and extra_area / polygon_area > _COMPANION_MAX_RATIO:
        return np.zeros_like(polygon)
    enclosed = _enclosed_by(primary_mask)
    containment = float(np.count_nonzero(extra & enclosed)) / extra_area
    if containment < _COMPANION_MIN_ADJACENCY:
        return np.zeros_like(polygon)
    return extra


_EXTRA_MIN_BACKGROUND_DISTANCE = 80.0
_EXTRA_MIN_KNOWN_DISTANCE = 60.0
_EXTRA_MIN_BLEND_DISTANCE = 42.0
# 量化分箱会把带抗锯齿的彩色文字拆成多个相邻色簇（实测红字被拆成 4 簇，
# 各约 1.3%~3%，合计 7.4%），门槛取 2% 会把它们逐个滤掉。放宽到 1% 由三重颜色
# 判别（距背景/距已知前景/混色距离）与笔画形态判别兜住误判。
_EXTRA_MIN_PIXEL_RATIO = 0.01
_EXTRA_MAX_PIXEL_RATIO = 0.40
_EXTRA_MAX_CLUSTERS = 3
_EXTRA_MAX_COMPONENT_EXTENT = 0.93
_EXTRA_MAX_STROKE_RATIO = 0.18
# 区域生长用的宽松阈值：颜色容差放大到 150，同时把「距背景」下限降到 40，
# 才能覆盖抗锯齿过渡色；靠空间连通性约束防止漏进背景。
_GROW_COLOUR_DISTANCE = 150.0
_GROW_MIN_BACKGROUND_DISTANCE = 40.0


def _merge_if_not_whole_box(
    polygon: np.ndarray,
    candidate: np.ndarray,
    addition: np.ndarray,
) -> np.ndarray:
    """并入补充蒙版，但不允许把结果推过整框回退阈值。

    一旦占框超过 0.9，上游会退化为整框蒙版，把背景一起送去修复，反而破坏底色与
    形状（实测残留由 73 升到 212）。这种情况下宁可少擦，保留原结果。
    """
    polygon_area = float(np.count_nonzero(polygon))
    union = candidate | addition
    if polygon_area and float(np.count_nonzero(union)) / polygon_area > 0.9:
        return candidate
    return union


def _extra_colour_text_masks(
    pixels: np.ndarray,
    polygon: np.ndarray,
    *,
    background: np.ndarray,
    distance_to_background: np.ndarray,
    known: tuple[np.ndarray, ...],
) -> tuple[np.ndarray, ...]:
    """找出区域内除已知前景色以外、形态像文字的颜色簇蒙版。

    做法：把框内像素按颜色量化分箱统计，取占比达标且离背景足够远的主要色簇，
    逐个按「距该色近 且 距背景远」取蒙版，再用连通域形态排除实心色块/图标。
    """
    region = pixels[polygon]
    total = float(len(region))
    if total < 64:
        return ()
    quantized = (region.astype(np.uint8) // 24).astype(np.int16)
    bins, counts = np.unique(quantized, axis=0, return_counts=True)
    order = np.argsort(-counts)
    results: list[np.ndarray] = []
    for index in order:
        if len(results) >= _EXTRA_MAX_CLUSTERS:
            break
        ratio = float(counts[index]) / total
        if ratio < _EXTRA_MIN_PIXEL_RATIO:
            break  # counts 已降序，后面只会更小
        selected = np.all(quantized == bins[index], axis=1)
        colour = np.median(region[selected].astype(np.float32), axis=0)
        if (
            float(np.linalg.norm(colour - background))
            < _EXTRA_MIN_BACKGROUND_DISTANCE
        ):
            continue
        if any(
            float(np.linalg.norm(colour - other)) < _EXTRA_MIN_KNOWN_DISTANCE
            for other in known
        ):
            continue  # 与已处理过的前景色重复
        if any(
            _distance_to_segment(colour, other, background) < _EXTRA_MIN_BLEND_DISTANCE
            for other in known
        ):
            # 落在「已知前景色 ↔ 背景色」连线附近的是抗锯齿混色（字形边缘的过渡色），
            # 不是另一种文字颜色。把它并入会抬高蒙版占框比例，进而触发上游把膨胀量
            # 减半，最终蒙版反而更小（实测单色区域 71% -> 58%）。
            continue
        contrast = float(np.linalg.norm(colour - background))
        distance_to_colour = np.linalg.norm(
            pixels.astype(np.float32) - colour,
            axis=2,
        )
        mask = polygon & (
            distance_to_colour <= max(60.0, min(140.0, contrast * 0.55))
        ) & (
            distance_to_background >= max(72.0, contrast * 0.5)
        )
        area = float(np.count_nonzero(mask))
        if not area or area / float(np.count_nonzero(polygon)) > _EXTRA_MAX_PIXEL_RATIO:
            continue
        # 形态判别放在严格蒙版上做：此时还没纳入过渡像素，笔画最干净，判别最可靠。
        if not _looks_like_strokes(mask, polygon):
            continue
        grown = _grow_colour_mask(
            mask,
            pixels,
            polygon,
            colour=colour,
            distance_to_background=distance_to_background,
        )
        if float(np.count_nonzero(grown)) / float(np.count_nonzero(polygon)) <= _EXTRA_MAX_PIXEL_RATIO:
            mask = grown
        results.append(mask)
        known = known + (colour,)
    return tuple(results)


def _grow_colour_mask(
    strict: np.ndarray,
    pixels: np.ndarray,
    polygon: np.ndarray,
    *,
    colour: np.ndarray,
    distance_to_background: np.ndarray,
) -> np.ndarray:
    """双阈值区域生长，补上彩色文字的抗锯齿边缘。

    量化分箱会把带抗锯齿的彩色文字拆成多个色簇，其中偏暗的边缘簇代表色离背景很近，
    单独判定必然被拒（实测红字边缘簇距背景仅 56，低于 80 的门槛），合并代表色也会
    被拉向背景。这里改用滞后阈值：以严格蒙版为种子，把「颜色宽松匹配且与种子空间
    连通」的像素并入，既能吃掉过渡色，又不会漏进不相连的背景区域。
    """
    loose = polygon & (
        np.linalg.norm(pixels.astype(np.float32) - colour, axis=2)
        <= _GROW_COLOUR_DISTANCE
    ) & (distance_to_background >= _GROW_MIN_BACKGROUND_DISTANCE)
    loose |= strict
    count, labels = cv2.connectedComponents(loose.astype(np.uint8), 8)
    if count <= 1:
        return strict
    keep = np.unique(labels[strict])
    keep = keep[keep > 0]
    if not len(keep):
        return strict
    return np.isin(labels, keep) & loose


def _distance_to_segment(
    point: np.ndarray,
    start: np.ndarray,
    end: np.ndarray,
) -> float:
    """RGB 空间中点到线段的距离，用于识别前景与背景之间的抗锯齿混色。"""
    direction = (end - start).astype(np.float32)
    length_squared = float(direction @ direction)
    if length_squared <= 1e-6:
        return float(np.linalg.norm(point - start))
    t = float(np.clip((point - start).astype(np.float32) @ direction / length_squared, 0.0, 1.0))
    return float(np.linalg.norm(point - (start + t * direction)))


def _looks_like_strokes(mask: np.ndarray, polygon: np.ndarray) -> bool:
    """判别蒙版是「文字笔画」还是「实心色块」。

    主判据是笔画宽度：对蒙版做距离变换，最大内切半径即最粗笔画的半宽。文字笔画相对
    文字框很细（实测粗体标题约占框短边 9%），而整块底色的内切半径能达到短边的 1/3。
    单纯用外接矩形填充率不够：底色块被文字挖出空洞后填充率会降到 0.9 以下，从而被
    误判成笔画（实测饱和双色标签的青绿底 extent=0.895，绕过了 0.93 的阈值）。
    """
    count, _, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), 8)
    if count <= 1:
        return False
    rows, columns = np.nonzero(polygon)
    if not len(rows):
        return False
    short_edge = float(min(rows.max() - rows.min() + 1, columns.max() - columns.min() + 1))
    if short_edge <= 0:
        return False
    radius = float(
        cv2.distanceTransform(mask.astype(np.uint8), cv2.DIST_L2, 3).max()
    )
    if radius / short_edge > _EXTRA_MAX_STROKE_RATIO:
        return False
    extents = tuple(
        float(row[cv2.CC_STAT_AREA]) / float(row[cv2.CC_STAT_WIDTH] * row[cv2.CC_STAT_HEIGHT])
        for row in stats[1:]
        if row[cv2.CC_STAT_WIDTH] and row[cv2.CC_STAT_HEIGHT]
    )
    if not extents:
        return False
    return float(np.median(extents)) < _EXTRA_MAX_COMPONENT_EXTENT


def _enclosed_by(mask: np.ndarray) -> np.ndarray:
    """返回 mask 自身加上它所围成的孔洞（即「描边 + 描边内部」）。

    先做一次闭运算把描边的抗锯齿缺口补上，再把不接触图像边界的背景连通域视为孔洞。
    """
    closed = cv2.morphologyEx(
        mask.astype(np.uint8),
        cv2.MORPH_CLOSE,
        np.ones((5, 5), dtype=np.uint8),
    )
    background = (closed == 0).astype(np.uint8)
    count, labels = cv2.connectedComponents(background, 4)
    if count <= 1:
        return closed > 0
    border = np.concatenate(
        (labels[0, :], labels[-1, :], labels[:, 0], labels[:, -1])
    )
    outside = set(int(value) for value in np.unique(border))
    holes = np.isin(labels, tuple(outside), invert=True) & (background > 0)
    return (closed > 0) | holes


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
    # 仅限竖排细长彩色标签。不要放开成双向（polygon_width >= polygon_height *
    # 1.8）：横排文字行天然宽扁，会让本分支被普通文字大量命中——语料实测 1116 区域
    # 中 189 个受影响，残留恶化>20 的 35 个 vs 改善 2 个，净 +2048。后面那三道判据
    # （饱和色占框 >= 25% / 单一主连通域 >= 75% / 中性文字对比 >= 65）在真实电商图
    # 上太容易满足，挡不住彩色底色条上的白字。详见 TASK-M5-001 §16。
    elongated = polygon_height >= polygon_width * 1.8
    if not elongated:
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
