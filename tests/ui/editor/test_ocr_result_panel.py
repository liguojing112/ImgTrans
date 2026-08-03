"""OCR 结果面板测试 — 搜索/筛选/列表定位联动。"""

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from src.domain.ocr import OcrResult, TextRegion, order_quad
from src.domain.translation import (
    TranslationMode,
    TranslationResult,
    TranslationSelection,
    TranslationStatus,
    TranslationUnit,
)
from src.ui.editor.widgets.ocr_result_panel import OcrResultPanel


def _region(region_id: str, text: str) -> TextRegion:
    return TextRegion(
        region_id,
        order_quad(((18, 18), (78, 18), (78, 48), (18, 48))),
        text,
        0.9,
        "zh-Hans",
        "fixture",
    )


def _make_panel(qtbot) -> OcrResultPanel:
    app = QApplication.instance() or QApplication(["ocr-panel-test"])
    panel = OcrResultPanel()
    qtbot.addWidget(panel)
    panel.show()
    result = OcrResult(
        (
            _region("r1", "你好"),
            _region("r2", "世界"),
            _region("r3", "测试"),
        ),
        "zh-Hans",
        "fixture",
        1.0,
    )
    units = (
        TranslationUnit(
            "r1", "你好", "zh-Hans", "en", "Hello",
            TranslationStatus.TRANSLATED,
        ),
        TranslationUnit(
            "r2", "世界", "zh-Hans", "en", "World",
            TranslationStatus.TRANSLATED,
        ),
    )
    translation = TranslationResult(
        units,
        TranslationSelection(TranslationMode.ALL, "en"),
        "fixture",
        1.0,
    )
    panel.set_result(result, translation)
    return panel


def test_select_region_locates_row(qtbot) -> None:
    """select_region 应滚动定位并选中对应行。"""
    panel = _make_panel(qtbot)

    panel.select_region("r2")

    item = panel.tree.currentItem()
    assert item is not None
    assert item.data(0, Qt.ItemDataRole.UserRole) == "r2"
    assert item.text(0) == "世界"


def test_select_region_missing_id_is_noop(qtbot) -> None:
    """不存在的区域 ID 不影响当前选中。"""
    panel = _make_panel(qtbot)

    panel.select_region("missing")
    assert panel.tree.currentItem() is None


def test_select_region_after_search_filter(qtbot) -> None:
    """搜索过滤后 select_region 仍可定位可见行。"""
    panel = _make_panel(qtbot)

    panel.search_edit.setText("世界")
    assert panel.tree.topLevelItemCount() == 1

    panel.select_region("r2")
    item = panel.tree.currentItem()
    assert item is not None
    assert item.data(0, Qt.ItemDataRole.UserRole) == "r2"


def test_search_and_status_filter(qtbot) -> None:
    """搜索原文/译文 + 按状态筛选。"""
    panel = _make_panel(qtbot)
    assert panel.tree.topLevelItemCount() == 3

    # 搜索译文
    panel.search_edit.setText("world")
    assert panel.tree.topLevelItemCount() == 1
    assert (
        panel.tree.topLevelItem(0).data(0, Qt.ItemDataRole.UserRole) == "r2"
    )

    # 搜索原文
    panel.search_edit.setText("你好")
    assert panel.tree.topLevelItemCount() == 1
    assert (
        panel.tree.topLevelItem(0).data(0, Qt.ItemDataRole.UserRole) == "r1"
    )

    # 按状态筛选：失败 → 无行
    panel.search_edit.clear()
    panel.status_filter.setCurrentIndex(
        panel.status_filter.findData("failed")
    )
    assert panel.tree.topLevelItemCount() == 0

    # 按状态筛选：已翻译 → 2 行
    panel.status_filter.setCurrentIndex(
        panel.status_filter.findData("translated")
    )
    assert panel.tree.topLevelItemCount() == 2


def test_show_regions_checkbox_emits_signal(qtbot) -> None:
    """「显示区域框」开关发射 show_regions_changed。"""
    panel = _make_panel(qtbot)

    emitted = []
    panel.show_regions_changed.connect(emitted.append)
    panel.show_regions.setChecked(False)

    assert emitted == [False]
