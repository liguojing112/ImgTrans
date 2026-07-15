import json
from pathlib import Path

from prototypes.complex_script_layout.verify_runtime_evidence import runtime_signature


def test_runtime_signature_ignores_pixel_positions(tmp_path: Path) -> None:
    run = tmp_path / "run"
    summary = {"platform": "test", "machine": "arm64", "case_count": 1}
    comparison = {
        "backend_case_counts": {
            "qt-qtextlayout": 1,
            "harfbuzz-python-bidi": 1,
        },
        "structural_violations": [],
    }
    (run / "run-summary.json").parent.mkdir(parents=True)
    (run / "run-summary.json").write_text(json.dumps(summary), encoding="utf-8")
    (run / "comparison.json").write_text(json.dumps(comparison), encoding="utf-8")
    result = {
        "request": {"case_id": "one"},
        "lines": [
            {
                "text_start": 0,
                "text_end": 1,
                "direction": "ltr",
                "clusters": [{"text_start": 0, "text_end": 1, "positions": [[1, 2]]}],
            }
        ],
    }
    for backend in ("qt-qtextlayout", "harfbuzz-python-bidi"):
        path = run / backend / "en" / "one.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(result), encoding="utf-8")
    first, _ = runtime_signature(run)
    result["lines"][0]["clusters"][0]["positions"] = [[99, 88]]
    (run / "qt-qtextlayout/en/one.json").write_text(json.dumps(result), encoding="utf-8")
    second, _ = runtime_signature(run)
    assert first == second

