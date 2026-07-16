from __future__ import annotations

from pathlib import Path
import platform
from threading import Lock

from PySide6.QtGui import QFontDatabase

from src.domain.layout import LayoutError


_LOCK = Lock()
_REGISTERED = False


def resolve_system_font(language_code: str) -> str:
    _register_system_fonts()
    available = {family.casefold(): family for family in QFontDatabase.families()}
    for preferred in _preferred_families(language_code, platform.system()):
        if preferred.casefold() in available:
            return available[preferred.casefold()]
    if available:
        return sorted(available.values())[0]
    raise LayoutError("font_unavailable", "系统中没有可用于渲染译文的合法字体")


def _register_system_fonts() -> None:
    global _REGISTERED
    with _LOCK:
        if _REGISTERED:
            return
        for path in _font_candidates(platform.system()):
            if path.is_file():
                QFontDatabase.addApplicationFont(str(path))
        _REGISTERED = True


def _font_candidates(system: str) -> tuple[Path, ...]:
    if system == "Windows":
        root = Path("C:/Windows/Fonts")
        return tuple(
            root / name
            for name in (
                "msyh.ttc",
                "meiryo.ttc",
                "malgun.ttf",
                "segoeui.ttf",
                "arial.ttf",
                "Nirmala.ttf",
                "leelawui.ttf",
            )
        )
    if system == "Darwin":
        return tuple(
            Path(path)
            for path in (
                "/System/Library/Fonts/PingFang.ttc",
                "/System/Library/Fonts/AppleSDGothicNeo.ttc",
                "/System/Library/Fonts/GeezaPro.ttc",
                "/System/Library/Fonts/Kohinoor.ttc",
                "/System/Library/Fonts/Thonburi.ttc",
                "/System/Library/Fonts/Supplemental/Arial.ttf",
            )
        )
    return tuple(
        Path(path)
        for path in (
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        )
    )


def _preferred_families(language_code: str, system: str) -> tuple[str, ...]:
    if system == "Windows":
        if language_code in {"zh-Hans", "zh-Hant"}:
            return ("Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI")
        if language_code in {"hi", "bn", "ar", "fa", "ur"}:
            return ("Nirmala UI", "Segoe UI", "Arial")
        if language_code == "th":
            return ("Leelawadee UI", "Tahoma", "Segoe UI")
        if language_code == "ja":
            return ("Yu Gothic UI", "Meiryo", "Segoe UI")
        if language_code == "ko":
            return ("Malgun Gothic", "Segoe UI")
        return ("Segoe UI", "Arial")
    if system == "Darwin":
        if language_code in {"zh-Hans", "zh-Hant"}:
            return ("PingFang SC", "PingFang TC", "Helvetica Neue")
        if language_code in {"ar", "fa", "ur"}:
            return ("Geeza Pro", "Arial")
        if language_code == "hi":
            return ("Kohinoor Devanagari", "Arial")
        if language_code == "bn":
            return ("Kohinoor Bangla", "Arial")
        if language_code == "th":
            return ("Thonburi", "Arial")
        return ("Helvetica Neue", "Arial")
    return ("Noto Sans", "Noto Sans CJK SC", "DejaVu Sans")
