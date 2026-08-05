"""商品分析用例 — OCR 文字识别 + LLM Vision 图片理解 → ProductAnalysisResult。"""

from __future__ import annotations

import json
from pathlib import Path

from src.domain.product_info import (
    ImageUnderstanding,
    ProductAnalysisResult,
    ProductFact,
    ProductManualInfo,
)


class AnalyzeProduct:
    """第二步：OCR 文字识别 + LLM Vision 图片理解 → 商品事实信息表。"""

    def __init__(self, ocr_adapter, llm_adapter, image_loader=None) -> None:
        self._ocr = ocr_adapter
        self._llm = llm_adapter
        self._image_loader = image_loader

    def _load_image(self, path: Path):
        """加载图片为 ImageDocument。优先使用注入的 loader，否则 fallback 到 PillowImageCodec。"""
        if self._image_loader is not None:
            from src.domain.image import ImageLimits
            return self._image_loader(path, ImageLimits())
        from src.domain.image import ImageLimits
        from src.infrastructure.pillow_image_codec import PillowImageCodec
        return PillowImageCodec().load(path, ImageLimits())

    def execute(
        self,
        image_paths: list[Path],
        manual_info: ProductManualInfo,
    ) -> ProductAnalysisResult:
        # 1) 对每张图运行 OCR
        ocr_texts: list[str] = []
        for path in image_paths:
            try:
                doc = self._load_image(path)
                result = self._ocr.recognize(doc, "en")
                for region in result.regions:
                    if region.text and region.text.strip():
                        ocr_texts.append(region.text.strip())
            except Exception as e:
                import traceback
                print(f"[AnalyzeProduct] OCR error for {path}: {e}")
                traceback.print_exc()

        ocr_combined = "\n".join(ocr_texts)

        # 2) 构建 Vision prompt
        prompt = self._build_vision_prompt(manual_info, ocr_combined)

        # 3) 调用 LLM Vision（分析前 3 张图，合并结果）
        vision_result: dict = {}
        max_images = min(3, len(image_paths))
        raw = ""
        for i in range(max_images):
            try:
                raw = self._llm.chat_with_image(
                    image_paths[i],
                    prompt,
                    max_tokens=4096,
                )
                partial = self._parse_vision_response(raw)
                if i == 0:
                    vision_result = partial
                else:
                    # 合并：非空值覆盖空值
                    for key, value in partial.items():
                        if value and not vision_result.get(key):
                            vision_result[key] = value
                print(f"[AnalyzeProduct] Vision image {i+1} raw ({len(raw)} chars)")
            except Exception as e:
                print(f"[AnalyzeProduct] Vision image {i+1} failed: {e}")
            print(raw[:500] if len(raw) > 500 else raw)
            print(f"[AnalyzeProduct] Parsed vision keys: {list(vision_result.keys())}")

        # 4) 组装 ImageUnderstanding
        understanding = ImageUnderstanding(
            category=vision_result.get("category", ""),
            appearance=vision_result.get("appearance", ""),
            main_colors=vision_result.get("main_colors", []),
            packaging=vision_result.get("packaging", ""),
            visible_accessories=vision_result.get("visible_accessories", []),
            usage_scene=vision_result.get("usage_scene", ""),
            visual_style=vision_result.get("visual_style", ""),
            background=vision_result.get("background", ""),
            suitable_as_main=vision_result.get("suitable_as_main", False),
            suitable_as_detail=vision_result.get("suitable_as_detail", False),
        )

        # 5) 组装 ProductFact（合并 OCR + Vision + 手动资料）
        fact = self._build_fact(manual_info, vision_result, ocr_combined)

        return ProductAnalysisResult(
            ocr_text=ocr_combined,
            image_understanding=understanding,
            product_fact=fact,
            raw_llm_response=json.dumps(vision_result, ensure_ascii=False),
        )

    def _build_vision_prompt(
        self, info: ProductManualInfo, ocr_text: str
    ) -> str:
        parts = ["请分析这张商品图片，提取以下信息。"]
        if info.name:
            parts.append(f"已知商品名称: {info.name}")
        if info.brand:
            parts.append(f"已知品牌: {info.brand}")
        if info.category:
            parts.append(f"已知类别: {info.category}")
        if ocr_text:
            parts.append(f"图片中识别到的文字:\n{ocr_text}")
        parts.append("""
请返回 JSON 格式（只返回 JSON，不要其他文字）:
{
  "category": "商品类别",
  "appearance": "外观描述",
  "main_colors": ["颜色1", "颜色2"],
  "packaging": "包装形式",
  "visible_accessories": ["可见配件"],
  "usage_scene": "使用场景",
  "visual_style": "视觉风格",
  "background": "背景描述",
  "suitable_as_main": true,
  "suitable_as_detail": true,
  "name": "商品名称",
  "brand": "品牌",
  "model": "型号",
  "specs": "规格",
  "color": "颜色",
  "material": "材质",
  "package_quantity": "包装数量",
  "target_audience": "适用对象",
  "main_functions": ["功能1", "功能2"]
}
对于无法从图片中确定的信息，请留空字符串或空数组，不要编造。""")
        return "\n".join(parts)

    def _parse_vision_response(self, raw: str) -> dict:
        try:
            data = json.loads(raw)
            if "result" in data:
                return data["result"]
            return data
        except json.JSONDecodeError:
            import re
            match = re.search(r'\{[\s\S]*\}', raw)
            if match:
                try:
                    data = json.loads(match.group(0))
                    if "result" in data:
                        return data["result"]
                    return data
                except json.JSONDecodeError:
                    pass
            return {}

    def _build_fact(
        self,
        info: ProductManualInfo,
        vision: dict,
        ocr_text: str,
    ) -> ProductFact:
        source: dict[str, str] = {}
        confirmed: dict[str, bool] = {}
        uncertain: dict[str, bool] = {}

        def _set(field: str, value: str, src: str):
            source[field] = src

        # 按优先级：手动输入 > Vision > OCR
        name = info.name or vision.get("name", "")
        _set("name", info.name, "手动" if info.name else "AI推断")

        brand = info.brand or vision.get("brand", "")
        _set("brand", info.brand, "手动" if info.brand else "AI推断")

        model = info.model or vision.get("model", "")
        _set("model", info.model, "手动" if info.model else "AI推断")

        specs = info.specs or vision.get("specs", "")
        _set("specs", info.specs, "手动" if info.specs else "AI推断")

        color = info.color or vision.get("color", "")
        _set("color", info.color, "手动" if info.color else "AI推断")

        material = info.material or vision.get("material", "")
        _set("material", info.material, "手动" if info.material else "AI推断")

        return ProductFact(
            name=name, brand=brand, model=model, specs=specs,
            color=color, material=material,
            package_quantity=vision.get("package_quantity", ""),
            target_audience=vision.get("target_audience", ""),
            usage_scene=info.scene or vision.get("usage_scene", ""),
            main_functions=vision.get("main_functions", []),
            visible_accessories=vision.get("visible_accessories", []),
            source=source,
            confirmed=confirmed,
            uncertain=uncertain,
        )
