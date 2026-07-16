from __future__ import annotations

import argparse
import json
from math import log10
from pathlib import Path
from statistics import mean, median

import cv2
import numpy as np


def quality_metrics(
    output: np.ndarray,
    reference: np.ndarray,
    original: np.ndarray,
    metric_mask: np.ndarray,
    allowed_mask: np.ndarray,
) -> dict[str, float | int | bool]:
    output_rgb = output[..., :3].astype(np.float32)
    reference_rgb = reference[..., :3].astype(np.float32)
    original_rgb = original[..., :3]
    selected = metric_mask.astype(bool)
    if not np.any(selected):
        raise ValueError("Metric mask cannot be empty")
    error = output_rgb[selected] - reference_rgb[selected]
    mse = float(np.mean(error * error))
    psnr = 100.0 if mse == 0 else 20 * log10(255.0 / np.sqrt(mse))
    crop = _masked_crop(metric_mask, padding=24)
    x0, y0, x1, y1 = crop
    output_crop = output_rgb[y0:y1, x0:x1]
    reference_crop = reference_rgb[y0:y1, x0:x1]
    outside = ~allowed_mask.astype(bool)
    outside_difference = np.abs(output_rgb - original_rgb.astype(np.float32))
    alpha_preserved = True
    if output.shape[2] == 4:
        alpha_preserved = bool(np.array_equal(output[..., 3], original[..., 3]))
    return {
        "psnr_db": round(psnr, 4),
        "ssim": round(_ssim(output_crop, reference_crop), 6),
        "gmsd": round(_gmsd(output_crop, reference_crop), 6),
        "masked_mae": round(float(np.mean(np.abs(error))), 4),
        "outside_changed_pixels": int(np.count_nonzero(np.any(outside_difference > 0, axis=2) & outside)),
        "outside_max_delta": int(np.max(outside_difference[outside])) if np.any(outside) else 0,
        "alpha_preserved": alpha_preserved,
    }


def aggregate_results(value: dict[str, object]) -> dict[str, object]:
    groups: dict[tuple[str, str], list[dict[str, object]]] = {}
    for item in value["results"]:
        groups.setdefault((item["backend"], item["strategy"]), []).append(item)
    summaries = []
    for (backend, strategy), items in sorted(groups.items()):
        summaries.append(
            {
                "backend": backend,
                "strategy": strategy,
                "count": len(items),
                "mean_psnr_db": round(mean(item["metrics"]["psnr_db"] for item in items), 4),
                "mean_ssim": round(mean(item["metrics"]["ssim"] for item in items), 6),
                "mean_gmsd": round(mean(item["metrics"]["gmsd"] for item in items), 6),
                "mean_inference_ms": round(mean(item["inference_ms"] for item in items), 2),
                "median_inference_ms": round(median(item["inference_ms"] for item in items), 2),
                "p95_inference_ms": round(
                    _percentile([item["inference_ms"] for item in items], 0.95), 2
                ),
                "max_inference_ms": round(max(item["inference_ms"] for item in items), 2),
                "max_peak_rss_mb": round(max(item["peak_rss_bytes"] for item in items) / 1024 / 1024, 2),
                "outside_changed_pixels": sum(
                    item["metrics"]["outside_changed_pixels"] for item in items
                ),
            }
        )
    risk_cases = []
    for item in value["results"]:
        if item["backend"] != "lama-onnxruntime" or item["strategy"] != "local-e2-f0":
            continue
        flags = []
        if item["metrics"]["ssim"] < 0.95:
            flags.append("low_local_ssim")
        if item["metrics"]["masked_mae"] > 10:
            flags.append("visible_residual_risk")
        if item["metrics"]["gmsd"] > 0.2:
            flags.append("texture_distortion_risk")
        if flags:
            risk_cases.append(
                {
                    "sample_id": item["sample_id"],
                    "category": item["category"],
                    "flags": flags,
                    "metrics": item["metrics"],
                    "output": item["output"],
                }
            )
    return {
        "schema_version": 1,
        "sample_count": value["sample_count"],
        "result_count": len(value["results"]),
        "failures": value["failures"],
        "model": value["model"],
        "memory_rounds_mb": value["memory_rounds_mb"],
        "summaries": summaries,
        "automatic_risk_cases": risk_cases,
        "recommendation": {
            "default": "lama-onnxruntime/local-e2-f0 with editable mask",
            "simple_background_fallback": "opencv-telea/local-e2-f0",
            "guarantee": "No automatic backend can guarantee artifact-free reconstruction on every product edge or complex texture.",
        },
    }


def _percentile(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * quantile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def _masked_crop(mask: np.ndarray, padding: int) -> tuple[int, int, int, int]:
    ys, xs = np.where(mask > 0)
    return (
        max(0, int(xs.min()) - padding),
        max(0, int(ys.min()) - padding),
        min(mask.shape[1], int(xs.max()) + 1 + padding),
        min(mask.shape[0], int(ys.max()) + 1 + padding),
    )


def _ssim(left: np.ndarray, right: np.ndarray) -> float:
    left_gray = cv2.cvtColor(left, cv2.COLOR_RGB2GRAY)
    right_gray = cv2.cvtColor(right, cv2.COLOR_RGB2GRAY)
    c1 = 6.5025
    c2 = 58.5225
    mu_left = cv2.GaussianBlur(left_gray, (11, 11), 1.5)
    mu_right = cv2.GaussianBlur(right_gray, (11, 11), 1.5)
    sigma_left = cv2.GaussianBlur(left_gray * left_gray, (11, 11), 1.5) - mu_left**2
    sigma_right = cv2.GaussianBlur(right_gray * right_gray, (11, 11), 1.5) - mu_right**2
    sigma_cross = cv2.GaussianBlur(left_gray * right_gray, (11, 11), 1.5) - mu_left * mu_right
    score = ((2 * mu_left * mu_right + c1) * (2 * sigma_cross + c2)) / (
        (mu_left**2 + mu_right**2 + c1) * (sigma_left + sigma_right + c2)
    )
    return float(np.mean(score))


def _gmsd(left: np.ndarray, right: np.ndarray) -> float:
    left_gray = cv2.cvtColor(left, cv2.COLOR_RGB2GRAY)
    right_gray = cv2.cvtColor(right, cv2.COLOR_RGB2GRAY)
    left_gradient = np.hypot(cv2.Sobel(left_gray, cv2.CV_32F, 1, 0), cv2.Sobel(left_gray, cv2.CV_32F, 0, 1))
    right_gradient = np.hypot(cv2.Sobel(right_gray, cv2.CV_32F, 1, 0), cv2.Sobel(right_gray, cv2.CV_32F, 0, 1))
    similarity = (2 * left_gradient * right_gradient + 170) / (
        left_gradient**2 + right_gradient**2 + 170
    )
    return float(np.std(similarity))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    value = json.loads(args.results.read_text(encoding="utf-8"))
    report = aggregate_results(value)
    output = args.output or args.results.with_name("evaluation.json")
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if report["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
