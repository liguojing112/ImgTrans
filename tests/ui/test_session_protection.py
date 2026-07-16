import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from src.application.bootstrap import StartupSnapshot
from src.domain.product import ProductInfo
from src.ui.main_window import MainWindow


def _window(tmp_path: Path, decisions: list[bool], messages: list[str]) -> MainWindow:
    def confirm(message: str) -> bool:
        messages.append(message)
        return decisions.pop(0)

    return MainWindow(
        StartupSnapshot(
            ProductInfo("图片翻译", "0.1.0", "M2"),
            tmp_path / "data",
            tmp_path / "cache",
        ),
        confirm_discard=confirm,
    )


def test_close_can_be_cancelled_when_single_result_is_unexported(tmp_path: Path) -> None:
    QApplication.instance() or QApplication(["session-close-test"])
    messages: list[str] = []
    window = _window(tmp_path, [False, True], messages)
    window.show()
    window._session_changes.mark_single_changed()
    assert not window.close()
    assert window.isVisible()
    assert "未导出" in messages[0]
    assert window.close()


def test_close_warning_includes_remaining_batch_result_count(tmp_path: Path) -> None:
    QApplication.instance() or QApplication(["session-batch-close-test"])
    messages: list[str] = []
    window = _window(tmp_path, [True], messages)
    window.show()
    window._session_changes.replace_batch_results({"one", "two", "three"})
    assert window.close()
    assert "3 张" in messages[0]
