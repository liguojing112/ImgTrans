"""图片导出服务 — 不与 QWidget 耦合的薄适配层。"""

from pathlib import Path

from src.application.image_io import ExportImage
from src.domain.image import ImageDocument, ImageFileFormat
from src.infrastructure.pillow_image_codec import PillowImageCodec


def export_document(
    document: ImageDocument,
    target: Path,
    export_usecase: ExportImage | None,
    codec: PillowImageCodec | None,
) -> Path:
    """导出图片到指定路径。返回 target。"""
    if export_usecase is not None:
        return export_usecase.execute(document, target)
    if codec is not None:
        fmt = ImageFileFormat.from_output_suffix(target.suffix)
        codec.save(document, target, fmt)
        return target
    raise ValueError("导出功能不可用")
