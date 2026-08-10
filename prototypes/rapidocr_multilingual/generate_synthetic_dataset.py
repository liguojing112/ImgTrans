from __future__ import annotations

from hashlib import sha256
from math import cos, radians, sin
from pathlib import Path
from random import Random
from typing import Any
import argparse
import json
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from PIL import Image, ImageDraw, ImageFont, features

from prototypes.rapidocr_multilingual.contracts import order_quad
from prototypes.rapidocr_multilingual.model_router import LANGUAGE_CODES


CANVAS_SIZE = (900, 600)
DIFFICULTIES = {
    "clear_print": {"font_size": 42, "angle": 0, "foreground": (20, 20, 20)},
    "small": {"font_size": 22, "angle": 0, "foreground": (25, 25, 25)},
    "rotated": {"font_size": 38, "angle": 8, "foreground": (20, 20, 20)},
    "low_contrast_complex": {
        "font_size": 36,
        "angle": -5,
        "foreground": (105, 105, 105),
    },
}
RTL_LANGUAGES = {"ar", "ur", "fa"}


def rotate_polygon(
    polygon: tuple[tuple[float, float], ...],
    source_size: tuple[int, int],
    rotated_size: tuple[int, int],
    angle: float,
    offset: tuple[int, int],
) -> tuple[tuple[float, float], ...]:
    center_x, center_y = source_size[0] / 2, source_size[1] / 2
    shift_x = (rotated_size[0] - source_size[0]) / 2 + offset[0]
    shift_y = (rotated_size[1] - source_size[1]) / 2 + offset[1]
    theta = radians(angle)
    result = []
    for x, y in polygon:
        relative_x, relative_y = x - center_x, y - center_y
        result.append(
            (
                cos(theta) * relative_x + sin(theta) * relative_y + center_x + shift_x,
                -sin(theta) * relative_x + cos(theta) * relative_y + center_y + shift_y,
            )
        )
    return order_quad(result)


def load_configuration(config_dir: Path) -> tuple[dict[str, list[str]], dict[str, Any]]:
    texts = json.loads((config_dir / "synthetic-text.json").read_text(encoding="utf-8"))
    fonts = json.loads((config_dir / "font-map.json").read_text(encoding="utf-8"))
    if set(texts) != set(LANGUAGE_CODES):
        raise ValueError("Synthetic text configuration must cover exactly the 25-language baseline")
    if set(fonts["languages"]) != set(LANGUAGE_CODES):
        raise ValueError("Font mapping must cover exactly the 25-language baseline")
    if any(len(values) != 5 for values in texts.values()):
        raise ValueError("Each language must provide exactly five synthetic phrases")
    return texts, fonts


def _font_inventory(font_dir: Path, config: dict[str, Any]) -> list[dict[str, Any]]:
    inventory = []
    for family, value in sorted(config["families"].items()):
        path = font_dir / value["filename"]
        if not path.is_file():
            raise FileNotFoundError(f"Required font is missing: {path}")
        inventory.append(
            {
                "family_id": family,
                "filename": path.name,
                "sha256": sha256(path.read_bytes()).hexdigest(),
                "size_bytes": path.stat().st_size,
                "license": value["license"],
                "source": value["source"],
            }
        )
    return inventory


def _background(difficulty: str, seed: int) -> Image.Image:
    image = Image.new("RGB", CANVAS_SIZE, (245, 245, 245))
    if difficulty != "low_contrast_complex":
        return image
    draw = ImageDraw.Draw(image)
    random = Random(seed)
    for _ in range(60):
        x = random.randrange(CANVAS_SIZE[0])
        y = random.randrange(CANVAS_SIZE[1])
        width = random.randrange(20, 180)
        height = random.randrange(10, 80)
        shade = random.randrange(145, 225)
        draw.rounded_rectangle((x, y, x + width, y + height), radius=8, fill=(shade,) * 3)
    return image


def _render_region(
    image: Image.Image,
    text: str,
    font_path: Path,
    font_size: int,
    foreground: tuple[int, int, int],
    angle: float,
    position: tuple[int, int],
    rtl: bool,
) -> tuple[tuple[float, float], ...]:
    font = ImageFont.truetype(str(font_path), font_size, layout_engine=ImageFont.Layout.RAQM)
    probe = ImageDraw.Draw(Image.new("L", (1, 1)))
    direction = "rtl" if rtl else "ltr"
    left, top, right, bottom = probe.textbbox((0, 0), text, font=font, direction=direction)
    width, height = max(1, right - left), max(1, bottom - top)
    padding = 12
    layer = Image.new("RGBA", (width + padding * 2, height + padding * 2), (0, 0, 0, 0))
    ImageDraw.Draw(layer).text(
        (padding - left, padding - top),
        text,
        font=font,
        fill=foreground + (255,),
        direction=direction,
    )
    source_polygon = (
        (padding, padding),
        (padding + width, padding),
        (padding + width, padding + height),
        (padding, padding + height),
    )
    rotated = layer.rotate(angle, expand=True, resample=Image.Resampling.BICUBIC)
    image.paste(rotated, position, rotated)
    return rotate_polygon(source_polygon, layer.size, rotated.size, angle, position)


def generate_dataset(font_dir: Path, output_dir: Path) -> dict[str, Any]:
    config_dir = Path(__file__).resolve().parent
    texts, font_config = load_configuration(config_dir)
    inventory = _font_inventory(font_dir, font_config)
    if not features.check_feature("raqm"):
        raise RuntimeError("Pillow must include libraqm for complex-script shaping")
    images_dir = output_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    samples = []

    for language_index, language in enumerate(LANGUAGE_CODES):
        family = font_config["languages"][language]
        font_path = font_dir / font_config["families"][family]["filename"]
        for difficulty_index, (difficulty, style) in enumerate(DIFFICULTIES.items()):
            image = _background(difficulty, language_index * 10 + difficulty_index)
            expected_regions = []
            for row, phrase in enumerate(texts[language]):
                text = f"{phrase} {row + 1:02d}"
                angle = style["angle"] * (-1 if row % 2 else 1)
                polygon = _render_region(
                    image=image,
                    text=text,
                    font_path=font_path,
                    font_size=style["font_size"],
                    foreground=style["foreground"],
                    angle=angle,
                    position=(45 + (row % 2) * 70, 35 + row * 108),
                    rtl=language in RTL_LANGUAGES,
                )
                expected_regions.append(
                    {
                        "polygon": [list(point) for point in polygon],
                        "text": text,
                        "difficulty": difficulty,
                    }
                )
            filename = f"{language}-{difficulty}.png"
            image.save(images_dir / filename, compress_level=6)
            samples.append(
                {
                    "id": f"synthetic-{language}-{difficulty}",
                    "image": f"images/{filename}",
                    "language_code": language,
                    "script": font_config["scripts"][language],
                    "license": "synthetic image; font license recorded in font-inventory.json",
                    "expected_regions": expected_regions,
                }
            )

    manifest = {
        "dataset_kind": "synthetic-ocr-engineering-baseline",
        "adapter": "rapidocr",
        "samples": samples,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output_dir / "font-inventory.json").write_text(
        json.dumps(inventory, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {"languages": len(LANGUAGE_CODES), "samples": len(samples), "regions": len(samples) * 5}


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate the 25-language synthetic OCR dataset")
    parser.add_argument("--font-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    summary = generate_dataset(args.font_dir.resolve(), args.output.resolve())
    print(json.dumps({"status": "completed", **summary}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
