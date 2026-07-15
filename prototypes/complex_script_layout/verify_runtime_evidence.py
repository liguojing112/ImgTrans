from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


BACKENDS = ("qt-qtextlayout", "harfbuzz-python-bidi")


def runtime_signature(run_dir: Path) -> tuple[str, dict[str, object]]:
    summary = json.loads((run_dir / "run-summary.json").read_text(encoding="utf-8"))
    comparison = json.loads((run_dir / "comparison.json").read_text(encoding="utf-8"))
    canonical: dict[str, object] = {}
    for backend in BACKENDS:
        cases = {}
        for path in sorted((run_dir / backend).glob("*/*.json")):
            value = json.loads(path.read_text(encoding="utf-8"))
            cases[value["request"]["case_id"]] = {
                "lines": [
                    {
                        "range": [line["text_start"], line["text_end"]],
                        "direction": line["direction"],
                        "clusters": [
                            [cluster["text_start"], cluster["text_end"]]
                            for cluster in line["clusters"]
                        ],
                    }
                    for line in value["lines"]
                ]
            }
        canonical[backend] = cases
    serialized = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    signature = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    evidence = {
        "platform": summary["platform"],
        "machine": summary["machine"],
        "case_count": summary["case_count"],
        "backend_case_counts": comparison["backend_case_counts"],
        "structural_violation_count": len(comparison["structural_violations"]),
        "layout_signature_sha256": signature,
    }
    return signature, evidence


def verify_run(
    candidate: Path,
    expected_machine: str,
    reference: Path | None = None,
) -> dict[str, object]:
    signature, candidate_evidence = runtime_signature(candidate)
    machine = str(candidate_evidence["machine"]).lower()
    expected = expected_machine.lower()
    machine_ok = machine == expected or {machine, expected} <= {"arm64", "aarch64"}
    checks = {
        "machine_matches": machine_ok,
        "all_120_cases_present": candidate_evidence["case_count"] == 120
        and set(candidate_evidence["backend_case_counts"].values()) == {120},
        "no_structural_violations": candidate_evidence["structural_violation_count"] == 0,
    }
    report: dict[str, object] = {
        "schema_version": 1,
        "candidate": candidate_evidence,
        "checks": checks,
        "passed": all(checks.values()),
    }
    if reference:
        reference_signature, reference_evidence = runtime_signature(reference)
        cross_check = signature == reference_signature
        report["reference"] = reference_evidence
        report["checks"]["layout_signature_matches_reference"] = cross_check
        report["passed"] = bool(report["passed"] and cross_check)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--expected-machine", required=True)
    parser.add_argument("--reference", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = verify_run(args.candidate, args.expected_machine, args.reference)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

