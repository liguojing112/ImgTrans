from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Qt, Signal


class _WorkerSignals(QObject):
    succeeded = Signal(object)
    failed = Signal(object)
    finished = Signal()


class _FunctionWorker(QRunnable):
    def __init__(self, operation: Callable[[], Any]) -> None:
        super().__init__()
        self.operation = operation
        self.signals = _WorkerSignals()

    def run(self) -> None:
        try:
            self.signals.succeeded.emit(self.operation())
        except Exception as error:
            self.signals.failed.emit(error)
        finally:
            self.signals.finished.emit()


class QtTaskRunner(QObject):
    def __init__(self, pool: QThreadPool | None = None) -> None:
        super().__init__()
        self._pool = pool or QThreadPool.globalInstance()
        self._workers: set[_FunctionWorker] = set()

    def submit(
        self,
        operation: Callable[[], Any],
        on_success: Callable[[Any], None],
        on_error: Callable[[Exception], None],
    ) -> None:
        worker = _FunctionWorker(operation)
        self._workers.add(worker)
        connection = Qt.ConnectionType.QueuedConnection
        worker.signals.succeeded.connect(on_success, connection)
        worker.signals.failed.connect(on_error, connection)
        worker.signals.finished.connect(lambda: self._workers.discard(worker), connection)
        self._pool.start(worker)
