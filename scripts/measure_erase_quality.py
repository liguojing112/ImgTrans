"""擦除质量量化基线工具。

两个用途：

1. 跑一轮基准，得到每个 OCR 区域的「蒙版覆盖率」与「擦除后 Sobel 残留能量」

       python scripts/measure_erase_quality.py run base
       ERASE_BENCH_SAMPLE=60 python scripts/measure_erase_quality.py run base

2. 把两轮结果逐区域配对对比，判断一次改动是净收益还是净损失

       python scripts/measure_erase_quality.py compare base fix

判读方式（重要，参见 tasks/TASK-M5-001-erase-quality-rootcause.md §12.4 与 §16.4）：
覆盖率与残留必须**联合判读**。过度擦除会把整框填平、边缘能量趋零，从而在残留指标上
刷出高分，所以覆盖率接近 100% 要当作误擦嫌疑而非成绩。判定一次改动是否可接受：
残留恶化的区域数不得超过改善的区域数，且覆盖 >= 99% 的区域数不得增加；对覆盖率高的
区域要开图人工核实。

翻译走 MockTranslationAdapter，保证多轮之间结果确定、可配对。
"""

from __future__ import annotations

import json
import os
import statistics
import sys
from pathlib import Path

_REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
_CORPUS = _REPOSITORY_ROOT / "测试数据"
_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
_OUTPUT_DIRECTORY = Path(os.environ.get("ERASE_BENCH_OUTPUT", "/tmp"))


def _report_path(label: str) -> Path:
    return _OUTPUT_DIRECTORY / f"erase_bench_{label}.json"


def _corpus_images() -> list[Path]:
    images = sorted(
        path
        for path in _CORPUS.rglob("*")
        if path.is_file() and path.suffix.lower() in _IMAGE_SUFFIXES
    )
    # 抽样按固定步长取，保证多轮之间取到同一批图，否则无法配对。
    sample = int(os.environ.get("ERASE_BENCH_SAMPLE", "0"))
    if sample and len(images) > sample:
        stride = len(images) / sample
        images = [images[int(index * stride)] for index in range(sample)]
    return images


def run(label: str) -> None:
    images = _corpus_images()
    if not images:
        raise SystemExit(f"语料目录为空: {_CORPUS}")

    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication(["measure-erase-quality"])

    import cv2
    import numpy as np
    from PIL import Image, ImageDraw

    from src.application.inpainting import BuildEraseMask, RepairTranslatedRegions
    from src.application.ocr import RecognizeText
    from src.application.translation import TranslateRegions
    from src.domain.image import ImageLimits
    from src.domain.protection import ProtectionEngine
    from src.domain.terminology import TerminologyCatalog
    from src.domain.translation import TranslationMode, TranslationSelection
    from src.infrastructure.fallback_inpaint_adapter import FallbackInpaintAdapter
    from src.infrastructure.inpainting_process import ProcessLamaAdapter
    from src.infrastructure.mock_translator import MockTranslationAdapter
    from src.infrastructure.model_delivery import FileModelRepository
    from src.infrastructure.opencv_inpaint_adapter import OpenCvInpaintAdapter
    from src.infrastructure.pillow_image_codec import PillowImageCodec
    from src.infrastructure.pillow_mask_rasterizer import PillowMaskRasterizer
    from src.infrastructure.rapidocr_adapter import RapidOcrAdapter
    from src.infrastructure.rapidocr_models import InstalledRapidOcrModels
    from src.platform.paths import PlatformPaths

    repository = FileModelRepository(PlatformPaths.discover().data_dir / "models")
    lama = repository.active("lama-inpainting")
    codec = PillowImageCodec()
    recognize = RecognizeText(
        RapidOcrAdapter(model_resolver=InstalledRapidOcrModels(repository).resolve)
    )
    translate = TranslateRegions(
        MockTranslationAdapter(),
        ProtectionEngine(),
        terminology_catalog=TerminologyCatalog(),
    )

    def residue(rgb, selection):
        grey = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY).astype(np.float32)
        gradient_x = cv2.Sobel(grey, cv2.CV_32F, 1, 0, ksize=3)
        gradient_y = cv2.Sobel(grey, cv2.CV_32F, 0, 1, ksize=3)
        magnitude = np.sqrt(gradient_x * gradient_x + gradient_y * gradient_y)
        return float(magnitude[selection].mean()) if selection.any() else 0.0

    report: dict = {"label": label, "images": []}
    for path in images:
        try:
            document = codec.load(path, ImageLimits())
        except Exception:
            continue
        height, width = document.asset.height, document.asset.width
        recognized = recognize.execute(document, "zh-Hans")
        if not recognized.regions:
            continue
        translated = translate.execute(
            recognized, TranslationSelection(TranslationMode.ALL, "en")
        )
        outcome = RepairTranslatedRegions(
            BuildEraseMask(PillowMaskRasterizer()),
            FallbackInpaintAdapter(
                ProcessLamaAdapter(Path(lama.path)), OpenCvInpaintAdapter()
            ),
        ).execute(document, recognized, translated)
        after = np.frombuffer(
            outcome.result.document.pixels, dtype=np.uint8
        ).reshape(height, width, 3)
        mask = np.frombuffer(
            outcome.erase_mask.pixels, dtype=np.uint8
        ).reshape(height, width) > 0
        entry: dict = {
            "image": f"{path.parent.parent.name[:14]}/{path.name}",
            "regions": [],
        }
        for region in recognized.regions:
            geometry = Image.new("L", (width, height), 0)
            ImageDraw.Draw(geometry).polygon(
                [(point.x, point.y) for point in region.polygon], fill=255
            )
            polygon = np.asarray(geometry, dtype=np.uint8) > 0
            if not polygon.any():
                continue
            entry["regions"].append(
                {
                    "text": region.text,
                    "coverage_pct": round(mask[polygon].mean() * 100, 1),
                    "residue_after": round(residue(after, polygon), 1),
                }
            )
        report["images"].append(entry)

    destination = _report_path(label)
    destination.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    coverage = [r["coverage_pct"] for e in report["images"] for r in e["regions"]]
    residues = [r["residue_after"] for e in report["images"] for r in e["regions"]]
    print(f"--- {label}: {len(coverage)} 区域 / {len(report['images'])} 图 ---")
    print(
        f"  平均覆盖率 {statistics.mean(coverage):.1f}%"
        f"   平均残留 {statistics.mean(residues):.1f}"
    )
    print(
        f"  覆盖>=90%: {sum(1 for c in coverage if c >= 90)}"
        f"   >=99%: {sum(1 for c in coverage if c >= 99)}"
    )
    print(f"JSON -> {destination}")


def _load(label: str) -> dict:
    data = json.loads(_report_path(label).read_text(encoding="utf-8"))
    return {
        (image["image"], index, region["text"]): region
        for image in data["images"]
        for index, region in enumerate(image["regions"])
    }


def compare(baseline_label: str, candidate_label: str, threshold: float = 20.0) -> None:
    baseline = _load(baseline_label)
    candidate = _load(candidate_label)
    keys = sorted(set(baseline) & set(candidate))
    print(
        f"配对区域 {len(keys)}"
        f" / {baseline_label} {len(baseline)} / {candidate_label} {len(candidate)}"
    )

    better, worse = [], []
    for key in keys:
        delta = candidate[key]["residue_after"] - baseline[key]["residue_after"]
        if delta <= -threshold:
            better.append((delta, key))
        elif delta >= threshold:
            worse.append((delta, key))
    net = sum(delta for delta, _ in better + worse)
    print(
        f"残留改善>{threshold:.0f}: {len(better)}"
        f"   恶化>{threshold:.0f}: {len(worse)}   净值 {net:+.1f}"
    )

    for title, rows in (
        ("改善", sorted(better)),
        ("恶化", sorted(worse, reverse=True)),
    ):
        print(f"\n--- {title} ---")
        for delta, key in rows[:25]:
            before, after = baseline[key], candidate[key]
            print(
                f"  {delta:+7.1f}"
                f"  残留 {before['residue_after']:6.1f}->{after['residue_after']:6.1f}"
                f"  覆盖 {before['coverage_pct']:5.1f}->{after['coverage_pct']:5.1f}"
                f"  {key[2][:22]!r} @{key[0].rsplit('/', 1)[-1][:30]}"
            )

    entered = [
        key
        for key in keys
        if candidate[key]["coverage_pct"] >= 99 > baseline[key]["coverage_pct"]
    ]
    left = [
        key
        for key in keys
        if baseline[key]["coverage_pct"] >= 99 > candidate[key]["coverage_pct"]
    ]
    print(f"\n新增覆盖>=99%(疑似误擦): {len(entered)}   退出>=99%: {len(left)}")
    for key in entered[:15]:
        print(
            f"  {key[2][:26]!r}"
            f" {baseline[key]['coverage_pct']}->{candidate[key]['coverage_pct']}"
        )

    touched = [
        key
        for key in keys
        if abs(candidate[key]["coverage_pct"] - baseline[key]["coverage_pct"]) >= 0.5
    ]
    print(f"\n受影响区域(覆盖率变化>=0.5pt): {len(touched)}")
    if not touched:
        return
    coverage_shift = sum(
        candidate[key]["coverage_pct"] - baseline[key]["coverage_pct"]
        for key in touched
    ) / len(touched)
    residue_shift = sum(
        candidate[key]["residue_after"] - baseline[key]["residue_after"]
        for key in touched
    ) / len(touched)
    print(
        f"  其平均覆盖变化 {coverage_shift:+.1f}pt"
        f"   平均残留变化 {residue_shift:+.1f}"
    )
    ordered = sorted(
        touched,
        key=lambda key: candidate[key]["coverage_pct"] - baseline[key]["coverage_pct"],
    )
    for key in ordered[:20]:
        before, after = baseline[key], candidate[key]
        print(
            f"  覆盖 {before['coverage_pct']:5.1f}->{after['coverage_pct']:5.1f}"
            f"  残留 {before['residue_after']:6.1f}->{after['residue_after']:6.1f}"
            f"  {key[2][:20]!r} @{key[0].rsplit('/', 1)[-1][:30]}"
        )


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in {"run", "compare"}:
        raise SystemExit(__doc__)
    if sys.argv[1] == "run":
        run(sys.argv[2] if len(sys.argv) > 2 else "run")
        return
    if len(sys.argv) < 4:
        raise SystemExit("compare 需要两个标签，例如: compare base fix")
    compare(sys.argv[2], sys.argv[3])


if __name__ == "__main__":
    main()
