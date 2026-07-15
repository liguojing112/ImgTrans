from __future__ import annotations

import threading
import time

from PySide6.QtCore import QThread, Signal


class ProbeWorkerThread(QThread):
    progress = Signal(int)
    succeeded = Signal(int)
    cancelled = Signal(int)
    failed = Signal(str)

    def __init__(self, duration_ms: int = 3_000, step_ms: int = 50, parent=None) -> None:
        super().__init__(parent)
        if duration_ms <= 0 or step_ms <= 0:
            raise ValueError("duration_ms and step_ms must be positive")
        self.duration_ms = duration_ms
        self.step_ms = min(step_ms, duration_ms)
        self._cancel_requested = threading.Event()

    def request_cancel(self) -> None:
        self._cancel_requested.set()

    def run(self) -> None:
        started = time.monotonic()
        try:
            self.progress.emit(0)
            while True:
                elapsed_ms = int((time.monotonic() - started) * 1_000)
                if self._cancel_requested.is_set():
                    self.cancelled.emit(elapsed_ms)
                    return
                if elapsed_ms >= self.duration_ms:
                    self.progress.emit(100)
                    self.succeeded.emit(elapsed_ms)
                    return
                progress = min(99, int(elapsed_ms * 100 / self.duration_ms))
                self.progress.emit(progress)
                time.sleep(min(self.step_ms, self.duration_ms - elapsed_ms) / 1_000)
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")
