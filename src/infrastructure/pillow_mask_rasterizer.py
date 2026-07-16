from __future__ import annotations

from PIL import Image, ImageDraw, ImageFilter

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
