from __future__ import annotations

import argparse
from collections.abc import Sequence
import multiprocessing
import os
from pathlib import Path
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from src.application.image_io import ExportImage, ImportImage
from src.application.image_limits import ImageLimitsCoordinator
from src.application.inpainting import BuildEraseMask, RepairTranslatedRegions
from src.application.ocr import RecognizeText
from src.application.translate_image import TranslateImage
from src.application.translation import TranslateRegions
from src.domain.image import ImageLimits
from src.domain.language import SUPPORTED_LANGUAGE_CODES
from src.domain.protection import ProtectionEngine
from src.domain.translation import TranslationMode, TranslationSelection
from src.infrastructure.fallback_inpaint_adapter import FallbackInpaintAdapter
from src.infrastructure.image_limits_config import (
    HttpImageLimitsClient,
    JsonImageLimitsCache,
)
from src.infrastructure.inpainting_process import ProcessLamaAdapter
from src.infrastructure.model_delivery import FileModelRepository
from src.infrastructure.opencv_inpaint_adapter import OpenCvInpaintAdapter
from src.infrastructure.pillow_image_codec import PillowImageCodec
from src.infrastructure.pillow_mask_rasterizer import PillowMaskRasterizer
from src.infrastructure.rapidocr_adapter import RapidOcrAdapter
from src.infrastructure.rapidocr_models import InstalledRapidOcrModels
from src.infrastructure.server_translation_adapter import ServerTranslationAdapter
from src.infrastructure.text_renderer import QtBasicTextLayoutAdapter, QtTextRenderer
from src.platform.paths import PlatformPaths


_INPUT_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}


def discover_images(input_dir: Path, limit: int) -> tuple[Path, ...]:
    if not input_dir.is_dir():
        raise ValueError("客户图片输入目录不存在")
    if not 1 <= limit <= 100:
        raise ValueError("单次联调图片数量必须在 1 到 100 之间")
    images = tuple(
        path
        for path in sorted(input_dir.iterdir(), key=lambda value: value.name.casefold())
        if path.is_file() and path.suffix.lower() in _INPUT_SUFFIXES
    )
    if not images:
        raise ValueError("客户图片输入目录中没有支持的图片")
    return images[:limit]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run customer images through the formal local image translation pipeline",
    )
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--ocr-language",
        choices=SUPPORTED_LANGUAGE_CODES,
        required=True,
    )
    parser.add_argument(
        "--target-language",
        choices=SUPPORTED_LANGUAGE_CODES,
        required=True,
    )
    parser.add_argument("--brand-term", action="append", default=[])
    parser.add_argument("--limit", type=int, default=10)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    multiprocessing.freeze_support()
    arguments = build_parser().parse_args(argv)
    backend_url = os.environ.get("IMGTRANS_API_BASE_URL", "").strip()
    api_token = os.environ.get("IMGTRANS_API_TOKEN", "").strip()
    try:
        validate_language_pair(arguments.ocr_language, arguments.target_language)
        if not backend_url:
            raise ValueError("IMGTRANS_API_BASE_URL 未配置")
        if len(api_token) < 16:
            raise ValueError("IMGTRANS_API_TOKEN 未配置或无效")
        images = discover_images(arguments.input_dir.resolve(), arguments.limit)
        output_dir = arguments.output_dir.resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        paths = PlatformPaths.discover()
        paths.ensure()
        repository = FileModelRepository(paths.data_dir / "models")
        lama = repository.active("lama-inpainting")
        if lama is None:
            raise ValueError("正式模型仓库中缺少 LaMa 模型")
        limits = ImageLimitsCoordinator(
            JsonImageLimitsCache(paths.data_dir / "config" / "image-limits.json"),
            ImageLimits(),
            HttpImageLimitsClient(backend_url),
        )
        limits.refresh()
        codec = PillowImageCodec()
        repair_adapter = FallbackInpaintAdapter(
            ProcessLamaAdapter(Path(lama.path)),
            OpenCvInpaintAdapter(),
        )
        workflow = TranslateImage(
            RecognizeText(
                RapidOcrAdapter(
                    model_resolver=InstalledRapidOcrModels(repository).resolve,
                )
            ),
            TranslateRegions(
                ServerTranslationAdapter(backend_url, api_token),
                ProtectionEngine(),
            ),
            RepairTranslatedRegions(
                BuildEraseMask(PillowMaskRasterizer()),
                repair_adapter,
            ),
            QtBasicTextLayoutAdapter(),
            QtTextRenderer(),
        )
    except (OSError, RuntimeError, ValueError) as error:
        print(f"customer_image_e2e_configuration_failed: {error}", file=sys.stderr)
        return 2

    application = QApplication.instance() or QApplication(["imgtrans-customer-e2e"])
    importer = ImportImage(codec, limits)
    exporter = ExportImage(codec)
    succeeded = 0
    failed = 0
    try:
        for index, source in enumerate(images, start=1):
            try:
                document = importer.execute(source)
                result = workflow.execute(
                    document,
                    arguments.ocr_language,
                    TranslationSelection(
                        TranslationMode.ALL,
                        arguments.target_language,
                    ),
                    tuple(arguments.brand_term),
                )
                target = output_dir / f"{index:04d}-{source.stem}-translated.png"
                exporter.execute(result.document, target)
                succeeded += 1
                print(
                    "customer_image_e2e_item_ok "
                    f"index={index} ocr_regions={len(result.ocr.regions)} "
                    f"translated={sum(unit.should_erase_source for unit in result.translation.units)} "
                    f"repair={result.repair.result.backend_id}"
                )
            except Exception as error:
                failed += 1
                print(
                    "customer_image_e2e_item_failed "
                    f"index={index} error={_public_error_code(error)}",
                    file=sys.stderr,
                )
            application.processEvents()
    finally:
        workflow.close()
    print(
        "customer_image_e2e_complete "
        f"total={len(images)} succeeded={succeeded} failed={failed}"
    )
    return 0 if failed == 0 else 1


def validate_language_pair(ocr_language: str, target_language: str) -> None:
    if ocr_language == target_language:
        raise ValueError("OCR 语言与目标语言不能相同")


def _public_error_code(error: Exception) -> str:
    code = getattr(error, "code", None)
    if isinstance(code, str) and code.replace("_", "").isalnum():
        return code
    return type(error).__name__


if __name__ == "__main__":
    raise SystemExit(main())
