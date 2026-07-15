from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any
import argparse
import json
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from prototypes.rapidocr_multilingual.contracts import normalize_text


def bbox_iou(first: list[list[float]], second: list[list[float]]) -> float:
    first_x = [point[0] for point in first]
    first_y = [point[1] for point in first]
    second_x = [point[0] for point in second]
    second_y = [point[1] for point in second]
    left = max(min(first_x), min(second_x))
    top = max(min(first_y), min(second_y))
    right = min(max(first_x), max(second_x))
    bottom = min(max(first_y), max(second_y))
    intersection = max(0.0, right - left) * max(0.0, bottom - top)
    first_area = (max(first_x) - min(first_x)) * (max(first_y) - min(first_y))
    second_area = (max(second_x) - min(second_x)) * (max(second_y) - min(second_y))
    union = first_area + second_area - intersection
    return intersection / union if union else 0.0


def levenshtein_distance(first: str, second: str) -> int:
    if len(first) < len(second):
        first, second = second, first
    previous = list(range(len(second) + 1))
    for first_index, first_character in enumerate(first, 1):
        current = [first_index]
        for second_index, second_character in enumerate(second, 1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[second_index] + 1,
                    previous[second_index - 1] + (first_character != second_character),
                )
            )
        previous = current
    return previous[-1]


def evaluate_results(results: dict[str, Any], iou_threshold: float = 0.5) -> dict[str, Any]:
    metrics: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "samples": 0,
            "expected_regions": 0,
            "matched_regions": 0,
            "character_total": 0,
            "character_errors": 0,
            "elapsed_ms": [],
            "peak_rss_bytes": 0,
            "failed_samples": [],
        }
    )
    for sample in results.get("samples", []):
        language = sample["language_code"]
        bucket = metrics[language]
        bucket["samples"] += 1
        bucket["peak_rss_bytes"] = max(bucket["peak_rss_bytes"], sample.get("peak_rss_bytes", 0))
        if sample.get("elapsed_ms") is not None:
            bucket["elapsed_ms"].append(sample["elapsed_ms"])
        expected = sample.get("expected_regions", [])
        predicted = sample.get("regions", [])
        bucket["expected_regions"] += len(expected)
        unused = set(range(len(predicted)))
        for expected_region in expected:
            candidates = [
                (bbox_iou(expected_region["polygon"], predicted[index]["polygon"]), index)
                for index in unused
            ]
            overlap, match_index = max(candidates, default=(0.0, -1))
            expected_text = normalize_text(expected_region["text"])
            bucket["character_total"] += max(1, len(expected_text))
            if overlap >= iou_threshold:
                unused.remove(match_index)
                bucket["matched_regions"] += 1
                predicted_text = normalize_text(predicted[match_index]["text"])
                bucket["character_errors"] += levenshtein_distance(expected_text, predicted_text)
            else:
                bucket["character_errors"] += max(1, len(expected_text))
        if sample.get("status") not in {"completed", "unsupported_language"}:
            bucket["failed_samples"].append(sample["sample_id"])

    language_metrics = []
    for language, bucket in sorted(metrics.items()):
        expected_count = bucket["expected_regions"]
        character_total = bucket["character_total"]
        recall = bucket["matched_regions"] / expected_count if expected_count else None
        accuracy = (
            max(0.0, 1 - bucket["character_errors"] / character_total)
            if character_total
            else None
        )
        elapsed = bucket.pop("elapsed_ms")
        language_metrics.append(
            {
                **bucket,
                "language_code": language,
                "detection_recall": recall,
                "character_accuracy": accuracy,
                "average_elapsed_ms": sum(elapsed) / len(elapsed) if elapsed else None,
                "engineering_baseline": (
                    "passed"
                    if recall is not None and accuracy is not None and recall >= 0.9 and accuracy >= 0.9
                    else "failed"
                    if expected_count
                    else "not_evaluated"
                ),
            }
        )
    return {
        "schema_version": 1,
        "dataset_kind": results.get("dataset_kind", "unknown"),
        "language_metrics": language_metrics,
        "coverage": results.get("coverage", []),
        "models": results.get("models", []),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate RapidOCR prototype results")
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    results = json.loads(args.results.read_text(encoding="utf-8"))
    report = evaluate_results(results)
    output = args.output or args.results.with_name("report.json")
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": "completed", "report": str(output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
