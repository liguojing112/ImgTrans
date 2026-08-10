"""文案生成用例 — 基于商品事实 + LLM 生成电商文案。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import uuid

from src.domain.product_info import ProductAnalysisResult, ProductFact, ProductManualInfo
from src.domain.copywriting import (
    CopywritingResult,
    CopywritingSettings,
    DetailModule,
    ImageTag,
    LongTailKeyword,
    ProductIntro,
    ProductTitle,
    SellingPoint,
)


# Keep the prompt language explicit.  Sending only a locale code (for example
# ``ja`` or ``zh-Hant``) makes some providers fall back to their default
# language, which is particularly visible in the detail/specification module.
_TARGET_LANGUAGE_NAMES = {
    "zh-Hans": "Simplified Chinese",
    "zh-Hant": "Traditional Chinese",
    "ru": "Russian",
    "ja": "Japanese",
    "ko": "Korean",
    "en": "English",
    "th": "Thai",
    "ar": "Arabic",
    "vi": "Vietnamese",
    "it": "Italian",
    "de": "German",
    "id": "Indonesian",
    "pt-PT": "European Portuguese",
    "pt-BR": "Brazilian Portuguese",
    "fil": "Filipino",
    "pl": "Polish",
    "ms": "Malay",
    "hi": "Hindi",
    "es": "Spanish",
    "fr": "French",
    "bn": "Bengali",
    "ur": "Urdu",
    "tr": "Turkish",
    "fa": "Persian",
    "sw": "Swahili",
}


class GenerateCopywriting:
    """第三步：基于事实信息表 + LLM 生成电商文案。"""

    def __init__(self, llm_adapter) -> None:
        self._llm = llm_adapter

    def execute(
        self,
        fact: ProductFact,
        manual_info: ProductManualInfo,
        settings: CopywritingSettings,
    ) -> CopywritingResult:
        print("[Copywriting] 开始生成文案...", flush=True)
        # 各类文案互相独立，并行调用 LLM 显著缩短总耗时（原为 8 次串行）
        with ThreadPoolExecutor(max_workers=6) as pool:
            tags_future = pool.submit(
                self._run_safe, self._generate_tags, fact, settings
            )
            keywords_future = pool.submit(
                self._run_safe, self._generate_keywords, fact, settings
            )
            titles_future = pool.submit(
                self._run_safe, self._generate_titles, fact, manual_info, settings
            )
            selling_points_future = pool.submit(
                self._run_safe, self._generate_selling_points, fact, settings
            )
            intro_future = pool.submit(
                self._run_safe, self._generate_intro, fact, settings
            )
            detail_future = pool.submit(
                self._run_safe, self._generate_detail_modules, fact, settings
            )
            tags = tags_future.result() or []
            keywords = keywords_future.result() or []
            titles = titles_future.result() or []
            selling_points = selling_points_future.result() or []
            intro = intro_future.result() or ProductIntro()
            detail_modules = detail_future.result() or []

        return CopywritingResult(
            tags=tags,
            keywords=keywords,
            titles=titles,
            selling_points=selling_points,
            intro=intro,
            detail_modules=detail_modules,
            target_language=settings.target_language,
        )

    def _run_safe(self, fn, *args):
        # 网络/限流偶发失败时重试两次，避免单项内容缺失
        for attempt in range(3):
            try:
                return fn(*args)
            except Exception as error:
                print(
                    f"[Copywriting] 生成失败(第{attempt + 1}次): {error}",
                    flush=True,
                )
                import time

                time.sleep(1.0 * (attempt + 1))
        return None

    def regenerate_item(
        self,
        fact: ProductFact,
        manual_info: ProductManualInfo,
        settings: CopywritingSettings,
        item_type: str,
    ) -> CopywritingResult:
        """重新生成单类文案。item_type 格式: "tags"|"keywords"|"titles"|
        "selling_points"|"intro"|"detail:overview"|..."""
        print(f"[Copywriting] 重新生成: {item_type}", flush=True)
        if item_type == "tags":
            tags = self._generate_tags(fact, settings)
            return CopywritingResult(tags=tags, keywords=[], titles=[],
                                     selling_points=[], intro=None, detail_modules=[],
                                     target_language=settings.target_language)
        elif item_type == "keywords":
            keywords = self._generate_keywords(fact, settings)
            return CopywritingResult(tags=[], keywords=keywords, titles=[],
                                     selling_points=[], intro=None, detail_modules=[],
                                     target_language=settings.target_language)
        elif item_type == "titles":
            titles = self._generate_titles(fact, manual_info, settings)
            return CopywritingResult(tags=[], keywords=[], titles=titles,
                                     selling_points=[], intro=None, detail_modules=[],
                                     target_language=settings.target_language)
        elif item_type == "selling_points":
            sps = self._generate_selling_points(fact, settings)
            return CopywritingResult(tags=[], keywords=[], titles=[],
                                     selling_points=sps, intro=None, detail_modules=[],
                                     target_language=settings.target_language)
        elif item_type == "intro":
            intro = self._generate_intro(fact, settings)
            return CopywritingResult(tags=[], keywords=[], titles=[],
                                     selling_points=[], intro=intro, detail_modules=[],
                                     target_language=settings.target_language)
        elif item_type.startswith("detail:"):
            section = item_type.split(":", 1)[1]
            modules = self._generate_detail_modules(fact, settings)
            filtered = [m for m in modules if m.section == section]
            return CopywritingResult(tags=[], keywords=[], titles=[],
                                     selling_points=[], intro=None,
                                     detail_modules=filtered,
                                     target_language=settings.target_language)
        return CopywritingResult(tags=[], keywords=[], titles=[],
                                 selling_points=[], intro=None, detail_modules=[],
                                 target_language=settings.target_language)

    # ── 图片标签 ──

    def _generate_tags(
        self, fact: ProductFact, settings: CopywritingSettings
    ) -> list[ImageTag]:
        prompt = self._base_prompt(fact, settings)
        prompt += (
            f"\n请生成 {settings.tag_count} 个电商图片标签，用于 {settings.target_language} 市场。"
            f"\n标签风格: {settings.style}，语气: {settings.tone}。"
            f"\n每个标签一行，只返回标签列表，不要编号。"
        )
        if settings.banned_words:
            prompt += f"\n不要使用以下词语: {', '.join(settings.banned_words)}"

        raw = self._llm.chat(
            [{"role": "user", "content": prompt}],
            max_tokens=1024,
        )
        return self._parse_lines(raw, settings, ImageTag)

    # ── 长尾场景词 ──

    def _generate_keywords(
        self, fact: ProductFact, settings: CopywritingSettings
    ) -> list[LongTailKeyword]:
        prompt = self._base_prompt(fact, settings)
        prompt += (
            f"\n请生成 {settings.keyword_count} 个长尾搜索场景词，用于 {settings.target_language} 市场。"
            f"\n每个场景词一行，同时在括号中给出中文含义。"
            f"\nFormat: one {self._language_name(settings)} keyword per line; "
            "do not default to English."
        )
        raw = self._llm.chat(
            [{"role": "user", "content": prompt}],
            max_tokens=2048,
        )
        return self._parse_lines(raw, settings, LongTailKeyword)[:settings.keyword_count]

    # ── 产品标题 ──

    def _generate_titles(
        self, fact: ProductFact, manual_info: ProductManualInfo,
        settings: CopywritingSettings,
    ) -> list[ProductTitle]:
        prompt = self._base_prompt(fact, settings)
        brand_hint = ""
        if settings.keep_brand and (fact.brand or manual_info.brand):
            brand_hint = f"标题中必须包含品牌: {fact.brand or manual_info.brand}"
        model_hint = ""
        if settings.keep_model and (fact.model or manual_info.model):
            model_hint = f"标题中必须包含型号: {fact.model or manual_info.model}"

        prompt += (
            f"\n请生成 {settings.title_count} 个产品标题，用于 {settings.target_language} 市场。"
            f"\n每个标题不超过 {settings.title_max_chars} 个字符。"
            f"\n风格: {settings.style}，语气: {settings.tone}。"
            + (f"\n{brand_hint}" if brand_hint else "")
            + (f"\n{model_hint}" if model_hint else "")
            + "\n每个标题一行。"
        )
        if settings.custom_keywords:
            prompt += f"\n尝试融入以下关键词: {', '.join(settings.custom_keywords)}"

        lines = self._llm.chat(
            [{"role": "user", "content": prompt}],
            max_tokens=2048,
        ).strip().split("\n")

        results: list[ProductTitle] = []
        for i, line in enumerate(lines):
            text = line.strip().lstrip("0123456789. -) ")
            if not text:
                continue
            results.append(ProductTitle(
                id=str(uuid.uuid4()),
                title=text,
                char_count=len(text),
                is_selected=(i == 0),
            ))
        return results[:settings.title_count]

    # ── 商品卖点 ──

    def _generate_selling_points(
        self, fact: ProductFact, settings: CopywritingSettings
    ) -> list[SellingPoint]:
        categories = [
            ("core", "核心卖点"),
            ("function", "功能卖点"),
            ("scene", "使用场景卖点"),
            ("material", "材质/结构卖点"),
            ("packaging", "包装与配件卖点"),
        ]
        prompt = self._base_prompt(fact, settings)
        prompt += (
            f"\n请为这个商品生成卖点，按以下分类各生成 1-2 条卖点，用于 {settings.target_language} 市场:"
        )
        for cat, label in categories:
            prompt += f"\n- {label}"
        prompt += "\n\n返回 JSON 格式:\n{"
        prompt += ", ".join(f'"{cat}": ["卖点1", "卖点2"]' for cat, _ in categories)
        prompt += "}\n只返回 JSON。"

        raw = self._llm.chat(
            [{"role": "user", "content": prompt}],
            max_tokens=1024,
        )

        try:
            data = json.loads(_extract_json(raw))
        except (json.JSONDecodeError, KeyError):
            data = {}

        results: list[SellingPoint] = []
        for i, (cat, _) in enumerate(categories):
            points = data.get(cat, [])
            for j, text in enumerate(points):
                results.append(SellingPoint(
                    id=str(uuid.uuid4()),
                    category=cat,
                    text=text,
                    order=i * 10 + j,
                ))
        return results

    # ── 商品简介 ──

    def _generate_intro(
        self, fact: ProductFact, settings: CopywritingSettings
    ) -> ProductIntro:
        prompt = self._base_prompt(fact, settings)
        prompt += (
            f"\n请为这个商品生成简介文案，用于 {settings.target_language} 市场。"
            f"\n风格: {settings.style}，语气: {settings.tone}。"
            f"\n请返回 JSON:\n{{"
            f'\n  "one_liner": "一句话简介（15词以内）",'
            f'\n  "short_description": "短描述（50词以内）",'
            f'\n  "standard_intro": "标准简介（100词以内）"'
            f"\n}}\n只返回 JSON。"
        )
        raw = self._llm.chat(
            [{"role": "user", "content": prompt}],
            max_tokens=1024,
        )
        try:
            data = json.loads(_extract_json(raw))
        except (json.JSONDecodeError, KeyError):
            data = {}
        return ProductIntro(
            one_liner=data.get("one_liner", ""),
            short_description=data.get("short_description", ""),
            standard_intro=data.get("standard_intro", ""),
        )

    # ── 详情文案 ──

    def _generate_detail_modules(
        self, fact: ProductFact, settings: CopywritingSettings
    ) -> list[DetailModule]:
        sections = [
            ("overview", "产品概述"),
            ("advantages", "核心优势"),
            ("functions", "功能介绍"),
            ("scenes", "使用场景"),
            ("specs", "规格参数"),
            ("packing", "包装清单"),
            ("instructions", "使用说明"),
            ("notes", "注意事项"),
        ]

        generated: dict[str, DetailModule] = {}
        # 分批生成：每批 4 个模块（max_tokens 4096 下不会截断），
        # 全部批次与规格并行，减少请求数、缩短总耗时
        batch_size = 4
        non_specs = [item for item in sections if item[0] != "specs"]
        batches = [
            non_specs[start:start + batch_size]
            for start in range(0, len(non_specs), batch_size)
        ]
        with ThreadPoolExecutor(max_workers=6) as pool:
            specs_future = pool.submit(
                self._run_safe, self._generate_specs, fact, settings
            )
            batch_futures = [
                pool.submit(
                    self._run_safe, self._generate_detail_batch, fact, settings, batch
                )
                for batch in batches
            ]
            specs = specs_future.result()
            batch_results = [future.result() for future in batch_futures]
        if specs:
            generated[specs.section] = specs
        for batch_result in batch_results:
            if batch_result:
                generated.update({module.section: module for module in batch_result})
        return [generated.get(sec, DetailModule(section=sec, title=label, content=""))
                for sec, label in sections]

    def _generate_specs(
        self, fact: ProductFact, settings: CopywritingSettings,
    ) -> DetailModule:
        """Generate factual specifications in the selected target language."""
        prompt = self._base_prompt(fact, settings)
        prompt += (
            "\nSPECIFICATION TRANSLATION (mandatory):\n"
            f"Write every human-readable label and value in {self._language_name(settings)}. "
            f"The target language is {self._language_name(settings)} (locale code: {settings.target_language}). "
            "Do not leave Chinese source text in the result unless it is a protected brand or model. "
            "Keep numbers, units, SKUs and protected brand/model names unchanged. "
            "Return one bullet per fact and no JSON, headings, explanations or source-language copy.\n"
            "Facts to render:\n"
            f"- Product name: {fact.name}\n"
            f"- Brand: {fact.brand}\n"
            f"- Model: {fact.model}\n"
            f"- Specification: {fact.specs}\n"
            f"- Color: {fact.color}\n"
            f"- Material: {fact.material}\n"
            f"- Package quantity: {fact.package_quantity}\n"
        )
        raw = self._llm.chat([{"role": "user", "content": prompt}], max_tokens=1024)
        content = raw.strip()
        if content.startswith("```"):
            content = "\n".join(
                line for line in content.splitlines()
                if not line.strip().startswith("```")
            )
        return DetailModule(section="specs", title="规格参数", content=content.strip())

    def _generate_detail_batch(
        self,
        fact: ProductFact,
        settings: CopywritingSettings,
        batch: list[tuple[str, str]],
    ) -> list[DetailModule]:
        prompt = self._base_prompt(fact, settings)
        prompt += (
            f"\nAll detail JSON values must be written in {self._language_name(settings)} "
            f"(locale {settings.target_language}); never fall back to English or Chinese."
        )
        prompt += (
            f"\n请为这个商品生成详情文案，用于 {settings.target_language} 市场。"
            f"\n风格: {settings.style}。"
            f"\n请按以下模块分别撰写，返回 JSON:\n{{"
        )
        for sec, label in batch:
            prompt += f'\n  "{sec}": "## {label}\\n\\n(内容)",'
        prompt += "\n}}\n只返回 JSON。"

        raw = self._llm.chat(
            [{"role": "user", "content": prompt}],
            max_tokens=2048,
        )
        try:
            data = json.loads(_extract_json(raw))
        except (json.JSONDecodeError, KeyError):
            data = {}

        results: list[DetailModule] = []
        for sec, label in batch:
            content = data.get(sec, "")
            if not content:
                content = data.get(label, "")
            results.append(DetailModule(
                section=sec,
                title=label,
                content=content,
            ))
        return results

    # ── 辅助 ──

    def _language_name(self, settings: CopywritingSettings) -> str:
        return _TARGET_LANGUAGE_NAMES.get(
            settings.target_language, settings.target_language
        )

    def _base_prompt(self, fact: ProductFact, settings: CopywritingSettings | None = None) -> str:
        parts = ["以下是一个商品的已知信息:\n"]
        if fact.name:
            parts.append(f"商品名称: {fact.name}")
        if fact.brand:
            parts.append(f"品牌: {fact.brand}")
        if fact.model:
            parts.append(f"型号: {fact.model}")
        if fact.specs:
            parts.append(f"规格: {fact.specs}")
        if fact.color:
            parts.append(f"颜色: {fact.color}")
        if fact.material:
            parts.append(f"材质: {fact.material}")
        if fact.package_quantity:
            parts.append(f"包装数量: {fact.package_quantity}")
        if fact.target_audience:
            parts.append(f"适用对象: {fact.target_audience}")
        if fact.usage_scene:
            parts.append(f"使用场景: {fact.usage_scene}")
        if fact.main_functions:
            parts.append(f"主要功能: {'、'.join(fact.main_functions)}")
        if fact.visible_accessories:
            parts.append(f"可见配件: {'、'.join(fact.visible_accessories)}")
        if settings and settings.platform and settings.platform != "general":
            parts.append(f"目标平台: {settings.platform}")
        if settings and settings.custom_requirements:
            parts.append(f"自定义要求: {settings.custom_requirements}")
        if settings:
            parts.append(
                "OUTPUT LANGUAGE (mandatory): "
                f"{self._language_name(settings)} (locale {settings.target_language}). "
                "All user-facing generated text must be written in this language. "
                "Do not use English as a fallback."
            )
        return "\n".join(parts)

    def _parse_lines(
        self, raw: str, settings: CopywritingSettings, cls,
    ) -> list:
        lines = raw.strip().split("\n")
        results: list = []
        for line in lines:
            text = line.strip().lstrip("0123456789. -•· ")
            if not text:
                continue
            item_id = str(uuid.uuid4())
            if cls is ImageTag:
                results.append(ImageTag(
                    id=item_id, tag=text, language=settings.target_language,
                ))
            elif cls is LongTailKeyword:
                meaning = ""
                if "(" in text and text.endswith(")"):
                    idx = text.rfind("(")
                    meaning = text[idx + 1:-1]
                    text = text[:idx].strip()
                results.append(LongTailKeyword(
                    id=item_id, keyword=text, original_meaning=meaning,
                ))
            elif cls is ProductTitle:
                results.append(ProductTitle(
                    id=item_id, title=text, char_count=len(text),
                ))
            else:
                results.append(cls(id=item_id, tag=text))
        return results


def _extract_json(raw: str) -> str:
    """从 LLM 返回中提取 JSON 块。"""
    raw = raw.strip()
    if raw.startswith("{"):
        return raw
    import re
    match = re.search(r'\{[\s\S]*\}', raw)
    if match:
        return match.group(0)
    return raw
