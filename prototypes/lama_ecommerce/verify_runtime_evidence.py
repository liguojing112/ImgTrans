from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


EXPECTED_MODEL_SHA256 = "7df918ac3921d3daf0aae1d219776cf0dc4e4935f035af81841b40adcf74fdf2"


def verify(results_path: Path, expected_machine: str) -> dict[str, object]:
    value = json.loads(results_path.read_text(encoding="utf-8"))
    machine = str(value["machine"]).lower()
    expected = expected_machine.lower()
    machine_matches = machine == expected or {machine, expected} <= {"arm64", "aarch64"}
    default_results = [
        item
        for item in value["results"]
        if item["strategy"] == "local-e2-f0"
    ]
    memory = value["memory_rounds_mb"]
    checks = {
        "machine_matches": machine_matches,
        "all_samples_present": value["sample_count"] == 35,
        "strategy_matrix_complete": len(value["results"]) == 91,
        "no_runtime_failures": not value["failures"],
        "model_hash_matches": value["model"]["sha256"] == EXPECTED_MODEL_SHA256,
        "model_loaded_once": value["model"]["inference_count"] == 59,
        "outside_pixels_preserved": all(
            item["metrics"]["outside_changed_pixels"] == 0 for item in value["results"]
        ),
        "alpha_preserved": all(item["metrics"]["alpha_preserved"] for item in value["results"]),
        "three_memory_rounds": len(memory) == 3,
        "idle_memory_not_growing": len(memory) == 3 and max(memory) - min(memory) <= 5,
        "both_default_backends_present": len(default_results) == 70,
    }
    return {
        "schema_version": 1,
        "platform": value["platform"],
        "machine": value["machine"],
        "checks": checks,
        "passed": all(checks.values()),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--expected-machine", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = verify(args.results, args.expected_machine)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

