from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from src.ui.pipeline_panel import PipelinePanel


def test_pipeline_completion_reports_font_fallback() -> None:
    QApplication.instance() or QApplication(["pipeline-panel-test"])
    panel = PipelinePanel()
    panel.set_completed(None, 0, 2)
    assert "2 个区域使用了回退字体" in panel.status_label.text()
