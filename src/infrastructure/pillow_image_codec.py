from __future__ import annotations

import os
import errno
from pathlib import Path
from uuid import uuid4

from PIL import Image, ImageOps, UnidentifiedImageError

from src.domain.image import (
    ImageAsset,
    ImageDocument,
    ImageFileFormat,
    ImageLimits,
    ImageValidationError,
)
from src.platform.storage import StorageGuard, StorageUnavailableError


class PillowImageCodec:
    def __init__(self, storage_guard: StorageGuard | None = None) -> None:
        self._storage_guard = storage_guard or StorageGuard()

    def load(self, source: Path, limits: ImageLimits) -> ImageDocument:
        source = source.expanduser()
        if not source.is_file():
            raise ImageValidationError("file_not_found", "找不到所选图片")
        expected_format = ImageFileFormat.from_input_suffix(source.suffix)
        try:
            file_size = source.stat().st_size
        except OSError as error:
            raise ImageValidationError(
                "input_unavailable",
                "无法读取所选图片，请检查文件权限",
            ) from error
        limits.validate_file_size(file_size)
        try:
            with Image.open(source) as opened:
                actual_format = self._map_pillow_format(opened.format)
                if actual_format is not expected_format:
                    raise ImageValidationError(
                        "extension_content_mismatch", "图片扩展名与实际内容格式不一致"
                    )
                limits.validate_dimensions(*opened.size)
                orientation = opened.getexif().get(274, 1)
                normalized = ImageOps.exif_transpose(opened)
                normalized.load()
                limits.validate_dimensions(*normalized.size)
                has_alpha = self._has_alpha(normalized)
                mode = "RGBA" if has_alpha else "RGB"
                working = normalized.convert(mode)
                width, height = working.size
                pixels = working.tobytes()
        except ImageValidationError:
            raise
        except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError) as error:
            raise ImageValidationError("invalid_image", "图片损坏或无法安全解码") from error
        asset = ImageAsset(
            source_path=source.resolve(),
            width=width,
            height=height,
            file_size=file_size,
            file_format=actual_format,
            has_alpha=has_alpha,
            orientation_applied=orientation not in (None, 1),
        )
        return ImageDocument(asset=asset, mode=mode, pixels=pixels)

    def save(
        self, document: ImageDocument, target: Path, output_format: ImageFileFormat
    ) -> None:
        target = target.expanduser()
        if not target.parent.is_dir():
            raise ImageValidationError("output_directory_missing", "导出目录不存在")
        try:
            self._storage_guard.ensure_available(
                target.parent,
                required_bytes=max(len(document.pixels) * 2, 16 * 1024 * 1024),
            )
        except StorageUnavailableError as error:
            code = "output_disk_full" if error.code == "disk_full" else "output_unavailable"
            raise ImageValidationError(code, str(error)) from error
        image = Image.frombytes(
            document.mode,
            (document.asset.width, document.asset.height),
            document.pixels,
        )
        temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
        try:
            export_image, options = self._prepare_export(image, output_format)
            export_image.save(temporary, format=output_format.value, **options)
            with temporary.open("rb+") as stream:
                os.fsync(stream.fileno())
            os.replace(temporary, target)
        except ImageValidationError:
            raise
        except OSError as error:
            if error.errno == errno.ENOSPC:
                raise ImageValidationError(
                    "output_disk_full",
                    "磁盘空间不足，图片未导出",
                ) from error
            if error.errno in {errno.EACCES, errno.EPERM, errno.EROFS}:
                raise ImageValidationError(
                    "output_permission_denied",
                    "没有权限写入所选导出目录",
                ) from error
            raise ImageValidationError(
                "export_failed",
                "图片导出失败，请检查目录权限和可用空间",
            ) from error
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass

    @staticmethod
    def _map_pillow_format(value: str | None) -> ImageFileFormat:
        mapping = {
            "JPEG": ImageFileFormat.JPEG,
            "PNG": ImageFileFormat.PNG,
            "WEBP": ImageFileFormat.WEBP,
        }
        try:
            return mapping[value or ""]
        except KeyError as error:
            raise ImageValidationError("unsupported_input_format", "图片内容不是 JPG、PNG 或 WebP") from error

    @staticmethod
    def _has_alpha(image: Image.Image) -> bool:
        return image.mode in {"RGBA", "LA"} or (
            image.mode == "P" and "transparency" in image.info
        )

    @staticmethod
    def _flatten_white(image: Image.Image) -> Image.Image:
        rgba = image.convert("RGBA")
        background = Image.new("RGB", rgba.size, "white")
        background.paste(rgba, mask=rgba.getchannel("A"))
        return background

    def _prepare_export(
        self, image: Image.Image, output_format: ImageFileFormat
    ) -> tuple[Image.Image, dict[str, object]]:
        if output_format is ImageFileFormat.JPEG:
            return self._flatten_white(image), {"quality": 95, "subsampling": 0}
        if output_format is ImageFileFormat.PNG:
            return image, {"compress_level": 6}
        if output_format is ImageFileFormat.WEBP:
            if image.mode == "RGBA":
                return image, {"lossless": True, "method": 6}
            return image, {"quality": 95, "method": 6}
        if output_format is ImageFileFormat.GIF:
            flattened = self._flatten_white(image)
            return flattened.convert("P", palette=Image.Palette.ADAPTIVE), {"save_all": False}
        if output_format is ImageFileFormat.TIFF:
            return image, {"compression": "tiff_lzw"}
        raise ImageValidationError("unsupported_output_format", "不支持该导出格式")
