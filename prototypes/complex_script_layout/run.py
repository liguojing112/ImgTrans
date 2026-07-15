from __future__ import annotations

import argparse
import json
import platform
from pathlib import Path
from time import perf_counter
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from prototypes.complex_script_layout.contracts import load_requests
from prototypes.complex_script_layout.prepare_fonts import prepare
from prototypes.complex_script_layout.qt_backend import QtLayoutBackend
from prototypes.complex_script_layout.shaping_backend import HarfBuzzLayoutBackend


def run_cases(cases_path: Path, output_dir: Path, fonts_dir: Path | None = None) -> dict[str, object]:
    fonts_dir = fonts_dir or output_dir / "fonts"
    prepare(Path(__file__).with_name("font-sources.json"), fonts_dir)
    requests = load_requests(cases_path, fonts_dir)
    backends = (QtLayoutBackend(), HarfBuzzLayoutBackend())
    summary: dict[str, object] = {
        "schema_version": 1,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "case_count": len(requests),
        "backends": {},
        "failures": [],
    }
    for backend in backends:
        started = perf_counter()
        completed = 0
        for request in requests:
            case_dir = output_dir / backend.name / request.language_code
            try:
                result = backend.render(
                    request,
                    case_dir / f"{request.case_id}-layer.png",
                    case_dir / f"{request.case_id}-debug.png",
                )
                (case_dir / f"{request.case_id}.json").write_text(
                    json.dumps(result.to_dict(), ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                completed += 1
            except Exception as error:
                summary["failures"].append(
                    {
                        "backend": backend.name,
                        "case_id": request.case_id,
                        "error": f"{type(error).__name__}: {error}",
                    }
                )
        summary["backends"][backend.name] = {
            "completed": completed,
            "duration_ms": round((perf_counter() - started) * 1000, 2),
        }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "run-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--fonts", type=Path)
    args = parser.parse_args()
    summary = run_cases(args.cases, args.output, args.fonts)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 1 if summary["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

