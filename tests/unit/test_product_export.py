"""商品文案导出 — PDF 排版测试。"""

from __future__ import annotations

import re
from pathlib import Path

from src.application.product_export import ExportCopywriting
from src.domain.copywriting import (
    CopywritingResult,
    DetailModule,
    ImageTag,
    LongTailKeyword,
    ProductIntro,
    ProductTitle,
    SellingPoint,
)


def _page_count(data: bytes) -> int:
    match = re.search(rb"/Count (\d+)", data)
    assert match is not None, "PDF 缺少 /Count 页树信息"
    return int(match.group(1))


def _result() -> CopywritingResult:
    return CopywritingResult(
        tags=[ImageTag("t1", "water bottle"), ImageTag("t2", "hiking")],
        keywords=[LongTailKeyword("k1", "outdoor water bottle", "户外水壶")],
        titles=[ProductTitle("p1", "Portable Steel Bottle", 22, True)],
        selling_points=[
            SellingPoint("s1", "core", "Keep cold for 24 hours"),
            SellingPoint("s2", "function", "Leak-proof cap"),
        ],
        intro=ProductIntro(one_liner="Light. Strong. Yours."),
        detail_modules=[
            DetailModule("overview", "Overview", "A sturdy bottle for daily use."),
        ],
        target_language="en",
    )


def test_export_pdf_creates_valid_single_page(tmp_path: Path) -> None:
    target = tmp_path / "copy.pdf"
    assert ExportCopywriting().execute(_result(), target, fmt="pdf") == target
    data = target.read_bytes()
    assert data.startswith(b"%PDF")
    assert _page_count(data) == 1


def test_export_pdf_includes_image_info_section(tmp_path: Path) -> None:
    image_info = [
        {
            "path": "img/1.jpg",
            "ocr": "BPA FREE",
            "understanding": "A steel bottle on a mountain",
            "fact": "Capacity 750ml",
        }
    ]
    target = tmp_path / "copy.pdf"
    ExportCopywriting().execute(_result(), target, fmt="pdf", image_info=image_info)
    data = target.read_bytes()
    assert data.startswith(b"%PDF")
    assert _page_count(data) >= 1


def test_export_pdf_paginates_long_content(tmp_path: Path) -> None:
    result = _result()
    result.detail_modules = [
        DetailModule("specs", f"Module {i}", "Long paragraph " * 30)
        for i in range(12)
    ]
    target = tmp_path / "long.pdf"
    ExportCopywriting().execute(result, target, fmt="pdf")
    assert _page_count(target.read_bytes()) > 1


def test_export_pdf_empty_result_still_writes_title_page(tmp_path: Path) -> None:
    target = tmp_path / "empty.pdf"
    ExportCopywriting().execute(
        CopywritingResult(target_language="fr"), target, fmt="pdf"
    )
    data = target.read_bytes()
    assert data.startswith(b"%PDF")
    assert _page_count(data) == 1
