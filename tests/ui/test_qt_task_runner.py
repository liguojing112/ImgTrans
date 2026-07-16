import os
import threading
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from src.ui.qt_task_runner import QtTaskRunner


def test_qt_task_runner_keeps_operation_off_main_thread() -> None:
    application = QApplication.instance() or QApplication(["imgtrans-runner-test"])
    main_thread = threading.get_ident()
    result: dict[str, int] = {}
    loop = QEventLoop()

    def operation() -> int:
        time.sleep(0.05)
        return threading.get_ident()

    def succeeded(worker_thread: object) -> None:
        result["worker"] = int(worker_thread)
        result["callback"] = threading.get_ident()
        loop.quit()

    started = time.perf_counter()
    QtTaskRunner().submit(operation, succeeded, lambda error: loop.quit())
    submit_elapsed = time.perf_counter() - started
    QTimer.singleShot(2_000, loop.quit)
    loop.exec()
    application.processEvents()
    assert submit_elapsed < 0.05
    assert result["worker"] != main_thread
    assert result["callback"] == main_thread
