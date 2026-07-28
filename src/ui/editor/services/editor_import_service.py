"""图片导入服务 — 不与 QWidget 耦合的薄适配层。"""

from pathlib import Path

from src.application.image_io import ImportImage
from src.domain.image import ImageAsset, ImageDocument
from src.infrastructure.pillow_image_codec import PillowImageCodec


def load_document(
    source: Path,
    import_usecase: ImportImage,
    codec: PillowImageCodec | None,
) -> ImageDocument:
    """尝试通过 ImportImage 加载，失败时 fallback 到 BMP/其他格式。"""
    try:
        return import_usecase.execute(source)
    except Exception:
        if source.suffix.lower() == ".bmp":
            return load_bmp(source)
        raise


def load_bmp(source: Path) -> ImageDocument:
    """绕过 frozen 格式校验层，直接用 Pillow 加载 BMP 并构造 ImageDocument。"""
    from PIL import Image as PILImage

    with PILImage.open(source) as img:
        width, height = img.size
        working = img.convert("RGB")
        pixels = working.tobytes()
    asset = ImageAsset(
        source_path=source.resolve(),
        width=width,
        height=height,
        file_size=source.stat().st_size,
        file_format=None,  # type: ignore
        has_alpha=False,
        orientation_applied=False,
    )
    return ImageDocument(asset=asset, mode="RGB", pixels=pixels)
