from __future__ import annotations

from PySide6.QtCore import Signal, Slot
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

try:
    from .dependency_probe import collect_report, format_summary
    from .worker_probe import ProbeWorkerThread
except ImportError:
    from dependency_probe import collect_report, format_summary
    from worker_probe import ProbeWorkerThread


class BootstrapWindow(QMainWindow):
    probe_completed = Signal(str)

    def __init__(self, *, default_duration_ms: int = 3_000) -> None:
        super().__init__()
        self.default_duration_ms = default_duration_ms
        self._thread: ProbeWorkerThread | None = None
        self._last_outcome: str | None = None

        self.setWindowTitle("Image Translator Platform Bootstrap")
        self.resize(760, 520)

        self.summary_label = QLabel()
        self.summary_label.setObjectName("summaryLabel")
        self.dependency_table = QTableWidget(0, 4)
        self.dependency_table.setObjectName("dependencyTable")
        self.dependency_table.setHorizontalHeaderLabels(
            ["Dependency", "Category", "Version", "Status"]
        )
        self.dependency_table.horizontalHeader().setStretchLastSection(True)

        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("progressBar")
        self.progress_bar.setRange(0, 100)
        self.status_label = QLabel("Idle")
        self.status_label.setObjectName("statusLabel")
        self.start_button = QPushButton("Start 3-second probe")
        self.start_button.setObjectName("startButton")
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setObjectName("cancelButton")
        self.cancel_button.setEnabled(False)

        buttons = QHBoxLayout()
        buttons.addWidget(self.start_button)
        buttons.addWidget(self.cancel_button)
        buttons.addStretch(1)

        layout = QVBoxLayout()
        layout.addWidget(self.summary_label)
        layout.addWidget(self.dependency_table)
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.status_label)
        layout.addLayout(buttons)

        central = QWidget()
        central.setLayout(layout)
        self.setCentralWidget(central)

        self.start_button.clicked.connect(self.start_probe)
        self.cancel_button.clicked.connect(self.cancel_probe)
        self.refresh_dependency_report()

    @property
    def is_probe_running(self) -> bool:
        return self._thread is not None and self._thread.isRunning()

    @property
    def last_outcome(self) -> str | None:
        return self._last_outcome

    def refresh_dependency_report(self) -> None:
        report = collect_report(import_modules=False)
        self.summary_label.setText(format_summary(report))
        self.dependency_table.setRowCount(len(report["dependencies"]))
        for row, dependency in enumerate(report["dependencies"]):
            values = (
                dependency["key"],
                dependency["category"],
                dependency.get("version") or "-",
                dependency["status"],
            )
            for column, value in enumerate(values):
                self.dependency_table.setItem(row, column, QTableWidgetItem(value))

    @Slot()
    def start_probe(self, duration_ms: int | None = None) -> None:
        if self.is_probe_running:
            return
        if isinstance(duration_ms, bool):
            duration_ms = None
        duration = duration_ms or self.default_duration_ms
        self._last_outcome = None
        self.progress_bar.setValue(0)
        self.status_label.setText("Running")
        self.start_button.setEnabled(False)
        self.cancel_button.setEnabled(True)

        thread = ProbeWorkerThread(duration_ms=duration, parent=self)
        thread.progress.connect(self.progress_bar.setValue)
        thread.succeeded.connect(self._on_finished)
        thread.cancelled.connect(self._on_cancelled)
        thread.failed.connect(self._on_failed)
        thread.finished.connect(self._on_thread_finished)
        thread.finished.connect(thread.deleteLater)

        self._thread = thread
        thread.start()

    @Slot()
    def cancel_probe(self) -> None:
        if self._thread is not None:
            self.status_label.setText("Cancelling")
            self._thread.request_cancel()

    @Slot(int)
    def _on_finished(self, elapsed_ms: int) -> None:
        self._last_outcome = "finished"
        self.status_label.setText(f"Finished in {elapsed_ms} ms")
        self.probe_completed.emit("finished")

    @Slot(int)
    def _on_cancelled(self, elapsed_ms: int) -> None:
        self._last_outcome = "cancelled"
        self.status_label.setText(f"Cancelled after {elapsed_ms} ms")
        self.probe_completed.emit("cancelled")

    @Slot(str)
    def _on_failed(self, message: str) -> None:
        self._last_outcome = "failed"
        self.status_label.setText(message)
        self.probe_completed.emit("failed")

    @Slot()
    def _on_thread_finished(self) -> None:
        self._thread = None
        self.start_button.setEnabled(True)
        self.cancel_button.setEnabled(False)

    def closeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if self.is_probe_running and self._thread is not None:
            self._thread.request_cancel()
            if not self._thread.wait(1_000):
                self.status_label.setText("Waiting for worker shutdown")
                event.ignore()
                return
        event.accept()
