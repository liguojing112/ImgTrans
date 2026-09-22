"""强化翻译 — 提示词组装（纯函数，可脱离 Qt 测试）。

指令用中文书写：客户要能看懂、能自己改，交给AI的指令不必用外语。
翻译方向显式写成「把{原图文字语言}翻译成{目标语言}」（如俄语 → 英语）：
上传的图不一定是中文原图，只点目标语言AI可能翻错方向。
"""
from __future__ import annotations

from src.ui.languages import LANGUAGE_LABELS

_HEAD_WITH_SOURCE = (
    "把这张图片重新生成一张同尺寸的图片：把图中{source}文字翻译成{target}，"
    "替换为下面的译文对照，保持原始版式、字体风格、配色、图标与产品元素完全不变，"
    "不要添加或删除元素。"
)
_HEAD = (
    "把这张图片重新生成一张同尺寸的图片：把图中文字翻译成{target}，"
    "替换为下面的译文对照，保持原始版式、字体风格、配色、图标与产品元素完全不变，"
    "不要添加或删除元素。"
)
_MAPPING_LABEL = "文字对照（原文 → 译文）："
_TAIL = "只替换文字内容，其余部分与原图保持一致。"
_FALLBACK_WITH_SOURCE = (
    "把这张图片中的所有{source}文字翻译成{target}并重新生成图片，"
    "保持原始版式、配色与产品元素完全不变。"
)
_FALLBACK = (
    "把这张图片中的所有文字翻译成{target}并重新生成图片，"
    "保持原始版式、配色与产品元素完全不变。"
)

# 无任何语言信息时的兜底（与翻译设置面板的默认目标语言一致）
_DEFAULT_TARGET_LANGUAGE = "zh-Hans"


def _label(code: str | None) -> str:
    return LANGUAGE_LABELS.get(code, "") if isinstance(code, str) else ""


def _resolve_target(translation_result, target_language: str | None) -> str:
    """译文自身记录的目标语言优先：对照表里的译文就是那个语言写的。"""
    selection = getattr(translation_result, "selection", None)
    from_result = getattr(selection, "target_language", None)
    if _label(from_result):
        return from_result
    if _label(target_language):
        return target_language
    return _DEFAULT_TARGET_LANGUAGE


def _resolve_source(ocr_result, translation_result, source_language: str | None) -> str | None:
    """原图文字语言：译文记录 → 面板当前选择 → OCR 实际使用的语言。"""
    selection = getattr(translation_result, "selection", None)
    from_selection = getattr(selection, "source_language", None)
    if _label(from_selection):
        return from_selection
    if _label(source_language):
        return source_language
    from_ocr = getattr(ocr_result, "language_code", None)
    if _label(from_ocr):
        return from_ocr
    return None


def _iter_units(translation_result) -> list:
    return list(getattr(translation_result, "units", ()) or ())


def _iter_regions(ocr_result) -> dict[str, str]:
    regions = getattr(ocr_result, "regions", ()) or ()
    return {r.region_id: r.text for r in regions if getattr(r, "text", "")}


def build_prompt(
    ocr_result,
    translation_result,
    target_language: str | None = None,
    source_language: str | None = None,
) -> str:
    """从 OCR 原文与译文组装图生图提示词。

    指令为中文并点名翻译方向；无翻译结果时返回同方向的通用模板。
    """
    target = _label(_resolve_target(translation_result, target_language)) or "目标语言"
    source = _label(_resolve_source(ocr_result, translation_result, source_language))

    original_texts = _iter_regions(ocr_result)
    pairs: list[tuple[str, str]] = []
    for unit in _iter_units(translation_result):
        source_text = original_texts.get(unit.region_id, "")
        translated = str(getattr(unit, "translated_text", "") or "").strip()
        if not translated:
            source_text = str(getattr(unit, "source_text", "") or "").strip()
            translated = source_text
        if source_text:
            pairs.append((source_text, translated))
    if not pairs:
        if source:
            return _FALLBACK_WITH_SOURCE.format(source=source, target=target)
        return _FALLBACK.format(target=target)

    if source:
        head = _HEAD_WITH_SOURCE.format(source=source, target=target)
    else:
        head = _HEAD.format(target=target)
    lines = [head, "", _MAPPING_LABEL]
    for source_text, translated in pairs:
        lines.append(f"{source_text} → {translated}")
    lines.append("")
    lines.append(_TAIL)
    return "\n".join(lines)
