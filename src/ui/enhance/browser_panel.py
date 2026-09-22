"""强化翻译 — 内嵌AI网页浏览器与自动化动作。

常规翻译管线处理不了的图片（艺术字、图文融合），通过AI图生图直接
生成译文版图片。AI页面 DOM 无公开契约，所有选择器集中在 JS_ACTIONS
顶部常量区，平台改版只需更新该处；每个动作独立降级提示，最坏退化为
现有手动流程（手动拖图 / 手动输入提示词 / 手动粘贴分享链接）。

发送动作不由程序执行：图片与提示词就绪后交给用户点「发送」，程序只轮询
输入框是否被清空来判断已发出，之后的生成检测与分享链接仍自动进行。

图片与提示词的写入走系统剪贴板 + QWebEnginePage.Paste 动作，而非
runJavaScript 里构造合成事件：AI只接受受信 paste（合成 ClipboardEvent
被忽略），真实 Paste 动作实测会触发AI prepare_upload → CommitImageUpload
并挂上附件缩略图，提示词也能正常进入 ProseMirror 内部状态。代价是占用
系统剪贴板。

分享链接同样经剪贴板：点消息上的「分享」图标进入选择态，底部工具栏出现
「复制链接」，点它由 navigator.clipboard.writeText 写入，本模块读回。该 API
需要 ClipboardReadWrite 权限，未授权时 promise 永远挂起（既不 resolve 也不
reject），所以构造时挂上 permissionRequested 授权；文档未聚焦时它还会 reject，
所以点击前把焦点还给网页。AI写剪贴板失败时会退化成 window.prompt 兜底，见
_DialogSafePage。

「分享」图标本身没有任何 aria-label / title / 文字（实测 DOM：同排按钮只有
「朗读」带 aria-label），DOM 里认不出来，只能逐个悬浮——悬浮时 tooltip 门户
里会出现「分享」两字，拿它的中心 x 和按钮中心对齐确认是同一个。整个寻找
过程因此是 Python 侧状态机。

runJavaScript 的两条硬限制（实测）：
1. JS 对象回传 Python 是空字符串，必须 JSON.stringify + 本模块解码；
2. 返回 Promise 的脚本（async IIFE）回调同样是空字符串，所以所有动作
   都是同步脚本，需要等待的一律由 Python 侧轮询。
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QImage
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEnginePermission, QWebEngineProfile
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication, QFrame, QLabel, QVBoxLayout, QWidget


# 分享链接形如 https://www.doubao.com/thread/<id>；剪贴板里可能夹带其它文字。
_SHARE_LINK = re.compile(r"https://[\w.-]*doubao\.com/(?:thread|share)/[^\s\"']+")

# prompt 兜底里给的是相对路径（thread/xxx），要补站点前缀
_SHARE_PATH = re.compile(r"^/?(?:thread|share)/[\w-]+$")

# tooltip 是悬浮后才异步挂上 DOM 的，每个图标悬浮后要等一会儿再读。
_HOVER_SETTLE_MS = 700
# 点「分享」后页面进入选择态、底部工具栏挂上 DOM 需要一点时间。
_SHARE_CLICK_SETTLE_MS = 1200
# tooltip 中心与按钮中心的允许偏差（tooltip 内层节点会偏十几像素）。
_TIP_CENTER_TOLERANCE = 24

# 点过「复制链接」后剪贴板是异步写入的：先只轮询读剪贴板，别急着再点一次
# （用户反馈「复制链接会被点两遍」）。超时才允许回到整轮重试点第二次。
_COPY_POLL_MS = 250
_COPY_WRITE_WAIT_MS = 2000

# 新一轮取链接前先清上一轮残留的「选择对话」弹窗，给页面一点稳定时间
_PRE_DISMISS_SETTLE_MS = 300
# 退出选择态后补一次 Escape 前的间隔（点「取消」可能已把弹窗关掉，Escape 兜底）
_DISMISS_ESCAPE_AFTER_MS = 400

# 发送回显（自己消息里的上传原图出现在会话里）的等待上限；真正的生成
# 等待用调用方传入的总超时。
_SEND_ECHO_TIMEOUT_MS = 30000

# Windows 剪贴板偶发被占用（setImage 静默失败，粘进去的是上一轮内容），
# 验证不到附件时重贴，重贴前会重新 setImage。
_UPLOAD_ATTEMPTS = 3
_PASTE_VERIFY_TIMEOUT_MS = 20000

# —— 自动化 JS：返回 {ok: bool, stage: str, detail: str} ——
# 选择器随AI改版可能失效；集中在此便于热修。

# 顶部「分享」是 Radix 下拉菜单，只派发 click() 不会展开，必须补全指针事件序列。
_JS_POINTER_CLICK = """
function pointerClick(node) {
    const rect = node.getBoundingClientRect();
    const x = rect.x + rect.width / 2;
    const y = rect.y + rect.height / 2;
    for (const type of ["pointerdown", "mousedown", "pointerup", "mouseup"]) {
        node.dispatchEvent(new PointerEvent(type, {bubbles: true, cancelable: true,
            pointerType: "mouse", button: 0,
            buttons: type.endsWith("down") ? 1 : 0, clientX: x, clientY: y}));
    }
    node.click();
}
"""

_JS_DOUBAO_SELECTORS = """
const INPUT_SELECTORS = [
    '[contenteditable="true"]',
    'textarea[placeholder]',
    'div[class*="input"] [contenteditable="true"]',
];
function findInput() {
    for (const sel of INPUT_SELECTORS) {
        const nodes = document.querySelectorAll(sel);
        for (const node of nodes) {
            const rect = node.getBoundingClientRect();
            if (rect.width > 80 && rect.height > 20) return node;
        }
    }
    return null;
}
"""

# 消息底部的操作栏：一排 20~32px 的图标按钮。取最靠下的一组（最新一条
# 消息在底部），排除输入区那排宽按钮（w>=36）与侧栏的零散小按钮。
_JS_ACTION_ROW = """
function findActionRow() {
    const rows = {};
    for (const btn of document.querySelectorAll("button")) {
        const rect = btn.getBoundingClientRect();
        if (!(rect.width > 0) || !(rect.height > 0)) continue;
        if (rect.width > 32 || rect.height > 32 || rect.y < 200) continue;
        const key = Math.round(rect.y / 6) * 6;
        (rows[key] = rows[key] || []).push(btn);
    }
    let best = null;
    let bestY = -1;
    for (const key of Object.keys(rows)) {
        const y = Number(key);
        if (rows[key].length >= 5 && y > bestY) { bestY = y; best = rows[key]; }
    }
    if (!best) return null;
    best.sort((a, b) => a.getBoundingClientRect().x - b.getBoundingClientRect().x);
    return best;
}
"""

# 悬浮第 N 个图标；返回它的中心 x，供 Python 侧核对 tooltip 归属。
_JS_HOVER_ROW_BUTTON = f"""
(() => {{
    {_JS_ACTION_ROW}
    const row = findActionRow();
    if (!row) return JSON.stringify({{ok: false, stage: "share_icon", detail: "action-row-not-found"}});
    const node = row[__INDEX__];
    if (!node) return JSON.stringify({{ok: false, stage: "share_icon", detail: "index-out-of-range"}});
    const rect = node.getBoundingClientRect();
    const cx = rect.x + rect.width / 2;
    const cy = rect.y + rect.height / 2;
    for (const type of ["pointerover", "mouseover", "pointermove", "mousemove"]) {{
        node.dispatchEvent(new MouseEvent(type, {{bubbles: true, cancelable: true,
            clientX: cx, clientY: cy}}));
    }}
    return JSON.stringify({{ok: true, stage: "share_icon", detail: "hovered", cx: Math.round(cx)}});
}})()
"""

_JS_CLICK_ROW_BUTTON = f"""
(() => {{
    {_JS_ACTION_ROW}
    {_JS_POINTER_CLICK}
    const row = findActionRow();
    if (!row) return JSON.stringify({{ok: false, stage: "share_icon", detail: "action-row-not-found"}});
    const node = row[__INDEX__];
    if (!node) return JSON.stringify({{ok: false, stage: "share_icon", detail: "index-out-of-range"}});
    pointerClick(node);
    return JSON.stringify({{ok: true, stage: "share_icon", detail: "clicked"}});
}})()
"""

# 生成结果与「自己发出去那条消息」里的上传原图都来自 CDN（http），无法用
# 地址区分；区分靠时序：发送后第一条增长是上传原图回显，之后（往往几十秒）
# 的增长才是生成的图。完成判定因此取「第二段增长」。
_JS_COUNT_LARGE_IMAGES = """
function countLargeImages() {
    return [...document.querySelectorAll('img')].filter((img) => {
        const src = img.src || "";
        return img.naturalWidth > 200 && img.naturalHeight > 200
            && !src.startsWith("blob:") && !src.startsWith("data:");
    }).length;
}
"""

JS_ACTIONS: dict[str, str] = {
    "check_page": f"""
    (() => {{
        {_JS_DOUBAO_SELECTORS}
        const input = findInput();
        if (!input) return JSON.stringify({{ok: false, stage: "check_page", detail: "input-not-found"}});
        return JSON.stringify({{ok: true, stage: "check_page", detail: "ready"}});
    }})()
    """,
    "focus_input": f"""
    (() => {{
        {_JS_DOUBAO_SELECTORS}
        const input = findInput();
        if (!input) return JSON.stringify({{ok: false, stage: "focus_input", detail: "input-not-found"}});
        input.focus();
        return JSON.stringify({{ok: true, stage: "focus_input", detail: "focused"}});
    }})()
    """,
    "blob_image_count": """
    (() => {
        const count = [...document.querySelectorAll('img')].filter(
            (img) => (img.src || "").startsWith("blob:") && img.naturalWidth >= 100
        ).length;
        return JSON.stringify({ok: true, stage: "blob_image_count", detail: "counted", count: count});
    })()
    """,
    "large_image_count": f"""
    (() => {{
        {_JS_COUNT_LARGE_IMAGES}
        return JSON.stringify({{ok: true, stage: "large_image_count", detail: "counted",
                                count: countLargeImages()}});
    }})()
    """,
    "input_state": f"""
    (() => {{
        {_JS_DOUBAO_SELECTORS}
        const input = findInput();
        if (!input) return JSON.stringify({{ok: false, stage: "input_state", detail: "input-not-found"}});
        const text = (input.innerText || "").trim();
        return JSON.stringify({{ok: true, stage: "input_state",
                                detail: text.length > 0 ? "has-text" : "empty",
                                textLength: text.length}});
    }})()
    """,
    "action_row_size": f"""
    (() => {{
        {_JS_ACTION_ROW}
        const row = findActionRow();
        if (!row) return JSON.stringify({{ok: false, stage: "share_icon",
                                          detail: "action-row-not-found"}});
        return JSON.stringify({{ok: true, stage: "share_icon", detail: "found", count: row.length}});
    }})()
    """,
    "tooltip_text": """
    (() => {
        // tooltip 门户里的文字（取第一行）；带上中心 x，Python 侧据此确认
        // 它属于刚悬浮的那个图标而不是上一个残留的
        const tips = [];
        for (const node of document.querySelectorAll(
                '[role="tooltip"], [class*="tooltip"], [class*="Tooltip"]')) {
            const text = (node.innerText || "").trim().split("\\n")[0];
            if (!text) continue;
            const rect = node.getBoundingClientRect();
            tips.push({text: text, cx: Math.round(rect.x + rect.width / 2)});
        }
        return JSON.stringify({ok: true, stage: "share_icon", detail: "read", tips: tips});
    })()
    """,
    "click_copy_link": f"""
    (() => {{
        {_JS_POINTER_CLICK}
        // 点「分享」后底部工具栏里的「复制链接」按钮（纯文字按钮，无 role）。
        // 先认 Radix 菜单项（旧版入口），再按精确文字找按钮，最后放宽到任意
        // 元素——文字用全等匹配，免得命中正文里提到「复制链接」的句子
        const areaAsc = (a, b) => {{
            const ra = a.getBoundingClientRect();
            const rb = b.getBoundingClientRect();
            return ra.width * ra.height - rb.width * rb.height;
        }};
        const visible = (node) => {{
            const rect = node.getBoundingClientRect();
            return rect.width > 0 && rect.height > 0;
        }};
        const norm = (s) => (s || "").replace(/\\s+/g, "");
        const isCopyLink = (node) => {{
            const attr = (node.getAttribute && (node.getAttribute("aria-label")
                || node.getAttribute("title")) || "");
            return norm(node.innerText) === "复制链接" || norm(attr) === "复制链接";
        }};
        let item = [...document.querySelectorAll('[role="menuitem"]')]
            .filter((node) => visible(node) && norm(node.innerText).includes("复制链接"))
            .sort(areaAsc)[0];
        if (!item) {{
            item = [...document.querySelectorAll('button, [role="button"]')]
                .filter((node) => visible(node) && isCopyLink(node))
                .sort(areaAsc)[0];
        }}
        if (!item) {{
            item = [...document.querySelectorAll("body *")]
                .filter((node) => visible(node) && isCopyLink(node))
                .sort(areaAsc)[0];
        }}
        if (!item) return JSON.stringify({{ok: false, stage: "copy_link",
                                          detail: "copy-link-not-found"}});
        if (item.disabled === true
            || item.getAttribute("aria-disabled") === "true")
            return JSON.stringify({{ok: false, stage: "copy_link",
                                  detail: "copy-link-disabled"}});
        pointerClick(item);
        return JSON.stringify({{ok: true, stage: "copy_link", detail: "clicked"}});
    }})()
    """,
    "dismiss_selection": """
    (() => {
        // 复制完退出消息选择态、关掉「选择对话」弹窗；失败无所谓，仅影响观感。
        // 旧版只在顶部 y<80 找「取消」，实际按钮在弹窗自己的工具栏里，永远
        // 找不到——弹窗残留到下一轮时，消息操作栏（含「分享」图标）不可见，
        // 第二、三轮就再也自动取不到链接（用户反馈）。现在取全页最小可见
        // 「取消」按钮，优先弹窗所在的页面下半部。
        const visible = (node) => {
            const rect = node.getBoundingClientRect();
            return rect.width > 0 && rect.height > 0;
        };
        const isCancel = (node) => {
            const t = (node.innerText || "").trim();
            const attr = (node.getAttribute && (node.getAttribute("aria-label")
                || node.getAttribute("title")) || "").trim();
            return t === "取消" || attr === "关闭" || attr === "取消";
        };
        const candidates = [...document.querySelectorAll('button, [role="button"]')]
            .filter((node) => visible(node) && isCancel(node))
            .sort((a, b) => {
                const ra = a.getBoundingClientRect();
                const rb = b.getBoundingClientRect();
                return ra.width * ra.height - rb.width * rb.height;
            });
        const item = candidates.find((n) => n.getBoundingClientRect().y > 120)
            || candidates[0];
        if (!item) return JSON.stringify({ok: false, stage: "dismiss", detail: "cancel-not-found"});
        item.click();
        return JSON.stringify({ok: true, stage: "dismiss", detail: "cancelled"});
    })()
    """,
    "dismiss_escape": """
    (() => {
        // 兜底：Radix 系弹窗监听 document 的 Escape 关闭，合成事件即可
        document.dispatchEvent(new KeyboardEvent("keydown",
            {key: "Escape", code: "Escape", keyCode: 27, which: 27, bubbles: true}));
        return JSON.stringify({ok: true, stage: "dismiss", detail: "escape-sent"});
    })()
    """,
    "clear_input": f"""
    (() => {{
        {_JS_DOUBAO_SELECTORS}
        const input = findInput();
        if (!input) return JSON.stringify({{ok: false, stage: "clear_input", detail: "input-not-found"}});
        input.focus();
        // 清掉上一轮残留文字（重新点图片时输入区可能还留着旧提示词）
        try {{
            const range = document.createRange();
            range.selectNodeContents(input);
            const sel = window.getSelection();
            sel.removeAllRanges();
            sel.addRange(range);
            document.execCommand("delete");
        }} catch (e) {{}}
        // 点掉附件缩略图旁的删除按钮，避免重复上传两份图
        const isClose = (btn) => {{
            const t = (btn.innerText || "").trim();
            const attr = (btn.getAttribute && (btn.getAttribute("aria-label")
                || btn.getAttribute("title")) || "").trim();
            return t === "×" || t === "X" || t === "✕"
                || /删除|移除|remove|delete/i.test(attr);
        }};
        let removed = 0;
        for (const img of [...document.querySelectorAll("img")]) {{
            if (!(img.src || "").startsWith("blob:")) continue;
            let node = img;
            for (let depth = 0; depth < 6 && node; depth++, node = node.parentElement) {{
                if (!node || !node.querySelectorAll) continue;
                const btn = [...node.querySelectorAll("button")].find((b) => {{
                    const r = b.getBoundingClientRect();
                    return r.width > 0 && r.width <= 40 && r.height <= 40 && isClose(b);
                }});
                if (btn) {{ btn.click(); removed++; break; }}
            }}
        }}
        const text = (input.innerText || "").trim();
        const blobCount = [...document.querySelectorAll("img")].filter(
            (img) => (img.src || "").startsWith("blob:") && img.naturalWidth >= 100
        ).length;
        return JSON.stringify({{ok: true, stage: "clear_input", detail: "cleared",
                                textLength: text.length, blobCount: blobCount, removed: removed}});
    }})()
    """,
    "clear_text": f"""
    (() => {{
        {_JS_DOUBAO_SELECTORS}
        const input = findInput();
        if (!input) return JSON.stringify({{ok: false, stage: "clear_text", detail: "input-not-found"}});
        input.focus();
        try {{
            const range = document.createRange();
            range.selectNodeContents(input);
            const sel = window.getSelection();
            sel.removeAllRanges();
            sel.addRange(range);
            document.execCommand("delete");
        }} catch (e) {{}}
        const text = (input.innerText || "").trim();
        return JSON.stringify({{ok: true, stage: "clear_text", detail: "cleared",
                                textLength: text.length}});
    }})()
    """,
}


class _DialogSafePage(QWebEnginePage):
    """JS 对话框一律自答，绝不让模态框卡住渲染进程。

    AI点「复制链接」时若 navigator.clipboard.writeText 被拒（文档未聚焦等），
    会退化成 window.prompt("Copy to clipboard: Ctrl+C, Enter", 链接) 让用户手抄。
    QtWebEngine 默认把 prompt 弹成模态对话框：渲染进程随之停住，runJavaScript
    的回调永远不回，自动化就卡在那儿；用户手点「确定」后流程才继续，于是每轮
    重试都弹一次框、还伴着一串点击。

    这里把 prompt 的默认值原样返回（等于替用户按了确定），顺便记下这个值——
    写剪贴板失败时它就是链接的兜底来源。
    """

    prompt_value: str = ""

    def javaScriptAlert(self, origin, msg) -> None:  # noqa: N802
        pass

    def javaScriptConfirm(self, origin, msg) -> bool:  # noqa: N802
        return False

    def javaScriptPrompt(self, origin, msg, default):  # noqa: N802
        # 返回值是 (是否确定, 输入框内容)；PySide6 要求元组，否则告警且拿不到值
        self.prompt_value = str(default or "")
        return (True, self.prompt_value)


def _decode_callback(callback):
    """runJavaScript 无法把 JS 对象转成 Python 值（回调收到空字符串），
    故页面动作统一 JSON.stringify 返回，这里解码回 dict。"""
    if callback is None:
        return None

    def _decoded(result):
        if isinstance(result, str):
            try:
                callback(json.loads(result))
                return
            except ValueError:
                pass
        callback(result)

    return _decoded


def _count_of(result: object) -> int:
    if isinstance(result, dict):
        value = result.get("count")
        if isinstance(value, (int, float)):
            return int(value)
    return 0


def _failure(stage: str, result: object) -> dict:
    detail = result.get("detail", "") if isinstance(result, dict) else ""
    return {"ok": False, "stage": stage, "detail": str(detail or "unexpected-result")}


class EnhanceTranslateBrowser(QWidget):
    """AI网页视图 + 自动化动作执行器。

    offscreen 测试环境不实例化（editor_page 用占位 QLabel 代替）；
    登录态由命名 profile 的持久化 cookie 承载，扫码一次跨会话有效。
    """

    automation_event = Signal(str, dict)

    DOUBAO_HOME = "https://www.doubao.com/chat/"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._profile = QWebEngineProfile("imgtrans-doubao", self)
        self._profile.setPersistentCookiesPolicy(
            QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies
        )
        from PySide6.QtCore import QStandardPaths

        cache_root = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.CacheLocation
        )
        self._profile.setPersistentStoragePath(str(Path(cache_root) / "webengine"))

        self._page = _DialogSafePage(self._profile, self)
        self._page.permissionRequested.connect(self._on_permission_requested)
        self._view = QWebEngineView(self)
        self._view.setPage(self._page)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._view)

        self._source_bytes: bytes | None = None
        self._blob_baseline = 0
        self._result_baseline = 0
        self._loaded = False
        self._load_finished = False
        self._pending_action = None
        self._view.loadFinished.connect(self._on_load_finished)

        # 抓分享链接的状态机游标。新一轮开始就自增，旧一轮的回调发现令牌变了
        # 就静静退出——否则上一轮的超时定时器还会接着点分享按钮。
        self._share_run = 0
        self._share_icon_index = None
        # 上传/填词/等待整条链的令牌：与 _share_run 分开，begin_flow 一起作废
        self._flow_run = 0

        # 生成等待 + 取链接期间盖在网页上的半透明遮罩：挡住用户鼠标乱点，
        # 防止打断自动化状态机（用户反馈等待期间乱点会搞坏后续流程）。
        self._overlay = QFrame(self)
        self._overlay.setStyleSheet("background-color: rgba(255, 255, 255, 100);")
        self._overlay_label = QLabel("AI 正在处理，请稍候…", self._overlay)
        self._overlay_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        overlay_layout = QVBoxLayout(self._overlay)
        overlay_layout.addWidget(self._overlay_label)
        self._overlay.hide()

    # —— 对外接口（editor_page / main_window 调用）——

    def begin_flow(self) -> None:
        """新一轮自动化开始：掐断旧轮询与分享状态机，防止共用基线互踩。"""
        self._flow_run += 1
        self._share_run += 1
        self._pending_action = None
        self._overlay.hide()

    def load_doubao(self) -> None:
        if not self._loaded:
            self._loaded = True
            self._view.load(QUrl(self.DOUBAO_HOME))

    def set_source_image(self, path: Path) -> None:
        self._source_bytes = Path(path).read_bytes()

    def run_action_when_ready(self, name: str, callback=None) -> None:
        """页面加载完成后执行动作：首次点击时AI尚未加载完，直接跑会找不到输入框。"""
        self._when_ready(lambda: self.run_action(name, callback))

    def run_action(self, name: str, callback=None) -> None:
        # runJavaScript 的第三个参数必须是可调用对象，回调可省但得给个空函数
        self._page.runJavaScript(
            JS_ACTIONS[name], 0, _decode_callback(callback or (lambda _result: None))
        )

    def set_automation_overlay(self, visible: bool, text: str = "") -> None:
        """生成等待 / 取链接期间盖住网页，挡住用户鼠标乱点。

        由主窗口按流程进度调用：检测到发送后显示，直到取链接结束
        （无论成败）；新一轮开始（begin_flow）也会隐藏。
        """
        if visible:
            if text:
                self._overlay_label.setText(text)
            self._overlay.setGeometry(self._view.geometry())
            self._overlay.show()
            self._overlay.raise_()
        else:
            self._overlay.hide()

    def upload_source_image(self, callback=None) -> None:
        """先清掉上一轮残留，再把原始图 → 系统剪贴板 → 真实粘贴进AI输入框。"""
        self._when_ready(lambda: self._clear_then_paste(callback))

    def fill_prompt_text(self, prompt: str, callback=None) -> None:
        """提示词 → 系统剪贴板 → 真实粘贴（ProseMirror 只认真实 paste 更新内部状态）。"""
        self._when_ready(lambda: self._clear_text_then_paste(prompt, callback))

    def wait_for_manual_send(
        self, callback=None, timeout_ms: int = 600000, interval_ms: int = 2000
    ) -> None:
        """等用户自己在AI页面点发送：以输入框被清空为「已发出」的判据。

        发送动作交给用户（避免替他决定何时发），后续的结果检测与分享链接
        仍自动进行。结果基线在这里取发送前的值；发送后自己消息里的上传
        原图回显也会计入大图数，完成判定因此是「第二段增长」。
        """
        self.run_action(
            "large_image_count",
            callback=lambda result: self._await_manual_send(
                result, callback, timeout_ms, interval_ms
            ),
        )

    def get_share_link(
        self, callback=None, timeout_ms: int = 45000, interval_ms: int = 800
    ) -> None:
        """消息「分享」图标 → 底部工具栏「复制链接」→ 从系统剪贴板读回链接。

        「分享」图标在 DOM 里认不出来（没有 aria-label / title / 文字），只能
        逐个悬浮读 tooltip，所以这里是 Python 侧状态机：每轮先试试点「复制链接」
        （上一轮可能已经点开选择态），不成就去找图标；找到点开后再回到开头点
        「复制链接」，最后读剪贴板。点击前清空剪贴板，否则会读到上一次的旧链接。
        """
        QApplication.clipboard().clear()
        self._share_run += 1
        self._share_icon_clicked = False
        self._page.prompt_value = ""
        self._share_callback = callback
        self._share_interval_ms = interval_ms
        self._share_deadline = time.monotonic() + timeout_ms / 1000.0
        self._share_last = "link-not-found"
        self._share_index = 0
        self._share_order: list[int] = []
        self._share_cursor = 0
        self._share_hover_cx = -1
        # 先清上一轮可能残留的「选择对话」弹窗：残留时消息操作栏（含「分享」
        # 图标）不可见，第二、三轮就再也自动取不到链接（用户反馈）。点「取消」
        # + Escape 兜底，给页面一点稳定时间再走正常流程。run 在这里捕获，
        # 定时器触发时若已有新一轮，_share_attempt 会按令牌静默退出。
        run = self._share_run
        self._page.runJavaScript(JS_ACTIONS["dismiss_selection"], 0)
        self._page.runJavaScript(JS_ACTIONS["dismiss_escape"], 0)
        QTimer.singleShot(_PRE_DISMISS_SETTLE_MS, lambda: self._share_attempt(run))

    # —— 分享链接状态机的各步 ——

    def _dismiss_selection_state(self) -> None:
        """取到链接后的收尾：点「取消」退出选择态，再补一次 Escape 兜底。

        只点「取消」不够稳：真机上弹窗偶尔残留到下一轮，把消息操作栏挡住，
        后续再也点不到「分享」。失败无所谓，仅影响观感。
        """
        self.run_action("dismiss_selection")
        QTimer.singleShot(
            _DISMISS_ESCAPE_AFTER_MS, lambda: self.run_action("dismiss_escape")
        )

    def _clipboard_link(self) -> str | None:
        """剪贴板里的分享链接。AI写剪贴板失败时走 window.prompt 兜底，
        那个相对路径记在页面上，一并认。"""
        match = _SHARE_LINK.search(QApplication.clipboard().text())
        if match is not None:
            return match.group(0)
        return self._share_link_from_prompt()

    def _share_link_from_prompt(self) -> str | None:
        value = str(getattr(self._page, "prompt_value", "") or "").strip()
        if not value:
            return None
        match = _SHARE_LINK.search(value)
        if match is not None:
            return match.group(0)
        if _SHARE_PATH.match(value):
            return "https://www.doubao.com/" + value.lstrip("/")
        return None

    def _share_attempt(self, run: int) -> None:
        if run != self._share_run:
            return
        link = self._clipboard_link()
        if link is not None:
            self._emit(
                self._share_callback,
                {"ok": True, "stage": "get_share_link", "detail": link},
            )
            self._dismiss_selection_state()
            return
        if time.monotonic() >= self._share_deadline:
            self._emit(
                self._share_callback,
                {"ok": False, "stage": "get_share_link", "detail": self._share_last},
            )
            return
        # 剪贴板写入要求文档处于聚焦状态，否则 promise 直接 reject
        self._view.setFocus()
        self.run_action("click_copy_link", callback=lambda r: self._share_after_copy(run, r))

    def _share_after_copy(self, run: int, result: object) -> None:
        if run != self._share_run:
            return
        if isinstance(result, dict) and result.get("ok"):
            # 按钮已点中：剪贴板异步写入，先只读不点，避免连点两次「复制链接」
            self._share_last = "link-not-found"
            wait_s = max(_COPY_WRITE_WAIT_MS, 0) / 1000.0
            self._await_clipboard_after_copy(run, time.monotonic() + wait_s)
            return
        self._share_last = _failure("get_share_link", result)["detail"]
        if self._share_icon_clicked:
            # 「分享」已经点开：对话框或「复制链接」按钮可能还在渲染，隔一会儿
            # 直接再点一次即可。绝不能再回头点「分享」图标——真机上再点一次
            # 会把已打开的对话框关掉，循环里就永远点不到「复制链接」（用户反馈
            # 生成后无法自动取链接、手动打开才行）
            QTimer.singleShot(self._share_interval_ms, lambda: self._share_attempt(run))
            return
        # 工具栏还没出现：去找消息操作栏里的「分享」图标，点开选择态
        self.run_action("action_row_size", callback=lambda r: self._share_after_row_size(run, r))

    def _await_clipboard_after_copy(self, run: int, write_deadline: float) -> None:
        """复制成功后轮询剪贴板；窗口内只读，超时才允许再点一次。"""

        def poll() -> None:
            if run != self._share_run:
                return
            link = self._clipboard_link()
            if link is not None:
                self._emit(
                    self._share_callback,
                    {"ok": True, "stage": "get_share_link", "detail": link},
                )
                self._dismiss_selection_state()
                return
            if time.monotonic() >= self._share_deadline:
                self._emit(
                    self._share_callback,
                    {"ok": False, "stage": "get_share_link", "detail": self._share_last},
                )
                return
            if time.monotonic() >= write_deadline:
                # 剪贴板迟迟没有链接：回到整轮（可能再点一次复制）
                self._share_attempt(run)
                return
            QTimer.singleShot(_COPY_POLL_MS, poll)

        poll()

    def _share_after_row_size(self, run: int, result: object) -> None:
        if run != self._share_run:
            return
        if not (isinstance(result, dict) and result.get("ok")):
            self._share_last = _failure("get_share_link", result)["detail"]
            QTimer.singleShot(self._share_interval_ms, lambda: self._share_attempt(run))
            return
        self._share_row_count = _count_of(result)
        # 上一轮已经确认过的位置排在最前，重试时不必再逐个悬浮一遍
        order = list(range(self._share_row_count))
        if self._share_icon_index in order:
            order.insert(0, order.pop(order.index(self._share_icon_index)))
        self._share_order = order
        self._share_cursor = 0
        self._share_hover_next(run)

    def _share_hover_next(self, run: int) -> None:
        if run != self._share_run:
            return
        if self._share_cursor >= len(self._share_order):
            self._share_last = "share-icon-not-found"
            QTimer.singleShot(self._share_interval_ms, lambda: self._share_attempt(run))
            return
        self._share_index = self._share_order[self._share_cursor]
        self._run_js(
            _JS_HOVER_ROW_BUTTON.replace("__INDEX__", str(self._share_index)),
            lambda r: self._share_after_hover(run, r),
        )

    def _share_after_hover(self, run: int, result: object) -> None:
        if run != self._share_run:
            return
        if not (isinstance(result, dict) and result.get("ok")):
            self._share_cursor += 1
            self._share_hover_next(run)
            return
        self._share_hover_cx = int(result.get("cx", -1))
        QTimer.singleShot(
            _HOVER_SETTLE_MS,
            lambda: self.run_action(
                "tooltip_text", callback=lambda r: self._share_after_tooltip(run, r)
            ),
        )

    def _share_after_tooltip(self, run: int, result: object) -> None:
        if run != self._share_run:
            return
        if self._is_share_tooltip(result):
            self._share_icon_index = self._share_index
            self._share_icon_clicked = True
            self._run_js(
                _JS_CLICK_ROW_BUTTON.replace("__INDEX__", str(self._share_index)),
                lambda _result: QTimer.singleShot(
                    _SHARE_CLICK_SETTLE_MS, lambda: self._share_attempt(run)
                ),
            )
            return
        self._share_cursor += 1
        self._share_hover_next(run)

    def _is_share_tooltip(self, result: object) -> bool:
        """刚悬浮那个图标的 tooltip 是不是「分享」。

        位置核对不可省：tooltip 门户是异步卸载的，前一个图标的提示会残留到
        下一次读取，只看文字会点错图标（例如点到「重新生成」）。
        """
        if not isinstance(result, dict):
            return False
        for tip in result.get("tips") or []:
            if not isinstance(tip, dict) or tip.get("text") != "分享":
                continue
            if abs(int(tip.get("cx", -9999)) - self._share_hover_cx) <= _TIP_CENTER_TOLERANCE:
                return True
        return False

    def _run_js(self, script: str, callback=None) -> None:
        self._page.runJavaScript(script, 0, _decode_callback(callback))

    def wait_for_result(
        self, callback=None, timeout_ms: int = 180000, interval_ms: int = 2000
    ) -> None:
        """轮询页面大图数量，出现「第二段增长」才视为生成完成。

        发送后马上会有一条增长——自己消息里的上传原图回显（CDN 地址，
        不是 blob:），只等它就复制分享链接会快好几秒，快照里还没有生成图。
        所以第一段增长只用来把基线抬到回显水位（若一次涨了 ≥2 张，说明
        生成图也已在页面里，直接算完成），之后再次增长才算生成完成。
        """
        self._poll_until(
            "large_image_count",
            lambda result: _count_of(result) > self._result_baseline,
            on_success=lambda result: self._await_generated_images(
                result, callback, timeout_ms, interval_ms
            ),
            on_timeout=lambda: self._emit(
                callback, {"ok": False, "stage": "wait_result", "detail": "timeout"}
            ),
            timeout_ms=min(_SEND_ECHO_TIMEOUT_MS, timeout_ms),
            interval_ms=interval_ms,
        )

    def _await_generated_images(
        self, echo: object, callback, timeout_ms: int, interval_ms: int
    ) -> None:
        echo_count = _count_of(echo)
        if echo_count > self._result_baseline + 1:
            # 一次涨了 ≥2 张：生成图与回显同帧渲染，直接算完成
            self._emit(
                callback, {"ok": True, "stage": "wait_result", "detail": "image-found"}
            )
            return
        self._result_baseline = echo_count
        self._poll_until(
            "large_image_count",
            lambda result: _count_of(result) > self._result_baseline,
            on_success=lambda result: self._emit(
                callback, {"ok": True, "stage": "wait_result", "detail": "image-found"}
            ),
            on_timeout=lambda: self._emit(
                callback, {"ok": False, "stage": "wait_result", "detail": "timeout"}
            ),
            timeout_ms=timeout_ms,
            interval_ms=interval_ms,
        )

    # —— 内部流程 ——

    @staticmethod
    def _on_permission_requested(permission: QWebEnginePermission) -> None:
        """只放行剪贴板写入（复制链接要用），其余权限一律拒绝。"""
        if permission.permissionType() == QWebEnginePermission.PermissionType.ClipboardReadWrite:
            permission.grant()
        else:
            permission.deny()

    def _when_ready(self, run) -> None:
        if self._load_finished:
            run()
            return
        self._pending_action = run

    def _on_load_finished(self, ok: bool) -> None:
        self._load_finished = bool(ok)
        pending = self._pending_action
        self._pending_action = None
        if ok and pending is not None:
            pending()

    def _clear_then_paste(self, callback) -> None:
        """清残留（旧附件/旧提示词）再贴图；清失败也继续贴，避免卡死。"""
        self.run_action(
            "clear_input",
            callback=lambda _result: self._paste_image(callback),
        )

    def _clear_text_then_paste(self, prompt: str, callback) -> None:
        self.run_action(
            "clear_text",
            callback=lambda _result: self._paste_text(prompt, callback),
        )

    def _paste_image(self, callback) -> None:
        image = QImage.fromData(self._source_bytes or b"")
        if image.isNull():
            self._emit(
                callback, {"ok": False, "stage": "upload", "detail": "image-unreadable"}
            )
            return
        self.run_action(
            "blob_image_count",
            callback=lambda result: self._paste_image_now(image, result, callback),
        )

    def _paste_image_now(
        self, image: QImage, before: object, callback, attempts_left: int = _UPLOAD_ATTEMPTS
    ) -> None:
        self._blob_baseline = _count_of(before)
        QApplication.clipboard().setImage(image)
        retry = None
        if attempts_left > 1:
            retry = lambda: self._paste_image_now(  # noqa: E731
                image, before, callback, attempts_left - 1
            )
        self._paste_and_verify(
            "upload",
            "blob_image_count",
            lambda result: _count_of(result) > self._blob_baseline,
            callback,
            on_retry=retry,
        )

    def _paste_text(self, prompt: str, callback) -> None:
        QApplication.clipboard().setText(prompt)
        self._paste_and_verify(
            "fill_prompt",
            "input_state",
            lambda result: isinstance(result, dict) and bool(result.get("textLength")),
            callback,
        )

    def _paste_and_verify(self, stage, verify_action, is_done, callback, on_retry=None) -> None:
        self.run_action(
            "focus_input",
            callback=lambda result: self._after_focus(
                result, stage, verify_action, is_done, callback, on_retry
            ),
        )

    def _after_focus(
        self, focus: object, stage, verify_action, is_done, callback, on_retry=None
    ) -> None:
        if not (isinstance(focus, dict) and focus.get("ok")):
            self._emit(callback, {"ok": False, "stage": stage, "detail": "input-not-found"})
            return
        self._page.triggerAction(QWebEnginePage.WebAction.Paste)
        self._poll_until(
            verify_action,
            is_done,
            on_success=lambda result: self._emit(
                callback, {"ok": True, "stage": stage, "detail": "pasted"}
            ),
            on_timeout=lambda: self._retry_or_fail(stage, callback, on_retry),
            timeout_ms=_PASTE_VERIFY_TIMEOUT_MS,
        )

    def _retry_or_fail(self, stage, callback, on_retry) -> None:
        if on_retry is None:
            self._emit(callback, {"ok": False, "stage": stage, "detail": "verify-timeout"})
        else:
            on_retry()

    def _await_manual_send(
        self, baseline: object, callback, timeout_ms: int, interval_ms: int
    ) -> None:
        self._result_baseline = _count_of(baseline)
        self._poll_until(
            "input_state",
            lambda state: isinstance(state, dict) and state.get("textLength") == 0,
            on_success=lambda state: self._emit(
                callback, {"ok": True, "stage": "send", "detail": "sent"}
            ),
            on_timeout=lambda: self._emit(
                callback, {"ok": False, "stage": "send", "detail": "not-sent"}
            ),
            timeout_ms=timeout_ms,
            interval_ms=interval_ms,
        )

    def _poll_until(
        self,
        action: str,
        is_done,
        on_success,
        on_timeout,
        timeout_ms: int,
        interval_ms: int = 1000,
    ) -> None:
        """轮询页面动作直到 is_done 为真；超时走 on_timeout 由调用方降级。

        begin_flow 之后旧轮询立即失效：否则上一轮 wait_for_result 还在改
        _result_baseline，新一轮的增长判定会永远对不上（第二次点击后检测不到
        生成结果）。
        """
        run = getattr(self, "_flow_run", 0)
        deadline = time.monotonic() + timeout_ms / 1000.0

        def _tick() -> None:
            if run != getattr(self, "_flow_run", 0):
                return
            self.run_action(action, callback=_on_result)

        def _on_result(result: object) -> None:
            if run != getattr(self, "_flow_run", 0):
                return
            if is_done(result):
                on_success(result)
            elif time.monotonic() >= deadline:
                on_timeout()
            else:
                QTimer.singleShot(interval_ms, _tick)

        _tick()

    @staticmethod
    def _emit(callback, result: dict) -> None:
        if callback is not None:
            callback(result)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self._overlay.isVisible():
            self._overlay.setGeometry(self._view.geometry())

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self.load_doubao()
