from __future__ import annotations

import platform
import sys
from pathlib import Path

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtGui import QColor, QImage, QImageReader

from prototypes.platform_bootstrap.build import (
    TARGETS,
    build_command,
    detect_current_target,
    validate_native_target,
)
from prototypes.platform_bootstrap.verify_artifact import pe_machine
from prototypes.platform_bootstrap.window import BootstrapWindow


def test_window_exposes_platform_and_dependency_status(qtbot) -> None:
    window = BootstrapWindow(default_duration_ms=100)
    qtbot.addWidget(window)
    window.show()

    assert platform.system() in window.summary_label.text()
    assert window.dependency_table.rowCount() >= 6
    assert window.start_button.isEnabled()
    assert not window.cancel_button.isEnabled()


def test_worker_completes_without_blocking_ui(qtbot) -> None:
    window = BootstrapWindow(default_duration_ms=150)
    qtbot.addWidget(window)
    window.show()

    with qtbot.waitSignal(window.probe_completed, timeout=1_500) as blocker:
        window.start_probe(150)

    assert blocker.args == ["finished"]
    qtbot.waitUntil(lambda: not window.is_probe_running, timeout=1_000)
    assert window.progress_bar.value() == 100
    assert window.last_outcome == "finished"


def test_worker_cancels_within_one_second(qtbot) -> None:
    window = BootstrapWindow(default_duration_ms=2_000)
    qtbot.addWidget(window)
    window.show()
    window.start_probe()

    with qtbot.waitSignal(window.probe_completed, timeout=1_000) as blocker:
        QTimer.singleShot(50, window.cancel_probe)

    assert blocker.args == ["cancelled"]
    qtbot.waitUntil(lambda: not window.is_probe_running, timeout=1_000)
    assert window.last_outcome == "cancelled"


def test_qt_image_plugins_read_rgb_rgba_and_chinese_path(tmp_path: Path) -> None:
    formats = {bytes(item).decode("ascii") for item in QImageReader.supportedImageFormats()}
    assert {"png", "jpeg", "webp"}.issubset(formats)

    rgb_path = tmp_path / "rgb.png"
    rgba_path = tmp_path / "中文透明图.png"
    rgb = QImage(64, 64, QImage.Format.Format_RGB32)
    rgb.fill(QColor("red"))
    rgba = QImage(64, 64, QImage.Format.Format_RGBA8888)
    rgba.fill(QColor(20, 40, 60, 80))
    assert rgb.save(str(rgb_path))
    assert rgba.save(str(rgba_path))

    loaded_rgb = QImageReader(str(rgb_path)).read()
    loaded_rgba = QImageReader(str(rgba_path)).read()
    assert loaded_rgb.size().width() == 64
    assert loaded_rgba.hasAlphaChannel()


def test_build_command_uses_native_spec_and_is_target_guarded() -> None:
    target = detect_current_target()
    assert TARGETS == ("windows-x64", "macos-arm64")
    assert target in TARGETS
    validate_native_target(target)
    command, dist_path, work_path = build_command(target, "ui")

    assert "PyInstaller" in command
    assert target in str(dist_path)
    assert target in str(work_path)
    other = next(item for item in TARGETS if item != target)
    with pytest.raises(RuntimeError, match="native-only"):
        validate_native_target(other)


def test_macos_arm64_workflow_has_required_build_gates() -> None:
    workflow = Path(".github/workflows/m0-platform-bootstrap-macos-arm64.yml").read_text(
        encoding="utf-8"
    )

    assert "runs-on: macos-14" in workflow
    assert "python -m pytest tests/prototypes/platform_bootstrap -q" in workflow
    assert "build.py --target macos-arm64" in workflow
    assert "verify_artifact.py --target macos-arm64" in workflow
    assert "codesign --verify --deep --strict" in workflow
    assert "ditto -c -k --sequesterRsrc --keepParent" in workflow
    assert "actions/upload-artifact@v4" in workflow


@pytest.mark.skipif(sys.platform != "win32", reason="PE validation only runs on Windows")
def test_pe_parser_identifies_current_python_as_x64() -> None:
    assert pe_machine(Path(sys.executable)) == "x86_64"
