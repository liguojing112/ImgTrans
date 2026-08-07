"""我的额度对话框 — 展示激活码、翻译时长剩余、商品详情次数剩余。"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QLabel, QVBoxLayout


class QuotaDialog(QDialog):
    """显示当前激活码的时长与次数额度；次数额度异步刷新为最新值。"""

    def __init__(
        self,
        code: str,
        expires_at: datetime,
        quota_total: int,
        quota_remaining: int,
        refresh_usage: Callable[[], object] | None = None,
        task_runner=None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("quotaDialog")
        self.setWindowTitle("我的额度")
        self.setMinimumWidth(380)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        title = QLabel("我的额度")
        title.setObjectName("homeCardTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        self._code_label = QLabel(f"激活码：{code}")
        self._code_label.setObjectName("homeCardDesc")
        self._code_label.setWordWrap(True)
        layout.addWidget(self._code_label)

        self._duration_label = QLabel(
            f"翻译时长剩余：{_format_duration(expires_at)}"
        )
        self._duration_label.setObjectName("homeCardDesc")
        layout.addWidget(self._duration_label)

        self._quota_label = QLabel(
            f"商品详情次数剩余：{quota_remaining} / {quota_total}"
        )
        self._quota_label.setObjectName("homeCardDesc")
        layout.addWidget(self._quota_label)

        if refresh_usage is not None and task_runner is not None:
            self._quota_label.setText("商品详情次数剩余：查询中…")
            task_runner.submit(refresh_usage, self._usage_loaded, self._usage_failed)

    def _usage_loaded(self, result) -> None:
        total = getattr(result, "quota_total", None)
        remaining = getattr(result, "quota_remaining", None)
        if isinstance(total, int) and isinstance(remaining, int):
            self._quota_label.setText(f"商品详情次数剩余：{remaining} / {total}")

    def _usage_failed(self, error: Exception) -> None:
        self._quota_label.setText(f"商品详情次数剩余：查询失败（{error}）")


def _format_duration(expires_at: datetime) -> str:
    remaining = expires_at - datetime.now(timezone.utc)
    if remaining.total_seconds() <= 0:
        return "已过期"
    total_hours = int(remaining.total_seconds() // 3600)
    if total_hours >= 24:
        return f"{total_hours // 24} 天 {total_hours % 24} 小时"
    return f"{total_hours} 小时"
