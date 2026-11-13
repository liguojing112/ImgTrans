from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

from PySide6.QtWidgets import QApplication

from src.application.batch import BatchOcrState
from src.domain.batch import (
    BatchItemSnapshot,
    BatchItemStatus,
    BatchSnapshot,
    BatchStatus,
)
from src.domain.image import ImageAsset, ImageDocument, ImageFileFormat
from src.domain.ocr import OcrResult, TextRegion, order_quad
from src.ui.batch_panel import BatchPanel
from src.ui.editor.main_window import EditorMainWindow


class _ImmediateTaskRunner:
    def submit(self, operation, on_success, on_error) -> None:
        try:
            on_success(operation())
        except Exception as error:
            on_error(error)


class _RecordingRunner:
    def __init__(self, snapshot: BatchSnapshot) -> None:
        self.snapshot = snapshot
        self.calls: list[dict] = []
        self.cancelled = False

    def execute(
        self,
        sources,
        ocr_language,
        selection,
        brand_terms=(),
        on_update=None,
        **options,
    ):
        self.calls.append(
            {
                "sources": tuple(sources),
                "ocr_language": ocr_language,
                "options": options,
            }
        )
        if on_update is not None:
            on_update(self.snapshot)
        return self.snapshot

    def cancel(self) -> None:
        self.cancelled = True

    def pause(self) -> None:
        pass

    def resume(self) -> None:
        pass


class _TranslateRunner:
    def execute(self, *_args, **_kwargs):
        raise AssertionError("仅 OCR 模式不应调用翻译批次")

    def cancel(self) -> None:
        pass

    def pause(self) -> None:
        pass

    def resume(self) -> None:
        pass


class _Store:
    def __init__(self, state) -> None:
        self.state = state

    def load(self, _ref):
        raise AssertionError("仅 OCR 批次不应加载成品图")

    def load_editable(self, _ref):
        return self.state


def _ocr() -> OcrResult:
    region = TextRegion(
        "r1",
        order_quad(((2, 2), (18, 2), (18, 12), (2, 12))),
        "HELLO",
        0.9,
        "en",
        "fixture",
    )
    return OcrResult((region,), "en", "fixture", 1.0)


def _document(w: int = 40, h: int = 30) -> ImageDocument:
    asset = ImageAsset(Path("a.png"), w, h, 1, ImageFileFormat.PNG, False, False)
    return ImageDocument(asset, "RGB", bytes((10, 20, 30)) * w * h)


def _snapshot(source: Path) -> BatchSnapshot:
    return BatchSnapshot(
        "batch-test1234",
        BatchStatus.COMPLETED,
        (
            BatchItemSnapshot(
                "item-1",
                source,
                BatchItemStatus.COMPLETED,
                result_ref="cache/a.png",
            ),
        ),
        2,
    )


def _window(runner, store) -> EditorMainWindow:
    QApplication.instance() or QApplication(["batch-ocr-mode-test"])
    return EditorMainWindow(
        import_image=object(),
        task_runner=_ImmediateTaskRunner(),
        run_batch=_TranslateRunner(),
        run_batch_ocr=runner,
        batch_result_store=store,
    )


def test_panel_switches_between_translate_and_ocr_modes() -> None:
    QApplication.instance() or QApplication(["batch-panel-mode-test"])
    panel = BatchPanel()
    panel.show()
    try:
        assert not panel.ocr_only
        assert panel.start_button.text() == "开始批量翻译"
        assert panel.export_text_button.isHidden()

        panel.mode.setCurrentIndex(panel.mode.findData("ocr"))
        assert panel.ocr_only
        assert panel.start_button.text() == "开始批量识别"
        assert not panel.target_language.isEnabled()
        assert not panel.export_text_button.isHidden()
    finally:
        panel.close()


def test_start_batch_in_ocr_mode_uses_ocr_runner(tmp_path: Path) -> None:
    source = (tmp_path / "a.png").resolve()
    runner = _RecordingRunner(_snapshot(source))
    window = _window(runner, _Store(BatchOcrState(_ocr())))
    try:
        panel = window._editor_page.batch_panel
        panel.mode.setCurrentIndex(panel.mode.findData("ocr"))
        panel.add_sources((source,))
        window._on_start_batch()

        assert runner.calls, "未走到 OCR 批次调度器"
        assert runner.calls[0]["sources"] == (source,)
        assert window._batch_snapshot is runner.snapshot
    finally:
        window.close()


def test_export_batch_text_writes_one_txt_per_image(
    tmp_path: Path, monkeypatch
) -> None:
    source = (tmp_path / "a.png").resolve()
    output_dir = tmp_path / "texts"
    output_dir.mkdir()
    runner = _RecordingRunner(_snapshot(source))
    window = _window(runner, _Store(BatchOcrState(_ocr())))
    try:
        panel = window._editor_page.batch_panel
        panel.mode.setCurrentIndex(panel.mode.findData("ocr"))
        panel.add_sources((source,))
        window._on_start_batch()
        panel = window._editor_page.batch_panel
        panel.set_snapshot(runner.snapshot)
        monkeypatch.setattr(
            "src.ui.editor.main_window.QFileDialog.getExistingDirectory",
            lambda *_args, **_kwargs: str(output_dir),
        )
        window._on_export_batch_text()

        assert (output_dir / "a.txt").read_text(encoding="utf-8") == "HELLO"
    finally:
        window.close()


def test_restore_batch_ocr_state_fills_ocr_result() -> None:
    QApplication.instance() or QApplication(["batch-ocr-restore-test"])
    window = EditorMainWindow(import_image=object())
    try:
        ocr = _ocr()
        window._restore_batch_editable(_document(), _document(), BatchOcrState(ocr))
        assert window._model.ocr_result is ocr
    finally:
        window.close()


def test_help_documents_batch_ocr_and_fixed_font_size() -> None:
    """使用说明需要写清批量 OCR 的用法与统一字号设置。"""
    from src.ui.help_dialog import _HELP_HTML

    assert "批量 OCR" in _HELP_HTML
    assert "仅 OCR（只识别文字）" in _HELP_HTML
    assert "导出识别文本" in _HELP_HTML
    assert "固定字号" in _HELP_HTML
    assert "固定字重" in _HELP_HTML
    assert "应用到全部图片" in _HELP_HTML
    assert "填的是像素（px），不是倍数" in _HELP_HTML
    assert "相对位置" in _HELP_HTML
    assert "更新 OCR 原文" in _HELP_HTML
