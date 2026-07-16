import json
from pathlib import Path

from prototypes.lama_ecommerce.verify_runtime_evidence import (
    EXPECTED_MODEL_SHA256,
    verify,
)


def test_verifier_accepts_complete_arm64_evidence(tmp_path: Path) -> None:
    default = {
        "strategy": "local-e2-f0",
        "metrics": {"outside_changed_pixels": 0, "alpha_preserved": True},
    }
    variant = {
        "strategy": "full-e2-f0",
        "metrics": {"outside_changed_pixels": 0, "alpha_preserved": True},
    }
    value = {
        "platform": "macOS-test",
        "machine": "arm64",
        "sample_count": 35,
        "results": [dict(default) for _ in range(70)]
        + [dict(variant) for _ in range(21)],
        "failures": [],
        "model": {"sha256": EXPECTED_MODEL_SHA256, "inference_count": 59},
        "memory_rounds_mb": [700.0, 700.1, 700.0],
    }
    path = tmp_path / "results.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    report = verify(path, "arm64")
    assert report["passed"]

