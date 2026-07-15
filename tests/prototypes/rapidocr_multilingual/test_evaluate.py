from __future__ import annotations

from pathlib import Path
import json
import subprocess
import sys

from prototypes.rapidocr_multilingual.evaluate import evaluate_results, levenshtein_distance


def _results(predicted_text: str, polygon: list[list[float]] | None = None) -> dict:
    expected_polygon = [[0, 0], [100, 0], [100, 30], [0, 30]]
    return {
        "dataset_kind": "unit-test",
        "samples": [
            {
                "sample_id": "sample-1",
                "language_code": "en",
                "status": "completed",
                "elapsed_ms": 25.0,
                "peak_rss_bytes": 1024,
                "expected_regions": [{"polygon": expected_polygon, "text": "hello"}],
                "regions": [
                    {
                        "polygon": polygon or expected_polygon,
                        "text": predicted_text,
                        "status": "ok",
                    }
                ],
            }
        ],
    }


def test_perfect_result_passes_engineering_baseline() -> None:
    metrics = evaluate_results(_results("hello"))["language_metrics"][0]
    assert metrics["detection_recall"] == 1.0
    assert metrics["character_accuracy"] == 1.0
    assert metrics["engineering_baseline"] == "passed"


def test_text_error_and_missed_box_fail_baseline() -> None:
    metrics = evaluate_results(
        _results("world", [[200, 200], [300, 200], [300, 230], [200, 230]])
    )["language_metrics"][0]
    assert metrics["detection_recall"] == 0.0
    assert metrics["character_accuracy"] == 0.0
    assert metrics["engineering_baseline"] == "failed"


def test_levenshtein_handles_unicode_characters() -> None:
    assert levenshtein_distance("مرحبا", "مرحبا") == 0
    assert levenshtein_distance("हिन्दी", "हिंदी") > 0


def test_evaluator_can_be_executed_as_a_script(tmp_path: Path) -> None:
    results_path = tmp_path / "results.json"
    results_path.write_text(json.dumps(_results("hello")), encoding="utf-8")
    completed = subprocess.run(
        [
            sys.executable,
            "prototypes/rapidocr_multilingual/evaluate.py",
            "--results",
            str(results_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    assert (tmp_path / "report.json").is_file()
