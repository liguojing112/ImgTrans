"""商品生成 — 商品信息领域模型。

包含商品素材图片、手动资料、AI分析结果等数据类。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ProductSourceImage:
    """商品素材图片"""

    id: str  # UUID
    path: Path  # 本地路径
    purpose: str = "main"  # main/detail/packaging/specs/scene/reference
    is_primary: bool = False
    order: int = 0


@dataclass
class ProductManualInfo:
    """手动输入的商品资料"""

    name: str = ""
    brand: str = ""
    category: str = ""
    model: str = ""
    specs: str = ""
    material: str = ""
    color: str = ""
    scene: str = ""
    target_market: str = ""
    original_description: str = ""
    notes: str = ""


@dataclass
class ProductFact:
    """商品事实信息（AI 分析结果 + 人工确认）"""

    name: str = ""
    brand: str = ""
    model: str = ""
    specs: str = ""
    color: str = ""
    material: str = ""
    package_quantity: str = ""
    target_audience: str = ""
    usage_scene: str = ""
    main_functions: list[str] = field(default_factory=list)
    visible_accessories: list[str] = field(default_factory=list)
    source: dict[str, str] = field(default_factory=dict)
    confirmed: dict[str, bool] = field(default_factory=dict)
    uncertain: dict[str, bool] = field(default_factory=dict)

    _FIELD_NAMES = (
        "name", "brand", "model", "specs", "color", "material",
        "package_quantity", "target_audience", "usage_scene",
    )

    @classmethod
    def field_names(cls) -> tuple[str, ...]:
        return cls._FIELD_NAMES

    def field_value(self, field_name: str) -> str:
        if field_name == "main_functions":
            return "、".join(self.main_functions)
        if field_name == "visible_accessories":
            return "、".join(self.visible_accessories)
        return getattr(self, field_name, "")

    def with_field(self, field_name: str, value: object) -> ProductFact:
        from dataclasses import replace
        return replace(self, **{field_name: value})


@dataclass
class ImageUnderstanding:
    """图片内容理解结果（LLM Vision 返回）"""

    category: str = ""
    appearance: str = ""
    main_colors: list[str] = field(default_factory=list)
    packaging: str = ""
    visible_accessories: list[str] = field(default_factory=list)
    usage_scene: str = ""
    visual_style: str = ""
    background: str = ""
    suitable_as_main: bool = False
    suitable_as_detail: bool = False


@dataclass
class ProductAnalysisResult:
    """AI 商品分析完整结果"""

    ocr_text: str = ""  # OCR 提取的全部文字
    image_understanding: ImageUnderstanding | None = None
    product_fact: ProductFact | None = None
    raw_llm_response: str = ""  # LLM 原始返回（调试用）


@dataclass
class ProductProject:
    """商品项目（可保存/恢复）"""

    id: str  # UUID
    name: str  # 商品名称
    created_at: str  # ISO 时间戳
    updated_at: str  # ISO 时间戳
    source_images: list[ProductSourceImage] = field(default_factory=list)
    manual_info: ProductManualInfo | None = None
    analysis_result: ProductAnalysisResult | None = None
    copywriting_result: object = None  # CopywritingResult
    target_language: str = "en"
    current_step: int = 0
