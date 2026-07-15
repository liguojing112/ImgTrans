from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from prototypes.complex_script_layout.line_breaker import grapheme_spans


BACKENDS = ("qt-qtextlayout", "harfbuzz-python-bidi")


def compare_results(results_dir: Path) -> dict[str, object]:
    by_backend: dict[str, dict[str, dict[str, object]]] = {}
    for backend in BACKENDS:
        cases = {}
        for path in (results_dir / backend).glob("*/*.json"):
            value = json.loads(path.read_text(encoding="utf-8"))
            cases[value["request"]["case_id"]] = value
        by_backend[backend] = cases
    case_ids = sorted(set.intersection(*(set(values) for values in by_backend.values())))
    comparisons = []
    violations = []
    for case_id in case_ids:
        qt = by_backend[BACKENDS[0]][case_id]
        hb = by_backend[BACKENDS[1]][case_id]
        qt_check = _structural_check(qt)
        hb_check = _structural_check(hb)
        item = {
            "case_id": case_id,
            "language_code": qt["request"]["language_code"],
            "line_count": {BACKENDS[0]: len(qt["lines"]), BACKENDS[1]: len(hb["lines"])},
            "line_count_equal": len(qt["lines"]) == len(hb["lines"]),
            "direction_sequence_equal": [line["direction"] for line in qt["lines"]]
            == [line["direction"] for line in hb["lines"]],
            "checks": {BACKENDS[0]: qt_check, BACKENDS[1]: hb_check},
        }
        comparisons.append(item)
        for backend, check in item["checks"].items():
            if not all(check.values()):
                violations.append({"case_id": case_id, "backend": backend, "checks": check})

    expected = max((len(values) for values in by_backend.values()), default=0)
    report: dict[str, object] = {
        "schema_version": 1,
        "case_count": len(case_ids),
        "backend_case_counts": {name: len(values) for name, values in by_backend.items()},
        "missing_pairs": expected - len(case_ids),
        "line_count_match_count": sum(item["line_count_equal"] for item in comparisons),
        "direction_match_count": sum(item["direction_sequence_equal"] for item in comparisons),
        "structural_violations": violations,
        "selection": {
            "primary": "qt-qtextlayout",
            "fallback": "harfbuzz-python-bidi",
            "reason": "Qt provides mature Unicode BiDi and language-aware line breaking; the independent backend keeps shaping inspectable and supplies a non-UI fallback.",
        },
        "comparisons": comparisons,
    }
    (results_dir / "comparison.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report


def _structural_check(value: dict[str, object]) -> dict[str, bool]:
    text = value["request"]["text"]
    valid_boundaries = {0, len(text)}
    for span in grapheme_spans(text):
        valid_boundaries.update((span.start, span.end))
    lines = value["lines"]
    clusters = [cluster for line in lines for cluster in line["clusters"]]
    return {
        "no_missing_glyph": all(0 not in cluster["glyph_ids"] for cluster in clusters),
        "line_breaks_grapheme_safe": all(
            line["text_start"] in valid_boundaries and line["text_end"] in valid_boundaries
            for line in lines
        ),
        "cluster_ranges_valid": all(
            0 <= cluster["text_start"] < cluster["text_end"] <= len(text)
            for cluster in clusters
        ),
        "ink_inside_width": value["ink_bounds"][0] >= -1
        and value["ink_bounds"][0] + value["ink_bounds"][2]
        <= value["request"]["width"] + 1,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", type=Path, required=True)
    args = parser.parse_args()
    report = compare_results(args.results)
    print(json.dumps({key: value for key, value in report.items() if key != "comparisons"}, indent=2))
    return 1 if report["missing_pairs"] or report["structural_violations"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
