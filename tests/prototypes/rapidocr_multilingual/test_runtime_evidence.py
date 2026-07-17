from __future__ import annotations

import copy

import pytest

from prototypes.rapidocr_multilingual.verify_runtime_evidence import (
    EXPECTED_PROFILES,
    REQUIRED_MODEL_FILES,
    EvidenceError,
    verify_evidence,
)


def valid_evidence() -> dict:
    return {
        "platform": "macOS-14.8.7-arm64-arm-64bit",
        "machine": "arm64",
        "probes": {
            language: {"model_id": model_id, "region_count": 1, "status": "loaded"}
            for language, model_id in EXPECTED_PROFILES.items()
        },
        "initialization_counts": {model_id: 1 for model_id in EXPECTED_PROFILES.values()},
        "load_times_ms": {model_id: 10.0 for model_id in EXPECTED_PROFILES.values()},
        "model_files": [
            {"name": name, "size_bytes": 1024} for name in REQUIRED_MODEL_FILES
        ],
    }


def test_valid_macos_arm64_evidence_passes() -> None:
    summary = verify_evidence(valid_evidence())
    assert summary["status"] == "passed"
    assert summary["profile_count"] == 6
    assert summary["total_model_size_bytes"] == len(REQUIRED_MODEL_FILES) * 1024


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda value: value.update(machine="x86_64"), "expected arm64"),
        (
            lambda value: value["initialization_counts"].update(
                {"ppocrv5-arabic-mobile": 2}
            ),
            "initialization count",
        ),
        (lambda value: value["model_files"].pop(), "missing required model files"),
    ],
)
def test_invalid_runtime_evidence_fails(mutate, message: str) -> None:
    evidence = copy.deepcopy(valid_evidence())
    mutate(evidence)
    with pytest.raises(EvidenceError, match=message):
        verify_evidence(evidence)

