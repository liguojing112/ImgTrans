import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from src.domain.manual_region import ManualInputMode
from src.ui.manual_region_panel import ManualRegionPanel


def test_manual_panel_paragraph_mode_defaults_to_long(qtbot) -> None:
    QApplication.instance() or QApplication(["manual-panel-paragraph-test"])
    panel = ManualRegionPanel()
    qtbot.addWidget(panel)

    assert panel.merge_paragraphs is True
    assert panel.paragraph_mode.itemData(0) == "long"
    assert panel.paragraph_mode.itemData(1) == "short"
    assert not panel.paragraph_row.isHidden()


def test_manual_panel_set_paragraph_mode(qtbot) -> None:
    QApplication.instance() or QApplication(["manual-panel-paragraph-test"])
    panel = ManualRegionPanel()
    qtbot.addWidget(panel)

    panel.set_paragraph_mode("short")
    assert panel.merge_paragraphs is False

    panel.set_paragraph_mode("not-a-mode")
    assert panel.merge_paragraphs is False  # 未知值不改动当前选择

    panel.set_paragraph_mode("long")
    assert panel.merge_paragraphs is True


def test_manual_panel_paragraph_mode_hidden_for_direct_translation(qtbot) -> None:
    QApplication.instance() or QApplication(["manual-panel-paragraph-test"])
    panel = ManualRegionPanel()
    qtbot.addWidget(panel)

    panel.mode_combo.setCurrentIndex(
        panel.mode_combo.findData(ManualInputMode.TRANSLATED_TEXT.value)
    )
    assert panel.paragraph_row.isHidden()

    panel.mode_combo.setCurrentIndex(
        panel.mode_combo.findData(ManualInputMode.AUTO.value)
    )
    assert not panel.paragraph_row.isHidden()
