"""商品详情生成 — 文案领域模型。

包含图片标签、长尾场景词、产品标题、卖点、简介和详情文案等数据类。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ImageTag:
    """图片标签"""

    id: str
    tag: str
    language: str = "en"


@dataclass
class LongTailKeyword:
    """长尾场景词"""

    id: str
    keyword: str  # 目标语言
    original_meaning: str = ""  # 中文含义


@dataclass
class ProductTitle:
    """产品标题"""

    id: str
    title: str
    char_count: int = 0
    is_selected: bool = False


@dataclass
class SellingPoint:
    """商品卖点"""

    id: str
    category: str  # core/function/scene/material/packaging
    text: str
    order: int = 0
    locked: bool = False


@dataclass
class ProductIntro:
    """商品简介"""

    one_liner: str = ""
    short_description: str = ""
    standard_intro: str = ""
    translations: dict[str, str] = field(default_factory=dict)


@dataclass
class DetailModule:
    """详情文案模块"""

    section: str  # overview/advantages/functions/scenes/specs/packing/instructions/notes
    title: str  # 模块标题
    content: str  # 模块内容


@dataclass
class CopywritingResult:
    """文案生成完整结果"""

    tags: list[ImageTag] = field(default_factory=list)
    keywords: list[LongTailKeyword] = field(default_factory=list)
    titles: list[ProductTitle] = field(default_factory=list)
    selling_points: list[SellingPoint] = field(default_factory=list)
    intro: ProductIntro | None = None
    detail_modules: list[DetailModule] = field(default_factory=list)
    target_language: str = "en"


@dataclass
class CopywritingSettings:
    """文案生成设置"""

    target_language: str = "en"
    target_country: str = ""
    platform: str = "general"
    style: str = "professional"
    tone: str = "neutral"
    title_count: int = 5
    tag_count: int = 10
    keyword_count: int = 10
    title_max_chars: int = 200
    keep_brand: bool = True
    keep_model: bool = True
    banned_words: list[str] = field(default_factory=list)
    custom_keywords: list[str] = field(default_factory=list)
    custom_requirements: str = ""
