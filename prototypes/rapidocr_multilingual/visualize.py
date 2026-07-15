from __future__ import annotations

from pathlib import Path
from typing import Any


def save_visualization(image_path: Path, sample_result: dict[str, Any], output_path: Path) -> None:
    from PIL import Image, ImageDraw, ImageOps

    with Image.open(image_path) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
    draw = ImageDraw.Draw(image)
    for index, region in enumerate(sample_result.get("regions", []), 1):
        points = [tuple(point) for point in region["polygon"]]
        color = "#21c55d" if region["status"] == "ok" else "#ef4444"
        draw.line(points + [points[0]], fill=color, width=3)
        label = (
            f"{index} {region['language_code']} {region['confidence']:.2f} "
            f"{region['text']}"
        )
        try:
            draw.text(points[0], label, fill=color, stroke_width=1, stroke_fill="white")
        except UnicodeEncodeError:
            draw.text(points[0], label.encode("ascii", "replace").decode(), fill=color)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path)

