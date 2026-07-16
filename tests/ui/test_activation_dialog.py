from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from src.domain.activation import ActivationSession
from src.application.bootstrap import StartupSnapshot
from src.domain.product import ProductInfo
from src.ui.activation_dialog import ActivationDialog
from src.ui.main_window import MainWindow


class _ImmediateRunner:
    def __init__(self) -> None:
        self.submissions = 0

    def submit(self, operation, on_success, on_error) -> None:
        self.submissions += 1
        try:
            on_success(operation())
        except Exception as error:
            on_error(error)


def _session() -> ActivationSession:
    now = datetime.now(timezone.utc)
    return ActivationSession(
        1,
        now,
        now + timedelta(days=10),
        "itd_dialog_device_token_123456",
    )


def test_activation_dialog_runs_operation_through_task_runner_and_hides_token() -> None:
    application = QApplication.instance() or QApplication(["imgtrans-test"])
    runner = _ImmediateRunner()
    current = {"session": None}
    received = []

    def activate(code: str) -> ActivationSession:
        assert code == "IT-ABCD"
        current["session"] = _session()
        return current["session"]

    dialog = ActivationDialog(
        activate,
        lambda: current["session"],
        lambda: current.update(session=None),
        runner,
    )
    dialog.activated.connect(received.append)
    dialog.code_edit.setText("IT-ABCD")
    dialog.request_activation()
    application.processEvents()

    assert runner.submissions == 2
    assert received == [current["session"]]
    assert "已激活" in dialog.status_label.text()
    assert "itd_dialog" not in dialog.status_label.text()
    assert dialog.code_edit.text() == ""
    dialog.close()


def test_main_window_exposes_activation_action_when_backend_callbacks_exist(tmp_path) -> None:
    application = QApplication.instance() or QApplication(["imgtrans-test"])
    runner = _ImmediateRunner()
    window = MainWindow(
        StartupSnapshot(
            ProductInfo("图片翻译", "0.1.0", "M4"),
            tmp_path / "data",
            tmp_path / "cache",
        ),
        task_runner=runner,
        activate_device=lambda code: _session(),
        activation_status=lambda: None,
        clear_activation=lambda: None,
    )
    assert window.activation_action.isEnabled()
    window.activation_action.trigger()
    application.processEvents()
    assert window.findChild(ActivationDialog, "activationDialog") is not None
    window.close()
