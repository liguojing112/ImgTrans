from __future__ import annotations

from pathlib import Path

from src.application.image_limits import CurrentImageLimits
from src.application.ports import ImageCodec
from src.domain.image import ImageDocument, ImageFileFormat, ImageLimits, ImageValidationError


class ImportImage:
    def __init__(
        self,
        codec: ImageCodec,
        limits: ImageLimits | CurrentImageLimits,
    ) -> None:
        self._codec = codec
        self._limits = limits

    def execute(self, source: Path) -> ImageDocument:
        limits = (
            self._limits
            if isinstance(self._limits, ImageLimits)
            else self._limits.current_limits
        )
        return self._codec.load(source, limits)


class ExportImage:
    def __init__(self, codec: ImageCodec) -> None:
        self._codec = codec

    def execute(self, document: ImageDocument, target: Path) -> Path:
        if target.resolve() == document.asset.source_path.resolve():
            raise ImageValidationError("source_overwrite", "不能覆盖导入的原始图片")
        output_format = ImageFileFormat.from_output_suffix(target.suffix)
        self._codec.save(document, target, output_format)
        return target
