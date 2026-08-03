"""图片导入服务 — 不与 QWidget 耦合的薄适配层。"""

from pathlib import Path

from src.application.image_io import ImportImage
from src.domain.image import ImageDocument
from src.infrastructure.pillow_image_codec import PillowImageCodec


def load_document(
    source: Path,
    import_usecase: ImportImage,
    codec: PillowImageCodec | None,
) -> ImageDocument:
    """通过正式导入用例加载并验证图片。"""
    return import_usecase.execute(source)
