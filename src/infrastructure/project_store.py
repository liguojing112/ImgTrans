"""商品项目持久化 — JSON 文件存储。

存储路径: {data_dir}/projects/{project_id}.json
项目索引: {data_dir}/projects/index.json
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.domain.product_info import (
    ImageUnderstanding,
    ProductAnalysisResult,
    ProductFact,
    ProductManualInfo,
    ProductProject,
    ProductSourceImage,
)
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


class ProjectStore:
    """商品项目 JSON 持久化存储。"""

    def __init__(self, projects_dir: Path) -> None:
        self._dir = projects_dir
        self._dir.mkdir(parents=True, exist_ok=True)
        self._index_path = self._dir / "index.json"

    # ── 保存 ──

    def save(self, project: ProductProject) -> Path:
        project_path = self._dir / f"{project.id}.json"
        data = _project_to_dict(project)
        data["updated_at"] = datetime.now(timezone.utc).isoformat()
        _atomic_write(project_path, data)
        self._update_index(project)
        return project_path

    # ── 加载 ──

    def load(self, project_id: str) -> ProductProject | None:
        project_path = self._dir / f"{project_id}.json"
        if not project_path.exists():
            return None
        data = json.loads(project_path.read_text(encoding="utf-8"))
        return _project_from_dict(data)

    # ── 列表 ──

    def list_recent(self, limit: int = 20) -> list[dict]:
        """返回最近项目摘要列表。"""
        entries = self._load_index()
        entries.sort(key=lambda e: e.get("updated_at", ""), reverse=True)
        return entries[:limit]

    # ── 删除 ──

    def delete(self, project_id: str) -> None:
        project_path = self._dir / f"{project_id}.json"
        if project_path.exists():
            project_path.unlink()
        self._remove_from_index(project_id)

    # ── 索引管理 ──

    def _load_index(self) -> list[dict]:
        if not self._index_path.exists():
            return []
        try:
            return json.loads(self._index_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []

    def _update_index(self, project: ProductProject) -> None:
        entries = self._load_index()
        # 提取封面图路径
        cover = ""
        if project.source_images:
            cover = str(project.source_images[0].path)
        entry = {
            "id": project.id,
            "name": project.name,
            "created_at": project.created_at,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "current_step": project.current_step,
            "target_language": project.target_language,
            "cover": cover,
        }
        for i, e in enumerate(entries):
            if e.get("id") == project.id:
                entries[i] = entry
                break
        else:
            entries.append(entry)
        _atomic_write(self._index_path, entries)

    def _remove_from_index(self, project_id: str) -> None:
        entries = [e for e in self._load_index() if e.get("id") != project_id]
        _atomic_write(self._index_path, entries)


def _atomic_write(path: Path, data: Any) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(data, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    tmp.replace(path)


# ── 序列化 ──

def _project_to_dict(p: ProductProject) -> dict:
    return {
        "id": p.id,
        "name": p.name,
        "created_at": p.created_at,
        "updated_at": p.updated_at,
        "source_images": [
            {
                "id": img.id,
                "path": str(img.path),
                "purpose": img.purpose,
                "is_primary": img.is_primary,
                "order": img.order,
            }
            for img in p.source_images
        ],
        "manual_info": {
            "name": p.manual_info.name if p.manual_info else "",
            "brand": p.manual_info.brand if p.manual_info else "",
            "category": p.manual_info.category if p.manual_info else "",
            "model": p.manual_info.model if p.manual_info else "",
            "specs": p.manual_info.specs if p.manual_info else "",
            "material": p.manual_info.material if p.manual_info else "",
            "color": p.manual_info.color if p.manual_info else "",
            "scene": p.manual_info.scene if p.manual_info else "",
            "target_market": p.manual_info.target_market if p.manual_info else "",
            "original_description": p.manual_info.original_description if p.manual_info else "",
            "notes": p.manual_info.notes if p.manual_info else "",
        },
        "analysis_result": _analysis_to_dict(p.analysis_result) if p.analysis_result else None,
        "copywriting_result": _copywriting_to_dict(p.copywriting_result) if p.copywriting_result else None,
        "target_language": p.target_language,
        "current_step": p.current_step,
    }


def _project_from_dict(d: dict) -> ProductProject:
    p = ProductProject(
        id=d["id"],
        name=d.get("name", ""),
        created_at=d.get("created_at", ""),
        updated_at=d.get("updated_at", ""),
        source_images=[
            ProductSourceImage(
                id=img["id"],
                path=Path(img["path"]),
                purpose=img.get("purpose", "main"),
                is_primary=img.get("is_primary", False),
                order=img.get("order", 0),
            )
            for img in d.get("source_images", [])
        ],
        manual_info=_manual_from_dict(d.get("manual_info", {})),
        target_language=d.get("target_language", "en"),
        current_step=d.get("current_step", 0),
    )
    if d.get("analysis_result"):
        p.analysis_result = _analysis_from_dict(d["analysis_result"])
    if d.get("copywriting_result"):
        p.copywriting_result = _copywriting_from_dict(d["copywriting_result"])
    return p


def _manual_from_dict(d: dict) -> ProductManualInfo:
    return ProductManualInfo(
        name=d.get("name", ""),
        brand=d.get("brand", ""),
        category=d.get("category", ""),
        model=d.get("model", ""),
        specs=d.get("specs", ""),
        material=d.get("material", ""),
        color=d.get("color", ""),
        scene=d.get("scene", ""),
        target_market=d.get("target_market", ""),
        original_description=d.get("original_description", ""),
        notes=d.get("notes", ""),
    )


def _analysis_to_dict(a: ProductAnalysisResult) -> dict:
    result: dict[str, Any] = {
        "ocr_text": a.ocr_text,
        "raw_llm_response": a.raw_llm_response,
    }
    if a.image_understanding:
        u = a.image_understanding
        result["image_understanding"] = {
            "category": u.category,
            "appearance": u.appearance,
            "main_colors": u.main_colors,
            "packaging": u.packaging,
            "visible_accessories": u.visible_accessories,
            "usage_scene": u.usage_scene,
            "visual_style": u.visual_style,
            "background": u.background,
            "suitable_as_main": u.suitable_as_main,
            "suitable_as_detail": u.suitable_as_detail,
        }
    if a.product_fact:
        f = a.product_fact
        result["product_fact"] = {
            "name": f.name, "brand": f.brand, "model": f.model,
            "specs": f.specs, "color": f.color, "material": f.material,
            "package_quantity": f.package_quantity,
            "target_audience": f.target_audience,
            "usage_scene": f.usage_scene,
            "main_functions": f.main_functions,
            "visible_accessories": f.visible_accessories,
            "source": f.source, "confirmed": f.confirmed,
            "uncertain": f.uncertain,
        }
    return result


def _analysis_from_dict(d: dict) -> ProductAnalysisResult:
    u = d.get("image_understanding", {})
    understanding = None
    if u:
        understanding = ImageUnderstanding(
            category=u.get("category", ""),
            appearance=u.get("appearance", ""),
            main_colors=u.get("main_colors", []),
            packaging=u.get("packaging", ""),
            visible_accessories=u.get("visible_accessories", []),
            usage_scene=u.get("usage_scene", ""),
            visual_style=u.get("visual_style", ""),
            background=u.get("background", ""),
            suitable_as_main=u.get("suitable_as_main", False),
            suitable_as_detail=u.get("suitable_as_detail", False),
        )
    f = d.get("product_fact", {})
    fact = None
    if f:
        fact = ProductFact(
            name=f.get("name", ""), brand=f.get("brand", ""),
            model=f.get("model", ""), specs=f.get("specs", ""),
            color=f.get("color", ""), material=f.get("material", ""),
            package_quantity=f.get("package_quantity", ""),
            target_audience=f.get("target_audience", ""),
            usage_scene=f.get("usage_scene", ""),
            main_functions=f.get("main_functions", []),
            visible_accessories=f.get("visible_accessories", []),
            source=f.get("source", {}), confirmed=f.get("confirmed", {}),
            uncertain=f.get("uncertain", {}),
        )
    return ProductAnalysisResult(
        ocr_text=d.get("ocr_text", ""),
        image_understanding=understanding,
        product_fact=fact,
        raw_llm_response=d.get("raw_llm_response", ""),
    )


def _copywriting_to_dict(cr) -> dict:
    """CopywritingResult → dict。cr 可能是 CopywritingResult 或其简化版。"""
    result: dict[str, Any] = {
        "target_language": getattr(cr, "target_language", "en"),
    }
    tags = getattr(cr, "tags", [])
    if tags:
        result["tags"] = [
            {"id": t.id if hasattr(t, 'id') else str(uuid.uuid4()),
             "tag": t.tag if hasattr(t, 'tag') else str(t),
             "language": t.language if hasattr(t, 'language') else "en"}
            for t in tags
        ]
    kws = getattr(cr, "keywords", [])
    if kws:
        result["keywords"] = [
            {"id": k.id if hasattr(k, 'id') else str(uuid.uuid4()),
             "keyword": k.keyword if hasattr(k, 'keyword') else str(k),
             "original_meaning": k.original_meaning if hasattr(k, 'original_meaning') else ""}
            for k in kws
        ]
    titles = getattr(cr, "titles", [])
    if titles:
        result["titles"] = [
            {"id": t.id if hasattr(t, 'id') else str(uuid.uuid4()),
             "title": t.title if hasattr(t, 'title') else str(t),
             "char_count": t.char_count if hasattr(t, 'char_count') else 0,
             "is_selected": t.is_selected if hasattr(t, 'is_selected') else False}
            for t in titles
        ]
    sps = getattr(cr, "selling_points", [])
    if sps:
        result["selling_points"] = [
            {"id": s.id if hasattr(s, 'id') else str(uuid.uuid4()),
             "category": s.category if hasattr(s, 'category') else "",
             "text": s.text if hasattr(s, 'text') else str(s),
             "order": s.order if hasattr(s, 'order') else 0,
             "locked": s.locked if hasattr(s, 'locked') else False}
            for s in sps
        ]
    intro = getattr(cr, "intro", None)
    if intro:
        result["intro"] = {
            "one_liner": intro.one_liner if hasattr(intro, 'one_liner') else "",
            "short_description": intro.short_description if hasattr(intro, 'short_description') else "",
            "standard_intro": intro.standard_intro if hasattr(intro, 'standard_intro') else "",
            "translations": intro.translations if hasattr(intro, 'translations') else {},
        }
    dms = getattr(cr, "detail_modules", [])
    if dms:
        result["detail_modules"] = [
            {"section": m.section if hasattr(m, 'section') else "",
             "title": m.title if hasattr(m, 'title') else "",
             "content": m.content if hasattr(m, 'content') else ""}
            for m in dms
        ]
    return result


def _copywriting_from_dict(d: dict) -> CopywritingResult:
    return CopywritingResult(
        tags=[ImageTag(id=t["id"], tag=t["tag"], language=t.get("language", "en"))
              for t in d.get("tags", [])],
        keywords=[LongTailKeyword(id=k["id"], keyword=k["keyword"],
                                   original_meaning=k.get("original_meaning", ""))
                   for k in d.get("keywords", [])],
        titles=[ProductTitle(id=t["id"], title=t["title"],
                              char_count=t.get("char_count", 0),
                              is_selected=t.get("is_selected", False))
                 for t in d.get("titles", [])],
        selling_points=[SellingPoint(id=s["id"], category=s.get("category", ""),
                                      text=s["text"], order=s.get("order", 0),
                                      locked=s.get("locked", False))
                         for s in d.get("selling_points", [])],
        intro=ProductIntro(**d["intro"]) if d.get("intro") else None,
        detail_modules=[DetailModule(**m) for m in d.get("detail_modules", [])],
        target_language=d.get("target_language", "en"),
    )
