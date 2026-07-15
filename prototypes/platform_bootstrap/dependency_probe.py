from __future__ import annotations

import argparse
import importlib
import importlib.metadata
import importlib.util
import json
import os
import platform
import sys
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable


@dataclass(frozen=True)
class ProbeSpec:
    key: str
    module: str
    distribution: str
    required: bool
    category: str
    alternative: str | None = None


PROBE_SPECS = (
    ProbeSpec("pyside6", "PySide6", "PySide6", True, "ui"),
    ProbeSpec("pillow", "PIL", "Pillow", True, "image"),
    ProbeSpec("opencv", "cv2", "opencv-python", True, "image"),
    ProbeSpec(
        "rapidocr_onnxruntime",
        "rapidocr_onnxruntime",
        "rapidocr-onnxruntime",
        False,
        "ocr-candidate",
        "TASK-M0-002 will select a locally packaged RapidOCR backend.",
    ),
    ProbeSpec(
        "rapidocr",
        "rapidocr",
        "rapidocr",
        False,
        "ocr-candidate",
        "TASK-M0-002 will select a locally packaged RapidOCR backend.",
    ),
    ProbeSpec(
        "onnxruntime",
        "onnxruntime",
        "onnxruntime",
        False,
        "inference-candidate",
        "Use the platform-compatible inference backend selected by TASK-M0-002.",
    ),
    ProbeSpec(
        "torch",
        "torch",
        "torch",
        False,
        "inpainting-candidate",
        "TASK-M0-004 may select a lighter local runtime behind InpaintingAdapter.",
    ),
    ProbeSpec(
        "pyinstaller",
        "PyInstaller",
        "pyinstaller",
        False,
        "packaging-tool",
        "Build-time only; it is intentionally absent from the packaged application.",
    ),
    ProbeSpec(
        "pytest",
        "pytest",
        "pytest",
        False,
        "test-tool",
        "Test-time only; it is intentionally absent from the packaged application.",
    ),
    ProbeSpec(
        "pytest_qt",
        "pytestqt",
        "pytest-qt",
        False,
        "test-tool",
        "Test-time only; it is intentionally absent from the packaged application.",
    ),
)


def _distribution_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def _sanitize_text(value: str) -> str:
    replacements = {
        str(Path.cwd()): "<workspace>",
        str(Path.home()): "<home>",
    }
    sanitized = value
    for source, replacement in replacements.items():
        if source:
            sanitized = sanitized.replace(source, replacement)
            sanitized = sanitized.replace(source.replace("\\", "/"), replacement)
    return sanitized[:500]


def _module_detail(key: str, module: Any) -> dict[str, Any]:
    if key == "pyside6":
        from PySide6.QtCore import qVersion
        from PySide6.QtGui import QImageReader

        return {
            "qt_version": qVersion(),
            "image_formats": sorted(
                bytes(item).decode("ascii", errors="replace")
                for item in QImageReader.supportedImageFormats()
            ),
        }
    if key == "opencv":
        return {"opencv_version": module.__version__}
    if key == "pillow":
        return {"pillow_version": module.__version__}
    if key == "onnxruntime":
        return {"providers": list(module.get_available_providers())}
    if key == "torch":
        tensor = module.zeros(1)
        return {
            "torch_version": module.__version__,
            "tensor_device": str(tensor.device),
            "mps_available": bool(
                getattr(module.backends, "mps", None)
                and module.backends.mps.is_available()
            ),
            "cuda_available": bool(module.cuda.is_available()),
        }
    return {}


def probe_dependency(spec: ProbeSpec, *, import_module: bool) -> dict[str, Any]:
    result: dict[str, Any] = asdict(spec)
    result["version"] = _distribution_version(spec.distribution)
    try:
        result["installed"] = importlib.util.find_spec(spec.module) is not None
    except (ImportError, ValueError) as exc:
        result["installed"] = False
        result["status"] = "error"
        result["error"] = _sanitize_text(f"{type(exc).__name__}: {exc}")
        return result

    if not result["installed"]:
        result["status"] = "missing"
        return result
    if not import_module:
        result["status"] = "available"
        return result

    started = time.perf_counter()
    try:
        module = importlib.import_module(spec.module)
        result["detail"] = _module_detail(spec.key, module)
        result["status"] = "loaded"
    except Exception as exc:  # Native import failures must become report data.
        result["status"] = "error"
        result["error"] = _sanitize_text(f"{type(exc).__name__}: {exc}")
    result["load_seconds"] = round(time.perf_counter() - started, 4)
    return result


def collect_report(*, import_modules: bool = True) -> dict[str, Any]:
    dependencies = [
        probe_dependency(spec, import_module=import_modules) for spec in PROBE_SPECS
    ]
    return {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "architecture": platform.architecture()[0],
        },
        "python": {
            "version": platform.python_version(),
            "implementation": platform.python_implementation(),
            "executable_name": Path(sys.executable).name,
        },
        "environment": {
            "frozen": bool(getattr(sys, "frozen", False)),
            "qt_platform": os.environ.get("QT_QPA_PLATFORM", "default"),
        },
        "dependencies": dependencies,
    }


def write_report(report: dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(output)


def format_summary(report: dict[str, Any]) -> str:
    platform_info = report["platform"]
    python_info = report["python"]
    loaded = sum(
        item["status"] in {"available", "loaded"} for item in report["dependencies"]
    )
    return (
        f"{platform_info['system']} {platform_info['release']} / "
        f"{platform_info['machine']} / Python {python_info['version']} / "
        f"dependencies {loaded}/{len(report['dependencies'])}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Probe desktop prototype dependencies")
    parser.add_argument("--json", action="store_true", help="Print JSON to stdout")
    parser.add_argument("--output", type=Path, help="Write JSON report atomically")
    parser.add_argument(
        "--metadata-only", action="store_true", help="Do not import discovered modules"
    )
    parser.add_argument(
        "--strict", action="store_true", help="Fail when a required dependency is unavailable"
    )
    args = parser.parse_args(argv)

    report = collect_report(import_modules=not args.metadata_only)
    if args.output:
        write_report(report, args.output)
    if args.json or not args.output:
        print(json.dumps(report, ensure_ascii=False, indent=2))

    if args.strict:
        failed = [
            item
            for item in report["dependencies"]
            if item["required"] and item["status"] not in {"available", "loaded"}
        ]
        return 1 if failed else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
