"""自定义取色对话框测试 — RGB 外置 ±、色板、十六进制输入联动。"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QDialog

from src.ui.color_picker_dialog import ColorPickerDialog, pick_color


def test_initial_rgb_and_hex(qtbot) -> None:
    dialog = ColorPickerDialog((220, 30, 30))
    qtbot.addWidget(dialog)
    dialog.show()

    assert dialog.selected_rgb() == (220, 30, 30)
    assert dialog._hex_edit.text() == "#DC1E1E"
    assert [spin.value() for spin in dialog._spins] == [220, 30, 30]
    # 数值框的内置箭头已隐藏（外置 −/+ 按钮替代）
    from PySide6.QtWidgets import QAbstractSpinBox

    for spin in dialog._spins:
        assert (
            spin.buttonSymbols()
            == QAbstractSpinBox.ButtonSymbols.NoButtons
        )


def test_spin_changes_update_rgb_and_hex(qtbot) -> None:
    dialog = ColorPickerDialog((0, 0, 0))
    qtbot.addWidget(dialog)
    dialog.show()

    dialog._spins[1].setValue(200)

    assert dialog.selected_rgb() == (0, 200, 0)
    assert dialog._hex_edit.text() == "#00C800"


def test_hex_input_updates_spins(qtbot) -> None:
    dialog = ColorPickerDialog((0, 0, 0))
    qtbot.addWidget(dialog)
    dialog.show()

    dialog._hex_edit.setText("#3366CC")
    dialog._hex_edit.textEdited.emit("#3366CC")

    assert dialog.selected_rgb() == (51, 102, 204)
    assert [spin.value() for spin in dialog._spins] == [51, 102, 204]


def test_preset_swatch_sets_rgb(qtbot) -> None:
    dialog = ColorPickerDialog((0, 0, 0))
    qtbot.addWidget(dialog)
    dialog.show()

    # 第 3 个色板是内置的强调红 (220, 30, 30)
    dialog._swatches[2].click()

    assert dialog.selected_rgb() == (220, 30, 30)
    assert dialog._hex_edit.text() == "#DC1E1E"


def test_pick_color_returns_rgb_or_none(monkeypatch) -> None:
    monkeypatch.setattr(
        ColorPickerDialog,
        "exec",
        lambda self: QDialog.DialogCode.Accepted,
    )
    assert pick_color(None, (1, 2, 3)) == (1, 2, 3)

    monkeypatch.setattr(
        ColorPickerDialog,
        "exec",
        lambda self: QDialog.DialogCode.Rejected,
    )
    assert pick_color(None, (1, 2, 3)) is None
