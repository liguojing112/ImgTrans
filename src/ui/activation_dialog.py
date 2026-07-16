from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from src.domain.activation import ActivationSession


class TaskRunner(Protocol):
    def submit(
        self,
        operation: Callable[[], Any],
        on_success: Callable[[Any], None],
        on_error: Callable[[Exception], None],
    ) -> None: ...


class ActivationDialog(QDialog):
    activated = Signal(object)
    activation_cleared = Signal()

    def __init__(
        self,
        activate: Callable[[str], ActivationSession],
        current_session: Callable[[], ActivationSession | None],
        clear_activation: Callable[[], None],
        task_runner: TaskRunner,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._activate = activate
        self._current_session = current_session
        self._clear_activation = clear_activation
        self._task_runner = task_runner
        self._has_session = False
        self.setObjectName("activationDialog")
        self.setWindowTitle("应用激活")
        self.setMinimumWidth(470)

        layout = QVBoxLayout(self)
        intro = QLabel("输入管理后台签发的激活码。激活凭据只保存在系统安全凭据库中。")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        form = QFormLayout()
        self.code_edit = QLineEdit()
        self.code_edit.setObjectName("activationCodeEdit")
        self.code_edit.setPlaceholderText("IT-XXXX-XXXX-XXXX-XXXX-XXXX-XXXX-XXXX-XXXX")
        self.code_edit.setMaxLength(42)
        self.code_edit.returnPressed.connect(self.request_activation)
        form.addRow("激活码", self.code_edit)
        layout.addLayout(form)

        self.status_label = QLabel()
        self.status_label.setObjectName("activationStatusLabel")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self.activate_button = QPushButton("激活")
        self.activate_button.setObjectName("activateDeviceButton")
        self.clear_button = QPushButton("清除本机激活")
        self.clear_button.setObjectName("clearActivationButton")
        self.buttons.addButton(self.clear_button, QDialogButtonBox.ButtonRole.ResetRole)
        self.buttons.addButton(self.activate_button, QDialogButtonBox.ButtonRole.AcceptRole)
        self.buttons.rejected.connect(self.reject)
        self.activate_button.clicked.connect(self.request_activation)
        self.clear_button.clicked.connect(self.request_clear)
        layout.addWidget(self.buttons)
        self._set_busy(True)
        self.status_label.setText("正在读取本机激活状态…")
        self._task_runner.submit(
            self._current_session,
            self._status_loaded,
            self._operation_failed,
        )

    def _status_loaded(self, result: object) -> None:
        if result is not None and not isinstance(result, ActivationSession):
            self._operation_failed(RuntimeError("本机激活状态无效"))
            return
        self._set_session_status(result)

    def _set_session_status(self, session: ActivationSession | None) -> None:
        if session is None:
            self._has_session = False
            self.status_label.setText("当前设备尚未激活")
        else:
            self._has_session = True
            expires = session.expires_at.astimezone().strftime("%Y-%m-%d %H:%M")
            self.status_label.setText(f"已激活，有效期至 {expires}")
        self._set_busy(False)

    def request_activation(self) -> None:
        code = self.code_edit.text().strip()
        if not code:
            self.status_label.setText("请输入激活码")
            return
        self._set_busy(True)
        self.status_label.setText("正在安全验证激活码…")
        self._task_runner.submit(
            lambda: self._activate(code),
            self._activation_succeeded,
            self._operation_failed,
        )

    def request_clear(self) -> None:
        self._set_busy(True)
        self.status_label.setText("正在清除本机激活凭据…")
        self._task_runner.submit(
            self._clear_activation,
            self._clear_succeeded,
            self._operation_failed,
        )

    def _activation_succeeded(self, result: object) -> None:
        if not isinstance(result, ActivationSession):
            self._operation_failed(RuntimeError("激活服务返回了无效结果"))
            return
        self.code_edit.clear()
        self._set_session_status(result)
        self.activated.emit(result)

    def _clear_succeeded(self, _result: object) -> None:
        self._set_session_status(None)
        self.activation_cleared.emit()

    def _operation_failed(self, error: Exception) -> None:
        self._set_busy(False)
        self.status_label.setText(f"操作失败：{error}")

    def _set_busy(self, busy: bool) -> None:
        self.code_edit.setEnabled(not busy)
        self.activate_button.setEnabled(not busy)
        self.clear_button.setEnabled(not busy and self._has_session)
