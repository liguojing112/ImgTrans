from __future__ import annotations

from PySide6.QtCore import QObject, QTimer, Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtNetwork import QNetworkInformation


def configure_qt_runtime() -> None:
    if QGuiApplication.instance() is None:
        QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
        )


class QtRuntimeMonitor(QObject):
    recovery_requested = Signal(str)

    def __init__(
        self,
        application: QGuiApplication,
        debounce_ms: int = 750,
        network_information: object | None = None,
    ) -> None:
        super().__init__(application)
        if debounce_ms < 0:
            raise ValueError("Runtime recovery debounce cannot be negative")
        self._debounce_ms = debounce_ms
        self._pending = False
        self._reasons: set[str] = set()
        self._last_application_state = application.applicationState()
        self._seen_active = (
            self._last_application_state is Qt.ApplicationState.ApplicationActive
        )
        application.applicationStateChanged.connect(self._application_state_changed)
        self._network_information = (
            network_information
            if network_information is not None
            else _load_network_information()
        )
        self._last_reachability = None
        if self._network_information is not None:
            self._last_reachability = self._network_information.reachability()
            self._network_information.reachabilityChanged.connect(
                self._reachability_changed
            )

    def _application_state_changed(self, state: Qt.ApplicationState) -> None:
        previous = self._last_application_state
        self._last_application_state = state
        if state is not Qt.ApplicationState.ApplicationActive:
            return
        if not self._seen_active:
            self._seen_active = True
            return
        if previous is not Qt.ApplicationState.ApplicationActive:
            self._schedule_recovery("resume")

    def _reachability_changed(self, reachability: object) -> None:
        previous = self._last_reachability
        self._last_reachability = reachability
        if (
            reachability == QNetworkInformation.Reachability.Online
            and previous != QNetworkInformation.Reachability.Online
        ):
            self._schedule_recovery("network-online")

    def _schedule_recovery(self, reason: str) -> None:
        self._reasons.add(reason)
        if self._pending:
            return
        self._pending = True
        QTimer.singleShot(self._debounce_ms, self._emit_recovery)

    def _emit_recovery(self) -> None:
        reasons = ",".join(sorted(self._reasons))
        self._reasons.clear()
        self._pending = False
        self.recovery_requested.emit(reasons)


def _load_network_information() -> QNetworkInformation | None:
    try:
        if not QNetworkInformation.loadDefaultBackend():
            return None
        return QNetworkInformation.instance()
    except RuntimeError:
        return None

