"""图片工具箱核心操作 — 裁剪 / 旋转 / 翻转 / 压缩 / 水印 / 导出。

复用现有 PillowImageCodec、PillowImageCropper、transform_image_document
以及 apply_watermark_template。
"""

from __future__ import annotations

import uuid
from pathlib import Path

from src.domain.image import ExportOptions, ImageDocument, ImageFileFormat, ImageLimits


def apply_operations(
    source: Path,
    params: object,  # OperationParams
    codec: object | None = None,
) -> Path:
    """对单张图片执行批量操作，返回结果临时文件路径。

    操作链：load → crop → rotate/flip → resize → watermark → save temp
    """
    from src.infrastructure.pillow_image_codec import PillowImageCodec
    from src.infrastructure.pillow_image_cropper import PillowImageCropper

    if codec is None:
        codec = PillowImageCodec()

    # 1) 加载（工具箱中间结果可能很小，用宽松限制）
    _relaxed_limits = ImageLimits(min_width=1, min_height=1)
    doc = codec.load(source, _relaxed_limits)

    # 2) 裁剪
    if params.crop_box:
        from src.domain.layout import TextBox
        x, y, w, h = params.crop_box
        center_x = x + w // 2
        center_y = y + h // 2
        box = TextBox(center_x=center_x, center_y=center_y, width=w, height=h)
        cropper = PillowImageCropper()
        doc = cropper.crop(doc, box)

    # 3) 旋转 / 翻转（分别应用，支持组合）
    from src.application.composition import transform_image_document
    from src.domain.composition import ImageTransform

    rotate_map = {0: None, 90: ImageTransform.ROTATE_90_CCW,
                  180: ImageTransform.ROTATE_180, 270: ImageTransform.ROTATE_90_CW}
    flip_map = {None: None, "horizontal": ImageTransform.FLIP_HORIZONTAL,
                "vertical": ImageTransform.FLIP_VERTICAL}

    rot_op = rotate_map.get(params.rotate_deg)
    flip_op = flip_map.get(params.flip)
    if rot_op is not None:
        doc = transform_image_document(doc, rot_op)
    if flip_op is not None:
        doc = transform_image_document(doc, flip_op)

    # 4) 尺寸限制
    if params.max_size:
        max_w, max_h = params.max_size
        doc = _resize_document(doc, max_w, max_h)

    # 5) 水印（多组文字水印 + 图片水印）
    has_watermarks = bool(
        getattr(params, "watermarks", None)
        or getattr(params, "watermark_image_path", None)
    )
    if has_watermarks:
        doc = _apply_watermark(doc, params)

    # 6) 保存到临时目录
    from src.platform.paths import PlatformPaths
    cache_dir = PlatformPaths.discover().cache_dir / "toolbox_output"
    cache_dir.mkdir(parents=True, exist_ok=True)

    output_format = params.output_format
    suffix = _format_to_suffix(output_format) if output_format else source.suffix.lower()
    if not suffix:
        suffix = ".png"

    temp_path = cache_dir / f"{uuid.uuid4().hex[:12]}{suffix}"
    _save_document(doc, temp_path, params)
    return temp_path


def export_image(
    source: Path,
    target_dir: Path,
    index: int = 0,
    output_format: str | None = None,
    quality: int = 95,
    codec: object | None = None,
) -> Path:
    """导出单张图片到目标目录（仅格式转换+质量，不做其他处理）。"""
    from src.infrastructure.pillow_image_codec import PillowImageCodec

    if codec is None:
        codec = PillowImageCodec()

    doc = codec.load(source, ImageLimits(min_width=1, min_height=1))
    suffix = _format_to_suffix(output_format) if output_format else source.suffix.lower()
    if not suffix:
        suffix = ".png"
    name = f"IMG_{index:04d}{suffix}"
    target = target_dir / name
    _save_document(doc, target, _SimpleParams(output_format, quality))
    return target


# —— 内部辅助 ——


def _resize_document(doc: ImageDocument, max_w: int, max_h: int) -> ImageDocument:
    """按比例缩放，保持宽高比，使图片不超过 max_w × max_h。"""
    w, h = doc.asset.width, doc.asset.height
    if w <= max_w and h <= max_h:
        return doc
    ratio = min(max_w / w, max_h / h)
    new_w = max(1, int(w * ratio))
    new_h = max(1, int(h * ratio))

    from PIL import Image
    import numpy as np

    pixels_arr = np.frombuffer(doc.pixels, dtype=np.uint8).reshape((h, w, -1))
    img = Image.fromarray(pixels_arr)
    img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
    new_pixels = np.array(img).tobytes()

    from src.domain.image import ImageAsset
    new_asset = ImageAsset(
        source_path=doc.asset.source_path,
        width=new_w,
        height=new_h,
        file_size=len(new_pixels),
        file_format=doc.asset.file_format,
        has_alpha=doc.mode == "RGBA",
        orientation_applied=doc.asset.orientation_applied,
    )
    return ImageDocument(asset=new_asset, mode=doc.mode, pixels=new_pixels)


def _apply_watermark(doc: ImageDocument, params: object) -> ImageDocument:
    """应用多组文字水印（支持翻转、自定义坐标、缩放）。"""
    items = getattr(params, "watermarks", None) or []
    text_items = [wm for wm in items if getattr(wm, "text", "").strip()]
    if not text_items and not getattr(params, "watermark_image_path", None):
        return doc

    from src.domain.composition import TextStyle, WatermarkLayer
    from src.infrastructure.pillow_image_codec import PillowImageCodec
    from src.application.composition import _paste_center, _watermark_image
    from PIL import Image

    base = Image.frombytes(
        doc.mode,
        (doc.asset.width, doc.asset.height),
        doc.pixels,
    ).convert("RGBA")

    w, h = doc.asset.width, doc.asset.height

    # 1) 多组文字水印
    for wm in text_items:
        color_hex = (getattr(wm, "color", "#FFFFFF") or "#FFFFFF").lstrip("#")
        try:
            if len(color_hex) != 6:
                raise ValueError
            fill_rgb = tuple(int(color_hex[i:i + 2], 16) for i in (0, 2, 4))
        except ValueError:
            fill_rgb = (255, 255, 255)

        scale = max(0.1, float(getattr(wm, "scale", 1.0)))
        base_font_size = max(1, int(getattr(wm, "font_size", 42)))
        # 字体随水印框缩放同步缩放
        font_size = max(1, int(base_font_size * scale))
        style = TextStyle(
            font_family=getattr(wm, "font_family", "sans-serif"),
            font_size=font_size,
            fill_rgb=fill_rgb,
        )
        text_len = max(1, len(wm.text))
        wm_width = max(80.0, min(w * 0.5, text_len * base_font_size)) * scale
        wm_height = max(30.0, base_font_size * 1.6) * scale

        center_x, center_y = _resolve_position(
            wm, w, h, wm_width, wm_height)

        layer = WatermarkLayer(
            f"watermark-{wm.id}",
            "text",
            center_x,
            center_y,
            wm_width,
            wm_height,
            opacity=float(getattr(wm, "opacity", 0.55)),
            tiled=bool(getattr(wm, "tiled", False)),
            text=wm.text,
            style=style,
            rotation_degrees=float(getattr(wm, "rotation", 0)),
        )
        overlay = _watermark_image(layer)
        if getattr(wm, "flip_h", False):
            overlay = overlay.transpose(Image.FLIP_LEFT_RIGHT)
        if getattr(wm, "flip_v", False):
            overlay = overlay.transpose(Image.FLIP_TOP_BOTTOM)
        if layer.tiled:
            step_x = max(20, int(layer.width * 1.5))
            step_y = max(20, int(layer.height * 2.0))
            for yy in range(-step_y, base.height + step_y, step_y):
                for xx in range(-step_x, base.width + step_x, step_x):
                    _paste_center(base, overlay, xx + step_x // 2, yy + step_y // 2)
        else:
            _paste_center(base, overlay, center_x, center_y)

    # 2) 图片水印（沿用模板位置）
    img_path = getattr(params, "watermark_image_path", None)
    if img_path:
        from src.application.composition import apply_watermark_template
        from src.application.batch_export import BatchWatermarkOptions
        wm_codec = PillowImageCodec()
        wm_doc = wm_codec.load(img_path, ImageLimits())
        options = BatchWatermarkOptions(
            kind="image",
            opacity=0.55,
            tiled=False,
            position="bottom_right",
            image=wm_doc,
        )
        doc = apply_watermark_template(doc, options)
        return doc

    output = base if doc.mode == "RGBA" else base.convert("RGB")
    return ImageDocument(doc.asset, doc.mode, output.tobytes())


_POSITION_RATIOS: dict[str, tuple[float, float]] = {
    "top_left": (0.15, 0.15),
    "top_center": (0.5, 0.15),
    "top_right": (0.85, 0.15),
    "middle_left": (0.15, 0.5),
    "center": (0.5, 0.5),
    "middle_right": (0.85, 0.5),
    "bottom_left": (0.15, 0.85),
    "bottom_center": (0.5, 0.85),
    "bottom_right": (0.85, 0.85),
}


def _resolve_position(wm, img_w: int, img_h: int,
                      wm_w: float, wm_h: float) -> tuple[float, float]:
    """计算水印中心坐标：优先自定义坐标，否则九宫格。"""
    custom_x = getattr(wm, "custom_x", None)
    custom_y = getattr(wm, "custom_y", None)
    if custom_x is not None and custom_y is not None:
        # 自定义坐标是水印框中心的比例位置
        cx = min(1.0, max(0.0, custom_x)) * img_w
        cy = min(1.0, max(0.0, custom_y)) * img_h
        # 防止超出边界
        cx = max(wm_w / 2, min(img_w - wm_w / 2, cx))
        cy = max(wm_h / 2, min(img_h - wm_h / 2, cy))
        return cx, cy

    position = str(getattr(wm, "position", "bottom_right")).replace("-", "_")
    rx, ry = _POSITION_RATIOS.get(position, (0.85, 0.85))
    return rx * img_w, ry * img_h

    return doc


def _save_document(doc: ImageDocument, target: Path, params: object) -> None:
    """保存文档到指定路径，应用格式转换和质量参数。"""
    from src.infrastructure.pillow_image_codec import PillowImageCodec

    fmt_str = getattr(params, "output_format", None)
    quality = getattr(params, "quality", 95)

    if fmt_str:
        fmt = ImageFileFormat.from_output_suffix(_format_to_suffix(fmt_str))
    else:
        fmt = ImageFileFormat.from_output_suffix(target.suffix.lower())

    options = ExportOptions(
        quality=quality,
        preserve_alpha=fmt != ImageFileFormat.JPEG,
    )
    codec = PillowImageCodec()
    codec.save(doc, target, fmt, options)


def _format_to_suffix(fmt: str) -> str:
    return {
        "png": ".png",
        "jpg": ".jpg",
        "jpeg": ".jpg",
        "webp": ".webp",
        "gif": ".gif",
        "tif": ".tiff",
        "tiff": ".tiff",
    }.get(fmt.lower(), ".png")


class _SimpleParams:
    """轻量参数对象，用于 export_image 中 _save_document 调用。"""

    def __init__(self, output_format: str | None, quality: int) -> None:
        self.output_format = output_format
        self.quality = quality
