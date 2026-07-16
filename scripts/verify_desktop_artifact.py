from __future__ import annotations

import argparse
from collections.abc import Iterable
import os
from pathlib import Path
import struct
import subprocess

from scripts.build_desktop import TARGETS, detect_current_target


REQUIRED_IMAGE_PLUGINS = frozenset({"qgif", "qjpeg", "qtiff", "qwebp"})


def default_artifact(target: str) -> Path:
    root = Path(__file__).resolve().parents[1]
    base = root / "dist" / "release" / target
    return base / ("ImgTrans" if target == "windows-x64" else "ImgTrans.app")


def executable_for(artifact: Path, target: str) -> Path:
    if target == "windows-x64":
        return artifact / "ImgTrans.exe"
    return artifact / "Contents" / "MacOS" / "ImgTrans"


def pe_architecture(path: Path) -> str:
    with path.open("rb") as stream:
        if stream.read(2) != b"MZ":
            raise ValueError("not a PE binary")
        stream.seek(0x3C)
        offset_data = stream.read(4)
        if len(offset_data) != 4:
            raise ValueError("truncated PE binary")
        stream.seek(struct.unpack("<I", offset_data)[0])
        if stream.read(4) != b"PE\0\0":
            raise ValueError("invalid PE signature")
        machine_data = stream.read(2)
        if len(machine_data) != 2:
            raise ValueError("truncated PE machine header")
    machine = struct.unpack("<H", machine_data)[0]
    return {0x8664: "x86_64", 0x014C: "x86", 0xAA64: "arm64"}.get(
        machine, f"unknown-{machine:#x}"
    )


def macho_architecture(path: Path) -> str:
    with path.open("rb") as stream:
        header = stream.read(8)
    if len(header) < 8:
        raise ValueError("truncated Mach-O binary")
    magic = header[:4]
    if magic in {b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca"}:
        return "universal"
    if magic == b"\xcf\xfa\xed\xfe":
        cpu_type = struct.unpack("<I", header[4:8])[0]
    elif magic == b"\xfe\xed\xfa\xcf":
        cpu_type = struct.unpack(">I", header[4:8])[0]
    else:
        raise ValueError("not a 64-bit Mach-O binary")
    return {
        0x0100000C: "arm64",
        0x01000007: "x86_64",
    }.get(cpu_type, f"unknown-{cpu_type:#x}")


def native_binary_architectures(
    artifact: Path,
    target: str,
) -> tuple[tuple[str, str], ...]:
    results: list[tuple[str, str]] = []
    for path in artifact.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(artifact).as_posix()
        try:
            with path.open("rb") as stream:
                magic = stream.read(4)
            if target == "windows-x64" and magic[:2] == b"MZ":
                results.append((relative, pe_architecture(path)))
            elif target == "macos-arm64" and magic in {
                b"\xcf\xfa\xed\xfe",
                b"\xfe\xed\xfa\xcf",
                b"\xca\xfe\xba\xbe",
                b"\xbe\xba\xfe\xca",
            }:
                results.append((relative, macho_architecture(path)))
        except OSError as error:
            raise RuntimeError(f"cannot inspect native binary: {relative}") from error
    return tuple(results)


def imageformat_plugins(artifact: Path) -> frozenset[str]:
    names: set[str] = set()
    for directory in artifact.rglob("imageformats"):
        if not directory.is_dir():
            continue
        for path in directory.iterdir():
            if path.is_file():
                name = path.name.lower()
                if name.startswith("lib"):
                    name = name[3:]
                for suffix in (".dll", ".dylib", ".so"):
                    if name.endswith(suffix):
                        name = name[: -len(suffix)]
                        break
                names.add(name)
    return frozenset(names)


def runtime_assets(artifact: Path) -> dict[str, bool]:
    files = tuple(path for path in artifact.rglob("*") if path.is_file())
    normalized = tuple(path.relative_to(artifact).as_posix().lower() for path in files)
    return {
        "rapidocr_config": any(name.endswith("rapidocr/config.yaml") for name in normalized)
        and any(name.endswith("rapidocr/default_models.yaml") for name in normalized),
        "model_weights_excluded": not any(name.endswith(".onnx") for name in normalized),
        "onnxruntime_native": any("onnxruntime_pybind11_state" in name for name in normalized),
        "opencv_native": any(
            name.endswith(("cv2.pyd", "cv2.abi3.so")) or "/cv2." in name
            for name in normalized
        ),
        "qt_core": any(
            "qt6core" in name
            or name.endswith("/qtcore")
            or "pyside6/qtcore." in name
            for name in normalized
        ),
    }


def scan_artifact(artifact: Path, forbidden_paths: Iterable[str]) -> tuple[str, ...]:
    path_needles = tuple(
        variant.encode(encoding)
        for value in forbidden_paths
        for variant in {value, value.replace("\\", "/")}
        for encoding in ("utf-8", "utf-16-le")
        if value
    )
    secret_needles = (
        b"ocp-apim-subscription-key",
        b"cognitive.microsofttranslator.com",
        b"test-activation-secret",
    )
    findings: list[str] = []
    for path in artifact.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(artifact).as_posix()
        try:
            data = path.read_bytes()
        except OSError as error:
            findings.append(f"unreadable:{relative}:{type(error).__name__}")
            continue
        lowered = data.lower()
        if any(needle in data for needle in path_needles):
            findings.append(f"workspace-path:{relative}")
        if any(needle in lowered for needle in secret_needles):
            findings.append(f"secret-pattern:{relative}")
    return tuple(findings)


def smoke_test(executable: Path) -> tuple[bool, str]:
    environment = os.environ.copy()
    environment.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        completed = subprocess.run(
            [str(executable), "--smoke-test"],
            capture_output=True,
            text=True,
            timeout=60,
            env=environment,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return False, type(error).__name__
    detail = (completed.stderr or completed.stdout)[-500:]
    return completed.returncode == 0, detail


def verify_artifact(artifact: Path, target: str, run_smoke: bool) -> tuple[bool, list[str]]:
    errors: list[str] = []
    executable = executable_for(artifact, target)
    if not artifact.is_dir():
        return False, ["artifact directory is missing"]
    if not executable.is_file():
        return False, ["main executable is missing"]

    expected = "x86_64" if target == "windows-x64" else "arm64"
    binaries = native_binary_architectures(artifact, target)
    if not binaries:
        errors.append("no native binaries were found")
    wrong_arch = [name for name, architecture in binaries if architecture != expected]
    if wrong_arch:
        errors.append(f"native binaries have unexpected architecture: {wrong_arch[:10]}")

    missing_plugins = REQUIRED_IMAGE_PLUGINS - imageformat_plugins(artifact)
    if missing_plugins:
        errors.append(f"Qt image plugins are missing: {sorted(missing_plugins)}")

    missing_assets = [name for name, present in runtime_assets(artifact).items() if not present]
    if missing_assets:
        errors.append(f"runtime assets are missing: {missing_assets}")

    workspace = str(Path(__file__).resolve().parents[1])
    findings = scan_artifact(artifact, (workspace,))
    if findings:
        errors.append(f"artifact safety scan failed: {list(findings[:10])}")

    if run_smoke:
        smoke_ok, detail = smoke_test(executable)
        if not smoke_ok:
            errors.append(f"packaged smoke test failed: {detail}")
    return not errors, errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify an ImgTrans desktop artifact")
    parser.add_argument("--target", choices=TARGETS, required=True)
    parser.add_argument("--artifact", type=Path)
    parser.add_argument("--skip-smoke", action="store_true")
    args = parser.parse_args(argv)
    artifact = args.artifact or default_artifact(args.target)
    can_run = detect_current_target() == args.target and not args.skip_smoke
    ok, errors = verify_artifact(artifact, args.target, can_run)
    if ok:
        print(f"release artifact verified: target={args.target}")
        return 0
    for error in errors:
        print(f"verification error: {error}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
