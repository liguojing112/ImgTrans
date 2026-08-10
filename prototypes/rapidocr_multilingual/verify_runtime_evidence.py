from __future__ import annotations

from pathlib import Path
from typing import Any
import argparse
import json
import math


EXPECTED_PROFILES = {
    "zh-Hans": "ppocrv6-multilingual-small",
    "ru": "ppocrv5-cyrillic-mobile",
    "ko": "ppocrv5-korean-mobile",
    "th": "ppocrv5-thai-mobile",
    "ar": "ppocrv5-arabic-mobile",
    "hi": "ppocrv5-devanagari-mobile",
}

REQUIRED_MODEL_FILES = {
    "PP-OCRv6_det_small.onnx",
    "PP-OCRv6_rec_small.onnx",
    "ch_ppocr_mobile_v2.0_cls_mobile.onnx",
    "cyrillic_PP-OCRv5_rec_mobile.onnx",
    "korean_PP-OCRv5_rec_mobile.onnx",
    "th_PP-OCRv5_rec_mobile.onnx",
    "arabic_PP-OCRv5_rec_mobile.onnx",
    "devanagari_PP-OCRv5_rec_mobile.onnx",
}


class EvidenceError(ValueError):
    pass


def verify_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    machine = str(evidence.get("machine", "")).lower()
    platform = str(evidence.get("platform", ""))
    if machine not in {"arm64", "aarch64"}:
        errors.append(f"expected arm64 machine, got {machine or 'missing'}")
    if "macos" not in platform.lower():
        errors.append(f"expected macOS platform, got {platform or 'missing'}")

    probes = evidence.get("probes", {})
    if set(probes) != set(EXPECTED_PROFILES):
        errors.append("probe language set does not match the six required profiles")
    for language, expected_model in EXPECTED_PROFILES.items():
        probe = probes.get(language, {})
        if probe.get("status") != "loaded":
            errors.append(f"{language} profile was not loaded")
        if probe.get("model_id") != expected_model:
            errors.append(f"{language} used {probe.get('model_id')!r}, expected {expected_model!r}")
        region_count = probe.get("region_count")
        if not isinstance(region_count, int) or region_count < 0:
            errors.append(f"{language} has invalid region_count")

    initialization_counts = evidence.get("initialization_counts", {})
    expected_models = set(EXPECTED_PROFILES.values())
    if set(initialization_counts) != expected_models:
        errors.append("initialization count model set does not match required profiles")
    for model_id in expected_models:
        if initialization_counts.get(model_id) != 1:
            errors.append(f"{model_id} initialization count must equal one")

    load_times = evidence.get("load_times_ms", {})
    if set(load_times) != expected_models:
        errors.append("load-time model set does not match required profiles")
    for model_id, value in load_times.items():
        if not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            errors.append(f"{model_id} has invalid load time")

    model_files = evidence.get("model_files", [])
    file_sizes = {
        str(item.get("name")): item.get("size_bytes")
        for item in model_files
        if isinstance(item, dict)
    }
    missing_files = sorted(REQUIRED_MODEL_FILES - set(file_sizes))
    if missing_files:
        errors.append(f"missing required model files: {missing_files}")
    for name in REQUIRED_MODEL_FILES.intersection(file_sizes):
        size = file_sizes[name]
        if not isinstance(size, int) or size <= 0:
            errors.append(f"{name} has invalid size")

    if errors:
        raise EvidenceError("; ".join(errors))

    slowest_model = max(load_times, key=load_times.get)
    return {
        "status": "passed",
        "platform": platform,
        "machine": machine,
        "profile_count": len(EXPECTED_PROFILES),
        "total_model_size_bytes": sum(file_sizes[name] for name in REQUIRED_MODEL_FILES),
        "slowest_model": slowest_model,
        "slowest_load_time_ms": load_times[slowest_model],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify macOS arm64 RapidOCR runtime evidence")
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    evidence = json.loads(args.evidence.read_text(encoding="utf-8"))
    try:
        summary = verify_evidence(evidence)
    except EvidenceError as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

