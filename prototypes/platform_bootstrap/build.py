from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path


TARGETS = ("windows-x64", "macos-arm64")


def detect_current_target() -> str | None:
    system = platform.system()
    machine = platform.machine().lower()
    if system == "Windows" and machine in {"amd64", "x86_64"}:
        return "windows-x64"
    if system == "Darwin" and machine in {"arm64", "aarch64"}:
        return "macos-arm64"
    return None


def validate_native_target(target: str) -> None:
    current = detect_current_target()
    if current != target:
        raise RuntimeError(
            f"PyInstaller builds are native-only: requested {target}, current {current or 'unsupported'}"
        )


def build_command(target: str, profile: str) -> tuple[list[str], Path, Path]:
    prototype_dir = Path(__file__).resolve().parent
    spec_name = "windows.spec" if target.startswith("windows") else "macos.spec"
    spec = prototype_dir / "packaging" / spec_name
    dist_path = prototype_dir / "dist" / target
    work_path = prototype_dir / "build" / target
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--distpath",
        str(dist_path),
        "--workpath",
        str(work_path),
        str(spec),
    ]
    return command, dist_path, work_path


def write_result(target: str, profile: str, status: str, return_code: int) -> Path:
    result = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "target": target,
        "profile": profile,
        "host_target": detect_current_target(),
        "python": platform.python_version(),
        "status": status,
        "return_code": return_code,
    }
    output = Path(__file__).resolve().parent / "results" / f"{target}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the platform bootstrap prototype")
    parser.add_argument("--target", choices=TARGETS, required=True)
    parser.add_argument(
        "--profile",
        choices=("ui", "native"),
        default="ui",
        help="ui bundles Qt/Pillow/OpenCV; native also bundles installed model runtimes",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    validate_native_target(args.target)
    command, dist_path, work_path = build_command(args.target, args.profile)
    if args.dry_run:
        print(json.dumps({"target": args.target, "command": [Path(part).name for part in command]}))
        return 0

    environment = os.environ.copy()
    environment["PLATFORM_BOOTSTRAP_TARGET"] = args.target
    environment["PLATFORM_BOOTSTRAP_PROFILE"] = args.profile
    dist_path.mkdir(parents=True, exist_ok=True)
    work_path.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(command, env=environment, check=False)
    status = "succeeded" if completed.returncode == 0 else "failed"
    output = write_result(args.target, args.profile, status, completed.returncode)
    print(f"build {status}; result={output.name}")
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
