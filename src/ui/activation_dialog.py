from __future__ import annotations

import io
from collections.abc import Callable
from typing import Any, Protocol

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
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
    purchase_requested = Signal()

    def __init__(
        self,
        activate: Callable[[str], ActivationSession],
        current_session: Callable[[], ActivationSession | None],
        clear_activation: Callable[[], None],
        task_runner: TaskRunner,
        parent=None,
        purchase_available: bool = False,
        unbind: Callable[[str], bool] | None = None,
        purchase_client=None,
        has_active_duration: bool = True,
    ) -> None:
        super().__init__(parent)
        self._activate = activate
        self._current_session = current_session
        self._clear_activation = clear_activation
        self._task_runner = task_runner
        self._has_session = False
        self._purchase_available = purchase_available
        self._unbind = unbind
        self._purchase_client = purchase_client
        self.setObjectName("activationDialog")
        self.setWindowTitle("应用激活")
        self.setMinimumSize(820, 500)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ─ 左侧：紫色背景 + 激活表单 ──
        left_panel = QWidget()
        # 注意：QSS 的 padding 会级联到子控件导致文字被挤出，改用布局 margins
        left_panel.setStyleSheet("background: #8b5cf6;")
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(40, 40, 40, 40)
        left_layout.setSpacing(20)

        logo = QLabel(" 优译图AI")
        logo.setStyleSheet(
            "color: #ffffff; font-size: 28px; font-weight: 700;"
        )
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        left_layout.addWidget(logo)
        left_layout.addStretch()

        self.code_edit = QLineEdit()
        self.code_edit.setObjectName("activationCodeEdit")
        self.code_edit.setPlaceholderText("输入激活码开始使用")
        self.code_edit.setMaxLength(42)
        self.code_edit.setFixedHeight(48)
        self.code_edit.setStyleSheet(
            "QLineEdit { background: #1a1a2e; color: #ffffff;"
            "  border: 1px solid #333355; border-radius: 8px;"
            "  padding: 12px 16px; font-size: 14px; }"
            "QLineEdit:focus { border-color: #3b82f6; }"
        )
        self.code_edit.returnPressed.connect(self.request_activation)
        left_layout.addWidget(self.code_edit)

        # 用 QLabel 实现按钮（QPushButton 在该环境中文字渲染异常，QLabel 文字可靠）
        self.activate_button = QLabel("确认激活")
        self.activate_button.setObjectName("activateDeviceButton")
        self.activate_button.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.activate_button.setFixedHeight(48)
        self.activate_button.setStyleSheet(
            "QLabel { background: qlineargradient(x1:0, y1:0, x2:0, y2:1,"
            "  stop:0 #4a8af4, stop:1 #3973db); color: #ffffff;"
            "  border: 1px solid #5a9af4; border-radius: 8px;"
            "  font-size: 16px; font-weight: 700; }"
        )
        self.activate_button.mousePressEvent = lambda event: self.request_activation()
        left_layout.addWidget(self.activate_button)

        self.status_label = QLabel()
        self.status_label.setObjectName("activationStatusLabel")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("color: #ffffff; font-size: 13px;")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        left_layout.addWidget(self.status_label)

        if unbind is not None:
            self.unbind_button = QPushButton("👉 我已付款，找回我的激活码")
            self.unbind_button.setObjectName("unbindDeviceButton")
            self.unbind_button.setStyleSheet(
                "QPushButton { background: transparent; color: #fbbf24;"
                "  border: none; font-size: 13px; }"
                "QPushButton:hover { color: #f59e0b; }"
            )
            self.unbind_button.setToolTip("输入激活码解绑本机，换机后可重新激活该码")
            self.unbind_button.clicked.connect(self.request_unbind)
            left_layout.addWidget(self.unbind_button, alignment=Qt.AlignmentFlag.AlignCenter)

        if purchase_available:
            self.purchase_button = QPushButton("扫码购买")
            self.purchase_button.setObjectName("purchaseActivationButton")
            self.purchase_button.setStyleSheet(
                "QPushButton { background: transparent; color: #ffffff;"
                "  border: 1px solid #ffffff; border-radius: 6px;"
                "  padding: 8px 24px; font-size: 13px; }"
                "QPushButton:hover { background: rgba(255,255,255,0.15); }"
            )
            self.purchase_button.setToolTip("微信扫码支付自动获得激活码")
            self.purchase_button.clicked.connect(self.purchase_requested.emit)
            left_layout.addWidget(self.purchase_button, alignment=Qt.AlignmentFlag.AlignCenter)

        if clear_activation is not None:
            self.clear_button = QPushButton("清除本机激活")
            self.clear_button.setObjectName("clearActivationButton")
            self.clear_button.setStyleSheet(
                "QPushButton { background: transparent; color: #f87171;"
                "  border: none; font-size: 12px; }"
                "QPushButton:hover { color: #ef4444; }"
            )
            self.clear_button.clicked.connect(self.request_clear)
            left_layout.addWidget(self.clear_button, alignment=Qt.AlignmentFlag.AlignCenter)

        left_layout.addStretch()
        layout.addWidget(left_panel, stretch=1)

        # ── 右侧：真实购买面板（选套餐 → 下单 → 二维码 → 轮询） ──
        if self._purchase_client is not None:
            from src.ui.purchase_dialog import PurchasePanel

            right_panel = QWidget()
            right_panel.setStyleSheet(
                "background: #f8f9fb; border-left: 1px solid #e2e6ee;"
            )
            right_layout = QVBoxLayout(right_panel)
            right_layout.setContentsMargins(24, 24, 24, 24)
            self._purchase_panel = PurchasePanel(
                self._purchase_client,
                task_runner,
                self,
                has_active_duration=has_active_duration,
            )
            self._purchase_panel.purchase_completed.connect(
                self._on_embedded_purchase
            )
            right_layout.addWidget(self._purchase_panel)
            layout.addWidget(right_panel, stretch=1)

        self._set_busy(True)
        self.status_label.setText("正在读取本机激活状态…")
        self._task_runner.submit(
            self._current_session,
            self._status_loaded,
            self._operation_failed,
        )

    def _on_embedded_purchase(self, code: str) -> None:
        """右侧购买面板支付成功 → 自动填入激活码并激活。"""
        self.code_edit.setText(code)
        self.request_activation()

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
            if session.quota_total > 0:
                self.status_label.setText(
                    f"已激活，有效期至 {expires}\n商品详情剩余次数：{session.quota_remaining}/{session.quota_total}"
                )
            else:
                self.status_label.setText(f"已激活，有效期至 {expires}")
        self._set_busy(False)

    def request_unbind(self) -> None:
        if self._unbind is None:
            return
        code = self.code_edit.text().strip()
        if not code:
            self.status_label.setText("请输入要解绑的激活码")
            return
        from PySide6.QtWidgets import QMessageBox

        reply = QMessageBox.question(
            self,
            "解绑换机",
            "解绑后本机激活将失效，该激活码可在其他设备重新激活。\n确定要解绑吗？",
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._set_busy(True)
        self.status_label.setText("正在解绑…")
        self._task_runner.submit(
            lambda: self._unbind(code),
            self._unbind_succeeded,
            self._operation_failed,
        )

    def _unbind_succeeded(self, ok: object) -> None:
        if not ok:
            self._operation_failed(RuntimeError("解绑失败，激活码无效或已停用"))
            return
        self.code_edit.clear()
        try:
            # 服务端已解绑，必须同步清掉本机凭据，否则本机仍显示"已激活"，
            # 用户遇到 401 后重新输入激活码会把该码再次绑回本机，新机器就无法激活
            self._clear_activation()
        except Exception as error:
            self._set_busy(False)
            self.status_label.setText(
                f"服务端已解绑，但本机激活凭据清除失败：{error}\n"
                "请再点一次「清除本机激活」"
            )
            return
        self._set_session_status(None)
        self.activation_cleared.emit()
        self.status_label.setText("解绑成功，本机已退出激活，可换机重新激活")

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
        # 确认激活按钮始终可点、始终深底白字（避免禁用态对比弱看不清）
        self.activate_button.setEnabled(True)
        if hasattr(self, "clear_button"):
            self.clear_button.setEnabled(not busy and self._has_session)
        if hasattr(self, "unbind_button"):
            self.unbind_button.setEnabled(not busy)
