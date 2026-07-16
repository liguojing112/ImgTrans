from __future__ import annotations

from pathlib import Path
import argparse

import cv2
import numpy as np

from prototypes.lama_ecommerce.contracts import DatasetManifest, SamplePaths


def sample_specs(manifest: DatasetManifest, output_dir: Path) -> tuple[SamplePaths, ...]:
    return tuple(
        SamplePaths(
            sample_id=f"{category}-{index:02d}",
            category=category,
            input_path=output_dir / f"{category}-{index:02d}-input.png",
            reference_path=output_dir / f"{category}-{index:02d}-reference.png",
            mask_path=output_dir / f"{category}-{index:02d}-mask.png",
            protect_path=output_dir / f"{category}-{index:02d}-protect.png",
        )
        for category in manifest.categories
        for index in range(1, manifest.samples_per_category + 1)
    )


def generate_dataset(manifest: DatasetManifest, output_dir: Path) -> tuple[SamplePaths, ...]:
    output_dir.mkdir(parents=True, exist_ok=True)
    specs = sample_specs(manifest, output_dir)
    for index, spec in enumerate(specs):
        category_index = manifest.categories.index(spec.category)
        variant = index % manifest.samples_per_category
        rng = np.random.default_rng(manifest.seed + category_index * 100 + variant)
        clean, protect = _background(
            spec.category, manifest.width, manifest.height, variant, rng
        )
        input_image, mask = _add_text(clean, spec.category, variant)
        protect[mask > 0] = 0
        _write_image(spec.reference_path, clean)
        _write_image(spec.input_path, input_image)
        cv2.imwrite(str(spec.mask_path), mask)
        cv2.imwrite(str(spec.protect_path), protect)
    return specs


def _background(
    category: str,
    width: int,
    height: int,
    variant: int,
    rng: np.random.Generator,
) -> tuple[np.ndarray, np.ndarray]:
    y, x = np.mgrid[0:height, 0:width]
    protect = np.zeros((height, width), np.uint8)
    if category == "solid":
        colors = ((238, 231, 219), (210, 228, 245), (232, 218, 239), (220, 238, 221))
        rgb = np.empty((height, width, 3), np.uint8)
        rgb[:] = colors[variant % len(colors)]
    elif category == "gradient":
        ratio = (x / max(1, width - 1))[..., None]
        left = np.array((35 + variant * 8, 90, 180), np.float32)
        right = np.array((245, 175 - variant * 6, 80), np.float32)
        rgb = np.clip(left * (1 - ratio) + right * ratio, 0, 255).astype(np.uint8)
    elif category == "fabric":
        weave = 25 * np.sin(x * 0.32) + 20 * np.sin(y * 0.37)
        noise = rng.normal(0, 7, (height, width))
        base = np.clip(150 + weave + noise, 0, 255)
        rgb = np.stack((base * 0.8, base * 0.55, base * 0.42), axis=-1).astype(np.uint8)
    elif category == "wood":
        grain = 28 * np.sin(x * 0.055 + 5 * np.sin(y * 0.018))
        grain += 8 * np.sin(x * 0.3)
        base = np.clip(145 + grain + rng.normal(0, 3, (height, width)), 0, 255)
        rgb = np.stack((base * 1.15, base * 0.78, base * 0.45), axis=-1).astype(np.uint8)
    elif category == "grid":
        rgb = np.full((height, width, 3), (235, 240, 244), np.uint8)
        spacing = 24 + variant * 3
        rgb[(x % spacing) < 3] = (45, 105, 170)
        rgb[(y % spacing) < 3] = (45, 105, 170)
    elif category == "package_pattern":
        rgb = np.full((height, width, 3), (246, 218, 66), np.uint8)
        for row in range(-40, height + 40, 72):
            for col in range(-40, width + 40, 96):
                center = (col + (row // 72 % 2) * 45, row)
                cv2.circle(rgb, center, 22, (230, 60, 72), -1, cv2.LINE_AA)
                cv2.circle(rgb, center, 10, (255, 250, 220), -1, cv2.LINE_AA)
        for offset in range(-height, width, 80):
            cv2.line(rgb, (offset, 0), (offset + height, height), (40, 150, 115), 5)
    elif category == "product_edge":
        ratio = (y / max(1, height - 1))[..., None]
        top = np.array((245, 245, 247), np.float32)
        bottom = np.array((185, 205, 225), np.float32)
        rgb = np.broadcast_to(top * (1 - ratio) + bottom * ratio, (height, width, 3)).astype(
            np.uint8
        ).copy()
        x0 = 235 + variant * 4
        cv2.rectangle(rgb, (x0, 75), (455, 445), (35, 42, 52), -1, cv2.LINE_AA)
        cv2.rectangle(rgb, (x0 + 12, 90), (443, 430), (65, 110, 185), -1, cv2.LINE_AA)
        cv2.ellipse(rgb, (x0 + 110, 190), (72, 95), 0, 0, 360, (225, 235, 248), -1)
        cv2.line(rgb, (x0, 75), (x0, 445), (250, 250, 252), 4, cv2.LINE_AA)
        cv2.rectangle(protect, (x0 + 55, 110), (430, 240), 255, -1)
    else:
        raise ValueError(f"Unsupported category: {category}")

    if variant == 4:
        alpha = np.clip((x + y - 80) * 2, 0, 255).astype(np.uint8)
        return np.dstack((rgb, alpha)), protect
    return rgb, protect


def _add_text(clean: np.ndarray, category: str, variant: int) -> tuple[np.ndarray, np.ndarray]:
    height, width = clean.shape[:2]
    mask = np.zeros((height, width), np.uint8)
    text = ("SALE", "25% OFF", "NEW", "SKU-2026", "LIMITED")[variant]
    scale = (1.7, 1.45, 1.8, 1.2, 1.25)[variant]
    thickness = 4
    text_size, _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_DUPLEX, scale, thickness)
    x = max(24, (width - text_size[0]) // 2)
    if category == "product_edge":
        x = 145
    y = 270 + (variant - 2) * 12
    cv2.putText(
        mask, text, (x, y), cv2.FONT_HERSHEY_DUPLEX, scale, 255, thickness + 5, cv2.LINE_AA
    )
    result = clean.copy()
    rgb = np.ascontiguousarray(result[..., :3])
    cv2.putText(
        rgb, text, (x, y), cv2.FONT_HERSHEY_DUPLEX, scale, (12, 12, 12), thickness + 5, cv2.LINE_AA
    )
    cv2.putText(
        rgb, text, (x, y), cv2.FONT_HERSHEY_DUPLEX, scale, (250, 250, 250), thickness, cv2.LINE_AA
    )
    result[..., :3] = rgb
    return result, mask


def _write_image(path: Path, image: np.ndarray) -> None:
    conversion = cv2.COLOR_RGBA2BGRA if image.shape[2] == 4 else cv2.COLOR_RGB2BGR
    if not cv2.imwrite(str(path), cv2.cvtColor(image, conversion)):
        raise RuntimeError(f"Could not write {path}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    specs = generate_dataset(DatasetManifest.load(args.manifest), args.output)
    print(f"generated {len(specs)} samples")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
