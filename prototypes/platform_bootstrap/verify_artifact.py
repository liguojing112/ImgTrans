from __future__ import annotations

import argparse
import json
import os
import struct
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable

try:
    from .build import TARGETS, detect_current_target
except ImportError:
    from build import TARGETS, detect_current_target


APP_NAMES = {
    "windows-x64": "PlatformBootstrap-windows-x64",
    "macos-arm64": "PlatformBootstrap-macos-arm64",
}


def default_artifact(target: str) -> Path:
    base = Path(__file__).resolve().parent / "dist" / target
    name = APP_NAMES[target]
    if target.startswith("windows"):
        return base / name
    return base / f"{name}.app"


def executable_for(artifact: Path, target: str) -> Path:
    name = APP_NAMES[target]
    if target.startswith("windows"):
        return artifact / f"{name}.exe"
    return artifact / "Contents" / "MacOS" / name


def pe_machine(executable: Path) -> str:
    with executable.open("rb") as stream:
        if stream.read(2) != b"MZ":
            raise ValueError("not a PE executable")
        stream.seek(0x3C)
        pe_offset = struct.unpack("<I", stream.read(4))[0]
        stream.seek(pe_offset)
        if stream.read(4) != b"PE\0\0":
            raise ValueError("invalid PE signature")
        machine = struct.unpack("<H", stream.read(2))[0]
    return {0x8664: "x86_64", 0x014C: "x86"}.get(machine, hex(machine))


def macho_architectures(executable: Path) -> list[str]:
    completed = subprocess.run(
        ["lipo", "-archs", str(executable)],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "lipo failed")
    return completed.stdout.strip().split()


def find_imageformat_plugins(artifact: Path) -> list[str]:
    plugins: list[str] = []
    for directory in artifact.rglob("imageformats"):
        if directory.is_dir():
            plugins.extend(path.name for path in directory.iterdir() if path.is_file())
    return sorted(set(plugins))


def _needle_variants(value: str) -> Iterable[bytes]:
    variants = {value, value.replace("\\", "/")}
    for item in variants:
        yield item.encode("utf-8", errors="ignore")
        yield item.encode("utf-16-le", errors="ignore")


def scan_artifact(artifact: Path, forbidden_paths: list[str]) -> list[str]:
    path_needles = [needle for value in forbidden_paths for needle in _needle_variants(value)]
    secret_needles = (
        b"subscription-key",
        b"api_key=",
        b"api-key=",
        b"cognitive.microsofttranslator.com",
    )
    findings: list[str] = []
    for path in artifact.rglob("*"):
        if not path.is_file():
            continue
        try:
            data = path.read_bytes()
        except OSError as exc:
            findings.append(f"unreadable:{path.name}:{type(exc).__name__}")
            continue
        lowered = data.lower()
        if any(needle and needle in data for needle in path_needles):
            findings.append(f"workspace-path:{path.name}")
        if any(needle in lowered for needle in secret_needles):
            findings.append(f"secret-pattern:{path.name}")
    return findings


def smoke_test(executable: Path) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="platform-bootstrap-") as temporary:
        report_path = Path(temporary) / "smoke.json"
        environment = os.environ.copy()
        environment.setdefault("QT_QPA_PLATFORM", "offscreen")
        completed = subprocess.run(
            [str(executable), "--smoke-test", "--report", str(report_path)],
            capture_output=True,
            text=True,
            timeout=30,
            env=environment,
            check=False,
        )
        report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else None
        return {
            "return_code": completed.returncode,
            "report": report,
            "stderr": completed.stderr[-500:],
        }


def verify(target: str, artifact: Path, *, run_smoke: bool) -> tuple[dict[str, object], bool]:
    executable = executable_for(artifact, target)
    result: dict[str, object] = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "target": target,
        "artifact_name": artifact.name,
        "artifact_exists": artifact.exists(),
        "executable_exists": executable.exists(),
    }
    if not artifact.exists() or not executable.exists():
        return result, False

    if target == "windows-x64":
        result["architectures"] = [pe_machine(executable)]
    else:
        result["architectures"] = macho_architectures(executable)
    expected_arch = "x86_64" if target == "windows-x64" else "arm64"
    result["architecture_ok"] = expected_arch in result["architectures"]

    plugins = find_imageformat_plugins(artifact)
    result["imageformat_plugins"] = plugins
    result["imageformat_plugins_ok"] = any(
        name.lower().startswith(("qjpeg", "qwebp")) for name in plugins
    )

    workspace = str(Path(__file__).resolve().parents[2])
    findings = scan_artifact(artifact, [workspace])
    result["scan_findings"] = findings
    result["scan_ok"] = not findings

    if run_smoke:
        result["smoke_test"] = smoke_test(executable)
        smoke_result = result["smoke_test"]
        smoke_report = smoke_result.get("report") if isinstance(smoke_result, dict) else None
        required_failures = []
        if isinstance(smoke_report, dict):
            required_failures = [
                item["key"]
                for item in smoke_report.get("dependencies", [])
                if item.get("required") and item.get("status") != "loaded"
            ]
        result["runtime_dependency_failures"] = required_failures
        result["smoke_ok"] = (
            isinstance(smoke_result, dict)
            and smoke_result["return_code"] == 0
            and not required_failures
        )
    else:
        result["smoke_test"] = "skipped"
        result["smoke_ok"] = True

    ok = all(
        bool(result[key])
        for key in ("architecture_ok", "imageformat_plugins_ok", "scan_ok", "smoke_ok")
    )
    return result, ok


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify a platform bootstrap artifact")
    parser.add_argument("--target", choices=TARGETS, required=True)
    parser.add_argument("--artifact", type=Path)
    parser.add_argument("--skip-run", action="store_true")
    args = parser.parse_args(argv)

    artifact = args.artifact or default_artifact(args.target)
    can_run = detect_current_target() == args.target and not args.skip_run
    result, ok = verify(args.target, artifact, run_smoke=can_run)
    output = Path(__file__).resolve().parent / "results" / f"{args.target}-verification.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "passed" if ok else "failed", "result": output.name}))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
