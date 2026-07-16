from __future__ import annotations

import argparse
import logging
import multiprocessing
import os
import sys
from pathlib import Path
from collections.abc import Sequence

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from src import __version__
from src.application.bootstrap import BootstrapApplication
from src.application.batch import RunBatch
from src.application.batch_export import ExportBatchSelection
from src.application.activation import ActivationCoordinator
from src.application.composition import CreateCompositionEditor
from src.application.image_io import ExportImage, ImportImage
from src.application.image_limits import ImageLimitsCoordinator
from src.application.inpainting import BuildEraseMask, RepairTranslatedRegions
from src.application.manual_region import ProcessManualRegion
from src.application.model_delivery import EnsureModels
from src.application.ocr import RecognizeText
from src.application.translation import TranslateRegions
from src.application.translate_image import TranslateImage
from src.domain.image import ImageLimits
from src.domain.activation import ActivationError
from src.domain.protection import ProtectionEngine
from src.domain.product import ProductInfo
from src.infrastructure.logging_config import configure_logging
from src.infrastructure.batch_result_store import PngBatchResultStore
from src.infrastructure.fallback_inpaint_adapter import FallbackInpaintAdapter
from src.infrastructure.inpainting_process import ProcessLamaAdapter
from src.infrastructure.image_limits_config import (
    HttpImageLimitsClient,
    JsonImageLimitsCache,
)
from src.infrastructure.lama_onnx_adapter import LAMA_MODEL_FILENAME
from src.infrastructure.activation_client import HttpActivationClient
from src.infrastructure.mock_translator import MockTranslationAdapter
from src.infrastructure.model_delivery import (
    FileModelRepository,
    HttpModelManifestClient,
    HttpRangeModelDownloader,
)
from src.infrastructure.opencv_inpaint_adapter import OpenCvInpaintAdapter
from src.infrastructure.pillow_mask_rasterizer import PillowMaskRasterizer
from src.infrastructure.pillow_image_cropper import PillowImageCropper
from src.infrastructure.pillow_image_codec import PillowImageCodec
from src.infrastructure.rapidocr_adapter import RapidOcrAdapter
from src.infrastructure.rapidocr_models import InstalledRapidOcrModels
from src.infrastructure.server_translation_adapter import ServerTranslationAdapter
from src.infrastructure.text_renderer import QtBasicTextLayoutAdapter, QtTextRenderer
from src.platform.paths import PlatformPaths, discover_model_target
from src.platform.credentials import create_platform_credential_store
from src.platform.qt_runtime import QtRuntimeMonitor, configure_qt_runtime
from src.ui.main_window import MainWindow
from src.ui.qt_task_runner import QtTaskRunner


def create_main_window() -> MainWindow:
    logger = configure_logging()
    product = ProductInfo(name="图片翻译", version=__version__, milestone="M4")
    startup = BootstrapApplication(product, PlatformPaths.discover()).execute()
    codec = PillowImageCodec()
    backend_url = os.environ.get("IMGTRANS_API_BASE_URL", "").strip()
    remote_image_limits = (
        HttpImageLimitsClient(backend_url) if backend_url else None
    )
    image_limits = ImageLimitsCoordinator(
        JsonImageLimitsCache(startup.data_dir / "config" / "image-limits.json"),
        ImageLimits(),
        remote_image_limits,
    )
    logger.info(
        "image_limits_ready source=%s version=%s",
        image_limits.current_limits.source,
        image_limits.current_limits.config_version,
    )
    import_image = ImportImage(codec, image_limits)
    export_image = ExportImage(codec)
    task_runner = QtTaskRunner()
    model_repository = FileModelRepository(startup.data_dir / "models")
    installed_lama = model_repository.active("lama-inpainting")
    default_model_path = (
        Path(installed_lama.path)
        if installed_lama is not None
        else startup.data_dir / "models" / LAMA_MODEL_FILENAME
    )
    model_path = Path(os.environ.get("IMGTRANS_LAMA_MODEL", default_model_path))
    inpainting = FallbackInpaintAdapter(
        ProcessLamaAdapter(model_path),
        OpenCvInpaintAdapter(),
    )
    recognize = RecognizeText(
        RapidOcrAdapter(
            model_resolver=InstalledRapidOcrModels(model_repository).resolve,
        )
    )
    translation_mode = os.environ.get("IMGTRANS_TRANSLATION_MODE", "mock").strip().lower()
    development_api_token = os.environ.get("IMGTRANS_API_TOKEN", "").strip()
    activation = None
    if backend_url:
        activation = ActivationCoordinator(
            HttpActivationClient(backend_url),
            create_platform_credential_store(),
            backend_url,
        )

    def access_token() -> str | None:
        if development_api_token:
            return development_api_token
        if activation is None:
            return None
        try:
            return activation.access_token()
        except ActivationError:
            return None

    if translation_mode == "mock":
        translation_adapter = MockTranslationAdapter()
    elif translation_mode == "server":
        if not backend_url:
            raise ValueError(
                "IMGTRANS_API_BASE_URL is required for server translation mode"
            )
        translation_adapter = ServerTranslationAdapter(backend_url, access_token)
    else:
        raise ValueError("IMGTRANS_TRANSLATION_MODE must be mock or server")
    translate = TranslateRegions(translation_adapter, ProtectionEngine())
    repair = RepairTranslatedRegions(
        BuildEraseMask(PillowMaskRasterizer()),
        inpainting,
    )
    layout_adapter = QtBasicTextLayoutAdapter()
    renderer = QtTextRenderer()
    workflow = TranslateImage(
        recognize,
        translate,
        repair,
        layout_adapter,
        renderer,
    )
    create_composition_editor = CreateCompositionEditor(
        layout_adapter,
        renderer,
    )
    process_manual_region = ProcessManualRegion(
        recognize,
        translate,
        PillowImageCropper(),
        PillowMaskRasterizer(),
        inpainting,
        layout_adapter,
    )
    batch_result_store = PngBatchResultStore(
        startup.cache_dir / "batch-results",
        codec,
    )
    run_batch = RunBatch(
        import_image,
        workflow,
        batch_result_store,
    )
    export_batch_selection = ExportBatchSelection(
        batch_result_store,
        export_image,
    )
    update_models = None
    if backend_url:
        model_platform, model_architecture = discover_model_target()
        update_models = EnsureModels(
            HttpModelManifestClient(backend_url, access_token),
            HttpRangeModelDownloader(),
            model_repository,
            startup.cache_dir / "model-downloads",
            model_platform,
            model_architecture,
        ).execute
    logger.info("application_ready version=%s", product.version)
    window = MainWindow(
        startup,
        import_image=import_image,
        export_image=export_image,
        recognize_text=recognize,
        translate_regions=translate,
        repair_regions=repair,
        translate_image=workflow,
        create_composition_editor=create_composition_editor,
        process_manual_region=process_manual_region,
        run_batch=run_batch,
        batch_result_store=batch_result_store,
        export_batch_selection=export_batch_selection,
        task_runner=task_runner,
        refresh_image_limits=image_limits.refresh,
        update_models=update_models,
        activate_device=activation.activate if activation is not None else None,
        activation_status=(
            activation.current_session if activation is not None else None
        ),
        clear_activation=activation.clear if activation is not None else None,
    )
    if remote_image_limits is not None:
        QTimer.singleShot(0, window.request_image_limits_refresh)
    if update_models is not None and development_api_token:
        QTimer.singleShot(0, window.request_model_update)
    elif activation is not None:
        QTimer.singleShot(0, window.request_activation_check)
    return window


def main(argv: Sequence[str] | None = None) -> int:
    multiprocessing.freeze_support()
    parser = argparse.ArgumentParser(prog="imgtrans")
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="create the main window and exit automatically",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    configure_qt_runtime()
    application = QApplication.instance() or QApplication(["imgtrans"])
    application.setApplicationName("ImgTrans")
    application.setApplicationVersion(__version__)
    window = create_main_window()
    runtime_monitor = QtRuntimeMonitor(application)
    runtime_monitor.recovery_requested.connect(window.request_runtime_recovery)
    window._runtime_monitor = runtime_monitor
    window.show()
    if args.smoke_test:
        QTimer.singleShot(100, application.quit)
    exit_code = application.exec()
    window.close()
    logging.shutdown()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
