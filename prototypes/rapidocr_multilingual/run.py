from __future__ import annotations

from pathlib import Path
from time import perf_counter
from typing import Any
import argparse
import json
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from prototypes.rapidocr_multilingual.adapter import FixtureAdapter, RapidOCRAdapter
from prototypes.rapidocr_multilingual.contracts import Manifest
from prototypes.rapidocr_multilingual.model_router import ModelRouter
from prototypes.rapidocr_multilingual.visualize import save_visualization


def _rss_bytes() -> int:
    try:
        import psutil

        return psutil.Process().memory_info().rss
    except ImportError:
        return 0


def run_manifest(manifest_path: Path, output_dir: Path, adapter_name: str = "auto") -> dict[str, Any]:
    manifest = Manifest.load(manifest_path)
    config_path = Path(__file__).with_name("model-config.json")
    router = ModelRouter(config_path)
    selected_adapter = manifest.adapter if adapter_name == "auto" else adapter_name
    if selected_adapter not in {"rapidocr", "fixture"}:
        raise ValueError(f"Unknown adapter: {selected_adapter}")
    adapter: Any = FixtureAdapter() if selected_adapter == "fixture" else RapidOCRAdapter()
    output_dir.mkdir(parents=True, exist_ok=True)

    sample_results = []
    for sample in manifest.samples:
        route = router.route(sample.language_code)
        result: dict[str, Any] = {
            "sample_id": sample.sample_id,
            "language_code": sample.language_code,
            "model_id": route.model_id,
            "expected_regions": [region.to_dict() for region in sample.expected_regions],
            "regions": [],
            "elapsed_ms": None,
            "peak_rss_bytes": _rss_bytes(),
            "status": "unsupported_language" if not route.supported else "pending",
            "error": route.reason,
        }
        if route.supported:
            started = perf_counter()
            try:
                if selected_adapter == "fixture":
                    regions = adapter.recognize(sample, route)
                else:
                    if sample.image is None:
                        raise ValueError("RapidOCR samples must include an image path")
                    image_path = (manifest_path.parent / sample.image).resolve()
                    regions = adapter.recognize(image_path, route)
                result["regions"] = [region.to_dict() for region in regions]
                result["status"] = "completed"
                result["error"] = None
            except Exception as exc:
                result["status"] = "failed"
                result["error"] = str(exc)
            result["elapsed_ms"] = (perf_counter() - started) * 1000
            result["peak_rss_bytes"] = max(result["peak_rss_bytes"], _rss_bytes())

        if sample.image:
            image_path = (manifest_path.parent / sample.image).resolve()
            if image_path.is_file() and result["regions"]:
                save_visualization(
                    image_path,
                    result,
                    output_dir / "visualizations" / f"{sample.sample_id}.png",
                )
        sample_results.append(result)

    models = [
        {
            "model_id": model_id,
            "initialization_count": adapter.initialization_counts[model_id],
            "load_time_ms": adapter.load_times_ms.get(model_id),
        }
        for model_id in sorted(adapter.initialization_counts)
    ]
    results = {
        "schema_version": 1,
        "dataset_kind": manifest.dataset_kind,
        "adapter": selected_adapter,
        "router_version": router.version,
        "coverage": router.coverage_matrix(),
        "models": models,
        "samples": sample_results,
    }
    results_path = output_dir / "results.json"
    results_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the RapidOCR multilingual validation prototype")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--adapter", choices=("auto", "rapidocr", "fixture"), default="auto")
    args = parser.parse_args()
    results = run_manifest(args.manifest.resolve(), args.output.resolve(), args.adapter)
    failures = sum(sample["status"] == "failed" for sample in results["samples"])
    print(
        json.dumps(
            {
                "status": "completed" if failures == 0 else "completed_with_failures",
                "samples": len(results["samples"]),
                "failures": failures,
                "results": str(args.output.resolve() / "results.json"),
            },
            ensure_ascii=False,
        )
    )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

