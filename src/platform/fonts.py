from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import platform
from threading import Lock

from PySide6.QtGui import QFontDatabase

from src.domain.layout import LayoutError


_LOCK = Lock()
_REGISTERED = False


@dataclass(frozen=True, slots=True)
class FontResolution:
    language_code: str
    family: str
    degraded: bool
    reason: str | None = None


def resolve_system_font(language_code: str) -> str:
    return resolve_system_font_details(language_code).family


def resolve_system_font_details(language_code: str) -> FontResolution:
    _register_system_fonts()
    return _select_font(
        language_code,
        platform.system(),
        tuple(QFontDatabase.families()),
    )


def _select_font(
    language_code: str,
    system: str,
    available_families: tuple[str, ...],
) -> FontResolution:
    available = {family.casefold(): family for family in available_families}
    for index, preferred in enumerate(_preferred_families(language_code, system)):
        if preferred.casefold() in available:
            return FontResolution(
                language_code,
                available[preferred.casefold()],
                index > 0,
                "preferred_font_unavailable" if index > 0 else None,
            )
    if available:
        return FontResolution(
            language_code,
            sorted(available.values(), key=str.casefold)[0],
            True,
            "script_font_unavailable",
        )
    raise LayoutError("font_unavailable", "系统中没有可用于渲染译文的合法字体")


def resolve_style_font_details(
    language_code: str,
    serif: bool,
) -> FontResolution:
    """按原图文字风格解析译文字体：衬线类优先衬线字体族，缺失时回退默认匹配。

    serif=True 来自原图文字的粗略分类（横细竖粗、笔画端部有装饰）；
    分类不可靠时调用方应传 False，保持无衬线默认，避免字体观感变差。
    """
    if not serif:
        return resolve_system_font_details(language_code)
    _register_system_fonts()
    return _select_style_font(
        language_code,
        platform.system(),
        tuple(QFontDatabase.families()),
    )


def _select_style_font(
    language_code: str,
    system: str,
    available_families: tuple[str, ...],
) -> FontResolution:
    available = {family.casefold(): family for family in available_families}
    for preferred in _serif_families(language_code, system):
        if preferred.casefold() in available:
            return FontResolution(
                language_code,
                available[preferred.casefold()],
                False,
                None,
            )
    return _select_font(language_code, system, available_families)


def _serif_families(language_code: str, system: str) -> tuple[str, ...]:
    if system == "Windows":
        if language_code in {"zh-Hans", "zh-Hant"}:
            return ("SimSun", "宋体", "NSimSun", "Songti SC", "STSong", "KaiTi", "楷体")
        if language_code == "ja":
            return ("Yu Mincho", "MS Mincho", "YuMincho")
        if language_code == "ko":
            return ("Batang", "BatangChe")
        return ("Times New Roman", "Georgia", "Cambria", "Constantia")
    if system == "Darwin":
        if language_code in {"zh-Hans", "zh-Hant"}:
            return ("Songti SC", "STSong", "Songti TC")
        if language_code == "ja":
            return ("Hiragino Mincho ProN", "YuMincho")
        if language_code == "ko":
            return ("AppleMyungjo",)
        return ("Times New Roman", "Georgia", "New York")
    return ("Noto Serif", "Noto Serif CJK SC", "DejaVu Serif")


def resolve_kai_font_details(
    language_code: str,
    preferred: str | None = None,
) -> FontResolution:
    """楷体类原图的译文字体：优先用户指定，其次系统/打包楷体，最后回退默认。"""
    if preferred and preferred.strip():
        return FontResolution(language_code, preferred.strip(), False, None)
    _register_system_fonts()
    available = {family.casefold(): family for family in QFontDatabase.families()}
    for name in (
        "KaiTi",
        "楷体",
        "STKaiti",
        "Kaiti SC",
        "HanWang KaiBold-Gb5",
        "TW-MOE-Std-Kai",
        "HanWangYanKai",
    ):
        if name.casefold() in available:
            return FontResolution(language_code, available[name.casefold()], False, None)
    return _select_font(language_code, platform.system(), tuple(QFontDatabase.families()))


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
                "YuGothR.ttc",
                "malgun.ttf",
                "segoeui.ttf",
                "arial.ttf",
                "Nirmala.ttc",
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
        if language_code == "zh-Hans":
            return ("PingFang SC", "PingFang TC", "Helvetica Neue", "Arial")
        if language_code == "zh-Hant":
            return ("PingFang TC", "PingFang SC", "Helvetica Neue", "Arial")
        if language_code == "ja":
            return ("Hiragino Sans", "Hiragino Kaku Gothic ProN", "Helvetica Neue")
        if language_code == "ko":
            return ("Apple SD Gothic Neo", "Helvetica Neue")
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
