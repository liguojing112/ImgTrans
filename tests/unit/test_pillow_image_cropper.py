from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

from src.domain.image import ImageAsset, ImageDocument, ImageFileFormat
from src.domain.layout import TextBox
from src.infrastructure.pillow_image_cropper import PillowImageCropper


def _tilted_bar_document(angle: float = 30.0) -> ImageDocument:
    image = Image.new("RGB", (200, 200), (0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rectangle((40, 90, 160, 110), fill=(255, 255, 255))
    image = image.rotate(
        angle,
        resample=Image.Resampling.BICUBIC,
        center=(100, 100),
        fillcolor=(0, 0, 0),
    )
    asset = ImageAsset(
        Path("tilted.png"), 200, 200, 1, ImageFileFormat.PNG, False, False
    )
    return ImageDocument(asset, "RGB", image.tobytes())


def _row_is_bright(document: ImageDocument, row: int) -> bool:
    width = document.asset.width
    offsets = [((row * width) + x) * 3 for x in (10, width // 2, width - 11)]
    return all(document.pixels[offset] > 200 for offset in offsets)


def test_crop_deskews_rotated_box() -> None:
    document = _tilted_bar_document()
    cropper = PillowImageCropper()

    straight = cropper.crop(document, TextBox(100, 100, 120, 20))
    assert straight.asset.width == 120
    assert straight.asset.height == 20

    rotated = cropper.crop(
        document, TextBox(100, 100, 120, 20, rotation_degrees=30)
    )
    assert rotated.asset.width == 120
    assert rotated.asset.height == 20
    # 按 30° 转正后，中间一行应该是那条白色横条
    assert not _row_is_bright(straight, 10)
    assert _row_is_bright(rotated, 10)
