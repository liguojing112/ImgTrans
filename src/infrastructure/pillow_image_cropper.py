from __future__ import annotations

from dataclasses import replace

from PIL import Image

from src.domain.image import ImageDocument
from src.domain.layout import TextBox


class PillowImageCropper:
    def crop(self, document: ImageDocument, box: TextBox) -> ImageDocument:
        left = max(0, int(box.center_x - box.width / 2))
        top = max(0, int(box.center_y - box.height / 2))
        right = min(document.asset.width, int(box.center_x + box.width / 2 + 0.999))
        bottom = min(document.asset.height, int(box.center_y + box.height / 2 + 0.999))
        if right <= left or bottom <= top:
            raise ValueError("Manual OCR crop is outside the image")
        image = Image.frombytes(
            document.mode,
            (document.asset.width, document.asset.height),
            document.pixels,
        )
        # 斜排文字：先按框的角度把图转正，再裁轴对齐矩形，OCR 拿到的是水平文字
        if abs(box.rotation_degrees) > 0.01:
            image = image.rotate(
                -box.rotation_degrees,
                center=(box.center_x, box.center_y),
                resample=Image.Resampling.BICUBIC,
                expand=False,
                fillcolor=(
                    (255, 255, 255)
                    if document.mode == "RGB"
                    else (255, 255, 255, 0)
                ),
            )
        image = image.crop((left, top, right, bottom))
        asset = replace(
            document.asset,
            width=image.width,
            height=image.height,
            file_size=len(image.tobytes()),
        )
        return ImageDocument(asset, document.mode, image.tobytes())
