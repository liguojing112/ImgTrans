"""工具对话框按钮行为测试 — 重点：Apply 按钮点击需触发请求信号。"""

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication, QDialogButtonBox

from src.domain.layout import TextBox
from src.ui.editor.widgets.tool_dialogs import (
    CropToolDialog,
    EraseToolDialog,
)
from src.ui.editor.canvas.scene import EditorScene


def test_erase_dialog_apply_button_emits_request(qtbot) -> None:
    """只有存在有效蒙版时，「确认消除」才允许发射请求。"""
    app = QApplication.instance() or QApplication(["tool-dialog-test"])
    dialog = EraseToolDialog()
    qtbot.addWidget(dialog)
    dialog.show()

    emitted = []
    dialog.apply_requested.connect(lambda: emitted.append(True))

    apply_button = dialog.findChild(
        QDialogButtonBox
    ).button(QDialogButtonBox.StandardButton.Apply)
    assert apply_button.text() == "确认消除"
    apply_button.click()
    assert emitted == []

    dialog.set_mask_ready(True)
    apply_button.click()

    assert emitted == [True]


def test_erase_dialog_exposes_paint_eraser_size_preview_and_follow_up(qtbot) -> None:
    app = QApplication.instance() or QApplication(["erase-tool-controls-test"])
    dialog = EraseToolDialog()
    qtbot.addWidget(dialog)
    brush_events = []
    preview_events = []
    undo_events = []
    add_text_events = []
    dialog.brush_changed.connect(lambda mode, size: brush_events.append((mode, size)))
    dialog.preview_changed.connect(preview_events.append)
    dialog.undo_requested.connect(lambda: undo_events.append(True))
    dialog.add_text_requested.connect(lambda: add_text_events.append(True))

    dialog.activate_mode("paint")
    dialog.brush_size.setValue(46)
    dialog.activate_mode("erase")
    dialog.preview.setChecked(False)
    dialog.set_completed("fixture-repair")
    dialog.undo_button.click()
    dialog.add_text_button.click()

    assert ("paint", 28) in brush_events
    assert ("paint", 46) in brush_events
    assert brush_events[-1] == ("erase", 46)
    assert preview_events == [False]
    assert undo_events == [True]
    assert add_text_events == [True]
    assert "fixture-repair" in dialog.mask_status.text()


def test_crop_dialog_apply_button_emits_request(qtbot) -> None:
    """「应用裁剪」按钮点击应发射 apply_requested（携带框选区域）。"""
    app = QApplication.instance() or QApplication(["tool-dialog-test"])
    dialog = CropToolDialog()
    qtbot.addWidget(dialog)
    dialog.show()

    # 未框选时点击不发射
    emitted = []
    dialog.apply_requested.connect(emitted.append)
    dialog.findChild(QDialogButtonBox).button(
        QDialogButtonBox.StandardButton.Apply
    ).click()
    assert emitted == []

    # 框选后点击发射
    dialog.set_selection(TextBox(100, 50, 80, 30))
    apply_button = dialog.findChild(QDialogButtonBox).button(
        QDialogButtonBox.StandardButton.Apply
    )
    assert apply_button.text() == "应用裁剪"
    apply_button.click()

    assert len(emitted) == 1
    assert isinstance(emitted[0], TextBox)
    assert emitted[0].width == 80
    assert emitted[0].height == 30


def test_crop_dialog_apply_without_selection_starts_canvas_selection(qtbot) -> None:
    """Apply should guide the user into canvas selection instead of a no-op."""
    app = QApplication.instance() or QApplication(["tool-dialog-test"])
    dialog = CropToolDialog()
    qtbot.addWidget(dialog)
    dialog.show()

    requested = []
    dialog.selection_requested.connect(lambda: requested.append(True))
    dialog.findChild(QDialogButtonBox).button(
        QDialogButtonBox.StandardButton.Apply
    ).click()

    assert requested == [True]
    assert dialog.isVisible()


def test_crop_dialog_cancel_button_is_chinese(qtbot) -> None:
    """「取消」按钮为中文。"""
    app = QApplication.instance() or QApplication(["tool-dialog-test"])
    dialog = CropToolDialog()
    qtbot.addWidget(dialog)
    cancel_button = dialog.findChild(QDialogButtonBox).button(
        QDialogButtonBox.StandardButton.Cancel
    )
    assert cancel_button.text() == "取消"


def test_crop_ratio_is_applied_during_canvas_drag(qtbot) -> None:
    app = QApplication.instance() or QApplication(["crop-ratio-test"])
    dialog = CropToolDialog()
    qtbot.addWidget(dialog)
    dialog.ratio.setCurrentIndex(dialog.ratio.findData("1:1"))
    assert dialog.selected_aspect_ratio() == 1.0

    scene = EditorScene()
    scene.set_area_selection_mode("crop", dialog.selected_aspect_ratio())
    constrained = scene._constrained_selection_rect(
        QPointF(100, 100), QPointF(300, 180)
    )
    assert constrained.width() == constrained.height()

    dialog.ratio.setCurrentIndex(dialog.ratio.findData("4:3"))
    scene.set_selection_aspect_ratio(dialog.selected_aspect_ratio())
    constrained = scene._constrained_selection_rect(
        QPointF(100, 100), QPointF(300, 180)
    )
    assert constrained.width() / constrained.height() == 4 / 3

    dialog.ratio.setCurrentIndex(dialog.ratio.findData(""))
    scene.set_selection_aspect_ratio(dialog.selected_aspect_ratio())
    free = scene._constrained_selection_rect(QPointF(100, 100), QPointF(300, 180))
    assert free.width() == 200
    assert free.height() == 80


def test_erase_dialog_disables_add_text_while_running(qtbot) -> None:
    """消除执行中「在修复背景上新增文字」应禁用，完成/失败后恢复。"""
    app = QApplication.instance() or QApplication(["tool-dialog-test"])
    dialog = EraseToolDialog()
    qtbot.addWidget(dialog)
    dialog.show()

    assert dialog.add_text_button.isEnabled()

    dialog.set_running(True)
    assert not dialog.add_text_button.isEnabled()
    assert not dialog.undo_button.isEnabled()
    assert not dialog.apply_button.isEnabled()

    dialog.set_completed("fake-backend")
    assert dialog.add_text_button.isEnabled()
    assert dialog.undo_button.isEnabled()

    dialog.set_running(True)
    dialog.set_failed("模拟失败")
    assert dialog.add_text_button.isEnabled()
    assert dialog.apply_button.isEnabled()


def test_ai_erase_keeps_rectangle_mode_after_auto_erase(qtbot) -> None:
    """矩形框选自动消除完成后，不自动跳回涂抹画笔，方便连续框选。"""
    from PySide6.QtGui import QUndoStack

    from src.ui.editor.editor_page import EditorPage

    page = EditorPage(QUndoStack())
    qtbot.addWidget(page)
    page.show()

    page.open_erase_dialog()
    dialog = page.erase_dialog
    assert dialog._current_mode == "paint"

    dialog.rectangle_button.click()
    assert dialog._current_mode == "rectangle"
    assert page.scene._selection_mode == "ai_erase"

    page.complete_ai_erase("opencv-text-fill")

    assert dialog._current_mode == "rectangle"
    assert dialog.rectangle_button.isChecked()
    assert page.scene._selection_mode == "ai_erase"


def test_ai_erase_rectangle_mode_frames_multiple_boxes(qtbot) -> None:
    """点一次「矩形框选」后可以连续框：消除期间暂停，完成后自动恢复框选。"""
    from PySide6.QtGui import QUndoStack

    from src.domain.layout import TextBox
    from src.ui.editor.editor_page import EditorPage

    page = EditorPage(QUndoStack())
    qtbot.addWidget(page)
    page.show()
    page.toolbar.set_active_tool("ai_erase")
    page.open_erase_dialog()
    page.erase_dialog.rectangle_button.click()
    assert page.scene._selection_mode == "ai_erase"

    page._on_area_selected("ai_erase", TextBox(50, 50, 40, 20))
    # 消除执行中不再接受新的框选（避免画了又被清空）
    assert page.scene._selection_mode is None

    page.complete_ai_erase("opencv-text-fill")
    # 完成后自动回到矩形框选，无需再点按钮
    assert page.erase_dialog._current_mode == "rectangle"
    assert page.scene._selection_mode == "ai_erase"
    assert page.scene._manual_selection_enabled
