from __future__ import annotations

import argparse
import json
import os
import platform
from pathlib import Path
import subprocess
import sys


TARGETS = ("windows-x64", "macos-arm64")


def detect_current_target(
    system: str | None = None,
    machine: str | None = None,
) -> str | None:
    current_system = system or platform.system()
    current_machine = (machine or platform.machine()).lower()
    if current_system == "Windows" and current_machine in {"amd64", "x86_64"}:
        return "windows-x64"
    if current_system == "Darwin" and current_machine in {"arm64", "aarch64"}:
        return "macos-arm64"
    return None


def validate_native_target(target: str) -> None:
    current = detect_current_target()
    if current != target:
        raise RuntimeError(
            f"release builds are native-only: requested {target}, "
            f"current {current or 'unsupported'}"
        )


def build_command(target: str) -> tuple[list[str], Path, Path]:
    if target not in TARGETS:
        raise ValueError(f"unsupported release target: {target}")
    root = Path(__file__).resolve().parents[1]
    dist_path = root / "dist" / "release" / target
    work_path = root / "build" / "release" / target
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
        str(root / "packaging" / "imgtrans.spec"),
    ]
    return command, dist_path, work_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the ImgTrans desktop application")
    parser.add_argument("--target", choices=TARGETS, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    validate_native_target(args.target)
    command, dist_path, work_path = build_command(args.target)
    if args.dry_run:
        print(
            json.dumps(
                {
                    "target": args.target,
                    "dist": str(dist_path),
                    "work": str(work_path),
                    "command": command,
                }
            )
        )
        return 0

    environment = os.environ.copy()
    environment["IMGTRANS_BUILD_TARGET"] = args.target
    if args.target == "macos-arm64":
        environment["MACOSX_DEPLOYMENT_TARGET"] = "13.0"
    completed = subprocess.run(command, env=environment, check=False)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())

