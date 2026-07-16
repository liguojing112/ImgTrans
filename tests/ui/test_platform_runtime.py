from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, QPointF, Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtNetwork import QNetworkInformation
from PySide6.QtWidgets import QApplication

from src.application.bootstrap import StartupSnapshot
from src.domain.activation import ActivationSession
from src.domain.image import ImageAsset, ImageDocument, ImageFileFormat
from src.domain.product import ProductInfo
from src.platform.qt_runtime import QtRuntimeMonitor, configure_qt_runtime
from src.ui.image_canvas import ImageCanvas
from src.ui.main_window import MainWindow


class _NetworkInformation(QObject):
    reachabilityChanged = Signal(object)

    def __init__(self, reachability) -> None:
        super().__init__()
        self._reachability = reachability

    def reachability(self):
        return self._reachability

    def set_reachability(self, value) -> None:
        self._reachability = value
        self.reachabilityChanged.emit(value)


class _RetinaCanvas(ImageCanvas):
    def devicePixelRatioF(self) -> float:
        return 2.0


class _DeferredRunner:
    def __init__(self) -> None:
        self.pending = []

    def submit(self, operation, on_success, on_error) -> None:
        self.pending.append((operation, on_success, on_error))


def _document() -> ImageDocument:
    return ImageDocument(
        ImageAsset(Path("fixture.png"), 400, 200, 1, ImageFileFormat.PNG, False, False),
        "RGB",
        bytes([255]) * 400 * 200 * 3,
    )


def test_qt_runtime_uses_fractional_high_dpi_policy() -> None:
    configure_qt_runtime()
    assert (
        QGuiApplication.highDpiScaleFactorRoundingPolicy()
        is Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )


def test_retina_device_ratio_does_not_change_document_coordinates(qtbot) -> None:
    canvas = _RetinaCanvas()
    qtbot.addWidget(canvas)
    canvas.resize(900, 600)
    canvas.set_document(_document())
    canvas.show()
    point = QPointF(137.25, 88.5)
    restored = canvas.view_to_document(canvas.document_to_view(point))
    assert abs(restored.x() - point.x()) < 0.001
    assert abs(restored.y() - point.y()) < 0.001


def test_resume_and_network_online_events_are_debounced(qtbot) -> None:
    application = QApplication.instance() or QApplication(["imgtrans-test"])
    network = _NetworkInformation(QNetworkInformation.Reachability.Disconnected)
    monitor = QtRuntimeMonitor(application, debounce_ms=0, network_information=network)
    monitor._seen_active = True
    monitor._application_state_changed(Qt.ApplicationState.ApplicationInactive)

    with qtbot.waitSignal(monitor.recovery_requested, timeout=1000) as signal:
        monitor._application_state_changed(Qt.ApplicationState.ApplicationActive)
        network.set_reachability(QNetworkInformation.Reachability.Online)
    assert set(signal.args[0].split(",")) == {"resume", "network-online"}


def test_runtime_recovery_does_not_submit_duplicate_refreshes(tmp_path: Path) -> None:
    application = QApplication.instance() or QApplication(["imgtrans-test"])
    runner = _DeferredRunner()
    now = datetime.now(timezone.utc)
    session = ActivationSession(1, now, now + timedelta(days=1), "itd_runtime_token_123456789")
    window = MainWindow(
        StartupSnapshot(
            ProductInfo("图片翻译", "0.1.0", "M4"),
            tmp_path / "data",
            tmp_path / "cache",
        ),
        task_runner=runner,
        refresh_image_limits=lambda: None,
        update_models=lambda: None,
        activate_device=lambda code: session,
        activation_status=lambda: session,
        clear_activation=lambda: None,
    )
    window.request_runtime_recovery("resume")
    window.request_runtime_recovery("network-online")
    assert len(runner.pending) == 2

    activation_task = next(item for item in runner.pending if item[0]() == session)
    activation_task[1](session)
    assert len(runner.pending) == 3
    window.close()

