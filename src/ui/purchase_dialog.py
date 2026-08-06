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


class PurchaseDialog(QDialog):
    """扫码购买激活码 — 选套餐 → 下单 → 二维码 → 轮询支付结果。"""

    purchase_completed = Signal(str)  # activation_code

    _POLL_MS = 3000

    def __init__(
        self,
        payment_client: PaymentClient,
        task_runner: TaskRunner,
        parent=None,
        preselect_plan_id: int | None = None,
    ) -> None:
        super().__init__(parent)
        self._client = payment_client
        self._task_runner = task_runner
        self._preselect_plan_id = preselect_plan_id
        self._plans: list[PayablePlan] = []
        self._selected_plan: PayablePlan | None = None
        self._order: PaymentOrderInfo | None = None
        self._polling = False
        self.setObjectName("purchaseDialog")
        self.setWindowTitle("扫码购买")
        self.setMinimumSize(380, 520)

        layout = QVBoxLayout(self)

        intro = QLabel("选择套餐后用微信扫码支付，支付成功后自动生成激活码。")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self._plan_combo = QComboBox()
        self._plan_combo.setObjectName("planCombo")
        layout.addWidget(self._plan_combo)

        self._plan_info_label = QLabel()
        self._plan_info_label.setWordWrap(True)
        layout.addWidget(self._plan_info_label)

        self._qrcode_label = QLabel("二维码将在此显示")
        self._qrcode_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._qrcode_label.setMinimumHeight(260)
        layout.addWidget(self._qrcode_label)

        self._status_label = QLabel()
        self._status_label.setWordWrap(True)
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._status_label)

        buttons = QHBoxLayout()
        self._buy_button = QPushButton("立即购买")
        self._buy_button.clicked.connect(self._start_purchase)
        close_button = QPushButton("关闭")
        close_button.clicked.connect(self.reject)
        buttons.addStretch()
        buttons.addWidget(self._buy_button)
        buttons.addWidget(close_button)
        layout.addLayout(buttons)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll_once)
        self._countdown_timer = QTimer(self)
        self._countdown_timer.timeout.connect(self._update_countdown)

        self._status_label.setText("正在加载套餐…")
        self._buy_button.setEnabled(False)
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
        self._on_plan_selected()
        self._status_label.setText("请选择套餐后购买")
        self._buy_button.setEnabled(True)

    def _on_plan_selected(self) -> None:
        plan_id = self._plan_combo.currentData()
        self._selected_plan = next(
            (p for p in self._plans if p.plan_id == plan_id), None
        )
        self._update_plan_info()

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
                f'<span style="font-size:28px;font-weight:bold;color:#ff4400;">'
                f'¥{plan.sale_amount_minor / 100:.2f}</span>'
                f'&nbsp;&nbsp;'
                f'<span style="font-size:14px;color:#999;text-decoration:line-through;">'
                f'¥{plan.amount_minor / 100:.2f}</span>'
            )
        else:
            parts.append(
                f'<span style="font-size:28px;font-weight:bold;color:#ff4400;">'
                f'¥{plan.amount_minor / 100:.2f}</span>'
            )
        # 权益描述
        if plan.benefits:
            parts.append(
                f'<span style="color:#666;font-size:12px;">{plan.benefits}</span>'
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
            self._countdown_timer.start(1000)

    def _update_countdown(self) -> None:
        ends = getattr(self, "_sale_ends", None)
        if ends is None:
            return
        remaining = ends - datetime.now(timezone.utc)
        base = getattr(self, "_plan_info_base", "")
        if remaining.total_seconds() <= 0:
            self._countdown_timer.stop()
            self._plan_info_label.setText(
                f"{base}<br/><span style='color:#999;font-size:12px;'>促销已结束</span>"
            )
            return
        total = int(remaining.total_seconds())
        hours, remainder = divmod(total, 3600)
        minutes, seconds = divmod(remainder, 60)
        self._plan_info_label.setText(
            f"{base}<br/><span style='color:#ff4400;font-size:12px;font-weight:bold;'>"
            f"优惠剩余 {hours:02d}:{minutes:02d}:{seconds:02d}</span>"
        )

    def _start_purchase(self) -> None:
        plan_id = self._plan_combo.currentData()
        if plan_id is None:
            return
        self._set_busy(True)
        self._status_label.setText("正在下单…")
        self._task_runner.submit(
            lambda: self._client.create_order(plan_id),
            self._order_created,
            self._operation_failed,
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
        self._buy_button.setEnabled(not busy)
        self._plan_combo.setEnabled(not busy)
