from __future__ import annotations

import argparse
import csv
import json
import platform
from pathlib import Path
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import cv2
import numpy as np
import psutil

from prototypes.lama_ecommerce.contracts import DatasetManifest, RepairRequest, SamplePaths
from prototypes.lama_ecommerce.evaluate import quality_metrics
from prototypes.lama_ecommerce.generate_dataset import generate_dataset
from prototypes.lama_ecommerce.lama_adapter import LaMaOnnxAdapter
from prototypes.lama_ecommerce.mask_variants import make_mask_variant
from prototypes.lama_ecommerce.opencv_baseline import OpenCVInpaintAdapter
from prototypes.lama_ecommerce.prepare_model import file_sha256, prepare_model


def run_benchmark(
    manifest_path: Path,
    output_dir: Path,
    model_path: Path | None = None,
    samples_per_category: int | None = None,
    variants: bool = True,
    memory_rounds: int = 3,
) -> dict[str, object]:
    manifest = DatasetManifest.load(manifest_path)
    samples = generate_dataset(manifest, output_dir / "dataset")
    if samples_per_category is not None:
        selected = []
        counts: dict[str, int] = {}
        for sample in samples:
            if counts.get(sample.category, 0) < samples_per_category:
                selected.append(sample)
                counts[sample.category] = counts.get(sample.category, 0) + 1
        samples = tuple(selected)
    if model_path is None:
        model_path = prepare_model(Path(__file__).with_name("model-source.json"), output_dir / "models")

    lama = LaMaOnnxAdapter(model_path)
    opencv = OpenCVInpaintAdapter()
    results: list[dict[str, object]] = []
    failures: list[dict[str, str]] = []
    seen_categories: set[str] = set()
    for sample_index, sample in enumerate(samples, start=1):
        image = _read_image(sample.input_path)
        reference = _read_image(sample.reference_path)
        mask = cv2.imread(str(sample.mask_path), cv2.IMREAD_GRAYSCALE)
        protect = cv2.imread(str(sample.protect_path), cv2.IMREAD_GRAYSCALE)
        strategies = [(opencv, "local", 2, 0), (lama, "local", 2, 0)]
        if variants and sample.category not in seen_categories:
            strategies.extend(
                [
                    (lama, "full", 2, 0),
                    (lama, "local", 0, 0),
                    (lama, "local", 5, 2),
                ]
            )
        seen_categories.add(sample.category)
        for adapter, mode, expand, feather in strategies:
            request = RepairRequest(
                image=image,
                mask=mask,
                protect_mask=protect,
                mode=mode,
                expand_px=expand,
                feather_px=feather,
                context_px=96,
            )
            try:
                result = adapter.inpaint(request)
                variant = make_mask_variant(mask, protect, expand, feather)
                metrics = quality_metrics(
                    result.image, reference, image, mask > 0, variant.allowed_mask
                )
                stem = f"{sample.sample_id}-{result.backend}-{result.strategy}"
                render_dir = output_dir / "renders" / sample.category
                render_dir.mkdir(parents=True, exist_ok=True)
                output_path = render_dir / f"{stem}.png"
                difference_path = render_dir / f"{stem}-difference.png"
                _write_image(output_path, result.image)
                difference = np.clip(
                    np.abs(result.image[..., :3].astype(np.int16) - reference[..., :3]) * 4,
                    0,
                    255,
                ).astype(np.uint8)
                _write_image(difference_path, difference)
                results.append(
                    {
                        "sample_id": sample.sample_id,
                        "category": sample.category,
                        "backend": result.backend,
                        "strategy": result.strategy,
                        "inference_ms": round(result.inference_ms, 2),
                        "peak_rss_bytes": result.peak_rss_bytes,
                        "crop": result.crop,
                        "metrics": metrics,
                        "output": str(output_path.relative_to(output_dir)),
                        "difference": str(difference_path.relative_to(output_dir)),
                    }
                )
                print(
                    f"[{sample_index}/{len(samples)}] {sample.sample_id} "
                    f"{result.backend}/{result.strategy}: {result.inference_ms:.0f} ms",
                    flush=True,
                )
            except Exception as error:
                failures.append(
                    {
                        "sample_id": sample.sample_id,
                        "backend": adapter.name,
                        "strategy": f"{mode}-e{expand}-f{feather}",
                        "error": f"{type(error).__name__}: {error}",
                    }
                )

    memory_values = []
    if samples and memory_rounds:
        sample = samples[0]
        image = _read_image(sample.input_path)
        mask = cv2.imread(str(sample.mask_path), cv2.IMREAD_GRAYSCALE)
        protect = cv2.imread(str(sample.protect_path), cv2.IMREAD_GRAYSCALE)
        request = RepairRequest(image, mask, protect, "local", 2, 0, 96)
        process = psutil.Process()
        for _ in range(memory_rounds):
            lama.inpaint(request)
            memory_values.append(round(process.memory_info().rss / 1024 / 1024, 2))

    source = json.loads(Path(__file__).with_name("model-source.json").read_text(encoding="utf-8"))
    report: dict[str, object] = {
        "schema_version": 1,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "sample_count": len(samples),
        "results": results,
        "failures": failures,
        "model": {
            "file": model_path.name,
            "size": model_path.stat().st_size,
            "sha256": file_sha256(model_path),
            "expected_sha256": source["sha256"],
            "license": source["license"],
            "load_ms": round(lama.load_ms, 2),
            "warmup_ms": round(lama.warmup_ms, 2),
            "inference_count": lama.inference_count,
        },
        "memory_rounds_mb": memory_values,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "results.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    _write_review_sheet(output_dir / "review-sheet.csv", results)
    return report


def _read_image(path: Path) -> np.ndarray:
    image = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if image is None:
        raise FileNotFoundError(path)
    conversion = cv2.COLOR_BGRA2RGBA if image.shape[2] == 4 else cv2.COLOR_BGR2RGB
    return cv2.cvtColor(image, conversion)


def _write_image(path: Path, image: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conversion = cv2.COLOR_RGBA2BGRA if image.shape[2] == 4 else cv2.COLOR_RGB2BGR
    if not cv2.imwrite(str(path), cv2.cvtColor(image, conversion)):
        raise RuntimeError(f"Could not save {path}")


def _write_review_sheet(path: Path, results: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(
            [
                "sample_id",
                "category",
                "backend",
                "strategy",
                "text_residual_1_to_5",
                "blur_1_to_5",
                "texture_distortion_1_to_5",
                "subject_deformation_1_to_5",
                "notes",
            ]
        )
        for item in results:
            if item["backend"] == "lama-onnxruntime" and item["strategy"] == "local-e2-f0":
                writer.writerow(
                    [item["sample_id"], item["category"], item["backend"], item["strategy"]]
                )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", type=Path)
    parser.add_argument("--samples-per-category", type=int)
    parser.add_argument("--no-variants", action="store_true")
    parser.add_argument("--memory-rounds", type=int, default=3)
    args = parser.parse_args()
    report = run_benchmark(
        args.manifest,
        args.output,
        args.model,
        args.samples_per_category,
        not args.no_variants,
        args.memory_rounds,
    )
    print(
        json.dumps(
            {
                "platform": report["platform"],
                "sample_count": report["sample_count"],
                "result_count": len(report["results"]),
                "failure_count": len(report["failures"]),
                "model": report["model"],
                "memory_rounds_mb": report["memory_rounds_mb"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 1 if report["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
