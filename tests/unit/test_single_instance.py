from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from src.main import _start_instance_channel


def test_second_launch_notifies_instead_of_showing_prompt() -> None:
    """重复启动不再弹「客户端已在运行」提示：只唤醒已有实例后退出。"""
    QApplication.instance() or QApplication(["imgtrans-single-instance-test"])
    should_run, server = _start_instance_channel()
    assert should_run and server is not None
    try:
        QTest.qWait(50)  # 让首个实例进入监听状态
        should_run_again, server_again = _start_instance_channel()
        assert not should_run_again and server_again is None
    finally:
        server.close()
