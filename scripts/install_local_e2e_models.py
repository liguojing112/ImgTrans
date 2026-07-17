from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
import hashlib
from pathlib import Path
import sys

import rapidocr

from src.domain.models import InstalledModel, ModelDeliveryError, ModelManifestEntry
from src.infrastructure.lama_onnx_adapter import (
    LAMA_MODEL_FILENAME,
    LAMA_MODEL_SHA256,
)
from src.infrastructure.model_delivery import FileModelRepository
from src.infrastructure.rapidocr_models import (
    CLASSIFICATION_MODEL_ID,
    DETECTION_MODEL_ID,
    RECOGNITION_MODEL_IDS,
)
from src.platform.paths import PlatformPaths, discover_model_target


_RAPIDOCR_FILES = {
    DETECTION_MODEL_ID: "PP-OCRv6_det_small.onnx",
    CLASSIFICATION_MODEL_ID: "ch_ppocr_mobile_v2.0_cls_mobile.onnx",
    RECOGNITION_MODEL_IDS["ppocrv6-common-small"]: "PP-OCRv6_rec_small.onnx",
    RECOGNITION_MODEL_IDS["ppocrv5-cyrillic-mobile"]: "cyrillic_PP-OCRv5_rec_mobile.onnx",
    RECOGNITION_MODEL_IDS["ppocrv5-korean-mobile"]: "korean_PP-OCRv5_rec_mobile.onnx",
    RECOGNITION_MODEL_IDS["ppocrv5-thai-mobile"]: "th_PP-OCRv5_rec_mobile.onnx",
    RECOGNITION_MODEL_IDS["ppocrv5-arabic-mobile"]: "arabic_PP-OCRv5_rec_mobile.onnx",
    RECOGNITION_MODEL_IDS["ppocrv5-devanagari-mobile"]: "devanagari_PP-OCRv5_rec_mobile.onnx",
}
LAMA_MODEL_ID = "lama-inpainting"


def discover_sources(
    rapidocr_root: Path,
    lama_model: Path,
) -> dict[str, Path]:
    sources: dict[str, Path] = {}
    for model_id, filename in _RAPIDOCR_FILES.items():
        matches = tuple(rapidocr_root.rglob(filename))
        if len(matches) > 1:
            raise ModelDeliveryError(f"RapidOCR 本地模型文件重名：{filename}")
        sources[model_id] = matches[0] if matches else rapidocr_root / filename
    sources[LAMA_MODEL_ID] = lama_model
    missing = [model_id for model_id, path in sources.items() if not path.is_file()]
    if missing:
        raise ModelDeliveryError(
            "本地联调模型不完整：" + ", ".join(sorted(missing))
        )
    if any(path.suffix.lower() != ".onnx" or path.stat().st_size <= 0 for path in sources.values()):
        raise ModelDeliveryError("本地联调模型文件无效")
    return sources


def install_local_models(
    repository: FileModelRepository,
    sources: Mapping[str, Path],
    platform: str,
    architecture: str,
    *,
    expected_lama_sha256: str = LAMA_MODEL_SHA256,
) -> tuple[InstalledModel, ...]:
    installed: list[InstalledModel] = []
    for model_id, source in sources.items():
        digest = _sha256(source)
        if model_id == LAMA_MODEL_ID and digest != expected_lama_sha256:
            raise ModelDeliveryError("LaMa 本地联调模型 SHA-256 不匹配")
        entry = ModelManifestEntry(
            model_id=model_id,
            version=f"local-e2e-{digest[:12]}",
            platform=platform,
            architecture=architecture,
            filename=source.name,
            object_version=f"local-e2e:{digest}",
            size_bytes=source.stat().st_size,
            sha256=digest,
            download_url=f"https://local.invalid/models/{model_id}",
            download_url_expires_at=datetime.now(timezone.utc) + timedelta(days=1),
        )
        record = repository.install(entry, source)
        if _sha256(Path(record.path)) != digest:
            raise ModelDeliveryError("本地联调模型安装后校验失败")
        installed.append(record)
    return tuple(installed)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Install existing local ONNX assets into the formal model repository",
    )
    parser.add_argument("--lama-model", type=Path, required=True)
    parser.add_argument("--rapidocr-root", type=Path)
    parser.add_argument("--target-dir", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    rapidocr_root = arguments.rapidocr_root or Path(rapidocr.__file__).resolve().parent
    target_dir = arguments.target_dir or PlatformPaths.discover().data_dir / "models"
    try:
        platform, architecture = discover_model_target()
        sources = discover_sources(rapidocr_root, arguments.lama_model.resolve())
        installed = install_local_models(
            FileModelRepository(target_dir),
            sources,
            platform,
            architecture,
        )
    except (ModelDeliveryError, OSError, RuntimeError) as error:
        print(f"local_e2e_model_install_failed: {error}", file=sys.stderr)
        return 1
    print(
        "local_e2e_model_install_ok "
        f"models={len(installed)} target={platform}-{architecture}"
    )
    return 0


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
