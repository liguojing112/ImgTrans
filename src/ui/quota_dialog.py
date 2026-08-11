"""我的额度对话框 — 展示激活码、翻译时长剩余、商品详情次数剩余。"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)


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

        subtitle = QLabel("我的额度")
        subtitle.setStyleSheet(
            "color: #ffffff; font-size: 20px; font-weight: 600;"
        )
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        left_layout.addWidget(subtitle)

        hint = QLabel("查看当前激活码的剩余使用额度")
        hint.setStyleSheet("color: #d8c7ff; font-size: 13px;")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setWordWrap(True)
        left_layout.addWidget(hint)
        left_layout.addStretch()

        outer.addWidget(left_panel, stretch=1)

        # ── 右侧：额度信息 ──
        right_panel = QWidget()
        right_panel.setStyleSheet("background: #ffffff;")
        layout = QVBoxLayout(right_panel)
        layout.setContentsMargins(48, 48, 48, 48)
        layout.setSpacing(20)

        self._code_label = QLabel(f"激活码：{code}")
        self._code_label.setStyleSheet(
            "color: #212733; font-size: 16px; font-weight: 600;"
        )
        self._code_label.setWordWrap(True)
        layout.addWidget(self._code_label)

        from PySide6.QtGui import QFont, QFontMetrics

        _big_font = QFont("Microsoft YaHei", 18)
        _big_font.setBold(True)
        _big_height = QFontMetrics(_big_font).height() + 8

        self._duration_label = QLabel(
            f"翻译时长剩余：{_format_duration(expires_at)}"
        )
        self._duration_label.setFont(_big_font)
        self._duration_label.setStyleSheet("color: #212733;")
        self._duration_label.setFixedHeight(_big_height)
        layout.addWidget(self._duration_label)

        self._quota_label = QLabel(
            f"商品详情次数剩余：{quota_remaining} / {quota_total}"
        )
        self._quota_label.setFont(_big_font)
        self._quota_label.setStyleSheet("color: #212733;")
        self._quota_label.setFixedHeight(_big_height)
        layout.addWidget(self._quota_label)

        note = QLabel("提示：时长额度是所有功能的基础；商品详情生成另需次数额度。")
        note.setStyleSheet("color: #98a0ad; font-size: 12px;")
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch()

        outer.addWidget(right_panel, stretch=2)

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
