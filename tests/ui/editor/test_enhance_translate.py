"""强化翻译自动化与提示词组装测试。"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from src.domain.layout import TextLayer, TextBox, TextLayout, TextStyle
from src.domain.translation import TranslationResult, TranslationSelection, TranslationMode, TranslationStatus, TranslationUnit
from src.ui.enhance.prompt_builder import build_prompt


def test_build_prompt_with_translation_pairs():
    ocr = type(
        "Ocr",
        (),
        {
            "regions": (
                type("R", (), {"region_id": "r1", "text": "SUMMER"})(),
                type("R", (), {"region_id": "r2", "text": "SALE"})(),
            ),
        },
    )()
    units = (
        TranslationUnit("r1", "SUMMER", "en", "zh-Hans", "夏季大促", TranslationStatus.TRANSLATED),
        TranslationUnit("r2", "SALE", "en", "zh-Hans", "特价", TranslationStatus.TRANSLATED),
    )
    result = TranslationResult(units, TranslationSelection(TranslationMode.ALL, "zh-Hans"), "fake", 1.0)

    prompt = build_prompt(ocr, result)

    assert "SUMMER → 夏季大促" in prompt
    assert "SALE → 特价" in prompt
    assert "版式" in prompt


def test_build_prompt_without_translation_uses_generic_template():
    prompt = build_prompt(None, None, "zh-Hans")
    assert "翻译成中文（简体）" in prompt
    assert "版式" in prompt


def test_build_prompt_names_target_language_in_chinese():
    """指令保持中文（客户要能看懂能改），只把目标语言名写进方向里。"""
    prompt = build_prompt(None, None, "en")
    assert "翻译成英语" in prompt
    assert "Translate" not in prompt


def test_build_prompt_unknown_language_falls_back_to_default_target():
    prompt = build_prompt(None, None, "xx-unknown")
    assert "翻译成中文（简体）" in prompt


def test_build_prompt_names_translation_direction():
    """原图不一定是中文：方向要写成「把{原图文字语言}翻译成{目标语言}」。"""
    ocr = type(
        "Ocr",
        (),
        {
            "language_code": "ru",
            "regions": (type("R", (), {"region_id": "r1", "text": "РАСПРОДАЖА"})(),),
        },
    )()
    units = (
        TranslationUnit("r1", "РАСПРОДАЖА", "ru", "en", "SALE", TranslationStatus.TRANSLATED),
    )
    result = TranslationResult(units, TranslationSelection(TranslationMode.ALL, "en"), "fake", 1.0)

    prompt = build_prompt(ocr, result)

    assert "把图中俄语文字翻译成英语" in prompt
    assert "РАСПРОДАЖА → SALE" in prompt


def test_build_prompt_source_language_param_wins_over_ocr_code():
    """面板当前选的原图文字语言优先于 OCR 结果里记录的。"""
    ocr = type("Ocr", (), {"language_code": "ru", "regions": ()})()

    prompt = build_prompt(ocr, None, "en", source_language="ja")

    assert "把这张图片中的所有日语文字翻译成英语" in prompt


def test_build_prompt_prefers_translation_result_language():
    """译文自带的目标语言优先于面板当前选择：对照表里的译文就是那个语言写的。"""
    ocr = type("Ocr", (), {"regions": (type("R", (), {"region_id": "r1", "text": "SUMMER"})(),)})()
    units = (
        TranslationUnit("r1", "SUMMER", "en", "ja", "サマー", TranslationStatus.TRANSLATED),
    )
    result = TranslationResult(units, TranslationSelection(TranslationMode.ALL, "ja"), "fake", 1.0)

    prompt = build_prompt(ocr, result, "en")

    assert "翻译成日语" in prompt
    assert "SUMMER → サマー" in prompt


def test_main_window_enhance_flow_requires_browser_or_degrades(monkeypatch):
    """offscreen 下浏览器为占位（无 set_source_image）→ 点击图片给降级提示。"""
    from tests.ui.editor.test_watermark_removal_quota import _SyncTaskRunner
    from src.ui.editor.main_window import EditorMainWindow

    QApplication.instance() or QApplication(["enhance-flow-test"])
    window = EditorMainWindow(
        import_image=object(),
        task_runner=_SyncTaskRunner(),
    )
    try:
        window._enter_editor()
        # 无文档时先导入一张
        import numpy as np
        from pathlib import Path as _Path
        from src.domain.image import ImageAsset, ImageDocument, ImageFileFormat

        asset = ImageAsset(_Path("a.png"), 40, 30, 1, ImageFileFormat.PNG, False, False)
        doc = ImageDocument(asset, "RGB", bytes(np.full((30, 40, 3), 255, dtype=np.uint8)))
        window._model.add_document(_Path("a.png"), doc, name="a.png")
        window._on_activate_document(window._model.active_document_id)
        window._editor_page.toolbar.set_active_tool("enhance_translate")

        window._on_enhance_document_activated()

        status = window._editor_page.enhance_panel.automation_status.text()
        # offscreen 占位无 set_source_image → 降级提示
        assert "手动" in status or "缺少" in status
    finally:
        window.close()


def test_toolbar_enhance_translate_click_only_enters_mode():
    """点击工具栏「强化翻译」只切页 + 点亮按钮，不得自动上传/填词。

    自动化入口是「点击左侧列表里的图片」（用户反馈：每次进入强化翻译
    没点图就会自动上传/填词）。
    """
    from types import SimpleNamespace

    from tests.ui.editor.test_watermark_removal_quota import _SyncTaskRunner
    from src.ui.editor.main_window import EditorMainWindow
    import numpy as np
    from pathlib import Path as _Path
    from src.domain.image import ImageAsset, ImageDocument, ImageFileFormat

    QApplication.instance() or QApplication(["enhance-toolbar-test"])
    window = EditorMainWindow(
        import_image=object(),
        task_runner=_SyncTaskRunner(),
    )
    try:
        window._enter_editor()
        asset = ImageAsset(_Path("a.png"), 40, 30, 1, ImageFileFormat.PNG, False, False)
        doc = ImageDocument(asset, "RGB", bytes(np.full((30, 40, 3), 255, dtype=np.uint8)))
        window._model.add_document(_Path("a.png"), doc, name="a.png")
        panel = window._editor_page.enhance_panel

        calls: list[str] = []
        window._editor_page.enhance_browser = SimpleNamespace(
            set_source_image=lambda path: calls.append(f"set:{path}"),
            load_doubao=lambda: calls.append("load"),
            run_action_when_ready=lambda *a, **k: calls.append("run"),
            begin_flow=lambda: calls.append("begin"),
        )

        window._editor_page.toolbar.buttons["enhance_translate"].click()

        assert calls == [], f"进入模式不应触发自动化，实际调用了 {calls}"
        assert "点击左侧列表中的图片" in panel.automation_status.text()
        assert window._editor_page.canvas_stack.currentIndex() == 1
        # 点击后按钮必须保持点亮（变蓝），否则用户不知道当前处于强化翻译模式
        assert window._editor_page.toolbar.buttons["enhance_translate"].isChecked()
    finally:
        window.close()


def test_enhance_click_without_document_keeps_button_lit():
    """没有图片时点「强化翻译」也要保持点亮。

    工具栏先发 feature_requested 再发 tool_changed，后者已经把画布与右侧面板
    切到强化翻译；此时若把工具退回「选择」，高亮就和实际模式对不上——用户看到
    的是「点了强化翻译没变蓝，但AI页面已经开了」。
    """
    from tests.ui.editor.test_watermark_removal_quota import _SyncTaskRunner
    from src.ui.editor.main_window import EditorMainWindow

    QApplication.instance() or QApplication(["enhance-no-doc-test"])
    window = EditorMainWindow(import_image=object(), task_runner=_SyncTaskRunner())
    try:
        window._enter_editor()
        window._editor_page.toolbar.buttons["enhance_translate"].click()

        toolbar = window._editor_page.toolbar
        assert toolbar.buttons["enhance_translate"].isChecked()
        assert not toolbar.buttons["select"].isChecked()
        assert toolbar.active_tool == "enhance_translate"
        assert window._editor_page.canvas_stack.currentIndex() == 1
        assert "导入图片" in window._editor_page.enhance_panel.automation_status.text()
    finally:
        window.close()


def test_right_panel_survives_switching_to_browser():
    """切到豆包浏览器时右侧面板（含解析链接框）必须还在。

    画布栈曾经罩住整块中央区，切豆包会把右侧面板一起换掉，用户看到的是
    「解析链接没了」。
    """
    from tests.ui.editor.test_watermark_removal_quota import _SyncTaskRunner
    from src.ui.editor.main_window import EditorMainWindow
    import numpy as np
    from pathlib import Path as _Path
    from src.domain.image import ImageAsset, ImageDocument, ImageFileFormat

    QApplication.instance() or QApplication(["enhance-right-panel-test"])
    window = EditorMainWindow(import_image=object(), task_runner=_SyncTaskRunner())
    try:
        window._enter_editor()
        asset = ImageAsset(_Path("a.png"), 40, 30, 1, ImageFileFormat.PNG, False, False)
        doc = ImageDocument(asset, "RGB", bytes(np.full((30, 40, 3), 255, dtype=np.uint8)))
        window._model.add_document(_Path("a.png"), doc, name="a.png")
        window.resize(1280, 800)
        window.show()

        page = window._editor_page
        page.toolbar.buttons["enhance_translate"].click()
        QApplication.processEvents()

        assert page.canvas_stack.currentIndex() == 1
        assert page.right_panel.isVisible()
        assert page.layer_tools_stack.currentWidget() is page.enhance_panel
        assert page.enhance_panel.link.isVisible()
    finally:
        window.close()


def test_clicking_image_with_browser_on_screen_triggers_automation():
    """豆包已在中央显示时，点击左侧图片即触发自动化。

    用户可见的失败模式是「点了没反应」：工具状态与画布不同步时不能静默跳过。
    """
    from tests.ui.editor.test_watermark_removal_quota import _SyncTaskRunner
    from src.ui.editor.main_window import EditorMainWindow
    import numpy as np
    from pathlib import Path as _Path
    from src.domain.image import ImageAsset, ImageDocument, ImageFileFormat

    QApplication.instance() or QApplication(["enhance-browser-on-test"])
    window = EditorMainWindow(import_image=object(), task_runner=_SyncTaskRunner())
    try:
        window._enter_editor()
        asset = ImageAsset(_Path("a.png"), 40, 30, 1, ImageFileFormat.PNG, False, False)
        doc = ImageDocument(asset, "RGB", bytes(np.full((30, 40, 3), 255, dtype=np.uint8)))
        window._model.add_document(_Path("a.png"), doc, name="a.png")

        panel = window._editor_page.enhance_panel
        panel.automation_status.setText("未开始")
        window._editor_page.show_enhance_browser(True)
        window._editor_page.toolbar.set_active_tool("select")

        window._on_enhance_document_activated()

        status = panel.automation_status.text()
        assert status != "未开始"
        assert "手动" in status or "缺少" in status or "连接豆包" in status
    finally:
        window.close()


def test_importing_parsed_result_does_not_upload_to_doubao():
    """「导入选中到编辑器」不得触发上传：导入会激活新文档，那不是用户点列表。

    否则解析出的成品图会被立刻再传给豆包，形成导入→上传→再生成的死循环。
    """
    from types import SimpleNamespace

    from tests.ui.editor.test_watermark_removal_quota import _SyncTaskRunner
    from src.ui.editor.main_window import EditorMainWindow
    import numpy as np
    from pathlib import Path as _Path
    from src.domain.image import ImageAsset, ImageDocument, ImageFileFormat

    QApplication.instance() or QApplication(["enhance-import-test"])
    window = EditorMainWindow(import_image=object(), task_runner=_SyncTaskRunner())
    try:
        window._enter_editor()

        def _doc(name: str) -> ImageDocument:
            asset = ImageAsset(_Path(name), 40, 30, 1, ImageFileFormat.PNG, False, False)
            return ImageDocument(asset, "RGB", bytes(np.full((30, 40, 3), 255, dtype=np.uint8)))

        window._model.add_document(_Path("a.png"), _doc("a.png"), name="a.png")
        window._editor_page.toolbar.set_active_tool("enhance_translate")

        calls: list[str] = []
        window._editor_page.enhance_browser = SimpleNamespace(
            set_source_image=lambda path: calls.append(f"set:{path}"),
            load_doubao=lambda: calls.append("load"),
            run_action_when_ready=lambda *a, **k: calls.append("run"),
        )
        panel = window._editor_page.enhance_panel
        panel.automation_status.setText("导入前")

        # 导入解析结果的落地路径：_on_image_loaded → add_document → 激活新文档
        window._on_image_loaded(_doc("parsed.png"))

        assert calls == [], f"导入不该重新上传豆包，实际调用了 {calls}"
        assert panel.automation_status.text() == "导入前"
    finally:
        window.close()


def test_clicking_left_list_image_uploads_to_doubao():
    """对照组：点左侧列表里的图片仍要触发上传（唯一的自动化入口）。"""
    from types import SimpleNamespace

    from tests.ui.editor.test_watermark_removal_quota import _SyncTaskRunner
    from src.ui.editor.main_window import EditorMainWindow
    import numpy as np
    from pathlib import Path as _Path
    from src.domain.image import ImageAsset, ImageDocument, ImageFileFormat

    QApplication.instance() or QApplication(["enhance-list-click-test"])
    window = EditorMainWindow(import_image=object(), task_runner=_SyncTaskRunner())
    try:
        window._enter_editor()

        def _doc(name: str) -> ImageDocument:
            asset = ImageAsset(_Path(name), 40, 30, 1, ImageFileFormat.PNG, False, False)
            return ImageDocument(asset, "RGB", bytes(np.full((30, 40, 3), 255, dtype=np.uint8)))

        window._model.add_document(_Path("a.png"), _doc("a.png"), name="a.png")
        window._model.add_document(_Path("b.png"), _doc("b.png"), name="b.png")
        window._editor_page.toolbar.set_active_tool("enhance_translate")

        calls: list[str] = []
        window._editor_page.enhance_browser = SimpleNamespace(
            set_source_image=lambda path: calls.append(f"set:{_Path(path).name}"),
            load_doubao=lambda: calls.append("load"),
            run_action_when_ready=lambda *a, **k: calls.append("run"),
        )
        # 强化翻译工具处于激活态（豆包占着中央），只清掉工具激活本身产生的那次调用
        calls.clear()

        panel = window._editor_page.image_list_panel
        # 模拟点击列表里另一张图：itemPressed → currentItemChanged → itemClicked
        target = next(
            item for doc_id, item in panel._items.items()
            if doc_id != window._model.active_document_id
        )
        panel._on_item_pressed(target)
        panel._list.setCurrentItem(target)
        panel._on_item_clicked(target)

        assert f"set:{target.text()}" in calls
        assert "load" in calls
    finally:
        window.close()


def test_enhance_activation_degrades_when_source_unreadable():
    """原始图读取失败时给降级提示，而非静默中断（用户表现为「点击没反应」）。"""
    from types import SimpleNamespace

    from tests.ui.editor.test_watermark_removal_quota import _SyncTaskRunner
    from src.ui.editor.main_window import EditorMainWindow
    import numpy as np
    from pathlib import Path as _Path
    from src.domain.image import ImageAsset, ImageDocument, ImageFileFormat

    QApplication.instance() or QApplication(["enhance-unreadable-test"])
    window = EditorMainWindow(
        import_image=object(),
        task_runner=_SyncTaskRunner(),
    )
    try:
        window._enter_editor()
        asset = ImageAsset(_Path("a.png"), 40, 30, 1, ImageFileFormat.PNG, False, False)
        doc = ImageDocument(asset, "RGB", bytes(np.full((30, 40, 3), 255, dtype=np.uint8)))
        window._model.add_document(_Path("a.png"), doc, name="a.png")

        def _boom(path):
            raise FileNotFoundError(str(path))

        window._editor_page.enhance_browser = SimpleNamespace(
            set_source_image=_boom,
            load_doubao=lambda: None,
            run_action_when_ready=lambda *a, **k: None,
        )
        window._editor_page.toolbar.set_active_tool("enhance_translate")

        window._on_enhance_document_activated()

        status = window._editor_page.enhance_panel.automation_status.text()
        assert "手动" in status
    finally:
        window.close()


def test_run_action_decodes_json_result():
    """JS 返回 JSON 字符串时解析为 dict。

    runJavaScript 无法把 JS 对象转成 Python dict（回调收到空字符串），
    因此页面动作统一 JSON.stringify，由 Python 侧解码。
    """
    from types import SimpleNamespace

    from src.ui.enhance.browser_panel import EnhanceTranslateBrowser

    received = []
    browser = SimpleNamespace(
        _page=SimpleNamespace(
            runJavaScript=lambda script, world, cb: cb(
                '{"ok": true, "stage": "check_page", "detail": "ready"}'
            )
        )
    )
    EnhanceTranslateBrowser.run_action(browser, "check_page", callback=received.append)

    assert received == [{"ok": True, "stage": "check_page", "detail": "ready"}]


def test_run_action_passes_through_non_json_result():
    """非 JSON 字符串原样回传（如脚本执行失败返回 undefined→None）。"""
    from types import SimpleNamespace

    from src.ui.enhance.browser_panel import EnhanceTranslateBrowser

    received = []
    browser = SimpleNamespace(
        _page=SimpleNamespace(runJavaScript=lambda script, world, cb: cb(None))
    )
    EnhanceTranslateBrowser.run_action(browser, "check_page", callback=received.append)

    assert received == [None]


def test_all_js_actions_return_json_strings():
    """每个页面动作都必须 JSON.stringify 返回，否则结果丢失。"""
    from src.ui.enhance.browser_panel import JS_ACTIONS

    for name, script in JS_ACTIONS.items():
        assert "JSON.stringify" in script, f"{name} 未 JSON 序列化返回值"


def test_run_action_waits_for_page_load():
    """页面未加载完成时动作暂存，loadFinished 后自动执行（首次点击即生效）。"""
    from functools import partial
    from types import SimpleNamespace

    from src.ui.enhance.browser_panel import EnhanceTranslateBrowser

    calls: list[tuple] = []
    browser = SimpleNamespace(
        _load_finished=False,
        _pending_action=None,
        run_action=lambda name, payload=None, callback=None: calls.append(
            (name, payload)
        ),
    )
    browser._when_ready = partial(EnhanceTranslateBrowser._when_ready, browser)

    EnhanceTranslateBrowser.run_action_when_ready(browser, "check_page")
    assert calls == []

    EnhanceTranslateBrowser._on_load_finished(browser, True)
    assert calls == [("check_page", None)]


def _png_bytes() -> bytes:
    from PySide6.QtCore import QBuffer, QIODevice
    from PySide6.QtGui import QImage

    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    QImage(20, 10, QImage.Format.Format_RGB32).save(buffer, "PNG")
    return bytes(buffer.data())


class _FakePage:
    """按脚本内的 stage 标记回放 JSON 结果的假 QWebEnginePage。"""

    def __init__(
        self,
        counts: list[int],
        input_lengths: list[int] | None = None,
    ) -> None:
        self.counts = list(counts)
        self.pasted = 0
        # 输入框文本长度脚本；用尽后固定为 3（有内容 = 用户尚未发送）
        self.input_lengths = list(input_lengths or [])

    def runJavaScript(self, script, world, callback):  # noqa: N802
        import json
        import re

        match = re.search(r'stage: "(\w+)"', script)
        stage = match.group(1) if match else ""
        if stage in {"blob_image_count", "large_image_count"}:
            count = self.counts.pop(0) if self.counts else 0
            payload = {"ok": True, "stage": stage, "detail": "counted", "count": count}
        elif stage == "input_state":
            length = self.input_lengths.pop(0) if self.input_lengths else 3
            payload = {"ok": True, "stage": stage, "detail": "has-text", "textLength": length}
        else:
            payload = {"ok": True, "stage": stage, "detail": "ok"}
        callback(json.dumps(payload))

    def triggerAction(self, action):  # noqa: N802
        self.pasted += 1


class _SharePage:
    """分享流程的假页面：复刻「图标认不出、只能悬浮读 tooltip」的真实形态。

    - 消息操作栏里只有第 share_index 个图标的 tooltip 是「分享」；
    - 点过它才进入选择态、底部工具栏才出现「复制链接」；
    - 点「复制链接」才把链接写进系统剪贴板。
    """

    def __init__(
        self,
        clipboard_text: str = "https://www.doubao.com/thread/wxyz",
        row_count: int = 6,
        share_index: int = 5,
        action_row: bool = True,
        fail_first_copy: bool = False,
        prompt_fallback: str = "",
        fail_copies: int = 0,
        initial_selection: bool = False,
    ) -> None:
        self.clipboard_text = clipboard_text
        self.row_count = row_count
        self.share_index = share_index
        self.action_row = action_row
        self.fail_first_copy = fail_first_copy
        # 前 N 次点「复制链接」一律点不到（模拟对话框/按钮渲染慢）
        self.fail_copies = fail_copies
        # 剪贴板写入被拒时页面会退化成 window.prompt，值记在这里（见 _DialogSafePage）
        self.prompt_fallback = prompt_fallback
        self.prompt_value = ""
        # 上一轮残留的「选择对话」弹窗：开跑前选择态还开着
        self.selection_mode = initial_selection
        self.hovers: list[int] = []
        self.copy_clicks = 0
        self.icon_clicks = 0
        self.dismiss_clicks = 0

    def runJavaScript(self, script, world, callback=None):  # noqa: N802
        import json
        import re

        def reply(payload):
            # 预清残留弹窗的 dismiss 脚本不带回调（fire-and-forget）
            if callback is not None:
                callback(json.dumps(payload))

        if '[role="tooltip"]' in script:
            index = self.hovers[-1] if self.hovers else -1
            text = "分享" if index == self.share_index else "复制"
            reply({"ok": True, "stage": "share_icon", "detail": "read",
                   "tips": [{"text": text, "cx": self._cx(index)}]})
            return
        if "pointerover" in script:
            index = int(re.search(r"row\[(\d+)\]", script).group(1))
            self.hovers.append(index)
            reply({"ok": True, "stage": "share_icon", "detail": "hovered",
                   "cx": self._cx(index)})
            return
        if "复制链接" in script:
            self.copy_clicks += 1
            if (
                not self.selection_mode
                or (self.fail_first_copy and self.copy_clicks == 1)
                or self.copy_clicks <= self.fail_copies
            ):
                reply({"ok": False, "stage": "copy_link",
                       "detail": "copy-link-not-found"})
                return
            if self.prompt_fallback:
                self.prompt_value = self.prompt_fallback
            else:
                QApplication.clipboard().setText(self.clipboard_text)
            reply({"ok": True, "stage": "copy_link", "detail": "clicked"})
            return
        if "取消" in script:  # dismiss_selection
            self.dismiss_clicks += 1
            self.selection_mode = False
            reply({"ok": True, "stage": "dismiss", "detail": "cancelled"})
            return
        if "count: row.length" in script:  # action_row_size
            if not self.action_row:
                reply({"ok": False, "stage": "share_icon",
                       "detail": "action-row-not-found"})
                return
            reply({"ok": True, "stage": "share_icon", "detail": "found",
                   "count": self.row_count})
            return
        if re.search(r"row\[\d+\]", script):  # 点「分享」图标
            self.selection_mode = True
            self.icon_clicks += 1
            reply({"ok": True, "stage": "share_icon", "detail": "clicked"})
            return
        reply({"ok": True, "stage": "other", "detail": "ok"})

    @staticmethod
    def _cx(index: int) -> int:
        return index * 34 + 220


def _fake_browser(page: _FakePage, **attrs):
    """把浏览器实例方法挂到 SimpleNamespace 上，避免真的建 Chromium。"""
    from functools import partial
    from types import SimpleNamespace

    from src.ui.enhance.browser_panel import EnhanceTranslateBrowser

    fake = SimpleNamespace(
        _load_finished=True, _pending_action=None, _page=page,
        _blob_baseline=0, _result_baseline=0, _source_bytes=None,
        _share_run=0, _share_icon_index=None, _flow_run=0,
        _share_icon_clicked=False,
        _view=SimpleNamespace(setFocus=lambda: None),
        _overlay=SimpleNamespace(hide=lambda: None, isVisible=lambda: False),
    )
    for key, value in attrs.items():
        setattr(fake, key, value)
    for name in (
        "_when_ready",
        "_poll_until",
        "_paste_image",
        "_paste_image_now",
        "_paste_text",
        "_paste_and_verify",
        "_after_focus",
        "_await_manual_send",
        "_await_generated_images",
        "_retry_or_fail",
        "_run_js",
        "_clipboard_link",
        "_share_link_from_prompt",
        "_share_attempt",
        "_share_after_copy",
        "_share_after_row_size",
        "_share_hover_next",
        "_share_after_hover",
        "_share_after_tooltip",
        "begin_flow",
        "_clear_then_paste",
        "_clear_text_then_paste",
        "_await_clipboard_after_copy",
        "_dismiss_selection_state",
    ):
        setattr(fake, name, partial(getattr(EnhanceTranslateBrowser, name), fake))
    fake.run_action = partial(EnhanceTranslateBrowser.run_action, fake)
    fake._emit = EnhanceTranslateBrowser._emit
    fake._is_share_tooltip = partial(
        EnhanceTranslateBrowser._is_share_tooltip, fake
    )
    return fake


def test_upload_source_image_pastes_clipboard_image(qtbot):
    """原始图走系统剪贴板 + 真实 Paste 动作，附件出现后回调成功。

    合成 ClipboardEvent 豆包会忽略（isTrusted=false），必须用 Paste 动作。
    """
    from src.ui.enhance.browser_panel import EnhanceTranslateBrowser

    page = _FakePage(counts=[0, 1])  # 粘贴前 0 张附件，粘贴后 1 张
    fake = _fake_browser(page, _source_bytes=_png_bytes())

    results: list = []
    EnhanceTranslateBrowser.upload_source_image(fake, callback=results.append)
    qtbot.waitUntil(lambda: bool(results), timeout=5000)

    assert results[0]["ok"] is True
    assert page.pasted == 1
    assert not QApplication.clipboard().image().isNull()


def test_upload_retries_paste_when_attachment_missing(qtbot, monkeypatch):
    """首次粘贴没挂上附件（Windows 剪贴板偶发被占用）→ 重新 setImage 再贴一次。"""
    from src.ui import enhance
    from src.ui.enhance.browser_panel import EnhanceTranslateBrowser

    monkeypatch.setattr(enhance.browser_panel, "_PASTE_VERIFY_TIMEOUT_MS", 40)
    page = _FakePage(counts=[0, 0, 0, 0, 1])
    fake = _fake_browser(page, _source_bytes=_png_bytes())

    results: list = []
    EnhanceTranslateBrowser.upload_source_image(fake, callback=results.append)
    qtbot.waitUntil(lambda: bool(results), timeout=8000)

    assert results[0]["ok"] is True
    assert page.pasted == 2


def test_upload_degrades_when_image_unreadable():
    """原始图解码失败立即降级，不触碰页面。"""
    from src.ui.enhance.browser_panel import EnhanceTranslateBrowser

    page = _FakePage(counts=[])
    fake = _fake_browser(page, _source_bytes=b"not-an-image")

    results: list = []
    EnhanceTranslateBrowser.upload_source_image(fake, callback=results.append)

    assert results[0]["ok"] is False
    assert results[0]["detail"] == "image-unreadable"
    assert page.pasted == 0


def test_wait_for_manual_send_detects_user_click(qtbot):
    """程序不点发送：等用户点完后输入框清空即视为已发出。"""
    from src.ui.enhance.browser_panel import EnhanceTranslateBrowser

    page = _FakePage(counts=[1], input_lengths=[3, 3, 0])
    fake = _fake_browser(page)

    results: list = []
    EnhanceTranslateBrowser.wait_for_manual_send(
        fake, callback=results.append, timeout_ms=5000, interval_ms=10
    )
    qtbot.waitUntil(lambda: bool(results), timeout=5000)

    assert results[0]["ok"] is True
    assert results[0]["stage"] == "send"
    assert fake._result_baseline == 1  # 结果基线取自发送前


def test_wait_for_manual_send_times_out_when_user_never_sends(qtbot):
    from src.ui.enhance.browser_panel import EnhanceTranslateBrowser

    page = _FakePage(counts=[1], input_lengths=[3, 3, 3, 3])
    fake = _fake_browser(page)

    results: list = []
    EnhanceTranslateBrowser.wait_for_manual_send(
        fake, callback=results.append, timeout_ms=40, interval_ms=10
    )
    qtbot.waitUntil(lambda: bool(results), timeout=5000)

    assert results[0]["ok"] is False
    assert results[0]["detail"] == "not-sent"


def test_wait_for_result_waits_for_second_growth(qtbot):
    """发送后第一条增长是自己消息里的上传原图回显，再次增长才算生成完成。"""
    from src.ui.enhance.browser_panel import EnhanceTranslateBrowser

    page = _FakePage(counts=[2, 3])  # 基线 1 → 回显 2 → 生成图 3
    fake = _fake_browser(page, _result_baseline=1)

    results: list = []
    EnhanceTranslateBrowser.wait_for_result(
        fake, callback=results.append, timeout_ms=5000, interval_ms=10
    )
    qtbot.waitUntil(lambda: bool(results), timeout=5000)

    assert results[0]["ok"] is True
    assert fake._result_baseline == 2  # 基线已抬到回显水位
    assert page.counts == []


def test_wait_for_result_ignores_send_echo(qtbot):
    """只有回显、没有生成图时不得判定完成（否则链接抓得太早，快照缺图）。"""
    from src.ui.enhance.browser_panel import EnhanceTranslateBrowser

    page = _FakePage(counts=[2, 2, 2])  # 回显后再无增长
    fake = _fake_browser(page, _result_baseline=1)

    results: list = []
    EnhanceTranslateBrowser.wait_for_result(
        fake, callback=results.append, timeout_ms=60, interval_ms=10
    )
    qtbot.waitUntil(lambda: bool(results), timeout=5000)

    assert results[0]["ok"] is False
    assert fake._result_baseline == 2


def test_wait_for_result_simultaneous_growth_counts_as_done(qtbot):
    """回显与生成图同帧渲染（一次涨 ≥2 张）直接算完成。"""
    from src.ui.enhance.browser_panel import EnhanceTranslateBrowser

    page = _FakePage(counts=[3])
    fake = _fake_browser(page, _result_baseline=1)

    results: list = []
    EnhanceTranslateBrowser.wait_for_result(
        fake, callback=results.append, timeout_ms=5000, interval_ms=10
    )
    qtbot.waitUntil(lambda: bool(results), timeout=5000)

    assert results[0]["ok"] is True
    assert page.counts == []


def test_wait_for_result_times_out_without_new_image(qtbot):
    from src.ui.enhance.browser_panel import EnhanceTranslateBrowser

    page = _FakePage(counts=[1, 1, 1, 1])
    fake = _fake_browser(page, _result_baseline=1)

    results: list = []
    EnhanceTranslateBrowser.wait_for_result(
        fake, callback=results.append, timeout_ms=40, interval_ms=10
    )
    qtbot.waitUntil(lambda: bool(results), timeout=5000)

    assert results[0]["ok"] is False
    assert results[0]["detail"] == "timeout"


def test_begin_flow_stops_previous_poll(qtbot):
    """begin_flow 后旧轮询静默退出，不再改基线，也不再回调。"""
    from src.ui.enhance.browser_panel import EnhanceTranslateBrowser

    page = _FakePage(counts=[1])
    fake = _fake_browser(page, _result_baseline=1)

    results: list = []
    EnhanceTranslateBrowser.wait_for_result(
        fake, callback=results.append, timeout_ms=50, interval_ms=10
    )
    fake.begin_flow()
    qtbot.wait(80)
    assert results == []

    # 新一轮仍能正常检测到增长
    page.counts = [2, 3]
    EnhanceTranslateBrowser.wait_for_result(
        fake, callback=results.append, timeout_ms=5000, interval_ms=10
    )
    qtbot.waitUntil(lambda: bool(results), timeout=5000)
    assert results[0]["ok"] is True


def test_begin_flow_bumps_share_run(qtbot):
    """新一轮自动化要一并作废抓分享链接的状态机。"""
    fake = _fake_browser(_FakePage(counts=[]))
    before = fake._share_run
    fake.begin_flow()
    assert fake._share_run == before + 1
    assert fake._flow_run == 1


def test_upload_clears_input_before_paste(qtbot):
    """贴图前先 clear_input：残留附件/旧提示词是「一次点出两份」的直接原因。"""
    import re

    from src.ui.enhance.browser_panel import EnhanceTranslateBrowser

    page = _FakePage(counts=[0, 1])
    fake = _fake_browser(page, _source_bytes=_png_bytes())
    stages: list[str] = []
    original = page.runJavaScript

    def spy(script, world, callback):
        match = re.search(r'stage: "(\w+)"', script)
        if match:
            stages.append(match.group(1))
        original(script, world, callback)

    page.runJavaScript = spy

    results: list = []
    EnhanceTranslateBrowser.upload_source_image(fake, callback=results.append)
    qtbot.waitUntil(lambda: bool(results), timeout=5000)

    assert stages[0] == "clear_input"
    assert results[0]["ok"] is True
    assert page.pasted == 1


def _fast_share(monkeypatch):
    """把悬浮/选择态的等待压到毫秒级，免得测试等真实渲染时长。"""
    from src.ui import enhance

    monkeypatch.setattr(enhance.browser_panel, "_HOVER_SETTLE_MS", 5)
    monkeypatch.setattr(enhance.browser_panel, "_SHARE_CLICK_SETTLE_MS", 5)
    monkeypatch.setattr(enhance.browser_panel, "_PRE_DISMISS_SETTLE_MS", 5)
    monkeypatch.setattr(enhance.browser_panel, "_DISMISS_ESCAPE_AFTER_MS", 5)


def test_get_share_link_hovers_icons_to_find_share(qtbot, monkeypatch):
    """「分享」图标没有 aria-label/文字，只能逐个悬浮读 tooltip 认出来。

    链接不是 DOM 里的 <a>，只能走剪贴板；剪贴板可能夹带「复制成功」等文案。
    """
    from src.ui.enhance.browser_panel import EnhanceTranslateBrowser

    _fast_share(monkeypatch)
    page = _SharePage(clipboard_text="已复制：https://www.doubao.com/thread/wabc123 快去分享")
    fake = _fake_browser(page)

    results: list = []
    EnhanceTranslateBrowser.get_share_link(
        fake, callback=results.append, timeout_ms=3000, interval_ms=10
    )
    qtbot.waitUntil(lambda: bool(results), timeout=8000)

    assert results[0]["ok"] is True
    assert results[0]["detail"] == "https://www.doubao.com/thread/wabc123"
    # 前面 5 个图标的 tooltip 都不是「分享」，第 6 个才是
    assert page.hovers == [0, 1, 2, 3, 4, 5]
    # 先探一次「复制链接」（工具栏还没出现），点开「分享」后再点才成功
    assert page.copy_clicks == 2


def test_get_share_link_retries_when_toolbar_not_ready(qtbot, monkeypatch):
    """底部工具栏「复制链接」首次点不到（还没渲染出来）→ 重试后成功。"""
    from src.ui.enhance.browser_panel import EnhanceTranslateBrowser

    _fast_share(monkeypatch)
    page = _SharePage(fail_first_copy=True)
    fake = _fake_browser(page)

    results: list = []
    EnhanceTranslateBrowser.get_share_link(
        fake, callback=results.append, timeout_ms=5000, interval_ms=10
    )
    qtbot.waitUntil(lambda: bool(results), timeout=8000)

    assert results[0]["ok"] is True
    assert page.copy_clicks >= 2


def test_get_share_link_slow_dialog_keeps_retrying_copy_without_reclicking_icon(
    qtbot, monkeypatch
):
    """点过「分享」后「复制链接」迟迟渲染不出来：只重试点按钮，不得再点图标。

    真机上再点一次「分享」图标会把已打开的对话框关掉——旧逻辑每失败一轮就
    回头找图标再点，对话框反复开关，永远点不到「复制链接」（用户反馈生成后
    无法自动取链接，手动打开才行）。
    """
    from src.ui.enhance.browser_panel import EnhanceTranslateBrowser

    _fast_share(monkeypatch)
    page = _SharePage(fail_copies=3)
    fake = _fake_browser(page)

    results: list = []
    EnhanceTranslateBrowser.get_share_link(
        fake, callback=results.append, timeout_ms=5000, interval_ms=10
    )
    qtbot.waitUntil(lambda: bool(results), timeout=8000)

    assert results[0]["ok"] is True
    assert page.icon_clicks == 1, "对话框已打开时不得再点「分享」图标"
    assert page.copy_clicks >= 4


def test_get_share_link_times_out_when_clipboard_has_no_link(qtbot, monkeypatch):
    """剪贴板里没有豆包分享链接（复制失败/被改版）时超时降级，不误报成功。"""
    from src.ui.enhance.browser_panel import EnhanceTranslateBrowser

    _fast_share(monkeypatch)
    page = _SharePage(clipboard_text="与豆包无关的文本")
    fake = _fake_browser(page)

    results: list = []
    EnhanceTranslateBrowser.get_share_link(
        fake, callback=results.append, timeout_ms=400, interval_ms=10
    )
    qtbot.waitUntil(lambda: bool(results), timeout=8000)

    assert results[0]["ok"] is False
    assert results[0]["detail"] == "link-not-found"


def test_copy_success_polls_clipboard_before_second_click(qtbot, monkeypatch):
    """点中「复制链接」后剪贴板异步写入：窗口内只读，不得立刻再点一次。"""
    from src.ui import enhance
    from src.ui.enhance.browser_panel import EnhanceTranslateBrowser

    monkeypatch.setattr(enhance.browser_panel, "_COPY_WRITE_WAIT_MS", 1500)
    monkeypatch.setattr(enhance.browser_panel, "_COPY_POLL_MS", 30)
    _fast_share(monkeypatch)

    page = _SharePage(clipboard_text="")  # 点复制时不立刻写剪贴板
    # 覆盖：点中复制 → 延迟 200ms 后才写入链接。选择态由流程自己点开
    # （预清残留弹窗会先关掉预设的选择态——残留对话框属于旧消息，不该用它取新链接）
    original = page.runJavaScript

    def delayed_copy(script, world, callback=None):
        if "复制链接" in script:
            page.copy_clicks += 1
            if not page.selection_mode:
                import json
                callback(json.dumps(
                    {"ok": False, "stage": "copy_link", "detail": "copy-link-not-found"}
                ))
                return

            def flush():
                QApplication.clipboard().setText(
                    page.clipboard_text or "https://www.doubao.com/thread/wxyz"
                )

            from PySide6.QtCore import QTimer

            QTimer.singleShot(200, flush)
            import json
            callback(json.dumps({"ok": True, "stage": "copy_link", "detail": "clicked"}))
            return
        original(script, world, callback)

    page.runJavaScript = delayed_copy
    fake = _fake_browser(page)

    QApplication.clipboard().clear()
    results: list = []
    EnhanceTranslateBrowser.get_share_link(
        fake, callback=results.append, timeout_ms=5000, interval_ms=10
    )
    qtbot.waitUntil(lambda: bool(results), timeout=8000)

    assert results[0]["ok"] is True
    # copy_clicks = 1 次开跑前的探测（无选择态必然点不到）+ 1 次真正点中。
    # 写入在等待窗口内完成 → 点中后不得再点第二次复制
    assert page.copy_clicks == 2
    assert page.icon_clicks == 1


def test_get_share_link_degrades_when_action_row_missing(qtbot, monkeypatch):
    """页面上没有消息操作栏（未进入会话/改版）→ 降级并报出原因，不空等超时。"""
    from src.ui.enhance.browser_panel import EnhanceTranslateBrowser

    _fast_share(monkeypatch)
    page = _SharePage(action_row=False)
    fake = _fake_browser(page)

    results: list = []
    EnhanceTranslateBrowser.get_share_link(
        fake, callback=results.append, timeout_ms=3000, interval_ms=10
    )
    qtbot.waitUntil(lambda: bool(results), timeout=8000)

    assert results[0]["ok"] is False
    assert results[0]["detail"] == "action-row-not-found"


def test_get_share_link_reuses_remembered_icon_position(qtbot, monkeypatch):
    """重试时先试上一轮确认过的位置，不必再把整排图标逐个悬浮一遍。

    满屏悬浮正是用户看到的「不停点击」画面。
    """
    from src.ui.enhance.browser_panel import EnhanceTranslateBrowser

    _fast_share(monkeypatch)
    page = _SharePage(share_index=5)
    fake = _fake_browser(page, _share_icon_index=5)

    results: list = []
    EnhanceTranslateBrowser.get_share_link(
        fake, callback=results.append, timeout_ms=3000, interval_ms=10
    )
    qtbot.waitUntil(lambda: bool(results), timeout=8000)

    assert results[0]["ok"] is True
    assert page.hovers == [5]


def test_get_share_link_closes_leftover_selection_dialog_first(qtbot, monkeypatch):
    """上一轮残留的「选择对话」弹窗：新一轮开跑前先关掉，再对新消息点「分享」。

    旧版 dismiss 只在页面顶部找「取消」（按钮实际在弹窗自己的工具栏里），
    弹窗残留到下一轮时消息操作栏不可见，第二、三轮再也取不到链接
    （用户反馈：走完一遍后第二次发送无法自动取链接）。
    """
    from src.ui.enhance.browser_panel import EnhanceTranslateBrowser

    _fast_share(monkeypatch)
    page = _SharePage(initial_selection=True)
    fake = _fake_browser(page)

    results: list = []
    EnhanceTranslateBrowser.get_share_link(
        fake, callback=results.append, timeout_ms=5000, interval_ms=10
    )
    qtbot.waitUntil(lambda: bool(results), timeout=8000)

    assert results[0]["ok"] is True
    # 残留弹窗被预清关掉——否则第一次「复制链接」就直接成功、根本不会去点图标
    assert page.dismiss_clicks >= 1
    assert page.icon_clicks == 1
    assert page.copy_clicks == 2


def test_get_share_link_falls_back_to_prompt_value(qtbot, monkeypatch):
    """剪贴板写入被拒时页面退化成 window.prompt（值被 _DialogSafePage 记下）。

    这条路径以前会弹出原生模态框卡死渲染进程，用户手点确定后重试又弹一次，
    表现成「不停的点击分享按钮」。
    """
    from src.ui.enhance.browser_panel import EnhanceTranslateBrowser

    _fast_share(monkeypatch)
    page = _SharePage(clipboard_text="", prompt_fallback="thread/xDJEGzrNKx9oSnTMa")
    fake = _fake_browser(page)

    results: list = []
    EnhanceTranslateBrowser.get_share_link(
        fake, callback=results.append, timeout_ms=3000, interval_ms=10
    )
    qtbot.waitUntil(lambda: bool(results), timeout=8000)

    assert results[0]["ok"] is True
    assert results[0]["detail"] == "https://www.doubao.com/thread/xDJEGzrNKx9oSnTMa"


def test_share_link_from_prompt_accepts_full_and_relative_urls(qtbot):
    """prompt 兜底给的可能是完整链接，也可能是 thread/xxx 相对路径。"""
    from src.ui.enhance.browser_panel import EnhanceTranslateBrowser

    page = _SharePage()
    fake = _fake_browser(page)

    page.prompt_value = "https://www.doubao.com/thread/abc123"
    assert EnhanceTranslateBrowser._share_link_from_prompt(fake) == (
        "https://www.doubao.com/thread/abc123"
    )
    page.prompt_value = "/share/abc123"
    assert EnhanceTranslateBrowser._share_link_from_prompt(fake) == (
        "https://www.doubao.com/share/abc123"
    )
    page.prompt_value = "随手输入的文本"
    assert EnhanceTranslateBrowser._share_link_from_prompt(fake) is None


def test_new_share_run_silences_previous_run(qtbot, monkeypatch):
    """重开一轮抓取后，上一轮排队的回调必须安静退出。

    否则上一轮的超时定时器会接着点「分享」图标——这正是用户看到的
    「自动填完链接后还在不停点击」。
    """
    from src.ui.enhance.browser_panel import EnhanceTranslateBrowser

    _fast_share(monkeypatch)
    page = _SharePage(clipboard_text="与豆包无关的文本")
    fake = _fake_browser(page)

    results: list = []
    EnhanceTranslateBrowser.get_share_link(
        fake, callback=results.append, timeout_ms=3000, interval_ms=10
    )
    stale_run = fake._share_run

    # 第二轮开始：令牌自增，旧令牌的回调应被忽略
    EnhanceTranslateBrowser.get_share_link(
        fake, callback=results.append, timeout_ms=3000, interval_ms=10
    )
    assert fake._share_run == stale_run + 1

    stale_copies = page.copy_clicks
    EnhanceTranslateBrowser._share_attempt(fake, stale_run)
    assert page.copy_clicks == stale_copies


def test_is_share_tooltip_ignores_stale_tooltip_from_other_icon(qtbot):
    """tooltip 门户异步卸载：位置对不上就不能当成刚悬浮的那个图标。

    否则会点到「重新生成」——白烧一次生成，还可能把结果图覆盖掉。
    """
    from src.ui.enhance.browser_panel import EnhanceTranslateBrowser

    page = _SharePage()
    fake = _fake_browser(page)
    fake._share_hover_cx = 390

    # 残留的上一个图标（「重新生成」）的 tooltip，位置对不上
    assert not EnhanceTranslateBrowser._is_share_tooltip(
        fake, {"tips": [{"text": "分享", "cx": 424}]}
    )
    # 位置吻合才算
    assert EnhanceTranslateBrowser._is_share_tooltip(
        fake, {"tips": [{"text": "分享", "cx": 377}]}
    )
    assert not EnhanceTranslateBrowser._is_share_tooltip(
        fake, {"tips": [{"text": "重新生成", "cx": 377}]}
    )
    assert not EnhanceTranslateBrowser._is_share_tooltip(fake, None)


def test_permission_handler_only_grants_clipboard_write():
    """只放行剪贴板写入（复制链接要用），其它权限一律拒绝。"""
    from PySide6.QtWebEngineCore import QWebEnginePermission

    from src.ui.enhance.browser_panel import EnhanceTranslateBrowser

    class _Perm:
        def __init__(self, kind):
            self.kind = kind
            self.state = None

        def permissionType(self):  # noqa: N802
            return self.kind

        def grant(self):
            self.state = "granted"

        def deny(self):
            self.state = "denied"

    allowed = _Perm(QWebEnginePermission.PermissionType.ClipboardReadWrite)
    denied = _Perm(QWebEnginePermission.PermissionType.Notifications)
    EnhanceTranslateBrowser._on_permission_requested(allowed)
    EnhanceTranslateBrowser._on_permission_requested(denied)

    assert allowed.state == "granted"
    assert denied.state == "denied"


def test_automation_callbacks_degrade_on_failure(monkeypatch):
    """每个自动化回调失败路径都给出对应降级提示。"""
    from tests.ui.editor.test_watermark_removal_quota import _SyncTaskRunner
    from src.ui.editor.main_window import EditorMainWindow
    import numpy as np
    from pathlib import Path as _Path
    from src.domain.image import ImageAsset, ImageDocument, ImageFileFormat

    QApplication.instance() or QApplication(["enhance-degrade-test"])
    window = EditorMainWindow(
        import_image=object(),
        task_runner=_SyncTaskRunner(),
    )
    try:
        window._enter_editor()
        panel = window._editor_page.enhance_panel

        # check 失败 → 提示登录/手动
        window._on_enhance_check_done({"ok": False, "detail": "input-not-found"}, "p")
        assert "AI" in panel.automation_status.text()

        # upload 失败 → 提示手动拖图
        window._on_enhance_upload_done({"ok": False}, "p")
        assert "手动拖入" in panel.automation_status.text()

        # fill 失败 → 提示手动输入提示词
        window._on_enhance_prompt_done({"ok": False})
        assert "手动输入提示词" in panel.automation_status.text()

        # 用户迟迟没点发送 → 提示手动发送并手动粘链接
        window._on_enhance_send_done({"ok": False})
        assert "手动发送" in panel.automation_status.text()

        # wait 失败 → 提示手动复制链接
        window._on_enhance_result_done({"ok": False})
        assert "复制链接" in panel.automation_status.text()

        # get_link 失败 → 提示手动粘贴
        window._on_enhance_link_done({"ok": False})
        assert "手动复制" in panel.automation_status.text()
    finally:
        window.close()


def test_overlay_blocks_page_during_generation_and_link_grab():
    """检测到发送后到取链接结束，遮罩盖住AI页面挡住用户鼠标。

    用户在等待期间点页面会关掉「选择对话」弹窗、触发新的选择态，自动化
    状态机随之失效（用户反馈等待期间乱点会搞坏流程）。取链接无论成败，
    结束即解锁；未检测到发送（用户还没点）不得盖。
    """
    from types import SimpleNamespace

    from src.ui.editor.main_window import EditorMainWindow
    from tests.ui.editor.test_watermark_removal_quota import _SyncTaskRunner

    QApplication.instance() or QApplication(["enhance-overlay-test"])
    window = EditorMainWindow(import_image=object(), task_runner=_SyncTaskRunner())
    try:
        window._enter_editor()
        calls: list[tuple[bool, str]] = []
        waits: list = []
        window._editor_page.enhance_browser = SimpleNamespace(
            set_automation_overlay=lambda v, t="": calls.append((v, t)),
            wait_for_result=lambda callback=None, **k: waits.append(callback),
            get_share_link=lambda callback=None, **k: None,
        )

        # 未检测到发送 → 解锁（用户还要自己点「发送」，页面必须可操作）
        window._on_enhance_send_done({"ok": False})
        assert calls == [(False, "")]

        calls.clear()
        # 检测到发送 → 等待生成期间盖遮罩
        window._on_enhance_send_done(
            {"ok": True, "stage": "send", "detail": "sent"}
        )
        assert len(waits) == 1
        assert calls[0][0] is True and "生成" in calls[0][1]

        calls.clear()
        # 生成完成 → 取链接期间继续盖
        window._on_enhance_result_done(
            {"ok": True, "stage": "wait_result", "detail": "image-found"}
        )
        assert calls[0][0] is True and "链接" in calls[0][1]

        calls.clear()
        # 取链接结束（成功）→ 解锁
        window._on_enhance_link_done(
            {"ok": True, "detail": "https://www.doubao.com/thread/ov1"},
            run=window._enhance_run,
        )
        assert calls[0] == (False, "")

        calls.clear()
        # 取链接结束（失败）→ 也解锁
        window._on_enhance_link_done(
            {"ok": False, "stage": "get_share_link", "detail": "link-not-found"},
            run=window._enhance_run,
        )
        assert calls[0] == (False, "")

        # 新一轮开始 → 解锁
        calls.clear()
        window._set_enhance_overlay(False)
        assert calls == [(False, "")]
    finally:
        window.close()


def test_auto_share_link_only_fills_box_without_auto_parse(monkeypatch):
    """自动抓到链接只回填输入框；「解析链接」必须由用户手动点。"""
    from types import SimpleNamespace

    from src.ui.editor import main_window as main_window_module
    from src.ui.editor.main_window import EditorMainWindow
    from tests.ui.editor.test_watermark_removal_quota import _SyncTaskRunner

    fetched: list[str] = []
    button_clicks: list[int] = []
    monkeypatch.setattr(
        main_window_module,
        "fetch_share_images",
        lambda url: (fetched.append(url), ())[1],
    )

    QApplication.instance() or QApplication(["enhance-manual-parse-test"])
    window = EditorMainWindow(import_image=object(), task_runner=_SyncTaskRunner())
    try:
        window._enter_editor()
        window._editor_page.enhance_browser = SimpleNamespace()
        panel = window._editor_page.enhance_panel
        panel.fetch_button.clicked.connect(lambda: button_clicks.append(1))
        window._share_link_grace_ms = 0

        window._on_enhance_result_done(
            {"ok": True, "stage": "wait_result", "detail": "image-found"}
        )
        # 结果完成后会延迟抓链接；直接走 link_done 更稳
        window._on_enhance_link_done(
            {"ok": True, "detail": "https://www.doubao.com/thread/autoclick"},
            run=window._enhance_run,
        )

        assert panel.link.text() == "https://www.doubao.com/thread/autoclick"
        assert "请点击下方「解析链接」" in panel.automation_status.text()
        assert button_clicks == []
        assert fetched == []
    finally:
        window.close()


def test_auto_share_link_success_does_not_click_fetch(monkeypatch):
    """旧回归：自动路径曾真实点下解析按钮；现要求只填链接不点。"""
    from tests.ui.editor.test_watermark_removal_quota import _SyncTaskRunner
    from src.ui.editor.main_window import EditorMainWindow
    from src.ui.editor import main_window as main_window_module

    fetched: list[str] = []
    button_clicks: list[int] = []
    monkeypatch.setattr(
        main_window_module,
        "fetch_share_images",
        lambda url: (fetched.append(url), ())[1],
    )

    QApplication.instance() or QApplication(["enhance-no-autoclick-test"])
    window = EditorMainWindow(import_image=object(), task_runner=_SyncTaskRunner())
    try:
        window._enter_editor()
        panel = window._editor_page.enhance_panel
        panel.fetch_button.clicked.connect(lambda: button_clicks.append(1))

        window._on_enhance_link_done(
            {"ok": True, "detail": "https://www.doubao.com/thread/manualuser"},
            run=window._enhance_run,
        )

        assert button_clicks == []
        assert fetched == []
        assert panel.link.text() == "https://www.doubao.com/thread/manualuser"
        assert "解析链接" in panel.automation_status.text()
    finally:
        window.close()


def test_manual_parse_is_single_flight_while_busy(monkeypatch):
    """解析在途时再点「解析链接」不得并发第二次 fetch。"""
    from tests.ui.editor.test_watermark_removal_quota import _SyncTaskRunner
    from src.ui.editor.main_window import EditorMainWindow
    from src.ui.editor import main_window as main_window_module

    fetched: list[str] = []
    pending_work: list = []

    class _HeldRunner:
        def submit(self, work, on_success, on_error):
            pending_work.append((work, on_success, on_error))

    monkeypatch.setattr(
        main_window_module,
        "fetch_share_images",
        lambda url: (fetched.append(url), ())[1],
    )

    QApplication.instance() or QApplication(["enhance-single-flight-test"])
    window = EditorMainWindow(import_image=object(), task_runner=_HeldRunner())
    try:
        window._enter_editor()
        panel = window._editor_page.enhance_panel

        window._on_enhance_link("https://www.doubao.com/thread/one")
        assert panel.busy
        assert len(pending_work) == 1

        window._on_enhance_link("https://www.doubao.com/thread/two")
        assert len(pending_work) == 1

        work, on_success, on_error = pending_work.pop(0)
        on_success(())
        assert not panel.busy
        window._on_enhance_link("https://www.doubao.com/thread/after")
        assert len(pending_work) == 1
        pending_work.pop(0)[0]()
        assert fetched == ["https://www.doubao.com/thread/after"]
    finally:
        window.close()


def test_manual_parse_failure_keeps_plain_error(monkeypatch):
    """手动粘链接解析失败时保持原有报错，不掺入自动流程的提示。"""
    from src.ui.editor import main_window as main_window_module
    from src.ui.editor.main_window import EditorMainWindow
    from src.infrastructure.doubao_share import DoubaoShareError
    from tests.ui.editor.test_watermark_removal_quota import _SyncTaskRunner

    QApplication.instance() or QApplication(["enhance-manual-fail-test"])
    window = EditorMainWindow(import_image=object(), task_runner=_SyncTaskRunner())
    try:
        window._enter_editor()

        def fake_fetch(url: str):
            raise DoubaoShareError("这个链接里没有解析到无水印原图")

        monkeypatch.setattr(main_window_module, "fetch_share_images", fake_fetch)

        panel = window._editor_page.enhance_panel
        status_before = panel.automation_status.text()
        window._on_enhance_link("https://www.doubao.com/thread/manual1")

        assert "没有解析到无水印原图" in panel.status.text()
        # 手动路径不该改写自动化状态栏
        assert panel.automation_status.text() == status_before
    finally:
        window.close()


def test_share_link_failure_hint_translates_reasons():
    """自动抓链接失败时，状态栏要带上能定位问题的人话原因。"""
    from src.ui.editor.main_window import EditorMainWindow

    hint = EditorMainWindow._share_link_failure_hint
    assert "没找到消息操作栏" in hint("action-row-not-found")
    assert "没找到「分享」" in hint("share-icon-not-found")
    assert "没找到「复制链接」按钮" in hint("copy-link-not-found")
    assert "剪贴板里没有链接" in hint("link-not-found")
    assert hint("whatever") == "whatever"


def test_share_link_failure_shows_reason_in_status():
    """抓链接失败时状态栏包含具体原因，用户截图即可定位是哪一环断了。"""
    from types import SimpleNamespace

    from src.ui.editor.main_window import EditorMainWindow
    from tests.ui.editor.test_watermark_removal_quota import _SyncTaskRunner

    QApplication.instance() or QApplication(["enhance-link-hint-test"])
    window = EditorMainWindow(import_image=object(), task_runner=_SyncTaskRunner())
    try:
        window._enter_editor()
        window._editor_page.enhance_browser = SimpleNamespace()

        window._on_enhance_link_done(
            {"ok": False, "stage": "get_share_link", "detail": "share-icon-not-found"}
        )

        status = window._editor_page.enhance_panel.automation_status.text()
        assert "没找到「分享」" in status
        assert "手动复制后粘贴" in status
    finally:
        window.close()


def test_auto_share_link_is_written_back_to_parse_box(monkeypatch):
    """自动抓到的链接回填解析框，并提示用户手动点「解析链接」。"""
    from tests.ui.editor.test_watermark_removal_quota import _SyncTaskRunner
    from src.ui.editor.main_window import EditorMainWindow
    from src.ui.editor import main_window as main_window_module

    fetched: list[str] = []
    monkeypatch.setattr(
        main_window_module,
        "fetch_share_images",
        lambda url: (fetched.append(url), ())[1],
    )

    QApplication.instance() or QApplication(["enhance-autolink-test"])
    window = EditorMainWindow(import_image=object(), task_runner=_SyncTaskRunner())
    try:
        window._enter_editor()
        panel = window._editor_page.enhance_panel

        window._on_enhance_link_done(
            {"ok": True, "detail": "https://www.doubao.com/thread/wabc123"}
        )

        assert panel.link.text() == "https://www.doubao.com/thread/wabc123"
        assert fetched == []
        assert "请点击下方「解析链接」" in panel.automation_status.text()
    finally:
        window.close()


def test_enhance_panel_shows_flow_without_prompt_box():
    """面板展示流程说明；提示词框已删（提示词直接填在AI输入框里，冗余）。"""
    QApplication.instance() or QApplication(["enhance-flow-panel-test"])
    from src.ui.editor.widgets.tool_dialogs import EnhanceTranslatePanel

    panel = EnhanceTranslatePanel()
    try:
        assert "手动点「解析链接」" in panel._FLOW_HINT
        assert not hasattr(panel, "prompt_edit")
        assert not hasattr(panel, "set_prompt")
    finally:
        panel.close()


def test_parsed_snapshot_without_generated_image_guides_manual_recopy(monkeypatch):
    """手动解析后快照缺生成图：状态栏提示重新复制再解析，不自动再点。"""
    from src.infrastructure.doubao_share import ShareImage
    from src.ui.editor import main_window as main_window_module
    from src.ui.editor.main_window import EditorMainWindow
    from tests.ui.editor.test_watermark_removal_quota import _SyncTaskRunner

    QApplication.instance() or QApplication(["enhance-no-gen-test"])
    window = EditorMainWindow(import_image=object(), task_runner=_SyncTaskRunner())
    try:
        window._enter_editor()
        uploaded = ShareImage(
            url="https://p3.byteimg.com/a.png~tplv-t-image_raw.png?sig=1", key="k-upload"
        )
        monkeypatch.setattr(
            main_window_module, "fetch_share_images", lambda url: (uploaded,)
        )

        window._on_enhance_link("https://www.doubao.com/thread/uploadonly")
        for _ in range(3):
            QApplication.processEvents()

        status = window._editor_page.enhance_panel.automation_status.text()
        assert "没有AI新生成的图" in status
        assert "解析链接" in status
    finally:
        window.close()


def test_help_documents_manual_parse_step():
    """使用说明必须写清强化翻译流程，且解析按钮由用户手动点。"""
    from src.ui.help_dialog import _HELP_HTML

    assert "强化翻译" in _HELP_HTML
    assert "手动点「解析链接」" in _HELP_HTML or "自己点「解析链接」" in _HELP_HTML
    assert "提示词" in _HELP_HTML


def test_second_activation_supersedes_first_automation():
    """再次点击左侧图片：run 自增、begin_flow 被调，旧轮次回调全部失效。"""
    from types import SimpleNamespace

    from tests.ui.editor.test_watermark_removal_quota import _SyncTaskRunner
    from src.ui.editor.main_window import EditorMainWindow
    import numpy as np
    from pathlib import Path as _Path
    from src.domain.image import ImageAsset, ImageDocument, ImageFileFormat

    QApplication.instance() or QApplication(["enhance-supersede-test"])
    window = EditorMainWindow(import_image=object(), task_runner=_SyncTaskRunner())
    try:
        window._enter_editor()
        asset = ImageAsset(_Path("a.png"), 40, 30, 1, ImageFileFormat.PNG, False, False)
        doc = ImageDocument(asset, "RGB", bytes(np.full((30, 40, 3), 255, dtype=np.uint8)))
        window._model.add_document(_Path("a.png"), doc, name="a.png")

        begin_calls: list[int] = []
        window._editor_page.enhance_browser = SimpleNamespace(
            set_source_image=lambda path: None,
            load_doubao=lambda: None,
            run_action_when_ready=lambda *a, **k: None,
            begin_flow=lambda: begin_calls.append(1),
        )
        window._editor_page.toolbar.set_active_tool("enhance_translate")
        panel = window._editor_page.enhance_panel

        run0 = window._enhance_run
        window._on_enhance_document_activated()
        first = window._enhance_run
        assert first == run0 + 1
        assert begin_calls == [1]

        window._on_enhance_document_activated()
        second = window._enhance_run
        assert second == first + 1
        assert begin_calls == [1, 1]
        assert panel.automation_status.text() == "正在连接AI并上传图片…"

        # 旧轮次的失败回调不得改写状态栏
        window._on_enhance_check_done(
            {"ok": False, "detail": "input-not-found"}, "p", run=first
        )
        assert panel.automation_status.text() == "正在连接AI并上传图片…"

        # 当前轮次照常降级
        window._on_enhance_check_done(
            {"ok": False, "detail": "input-not-found"}, "p", run=second
        )
        assert "AI" in panel.automation_status.text()

        # run=None（直接调用的旧测试/手动路径）不受令牌约束
        panel.automation_status.setText("占位")
        window._on_enhance_prompt_done({"ok": False})
        assert "手动输入提示词" in panel.automation_status.text()
    finally:
        window.close()
