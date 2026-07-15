from __future__ import annotations

import json
from pathlib import Path

from prototypes.platform_bootstrap.dependency_probe import (
    PROBE_SPECS,
    collect_report,
    main,
    write_report,
)


def test_metadata_report_has_stable_schema_and_no_workspace_path() -> None:
    report = collect_report(import_modules=False)

    assert report["schema_version"] == 1
    assert report["platform"]["system"]
    assert report["platform"]["machine"]
    assert {item["key"] for item in report["dependencies"]} == {
        spec.key for spec in PROBE_SPECS
    }
    serialized = json.dumps(report)
    assert str(Path.cwd()) not in serialized


def test_required_dependencies_load() -> None:
    report = collect_report(import_modules=True)
    failures = [
        item
        for item in report["dependencies"]
        if item["required"] and item["status"] != "loaded"
    ]
    assert failures == []


def test_missing_optional_dependency_is_reported_not_raised() -> None:
    report = collect_report(import_modules=False)
    candidates = {
        item["key"]: item for item in report["dependencies"] if not item["required"]
    }

    assert candidates
    assert all(item["status"] in {"available", "missing"} for item in candidates.values())
    assert all(item["alternative"] for item in candidates.values())


def test_report_write_is_atomic_and_utf8(tmp_path: Path) -> None:
    output = tmp_path / "report.json"
    report = collect_report(import_modules=False)

    write_report(report, output)

    assert json.loads(output.read_text(encoding="utf-8")) == report
    assert not output.with_suffix(".json.tmp").exists()


def test_cli_strict_succeeds_for_required_environment(capsys) -> None:
    exit_code = main(["--json", "--metadata-only", "--strict"])

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out)["schema_version"] == 1
