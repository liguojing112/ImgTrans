"""万象笔记入口 — 用系统自带的 Microsoft Edge 打开网页。

不再内嵌 QtWebEngine：客户机器上 GPU 合成层处理固定定位的底部菜单栏时会
闪动，而自带的 Edge 渲染稳定，也不用随包分发 Chromium。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


def open_in_edge(url: str) -> str:
    """用 Microsoft Edge 打开链接，返回实际使用的浏览器名。

    Edge 不可用时退回系统默认浏览器，保证入口仍然可用。
    """
    edge = _find_edge()
    if edge is not None:
        try:
            subprocess.Popen([str(edge), url], close_fds=True)
            return "Microsoft Edge"
        except OSError:
            pass
    _open_with_default(url)
    return "系统默认浏览器"


def _find_edge() -> Path | None:
    if sys.platform != "win32":
        return None
    candidates = (
        os.environ.get("PROGRAMFILES(X86)"),
        os.environ.get("PROGRAMFILES"),
        os.environ.get("LOCALAPPDATA"),
    )
    for root in candidates:
        if not root:
            continue
        candidate = Path(root) / "Microsoft" / "Edge" / "Application" / "msedge.exe"
        if candidate.is_file():
            return candidate
    found = shutil.which("msedge")
    return Path(found) if found else None


def _open_with_default(url: str) -> None:
    if sys.platform == "win32":
        os.startfile(url)  # noqa: S606 - 已由调用方确认是用户配置的链接
        return
    import webbrowser

    webbrowser.open(url)
