"""文案导出用例 — TXT / JSON / CSV 格式导出。"""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime
from pathlib import Path

from src.domain.copywriting import CopywritingResult, DetailModule


class ExportCopywriting:
    """导出文案 — 支持 TXT、JSON 和 CSV 格式（含全部商品图片信息）。"""

    def execute(
        self,
        result: CopywritingResult,
        target: Path,
        fmt: str = "txt",
        image_info: list | None = None,
    ) -> Path:
        """image_info: 每张商品图片的分析信息（路径/OCR/理解/事实）。"""
        if fmt == "json":
            return self._export_json(result, target, image_info)
        if fmt == "csv":
            return self._export_csv(result, target, image_info)
        return self._export_txt(result, target, image_info)

    @staticmethod
    def _format_image_info(image_info: list) -> list[str]:
        """把每图信息格式化为行（TXT 用）。"""
        lines: list[str] = []
        for index, info in enumerate(image_info):
            path = info.get("path", "")
            name = path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1] if path else ""
            lines.append(f"  图 {index + 1}: {name or path}")
            ocr = info.get("ocr", "")
            if ocr:
                lines.append(f"    OCR 文字: {ocr[:200]}")
            understanding = info.get("understanding", "")
            if understanding:
                lines.append(f"    内容理解: {understanding[:300]}")
            fact = info.get("fact", "")
            if fact:
                lines.append(f"    事实信息: {fact[:300]}")
        return lines

    def _export_txt(
        self, result: CopywritingResult, target: Path, image_info: list | None = None
    ) -> Path:
        lines = []
        lines.append("=" * 50)
        lines.append(f"商品文案导出 — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"目标语言: {result.target_language}")
        lines.append("=" * 50)

        if image_info:
            lines.append("\n【商品图片信息】")
            lines.extend(self._format_image_info(image_info))

        if result.tags:
            lines.append("\n【图片标签】")
            for tag in result.tags:
                lines.append(f"  - {tag.tag}")

        if result.keywords:
            lines.append("\n【长尾场景词】")
            for kw in result.keywords:
                meaning = f" ({kw.original_meaning})" if kw.original_meaning else ""
                lines.append(f"  - {kw.keyword}{meaning}")

        if result.titles:
            lines.append("\n【产品标题】")
            for title in result.titles:
                marker = " ★" if title.is_selected else ""
                lines.append(f"  - {title.title} [{title.char_count}字符]{marker}")

        if result.selling_points:
            lines.append("\n【商品卖点】")
            category_labels = {
                "core": "核心卖点", "function": "功能卖点",
                "scene": "使用场景卖点", "material": "材质/结构卖点",
                "packaging": "包装与配件卖点",
            }
            current_cat = ""
            for sp in result.selling_points:
                cat_label = category_labels.get(sp.category, sp.category)
                if cat_label != current_cat:
                    current_cat = cat_label
                    lines.append(f"  [{cat_label}]")
                lines.append(f"    - {sp.text}")

        if result.intro:
            lines.append("\n【商品简介】")
            if result.intro.one_liner:
                lines.append(f"  一句话: {result.intro.one_liner}")
            if result.intro.short_description:
                lines.append(f"  短描述: {result.intro.short_description}")
            if result.intro.standard_intro:
                lines.append(f"  标准简介: {result.intro.standard_intro}")

        if result.detail_modules:
            lines.append("\n【详情文案】")
            for mod in result.detail_modules:
                if mod.content:
                    lines.append(f"\n  ## {mod.title}")
                    lines.append(f"  {mod.content}")

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("\n".join(lines), encoding="utf-8")
        return target

    def _export_json(
        self, result: CopywritingResult, target: Path, image_info: list | None = None
    ) -> Path:
        data = {
            "exported_at": datetime.now().isoformat(),
            "target_language": result.target_language,
            "product_images": image_info or [],
            "tags": [{"tag": t.tag, "language": t.language} for t in result.tags],
            "keywords": [
                {"keyword": k.keyword, "original_meaning": k.original_meaning}
                for k in result.keywords
            ],
            "titles": [
                {"title": t.title, "char_count": t.char_count, "selected": t.is_selected}
                for t in result.titles
            ],
            "selling_points": [
                {"category": s.category, "text": s.text, "locked": s.locked}
                for s in result.selling_points
            ],
        }
        if result.intro:
            data["intro"] = {
                "one_liner": result.intro.one_liner,
                "short_description": result.intro.short_description,
                "standard_intro": result.intro.standard_intro,
                "translations": result.intro.translations,
            }
        if result.detail_modules:
            data["detail_modules"] = [
                {"section": m.section, "title": m.title, "content": m.content}
                for m in result.detail_modules if m.content
            ]

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return target

    def _export_csv(
        self, result: CopywritingResult, target: Path, image_info: list | None = None
    ) -> Path:
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["类型", "分类", "内容", "备注"])
        if image_info:
            for index, info in enumerate(image_info):
                path = info.get("path", "")
                name = path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1] if path else ""
                ocr = info.get("ocr", "")
                understanding = info.get("understanding", "")
                fact = info.get("fact", "")
                content = f"{ocr or ''} {understanding or ''} {fact or ''}".strip()
                writer.writerow(["商品图片信息", f"图{index + 1}", content, name])
        for tag in result.tags:
            writer.writerow(["图片标签", "", tag.tag, tag.language])
        for kw in result.keywords:
            writer.writerow(["长尾场景词", "", kw.keyword, kw.original_meaning])
        for title in result.titles:
            marker = "★" if title.is_selected else ""
            writer.writerow(["产品标题", marker, title.title, f"{title.char_count}字符"])
        for sp in result.selling_points:
            writer.writerow(["商品卖点", sp.category, sp.text, "锁定" if sp.locked else ""])
        if result.intro:
            if result.intro.one_liner:
                writer.writerow(["商品简介", "一句话", result.intro.one_liner, ""])
            if result.intro.short_description:
                writer.writerow(["商品简介", "短描述", result.intro.short_description, ""])
            if result.intro.standard_intro:
                writer.writerow(["商品简介", "标准简介", result.intro.standard_intro, ""])
        for mod in result.detail_modules:
            if mod.content:
                writer.writerow(["详情文案", mod.title, mod.content, ""])

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(buf.getvalue(), encoding="utf-8-sig")
        return target
