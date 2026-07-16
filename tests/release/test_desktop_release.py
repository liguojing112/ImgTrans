from __future__ import annotations

from pathlib import Path
import struct
import sys

import pytest

from scripts.build_desktop import (
    TARGETS,
    build_command,
    detect_current_target,
    validate_native_target,
)
from scripts.verify_desktop_artifact import (
    REQUIRED_IMAGE_PLUGINS,
    imageformat_plugins,
    macho_architecture,
    pe_architecture,
    runtime_assets,
    scan_artifact,
    verify_artifact,
)


def _write_pe(path: Path, machine: int = 0x8664) -> None:
    data = bytearray(0x86)
    data[:2] = b"MZ"
    data[0x3C:0x40] = struct.pack("<I", 0x80)
    data[0x80:0x84] = b"PE\0\0"
    data[0x84:0x86] = struct.pack("<H", machine)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _write_macho(path: Path, cpu_type: int) -> None:
    path.write_bytes(b"\xcf\xfa\xed\xfe" + struct.pack("<I", cpu_type))


def test_only_supported_native_release_targets_are_detected() -> None:
    assert TARGETS == ("windows-x64", "macos-arm64")
    assert detect_current_target("Windows", "AMD64") == "windows-x64"
    assert detect_current_target("Darwin", "arm64") == "macos-arm64"
    assert detect_current_target("Darwin", "x86_64") is None
    assert detect_current_target("Windows", "arm64") is None


def test_build_command_uses_formal_spec_and_release_directories() -> None:
    target = detect_current_target()
    assert target in TARGETS
    validate_native_target(target)
    command, dist_path, work_path = build_command(target)
    command_text = " ".join(command)
    assert "PyInstaller" in command
    assert "--clean" in command
    assert "packaging" in command_text and "imgtrans.spec" in command_text
    assert "prototypes" not in command_text
    assert tuple(dist_path.parts[-2:]) == ("release", target)
    assert tuple(work_path.parts[-2:]) == ("release", target)


@pytest.mark.skipif(sys.platform != "win32", reason="PE host check requires Windows")
def test_pe_parser_identifies_current_python_as_x64() -> None:
    assert pe_architecture(Path(sys.executable)) == "x86_64"


def test_binary_parsers_reject_wrong_or_universal_architectures(tmp_path: Path) -> None:
    x64_pe = tmp_path / "x64.exe"
    x86_pe = tmp_path / "x86.exe"
    arm64_macho = tmp_path / "arm64"
    x64_macho = tmp_path / "x64"
    universal = tmp_path / "universal"
    _write_pe(x64_pe)
    _write_pe(x86_pe, 0x014C)
    _write_macho(arm64_macho, 0x0100000C)
    _write_macho(x64_macho, 0x01000007)
    universal.write_bytes(b"\xca\xfe\xba\xbe" + b"\0" * 4)

    assert pe_architecture(x64_pe) == "x86_64"
    assert pe_architecture(x86_pe) == "x86"
    assert macho_architecture(arm64_macho) == "arm64"
    assert macho_architecture(x64_macho) == "x86_64"
    assert macho_architecture(universal) == "universal"


def test_release_verifier_requires_all_image_plugins_and_model_runtimes(
    tmp_path: Path,
) -> None:
    artifact = tmp_path / "ImgTrans"
    _write_pe(artifact / "ImgTrans.exe")
    plugins = artifact / "_internal" / "PySide6" / "plugins" / "imageformats"
    plugins.mkdir(parents=True)
    for name in REQUIRED_IMAGE_PLUGINS:
        (plugins / f"{name}.dll").write_bytes(b"fixture")
    rapidocr = artifact / "_internal" / "rapidocr"
    rapidocr.mkdir(parents=True)
    (rapidocr / "config.yaml").write_bytes(b"fixture")
    (rapidocr / "default_models.yaml").write_bytes(b"fixture")
    runtime = artifact / "_internal"
    (runtime / "onnxruntime_pybind11_state.pyd").write_bytes(b"fixture")
    (runtime / "cv2.pyd").write_bytes(b"fixture")
    (runtime / "Qt6Core.dll").write_bytes(b"fixture")

    assert imageformat_plugins(artifact) == REQUIRED_IMAGE_PLUGINS
    assert all(runtime_assets(artifact).values())
    assert verify_artifact(artifact, "windows-x64", run_smoke=False) == (True, [])


def test_runtime_asset_check_accepts_macos_qt_core_layout(tmp_path: Path) -> None:
    artifact = tmp_path / "ImgTrans.app"
    resources = artifact / "Contents" / "Resources"
    (resources / "rapidocr").mkdir(parents=True)
    (resources / "rapidocr" / "config.yaml").write_bytes(b"fixture")
    (resources / "rapidocr" / "default_models.yaml").write_bytes(b"fixture")
    (resources / "PySide6").mkdir(parents=True)
    (resources / "PySide6" / "QtCore.abi3.so").write_bytes(b"fixture")
    (resources / "onnxruntime_pybind11_state.so").write_bytes(b"fixture")
    (resources / "cv2.abi3.so").write_bytes(b"fixture")
    assert all(runtime_assets(artifact).values())


def test_artifact_scan_detects_workspace_path_and_forbidden_secret_pattern(
    tmp_path: Path,
) -> None:
    artifact = tmp_path / "artifact"
    artifact.mkdir()
    (artifact / "path.bin").write_bytes(b"C:\\Workspace\\ImgTrans\\src")
    (artifact / "secret.bin").write_bytes(b"Ocp-Apim-Subscription-Key")
    findings = scan_artifact(artifact, (r"C:\Workspace\ImgTrans",))
    assert any(item.startswith("workspace-path:") for item in findings)
    assert any(item.startswith("secret-pattern:") for item in findings)


def test_formal_spec_and_workflow_have_release_gates() -> None:
    spec = Path("packaging/imgtrans.spec").read_text(encoding="utf-8")
    workflow = Path(".github/workflows/m4-desktop-release-build.yml").read_text(
        encoding="utf-8"
    )
    assert 'root / "src" / "__main__.py"' in spec
    assert 'collect_data_files(' in spec
    assert 'excludes=["models/*.onnx", "**/*.onnx"]' in spec
    assert 'collect_submodules("rapidocr")' in spec
    assert 'collect_dynamic_libs("onnxruntime")' in spec
    assert '"server"' in spec and '"prototypes"' in spec
    assert "windows-2022" in workflow
    assert "runs-on: macos-14" in workflow
    assert "expected Apple Silicon arm64 runner" in workflow
    assert "python -m pytest -q" in workflow
    assert "python -m scripts.build_desktop --target windows-x64" in workflow
    assert "python -m scripts.build_desktop --target macos-arm64" in workflow
    assert workflow.count("python -m scripts.verify_desktop_artifact") == 2
    assert "codesign --verify --deep --strict" in workflow
    assert "actions/upload-artifact@v4" in workflow
    assert "prototypes/" not in workflow


def test_release_dependency_is_pinned() -> None:
    project = Path("pyproject.toml").read_text(encoding="utf-8")
    assert 'PyInstaller==6.19.0' in project
