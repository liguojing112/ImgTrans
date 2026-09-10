from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton

from src.domain.activation import ActivationSession
from src.application.bootstrap import StartupSnapshot
from src.domain.product import ProductInfo
from src.ui.activation_dialog import ActivationDialog
from src.ui.main_window import MainWindow
from src.ui.purchase_dialog import _format_countdown


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


def test_purchase_countdown_displays_one_tenth_of_a_second() -> None:
    assert _format_countdown(7199.09) == "01:59:59.0"
    assert _format_countdown(0.09) == "00:00:00.0"


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


def test_unbind_success_clears_local_session_and_emits_cleared() -> None:
    application = QApplication.instance() or QApplication(["imgtrans-test"])
    runner = _ImmediateRunner()
    cleared = []

    dialog = ActivationDialog(
        lambda code: _session(),
        lambda: _session(),
        lambda: cleared.append(True),
        runner,
        unbind=lambda code: True,
    )
    cleared_events = []
    dialog.activation_cleared.connect(lambda: cleared_events.append(True))
    dialog.code_edit.setText("IT-ABCD")
    with mock.patch.object(
        QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes
    ):
        dialog.request_unbind()
    application.processEvents()

    assert cleared, "解绑成功后必须清除本机激活凭据，否则本机仍显示已激活"
    assert cleared_events == [True]
    assert "解绑成功" in dialog.status_label.text()
    assert dialog.code_edit.text() == ""
    dialog.close()


def test_unbind_false_reports_failure_and_keeps_local_session() -> None:
    application = QApplication.instance() or QApplication(["imgtrans-test"])
    runner = _ImmediateRunner()
    cleared = []

    dialog = ActivationDialog(
        lambda code: _session(),
        lambda: _session(),
        lambda: cleared.append(True),
        runner,
        unbind=lambda code: False,
    )
    dialog.code_edit.setText("IT-ABCD")
    with mock.patch.object(
        QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes
    ):
        dialog.request_unbind()
    application.processEvents()

    assert cleared == []
    assert "失败" in dialog.status_label.text()
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


class _UnbindClient:
    def __init__(self) -> None:
        self.codes: list[str] = []

    def unbind(self, activation_code: str) -> bool:
        self.codes.append(activation_code)
        return True


def test_launcher_activation_dialog_offers_unbind_when_quota_client_present(tmp_path) -> None:
    application = QApplication.instance() or QApplication(["imgtrans-test"])
    client = _UnbindClient()
    window = MainWindow(
        StartupSnapshot(
            ProductInfo("图片翻译", "0.1.0", "M4"),
            tmp_path / "data",
            tmp_path / "cache",
        ),
        task_runner=_ImmediateRunner(),
        activate_device=lambda code: _session(),
        activation_status=lambda: None,
        clear_activation=lambda: None,
        quota_client=client,
    )
    window.activation_action.trigger()
    application.processEvents()

    dialog = window.findChild(ActivationDialog, "activationDialog")
    assert dialog is not None
    button = window.findChild(QPushButton, "unbindDeviceButton")
    assert button is not None, "启动窗口的激活对话框也必须能解绑换机"
    assert "解绑" in button.text()
    dialog.close()
    window.close()


def test_unbind_normalizes_code_case_and_clears_local_hint() -> None:
    application = QApplication.instance() or QApplication(["imgtrans-test"])
    client = _UnbindClient()
    dialog = ActivationDialog(
        lambda code: _session(),
        lambda: _session(),
        lambda: None,
        _ImmediateRunner(),
        unbind=client.unbind,
    )
    dialog.code_edit.setText(" it-abcd ")
    with mock.patch.object(
        QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes
    ):
        dialog.request_unbind()
    application.processEvents()

    assert client.codes == ["IT-ABCD"]
    assert "解绑成功" in dialog.status_label.text()

    dialog.code_edit.setText("IT-ABCD")
    dialog.request_clear()
    application.processEvents()
    assert "服务器仍保留本机绑定" in dialog.status_label.text()
    dialog.close()
