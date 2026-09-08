"""商品详情生成窗口测试 — 完成按钮的生成状态检查。"""

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox

from src.ui.product.product_window import ProductWindow


class FakeTaskRunner:
    def submit(self, operation, on_success, on_error):
        on_success(operation())


class FakeCodec:
    def load(self, path):
        raise FileNotFoundError(path)


def _make_window() -> ProductWindow:
    app = QApplication.instance() or QApplication(["product-window-test"])
    window = ProductWindow(
        task_runner=FakeTaskRunner(),
        codec=FakeCodec(),
        ocr_adapter=object(),
        llm_adapter=object(),
    )
    window.show()
    return window


def test_finish_blocked_while_generating(monkeypatch) -> None:
    """文案生成中点击「完成」应提示「请先完成文案生成」。"""
    window = _make_window()
    warnings = []
    monkeypatch.setattr(
        QMessageBox, "warning",
        lambda parent, title, text: warnings.append((title, text)),
    )
    try:
        window._generating = True
        window._model.copywriting_result = object()  # 即使已有结果，生成中也不允许

        window._on_finish()

        assert len(warnings) == 1
        assert warnings[0] == ("提示", "请先完成文案生成。")
    finally:
        window.close()


def test_finish_blocked_without_result(monkeypatch) -> None:
    """从未生成文案时点击「完成」应提示「请先完成文案生成」。"""
    window = _make_window()
    warnings = []
    monkeypatch.setattr(
        QMessageBox, "warning",
        lambda parent, title, text: warnings.append((title, text)),
    )
    try:
        window._generating = False
        window._model.copywriting_result = None

        window._on_finish()

        assert len(warnings) == 1
        assert warnings[0] == ("提示", "请先完成文案生成。")
    finally:
        window.close()


def test_finish_allowed_after_generation(monkeypatch) -> None:
    """生成完成后点击「完成」不再提示，进入完成流程。"""
    window = _make_window()
    warnings = []
    saved = []
    monkeypatch.setattr(
        QMessageBox, "warning",
        lambda parent, title, text: warnings.append((title, text)),
    )
    monkeypatch.setattr(
        QMessageBox, "information",
        lambda parent, title, text: None,
    )
    monkeypatch.setattr(
        window, "_on_save_project", lambda **kwargs: saved.append(kwargs)
    )
    try:
        window._generating = False
        window._model.copywriting_result = object()

        window._on_finish()

        assert warnings == []
        assert len(saved) == 1
    finally:
        window.close()


def _result_with_content():
    from src.domain.copywriting import (
        CopywritingResult,
        DetailModule,
        ImageTag,
        ProductIntro,
    )

    return CopywritingResult(
        tags=[ImageTag("t1", "tag one")],
        intro=ProductIntro(one_liner="old", short_description="", standard_intro=""),
        detail_modules=[
            DetailModule("overview", "产品概述", "old overview"),
            DetailModule("advantages", "核心优势", "old advantages"),
        ],
    )


def test_merge_partial_result_empty_does_not_overwrite() -> None:
    """重新生成返回空内容时不得覆盖已有文案。"""
    window = _make_window()
    try:
        from src.domain.copywriting import CopywritingResult, DetailModule, ProductIntro

        cr = _result_with_content()
        window._model.copywriting_results = {0: cr}

        window._merge_partial_result(CopywritingResult(intro=ProductIntro()))
        assert cr.intro.one_liner == "old"

        window._merge_partial_result(CopywritingResult(
            detail_modules=[DetailModule("advantages", "核心优势", "")]
        ))
        contents = {m.section: m.content for m in cr.detail_modules}
        assert contents == {
            "overview": "old overview",
            "advantages": "old advantages",
        }

        window._merge_partial_result(CopywritingResult(
            detail_modules=[DetailModule("advantages", "核心优势", "new advantages")]
        ))
        contents = {m.section: m.content for m in cr.detail_modules}
        assert contents == {
            "overview": "old overview",
            "advantages": "new advantages",
        }
        assert len(cr.detail_modules) == 2
    finally:
        window.close()


def test_empty_section_names_reports_missing_content() -> None:
    from src.ui.product.product_window import _empty_section_names
    from src.domain.copywriting import CopywritingResult, DetailModule, ProductIntro

    empty = CopywritingResult(detail_modules=[
        DetailModule("overview", "产品概述", ""),
    ])
    assert "商品简介" in _empty_section_names(empty)
    assert "详情文案" in _empty_section_names(empty)
    assert "图片标签" in _empty_section_names(empty)

    good = CopywritingResult(
        tags=["x"], keywords=["y"], titles=["z"], selling_points=["s"],
        intro=ProductIntro(one_liner="L"),
        detail_modules=[DetailModule("overview", "产品概述", "有内容")],
    )
    assert _empty_section_names(good) == []


def test_regeneration_controls_disable_while_request_is_in_flight() -> None:
    window = _make_window()
    try:
        intro = window._step_copywriting._intro_regen_btn
        # 详情重生成已从「每节一个按钮」改为「当前节单个按钮」
        detail = window._step_copywriting._detail_regen_btn

        window._step_copywriting.set_regeneration_active("intro", True)
        window._step_copywriting.set_regeneration_active("detail:specs", True)
        assert not intro.isEnabled()
        assert not detail.isEnabled()

        window._step_copywriting.set_regeneration_active("intro", False)
        window._step_copywriting.set_regeneration_active("detail:specs", False)
        assert intro.isEnabled()
        assert detail.isEnabled()
    finally:
        window.close()
