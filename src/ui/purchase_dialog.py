from __future__ import annotations

import io
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any, Protocol

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.infrastructure.payment_client import (
    PayablePlan,
    PaymentClient,
    PaymentOrderInfo,
)


class TaskRunner(Protocol):
    def submit(
        self,
        operation: Callable[[], Any],
        on_success: Callable[[Any], None],
        on_error: Callable[[Exception], None],
    ) -> None: ...


class PurchasePanel(QWidget):
    """扫码购买面板 — 选套餐 → 下单 → 二维码 → 轮询（可嵌入窗口）。"""

    purchase_completed = Signal(str)  # activation_code
    renew_completed = Signal()  # 续购成功（已叠加到当前激活码）

    _POLL_MS = 3000

    def __init__(
        self,
        payment_client: PaymentClient,
        task_runner: TaskRunner,
        parent=None,
        preselect_plan_id: int | None = None,
        renew_code: str | None = None,
        has_active_duration: bool = True,
    ) -> None:
        super().__init__(parent)
        self._client = payment_client
        self._task_runner = task_runner
        self._preselect_plan_id = preselect_plan_id
        self._renew_code = renew_code
        self._is_renewal = renew_code is not None
        self._has_active_duration = has_active_duration
        self._plans: list[PayablePlan] = []
        self._selected_plan: PayablePlan | None = None
        self._order: PaymentOrderInfo | None = None
        self._polling = False
        self.setObjectName("purchaseDialog")

        layout = QVBoxLayout(self)

        intro_text = (
            "选择套餐后用微信扫码支付，时长/次数将叠加到当前激活码。"
            if self._is_renewal
            else "选择套餐后用微信扫码支付，支付成功后自动生成激活码。"
        )
        if not self._has_active_duration:
            intro_text += "\n提示：商品详情次数包需先购买翻译时长包后才能购买。"
        intro = QLabel(intro_text)
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self._plan_combo = QComboBox()
        self._plan_combo.setObjectName("planCombo")
        layout.addWidget(self._plan_combo)

        self._plan_info_label = QLabel()
        self._plan_info_label.setWordWrap(True)
        # 二维码上方的套餐信息：居中、加大加粗
        self._plan_info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._plan_info_label.setStyleSheet(
            "font-size: 20px; font-weight: 700; color: #212733;"
        )
        layout.addWidget(self._plan_info_label)

        self._qrcode_label = QLabel("二维码将在此显示")
        self._qrcode_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._qrcode_label.setMinimumHeight(260)
        layout.addWidget(self._qrcode_label)

        self._status_label = QLabel()
        self._status_label.setWordWrap(True)
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._status_label)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll_once)
        self._countdown_timer = QTimer(self)
        self._countdown_timer.timeout.connect(self._update_countdown)

        self._status_label.setText("正在加载套餐…")
        self._task_runner.submit(
            self._client.list_plans, self._plans_loaded, self._operation_failed
        )

    def _plans_loaded(self, result: object) -> None:
        if not isinstance(result, list):
            self._operation_failed(RuntimeError("套餐服务返回无效结果"))
            return
        self._plans = result
        if not self._plans:
            self._status_label.setText("暂无可购买套餐")
            return
        self._plan_combo.clear()
        duration_plans = [p for p in self._plans if p.plan_type != "quota"]
        quota_plans = [p for p in self._plans if p.plan_type == "quota"]

        def _suffix(plan: PayablePlan) -> str:
            if plan.plan_type == "combo":
                return f"{plan.duration_hours} 小时 + {plan.quota} 次"
            if plan.plan_type == "quota":
                return f"{plan.quota} 次"
            return f"{plan.duration_hours} 小时"

        def _add_group(title: str, items: list[PayablePlan]) -> None:
            if not items:
                return
            if self._plan_combo.count() > 0:
                self._plan_combo.insertSeparator(self._plan_combo.count())
            self._plan_combo.addItem(title)
            for plan in items:
                suffix = _suffix(plan)
                if plan.is_on_sale and plan.sale_amount_minor is not None:
                    label = (
                        f"{plan.name}  —  ¥{plan.sale_amount_minor / 100:.2f}"
                        f"（原价 ¥{plan.amount_minor / 100:.2f}）  /  {suffix}"
                    )
                else:
                    label = (
                        f"{plan.name}  —  ¥{plan.amount_minor / 100:.2f}  /  {suffix}"
                    )
                self._plan_combo.addItem(label, plan.plan_id)

        _add_group("── 翻译时长包 ──", duration_plans)
        _add_group("── 商品详情次数包 ──", quota_plans)
        self._plan_combo.currentIndexChanged.connect(self._on_plan_selected)
        if self._preselect_plan_id is not None:
            index = self._plan_combo.findData(self._preselect_plan_id)
            if index >= 0:
                self._plan_combo.setCurrentIndex(index)
                self._status_label.setText("选择套餐后自动生成付款码")
                return
        self._on_plan_selected()
        self._status_label.setText("选择套餐后自动生成付款码")

    def _on_plan_selected(self) -> None:
        plan_id = self._plan_combo.currentData()
        self._selected_plan = next(
            (p for p in self._plans if p.plan_id == plan_id), None
        )
        if (
            self._selected_plan is not None
            and self._selected_plan.plan_type == "quota"
            and not self._has_active_duration
        ):
            self._guide_to_duration_plan()
            return
        self._update_plan_info()
        self._auto_purchase()

    def _guide_to_duration_plan(self) -> None:
        """无活跃时长时选中次数包：提示并切回时长包，避免下单被服务端拒绝。"""
        self._plan_combo.blockSignals(True)
        for i in range(self._plan_combo.count()):
            data = self._plan_combo.itemData(i)
            if data is not None and any(
                p.plan_id == data and p.plan_type != "quota" for p in self._plans
            ):
                self._plan_combo.setCurrentIndex(i)
                break
        self._plan_combo.blockSignals(False)
        self._selected_plan = next(
            (p for p in self._plans if p.plan_id == self._plan_combo.currentData()),
            None,
        )
        QMessageBox.information(
            self,
            "提示",
            "商品详情次数包需搭配翻译时长使用，请先购买翻译时长包后再购买次数包",
        )
        self._status_label.setText(
            "请先购买「翻译时长包」获得时长额度，再购买次数包"
        )
        self._update_plan_info()
        self._auto_purchase()

    def _update_plan_info(self) -> None:
        self._countdown_timer.stop()
        plan = self._selected_plan
        if plan is None:
            self._plan_info_label.setText("")
            return
        parts = []
        # 价格区（仿电商：大红促销价 + 划线原价）
        if plan.is_on_sale and plan.sale_amount_minor is not None:
            parts.append(
                f'<span style="font-weight:bold;font-size:34px;color:#ff4400;">'
                f'¥{plan.sale_amount_minor / 100:.2f}</span>'
                f'&nbsp;&nbsp;'
                f'<span style="color:#999;text-decoration:line-through;">'
                f'¥{plan.amount_minor / 100:.2f}</span>'
            )
        else:
            parts.append(
                f'<span style="font-weight:bold;font-size:34px;color:#ff4400;">'
                f'¥{plan.amount_minor / 100:.2f}</span>'
            )
        # 权益描述
        if plan.benefits:
            parts.append(
                f'<span style="color:#666;">{plan.benefits}</span>'
            )
        self._plan_info_base = "<br/>".join(parts)
        self._plan_info_label.setTextFormat(Qt.TextFormat.RichText)
        self._plan_info_label.setText(self._plan_info_base)
        if plan.is_on_sale and plan.sale_ends_at:
            try:
                self._sale_ends = datetime.fromisoformat(
                    plan.sale_ends_at.replace("Z", "+00:00")
                )
            except ValueError:
                return
            self._update_countdown()
            self._countdown_timer.start(100)

    def _update_countdown(self) -> None:
        ends = getattr(self, "_sale_ends", None)
        if ends is None:
            return
        remaining = ends - datetime.now(timezone.utc)
        base = getattr(self, "_plan_info_base", "")
        if remaining.total_seconds() <= 0:
            self._countdown_timer.stop()
            self._plan_info_label.setText(
                f"{base}<br/><span style='color:#999;'>促销已结束</span>"
            )
            return
        self._plan_info_label.setText(
            f"{base}<br/><span style='color:#ff4400;font-weight:bold;'>"
            f"优惠剩余 {_format_countdown(remaining.total_seconds())}</span>"
        )

    def _auto_purchase(self) -> None:
        """选套餐后自动下单并显示二维码；切换套餐时旧下单结果被丢弃。"""
        plan_id = self._plan_combo.currentData()
        if plan_id is None:
            return
        self._ordering_seq = getattr(self, "_ordering_seq", 0) + 1
        seq = self._ordering_seq
        self._timer.stop()
        self._polling = False
        self._status_label.setText("正在下单…")
        self._set_busy(True)
        self._task_runner.submit(
            lambda: self._client.create_order(plan_id, self._renew_code),
            lambda result: (
                self._order_created(result) if seq == self._ordering_seq else None
            ),
            lambda error: (
                self._operation_failed(error) if seq == self._ordering_seq else None
            ),
        )
    def _order_created(self, result: object) -> None:
        if not isinstance(result, PaymentOrderInfo):
            self._operation_failed(RuntimeError("下单返回无效结果"))
            return
        self._order = result
        self._show_qrcode(result.code_url)
        self._status_label.setText(
            f"请使用微信扫码支付 ¥{result.amount_minor / 100:.2f}\n支付完成后将自动激活"
        )
        self._set_busy(False)
        self._polling = True
        self._timer.start(self._POLL_MS)

    def _show_qrcode(self, code_url: str) -> None:
        try:
            import qrcode
        except ImportError:
            self._status_label.setText("缺少二维码组件，无法生成付款码")
            return
        try:
            buf = io.BytesIO()
            qrcode.make(code_url).save(buf, format="PNG")
            pixmap = QPixmap()
            pixmap.loadFromData(buf.getvalue())
            self._qrcode_label.setPixmap(
                pixmap.scaled(
                    240, 240,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        except Exception:
            self._qrcode_label.setText("二维码生成失败")

    def _poll_once(self) -> None:
        if not self._polling or self._order is None:
            return
        self._task_runner.submit(
            lambda: self._client.poll_order(self._order.order_id),
            self._polled,
            self._poll_failed,
        )

    def _polled(self, result: object) -> None:
        if not isinstance(result, PaymentOrderInfo):
            return
        if result.status == "paid" and result.activation_code:
            self._timer.stop()
            self._polling = False
            self._status_label.setText(f"支付成功，激活码：{result.activation_code}")
            QMessageBox.information(
                self, "支付成功", f"激活码已生成：\n{result.activation_code}\n正在绑定本机…"
            )
            self.purchase_completed.emit(result.activation_code)
            self.accept()
        elif result.status == "paid" and self._is_renewal:
            self._timer.stop()
            self._polling = False
            self._status_label.setText("续购成功，时长/次数已叠加到当前激活码")
            self.renew_completed.emit()
            self.accept()
        elif result.status == "paid":
            self._timer.stop()
            self._polling = False
            self._status_label.setText("支付成功但未取得激活码，请联系客服")

    def _poll_failed(self, error: Exception) -> None:
        self._timer.stop()
        self._polling = False
        self._status_label.setText(f"查询支付结果失败：{error}")

    def _operation_failed(self, error: Exception) -> None:
        self._set_busy(False)
        self._status_label.setText(f"操作失败：{error}")

    def _set_busy(self, busy: bool) -> None:
        self._plan_combo.setEnabled(not busy)


def _format_countdown(total_seconds: float) -> str:
    total_tenths = max(0, int(total_seconds * 10))
    total, tenths = divmod(total_tenths, 10)
    hours, remainder = divmod(total, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{tenths}"


class PurchaseDialog(QDialog):
    """扫码购买激活码对话框（独立窗口用法，兼容原有调用）。"""

    purchase_completed = Signal(str)  # activation_code
    renew_completed = Signal()  # 续购成功（已叠加到当前激活码）

    def __init__(
        self,
        payment_client: PaymentClient,
        task_runner: TaskRunner,
        parent=None,
        preselect_plan_id: int | None = None,
        renew_code: str | None = None,
        has_active_duration: bool = True,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("purchaseDialog")
        self.setWindowTitle("续购套餐" if renew_code is not None else "扫码购买")
        self.setMinimumSize(820, 500)
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ── 左侧：紫色背景 + 标题 ──
        left_panel = QWidget()
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
        title = QLabel("续购时长/次数" if renew_code is not None else "扫码购买")
        title.setStyleSheet(
            "color: #ffffff; font-size: 20px; font-weight: 600;"
        )
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        left_layout.addWidget(title)
        hint = QLabel(
            "选择套餐后用微信扫码支付，时长/次数将叠加到当前激活码。"
            if renew_code is not None
            else "选择套餐后用微信扫码支付，支付成功后自动生成激活码。"
        )
        hint.setStyleSheet("color: #d8c7ff; font-size: 13px;")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setWordWrap(True)
        left_layout.addWidget(hint)
        left_layout.addStretch()
        outer.addWidget(left_panel, stretch=1)

        # ── 右侧：购买面板 ──
        right_panel = QWidget()
        right_panel.setStyleSheet("background: #ffffff;")
        layout = QVBoxLayout(right_panel)
        layout.setContentsMargins(24, 24, 24, 8)
        layout.setSpacing(0)
        self._panel = PurchasePanel(
            payment_client,
            task_runner,
            self,
            preselect_plan_id=preselect_plan_id,
            renew_code=renew_code,
            has_active_duration=has_active_duration,
        )
        self._panel.purchase_completed.connect(self.purchase_completed.emit)
        self._panel.renew_completed.connect(self.renew_completed.emit)
        layout.addWidget(self._panel)
        buttons = QHBoxLayout()
        close_button = QPushButton("关闭")
        close_button.setFixedSize(90, 34)
        close_button.setStyleSheet(
            "QPushButton { background: #ffffff; color: #3973db;"
            "  border: 1px solid #3973db; border-radius: 6px;"
            "  font-size: 14px; font-weight: 600; }"
            "QPushButton:hover { background: #eef2fb; }"
        )
        close_button.clicked.connect(self.reject)
        buttons.addStretch()
        buttons.addWidget(close_button)
        layout.addLayout(buttons)
        outer.addWidget(right_panel, stretch=2)
