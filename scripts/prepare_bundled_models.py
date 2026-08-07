"""把 OCR/修复模型复制到 packaging/bundled_models，供 PyInstaller 打进 exe。

模型源：rapidocr pip 包自带 onnx + 本地 LaMa 模型（环境变量
IMGTRANS_LAMA_MODEL 或 data_dir/models 下查找）。
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil

import rapidocr

_RAPIDOCR_FILES = {
    "rapidocr-det-ppocrv6-small": "PP-OCRv6_det_small.onnx",
    "rapidocr-cls-angle-mobile": "ch_ppocr_mobile_v2.0_cls_mobile.onnx",
    "rapidocr-rec-ppocrv6-common-small": "PP-OCRv6_rec_small.onnx",
    "rapidocr-rec-ppocrv5-cyrillic-mobile": "cyrillic_PP-OCRv5_rec_mobile.onnx",
    "rapidocr-rec-ppocrv5-korean-mobile": "korean_PP-OCRv5_rec_mobile.onnx",
    "rapidocr-rec-ppocrv5-thai-mobile": "th_PP-OCRv5_rec_mobile.onnx",
    "rapidocr-rec-ppocrv5-arabic-mobile": "arabic_PP-OCRv5_rec_mobile.onnx",
    "rapidocr-rec-ppocrv5-devanagari-mobile": "devanagari_PP-OCRv5_rec_mobile.onnx",
}
LAMA_MODEL_ID = "lama-inpainting"
LAMA_MODEL_FILENAME = "inpainting_lama_2025jan.onnx"


def _find_source(root: Path, filename: str) -> Path | None:
    direct = root / filename
    if direct.is_file():
        return direct
    matches = tuple(root.rglob(filename))
    return matches[0] if matches else None


def find_lama_model() -> Path:
    env_value = os.environ.get("IMGTRANS_LAMA_MODEL", "").strip()
    if env_value:
        candidate = Path(env_value)
        if candidate.is_file():
            return candidate.resolve()
    try:
        from src.platform.paths import PlatformPaths
    except ImportError:
        pass
    else:
        models_dir = PlatformPaths.discover().data_dir / "models"
        if models_dir.is_dir():
            matches = tuple(models_dir.rglob(LAMA_MODEL_FILENAME))
            if matches:
                return matches[0].resolve()
    raise FileNotFoundError(
        f"未找到 LaMa 模型 {LAMA_MODEL_FILENAME}（用 --lama-model 或 IMGTRANS_LAMA_MODEL 指定）"
    )


def prepare(
    out_root: Path,
    rapidocr_root: Path,
    lama_model: Path | None,
) -> list[Path]:
    out_root.mkdir(parents=True, exist_ok=True)
    installed: list[Path] = []
    for model_id, filename in _RAPIDOCR_FILES.items():
        source = _find_source(rapidocr_root, filename)
        if source is None:
            raise FileNotFoundError(f"rapidocr 包缺少模型：{filename}")
        target = out_root / model_id / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        installed.append(target)
    lama_source = lama_model or find_lama_model()
    lama_target = out_root / LAMA_MODEL_ID / LAMA_MODEL_FILENAME
    lama_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(lama_source, lama_target)
    installed.append(lama_target)
    return installed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepare bundled ONNX models for desktop build")
    parser.add_argument("--rapidocr-root", type=Path)
    parser.add_argument("--lama-model", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    out_root = root / "packaging" / "bundled_models"
    rapidocr_root = args.rapidocr_root or Path(rapidocr.__file__).resolve().parent
    try:
        installed = prepare(out_root, rapidocr_root, args.lama_model)
    except (FileNotFoundError, OSError) as error:
        print(f"prepare_bundled_models_failed: {error}", file=sys.stderr)
        return 1
    total_bytes = sum(path.stat().st_size for path in installed)
    print(
        f"prepare_bundled_models_ok models={len(installed)} "
        f"bytes={total_bytes} dest={out_root}"
    )
    return 0


if __name__ == "__main__":
    import sys

    raise SystemExit(main())
