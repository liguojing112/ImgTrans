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
    """文字笔画蒙版填充：磨平底色，再补回与周边一致的颗粒噪点。

    只做平滑填充会在擦除区留下一块「过于干净」的色斑——原图是有颗粒的
    拍摄素材，平滑区与周边纹理对不上，远看就是一片淡色轮廓（实测 0901
    水印图色差 6.0、噪点 3.4 vs 周边 5.7）。这里先估计低频底色，再把
    邻域的真实高频噪点搬进填充区，两者都对上后基本看不出处理痕迹。
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
    # 优先「整块背景覆盖」：背景是纯色/重复纹理时（水印时间、纯色底上的
    # 标签），整图里能找到大量同款无字区域，直接把一整块真实背景盖上去，
    # 比任何合成填充都干净——实测 0901 残影差 T10 -1.98~-3.52 → 覆盖后 -0.05。
    # 找不到合适背景（彩色标签、渐变条这类全图唯一区域）时才走下面的合成。
    patched = _fill_from_background_patch(source, mask, rgb)
    if patched is not None:
        return ImageDocument(document.asset, document.mode, patched.tobytes())
    # 取样环带必须离开蒙版边缘几个像素：紧贴笔画的那一圈被白字的
    # 半透明白晕/抗锯齿污染，主色会明显偏暗（实测 0901 时间数字：
    # 紧邻环带主色 [28,53,167]，真实底色 [78,98,182]，填充后整块发暗，
    # 客户看到的就是一个比周围暗的矩形印子）。
    mask_u8 = mask.astype(np.uint8)
    near = cv2.dilate(mask_u8, np.ones((9, 9), dtype=np.uint8)) > 0
    far = cv2.dilate(mask_u8, np.ones((41, 41), dtype=np.uint8)) > 0
    ring = far & ~near
    if np.count_nonzero(ring) < 256:
        ring = (
            cv2.dilate(mask_u8, np.ones((5, 5), dtype=np.uint8)) > 0
        ) & ~mask
    dominant, ratio = _dominant_background_color(rgb[ring])
    if dominant is not None and ratio >= 0.6:
        output = _fill_flat_background(source, mask, rgb, dominant)
    else:
        output = _fill_grain_matched_background(source, mask, rgb)
    return ImageDocument(document.asset, document.mode, output.tobytes())


def _fill_from_background_patch(
    source: np.ndarray,
    mask: np.ndarray,
    rgb: np.ndarray,
) -> np.ndarray | None:
    """用整图里另一块「同款干净背景」整块覆盖蒙版区。

    适用前提是背景可重复：纯色/带颗粒的底色、平铺纹理。此时整图里存在
    大量与蒙版区同色的无字区域，随便挑一块盖上来，底色、颗粒、明暗过渡
    都与周围天然一致，不会留下任何合成痕迹。

    找不到合格背景（彩色标签、渐变条这类全图唯一的区域）时返回 None，
    由调用方退回合成填充。
    """
    height, width = mask.shape
    rows, columns = np.nonzero(mask)
    if not len(rows):
        return None
    pad = _PATCH_PADDING
    y0 = max(0, int(rows.min()) - pad)
    y1 = min(height, int(rows.max()) + 1 + pad)
    x0 = max(0, int(columns.min()) - pad)
    x1 = min(width, int(columns.max()) + 1 + pad)
    patch_height, patch_width = y1 - y0, x1 - x0
    if patch_height < 8 or patch_width < 8:
        return None
    # 目标块太大时搜索空间急剧缩小，且多是大段标语，覆盖不值得
    if patch_height * patch_width > _PATCH_MAX_AREA:
        return None

    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY).astype(np.float32)
    low_frequency = cv2.GaussianBlur(gray, (0, 0), 8.0)
    # 参照取「蒙版外、且不是白字」的像素：目标块里白字占了大半，连白字一起
    # 求中位会把参照抬到 117（真实背景才 60），之后所有候选都过不了亮度关。
    # 低频图同样只能用这些像素统计，否则白字的晕染会渗进参照值。
    target_window = np.zeros((height, width), dtype=bool)
    target_window[y0:y1, x0:x1] = True
    sample = target_window & ~mask & (gray < 150)
    if np.count_nonzero(sample) < 64:
        return None
    target_color = np.median(rgb[sample].astype(np.float32), axis=0)
    target_low = float(np.median(gray[sample]))
    has_text = gray > 150

    best: tuple[float, int, int] | None = None
    step = max(2, min(patch_height, patch_width) // 8)
    for top in range(0, height - patch_height, step):
        for left in range(0, width - patch_width, step):
            if (
                top < y1
                and top + patch_height > y0
                and left < x1
                and left + patch_width > x0
            ):
                continue
            window = np.s_[top : top + patch_height, left : left + patch_width]
            if has_text[window].any():
                continue
            if (
                abs(float(np.median(gray[window])) - target_low)
                > _PATCH_LOW_TOLERANCE
            ):
                continue
            distance = float(
                np.linalg.norm(
                    np.median(rgb[window].astype(np.float32), axis=(0, 1))
                    - target_color
                )
            )
            if distance > _PATCH_COLOR_TOLERANCE:
                continue
            roughness = float(low_frequency[window].std())
            if roughness > _PATCH_MAX_ROUGHNESS:
                continue
            score = distance + roughness
            if best is None or score < best[0]:
                best = (score, top, left)
    if best is None:
        return None

    _, top, left = best
    output = source.copy()
    coverage = np.ones((patch_height, patch_width), np.float32)
    feather = min(_PATCH_FEATHER, patch_height // 3, patch_width // 3)
    if feather > 0:
        ramp = np.linspace(0.0, 1.0, feather, dtype=np.float32)
        coverage[:feather, :] *= ramp[:, None]
        coverage[-feather:, :] *= ramp[::-1][:, None]
        coverage[:, :feather] *= ramp[None, :]
        coverage[:, -feather:] *= ramp[::-1][None, :]
    alpha = coverage[..., None]
    destination = output[y0:y1, x0:x1, :3].astype(np.float32)
    donor = rgb[top : top + patch_height, left : left + patch_width].astype(
        np.float32
    )
    output[y0:y1, x0:x1, :3] = np.clip(
        destination * (1.0 - alpha) + donor * alpha,
        0,
        255,
    ).astype(np.uint8)
    return output


# 背景覆盖块的外扩留边（把抗锯齿边一起换掉）与羽化宽度
_PATCH_PADDING = 4
_PATCH_FEATHER = 4
# 超过这个面积的蒙版不走整块覆盖：大段标语在图里找不到同尺寸的干净区
_PATCH_MAX_AREA = 40000
# 候选背景块必须与目标块同底色、同低频亮度、且本身足够平坦
_PATCH_COLOR_TOLERANCE = 12.0
_PATCH_LOW_TOLERANCE = 6.0
_PATCH_MAX_ROUGHNESS = 6.0


def _fill_grain_matched_background(
    source: np.ndarray,
    mask: np.ndarray,
    rgb: np.ndarray,
) -> np.ndarray:
    """低频抹平 + 邻域真实高频噪点回填，消除「平滑色斑」。

    周边噪点很弱（纯色/平滑渐变）时不做颗粒注入，避免给干净背景加噪。
    """
    height, width = mask.shape
    mask_u8 = mask.astype(np.uint8) * 255
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY).astype(np.float32)
    # 邻域窗口：包住蒙版但不含蒙版本身，用来取真实纹理
    neighborhood = cv2.dilate(
        mask_u8, np.ones((31, 31), dtype=np.uint8)
    ) > 0
    outer_band = neighborhood & ~(cv2.dilate(
        mask_u8, np.ones((7, 7), dtype=np.uint8)
    ) > 0)
    if np.count_nonzero(outer_band) < 64:
        outer_band = ~mask
    if not np.any(outer_band):
        return source

    high_frequency = gray - cv2.GaussianBlur(gray, (0, 0), 1.4)
    # 用 MAD 而不是 std 估计颗粒强度：环带里难免混入渐变边缘、相邻笔画
    # 这类少量强结构，std 会被它们抬高（实测同一张电商图 std 13~16.5，
    # 而纯背景区只有 9.6），照抄进去的颗粒比原图重，放大就是一层脏噪点。
    # MAD 只看样本的主体分布，对少量离群值不敏感，更接近真实颗粒。
    samples = high_frequency[outer_band]
    median = float(np.median(samples))
    robust = 1.4826 * float(np.median(np.abs(samples - median)))
    # std 上限：MAD 在「颗粒很细 + JPEG 平滑」的区域会低估（实测同一张图
    # 有的块 0.5、有的块 4.2），只取 MAD 会让原本有颗粒的皮肤/渐变区变哑。
    # 两者取中间：MAD 压住强结构造成的虚高，std 兜住 MAD 的低估。
    grain = 0.5 * (robust + float(samples.std()))

    # 底色用 TELEA 扩散，而不是「就近取最近背景色」。
    #
    # 最近邻在两种真实素材上都会留痕：
    # - 0901 时间水印：笔画很细，最近的背景像素就是白字的抗锯齿边
    #   （亮度 170~245），整片拷进来形成孤立亮斑，客户圈出来的
    #   「旧数字 9 的圈里有白点」就是它。
    # - 电商黄标签：标签底色本身是渐变（左上 [225,165,44] → 右下
    #   [203,138,46]），最近邻会把远处的深色搬到近处的浅色区，把渐变
    #   抹成一块块深黄斑，实测 dE 35~60。
    # TELEA 从蒙版边界向内扩散，天然延续渐变、也不会整块搬运污染像素；
    # 同一批素材上亮斑 0 个、dE 降到 13~27 且无块状。
    smooth = _telea_background(rgb, mask)

    if grain >= 3.0:
        # 噪点按「亮度」生成并三通道同幅叠加。
        #
        # 不能逐像素从邻区抽三个通道的高频再拼起来：原图颗粒是亮度噪点
        # （三通道相关系数 0.98），分别抽样后相关性掉到 0.77，填充区会
        # 出现满屏彩色小点（客户放大后看到的紫/绿/白细点就是它）。
        # 也不能整块平移邻区纹理：平移进来的高频不是零均值，会沿笔画
        # 轮廓叠出一圈网纹（实测 0901 旧字区偏暗 -0.6 亮度）。
        rows, columns = np.nonzero(mask)
        generator = np.random.default_rng(_GRAIN_SEED)
        noise = generator.normal(0.0, grain, size=(height, width)).astype(
            np.float32
        )
        smooth[rows, columns] += np.clip(
            noise[rows, columns],
            -3.0 * grain,
            3.0 * grain,
        )[:, None]

    # 只在蒙版边缘做软过渡，内部必须完全替换。
    # 若直接用高斯模糊后的蒙版混合，笔画细处 alpha<1，原白字会被保留下来，
    # 填充区整体偏亮，反而形成新的可见痕迹（实测+40 亮度）。
    alpha = cv2.GaussianBlur(
        mask.astype(np.float32), (0, 0), 1.2
    )[..., None]
    alpha = np.maximum(alpha, mask.astype(np.float32)[..., None])
    output = source.copy()
    blended = rgb.astype(np.float32) * (1.0 - alpha) + smooth * alpha
    output[:, :, :3] = np.clip(blended, 0, 255).astype(np.uint8)
    return output


# 噪点搬运使用固定种子：同一张图重复擦除的结果稳定，便于复现与对比
_GRAIN_SEED = 20261111

# 底色扩散半径。太大时 TELEA 会把远处的结构（相邻字符的笔画）拉进来，
# 太小则笔画中段的扩散颜色不够稳。3 在 0901 与电商图上都验证过。
_TELEA_RADIUS = 3.0


def _telea_background(rgb: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """从蒙版边界向内扩散出底色（OpenCV TELEA）。

    返回与 rgb 同尺寸的浮点图，蒙版内是扩散结果、蒙版外保持原值。

    扩散前要先把蒙版外紧邻的抗锯齿亮边也一并划入蒙版：TELEA 是从边界
    向内找已知像素，那圈亮边（白字半透明白晕）会被当成底色源，笔画细
    的时候能把整条笔画染成浅色（实测细字场景笔画均值 65 → 118）。
    只有紧贴着蒙版、且比周边明显更亮的像素才会被并入。
    """
    height, width = mask.shape
    mask_u8 = mask.astype(np.uint8)
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY).astype(np.float32)
    ring = (cv2.dilate(mask_u8, np.ones((3, 3), np.uint8)) > 0) & ~mask
    source = mask
    if np.count_nonzero(ring) >= 16:
        neighbors = (cv2.dilate(mask_u8, np.ones((9, 9), np.uint8)) > 0) & ~ring & ~mask
        if np.count_nonzero(neighbors) >= 16:
            halo = ring & (gray > float(np.median(gray[neighbors])) + 25.0)
            if np.count_nonzero(halo) >= 8:
                source = mask | halo
    bgr = cv2.cvtColor(np.clip(rgb, 0, 255).astype(np.uint8), cv2.COLOR_RGB2BGR)
    try:
        repaired = cv2.cvtColor(
            cv2.inpaint(
                bgr,
                source.astype(np.uint8) * 255,
                _TELEA_RADIUS,
                cv2.INPAINT_TELEA,
            ),
            cv2.COLOR_BGR2RGB,
        ).astype(np.float32)
    except cv2.error:
        # 极端尺寸（如 1px 宽）会让 inpaint 报错，退回原图避免整条链路失败
        repaired = rgb.astype(np.float32)
    smooth = rgb.astype(np.float32).copy()
    smooth[mask] = repaired[mask]
    return smooth


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
