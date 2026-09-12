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
from src.application.inpainting import (
    BuildEraseMask,
    RepairSelection,
    RepairTranslatedRegions,
)
from src.application.manual_region import ProcessManualRegion
from src.application.ocr import RecognizeText
from src.application.translation import TranslateRegions
from src.application.translate_image import TranslateImage
from src.domain.image import ImageLimits
from src.domain.activation import ActivationError
from src.domain.protection import ProtectionEngine
from src.domain.terminology import TerminologyCatalog
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
from src.infrastructure.model_delivery import FileModelRepository
from src.infrastructure.opencv_inpaint_adapter import OpenCvInpaintAdapter
from src.infrastructure.pillow_mask_rasterizer import PillowMaskRasterizer
from src.infrastructure.pillow_image_cropper import PillowImageCropper
from src.infrastructure.pillow_image_codec import PillowImageCodec
from src.infrastructure.rapidocr_adapter import RapidOcrAdapter
from src.infrastructure.rapidocr_models import InstalledRapidOcrModels
from src.infrastructure.server_translation_adapter import ServerTranslationAdapter
from src.infrastructure.text_renderer import QtBasicTextLayoutAdapter, QtTextRenderer
from src.infrastructure.user_preferences import (
    JsonBrandTermsPreferences,
    JsonEcommercePreferences,
    JsonFontPreferences,
    JsonModelTermsPreferences,
    JsonParagraphModePreferences,
    JsonTerminologyPreferences,
)
from src.platform.paths import PlatformPaths
from src.platform.credentials import create_platform_credential_store
from src.platform.qt_runtime import QtRuntimeMonitor, configure_qt_runtime
from src.ui.main_window import MainWindow
from src.ui.editor.main_window import EditorMainWindow
from src.ui.qt_task_runner import QtTaskRunner


def _create_access_token_source(
    activation: ActivationCoordinator | None,
):
    development_api_token = os.environ.get("IMGTRANS_API_TOKEN", "").strip()

    def access_token() -> str | None:
        if development_api_token:
            return development_api_token
        if activation is None:
            return None
        try:
            return activation.access_token()
        except ActivationError:
            return None

    return access_token


def _create_translation_adapter(
    backend_url: str,
    activation: ActivationCoordinator | None,
    access_token=None,
    ecommerce_terms: dict[str, str] | None = None,
    ecommerce_prompt: str | None = None,
) -> MockTranslationAdapter | ServerTranslationAdapter:
    translation_mode = os.environ.get(
        "IMGTRANS_TRANSLATION_MODE",
        "server",
    ).strip().lower()
    token_source = access_token or _create_access_token_source(activation)

    if translation_mode == "mock":
        return MockTranslationAdapter()
    if translation_mode == "server":
        if not backend_url:
            raise ValueError(
                "IMGTRANS_API_BASE_URL is required for server translation mode"
            )
        # 电商翻译模式：词库 + LLM 直接电商翻译；LLM 不可用时自动降级 Azure
        llm_adapter = None
        try:
            from src.infrastructure.server_llm_adapter import ServerLLMAdapter

            llm_adapter = ServerLLMAdapter(backend_url, token_source)
        except Exception:
            llm_adapter = None
        return ServerTranslationAdapter(
            backend_url,
            token_source,
            llm_adapter=llm_adapter,
            ecommerce=True,
            ecommerce_terms=ecommerce_terms,
            ecommerce_prompt=ecommerce_prompt,
        )
    raise ValueError("IMGTRANS_TRANSLATION_MODE must be mock or server")


def _create_payment_client(base_url: str):
    if not base_url:
        return None
    from src.infrastructure.payment_client import PaymentClient
    return PaymentClient(base_url)


def _create_quota_client(base_url: str):
    if not base_url:
        return None
    from src.infrastructure.quota_client import QuotaClient
    return QuotaClient(base_url)


def _with_bundled_models(repository):
    """打包版 exe 用内置模型兜底（data_dir 缺模型时直接加载内置 onnx）。"""
    from src.infrastructure.bundled_models import (
        BundledModelRepository,
        bundled_models_root,
    )

    root = bundled_models_root()
    if root is None:
        return repository
    return BundledModelRepository(repository, root)


DEFAULT_BACKEND_URL = "https://imgtrans.rchtop.top"


def create_main_window() -> MainWindow:
    logger = configure_logging()
    product = ProductInfo(name="图片翻译", version=__version__, milestone="M4")
    startup = BootstrapApplication(product, PlatformPaths.discover()).execute()
    codec = PillowImageCodec()
    backend_url = os.environ.get("IMGTRANS_API_BASE_URL", DEFAULT_BACKEND_URL).strip()
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
    model_repository = _with_bundled_models(FileModelRepository(startup.data_dir / "models"))
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
    activation = None
    if backend_url:
        activation = ActivationCoordinator(
            HttpActivationClient(backend_url),
            create_platform_credential_store(),
            backend_url,
        )

    access_token = _create_access_token_source(activation)
    preferences_path = startup.data_dir / "config" / "preferences.json"
    ecommerce_preferences = JsonEcommercePreferences(preferences_path)
    ecommerce_terms, ecommerce_prompt = ecommerce_preferences.load()
    translation_adapter = _create_translation_adapter(
        backend_url,
        activation,
        access_token,
        ecommerce_terms=ecommerce_terms,
        ecommerce_prompt=ecommerce_prompt,
    )
    terminology_catalog = TerminologyCatalog()
    translate = TranslateRegions(
        translation_adapter,
        ProtectionEngine(),
        terminology_catalog=terminology_catalog,
    )
    erase_mask_builder = BuildEraseMask(PillowMaskRasterizer())
    repair = RepairTranslatedRegions(erase_mask_builder, inpainting)
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
    repair_selection = RepairSelection(inpainting)
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
    brand_terms_preferences = JsonBrandTermsPreferences(preferences_path)
    terminology_preferences = JsonTerminologyPreferences(preferences_path)
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
        brand_terms_preferences=brand_terms_preferences,
        terminology_preferences=terminology_preferences,
        terminology_catalog=terminology_catalog,
        ecommerce_preferences=ecommerce_preferences,
        update_ecommerce_translation=getattr(
            translation_adapter,
            "set_ecommerce_override",
            None,
        ),
        export_batch_selection=export_batch_selection,
        task_runner=task_runner,
        refresh_image_limits=image_limits.refresh,
        activate_device=activation.activate if activation is not None else None,
        activation_status=(
            activation.current_session if activation is not None else None
        ),
        verify_activation=activation.verify if activation is not None else None,
        clear_activation=activation.clear if activation is not None else None,
        payment_client=_create_payment_client(backend_url),
        codec=codec,
        quota_client=_create_quota_client(backend_url),
        access_token=activation.access_token if activation is not None else None,
        backend_url=backend_url,
    )
    if remote_image_limits is not None:
        QTimer.singleShot(0, window.request_image_limits_refresh)
    if activation is not None:
        QTimer.singleShot(0, window.request_activation_check)
    return window


def _application_icon():
    """加载客户端图标；打包后从 _MEIPASS，开发时从 packaging/assets。"""
    from PySide6.QtGui import QIcon

    candidates = []
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys._MEIPASS) / "assets" / "imgtrans.png")
    candidates.append(
        Path(__file__).resolve().parent.parent / "packaging" / "assets" / "imgtrans.png"
    )
    for path in candidates:
        if path.is_file():
            return QIcon(str(path))
    return QIcon()


def _install_qt_translator(application: QApplication) -> None:
    """安装 Qt 简体中文翻译，使标准按钮（确定/取消/是/否）显示中文。"""
    from PySide6.QtCore import QLibraryInfo, QTranslator

    translator = QTranslator(application)
    path = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    if translator.load("qtbase_zh_CN", path):
        application.installTranslator(translator)


_shared_instance_memory = None


def _ensure_single_instance() -> bool:
    """同一时间只允许一个客户端实例运行（双击多次只开一个窗口）。"""
    global _shared_instance_memory
    from PySide6.QtCore import QSharedMemory

    memory = QSharedMemory("ImgTransDesktopSingleInstance")
    if memory.attach():
        return False
    if not memory.create(1):
        return False
    _shared_instance_memory = memory
    return True


def main(argv: Sequence[str] | None = None) -> int:
    multiprocessing.freeze_support()
    parser = argparse.ArgumentParser(prog="imgtrans")
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="create the main window and exit automatically",
    )
    parser.add_argument(
        "--editor",
        action="store_true",
        help="launch the new editor UI (under development)",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    if not args.smoke_test and not _ensure_single_instance():
        from PySide6.QtWidgets import QMessageBox

        app = QApplication.instance() or QApplication(["imgtrans"])
        QMessageBox.warning(None, "提示", "客户端已在运行，请切换到已打开的窗口")
        return 0
    configure_qt_runtime()
    application = QApplication.instance() or QApplication(["imgtrans"])
    application.setApplicationName("优译图AI")
    application.setApplicationVersion(__version__)
    application.setWindowIcon(_application_icon())
    _install_qt_translator(application)
    if args.editor:
        window = _create_editor_window()
    else:
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


def _create_editor_window() -> EditorMainWindow:
    """构建编辑器窗口的完整依赖集。"""
    configure_logging()
    startup = BootstrapApplication(
        ProductInfo(name="图片翻译", version=__version__, milestone="M4"),
        PlatformPaths.discover(),
    ).execute()
    codec = PillowImageCodec()
    backend_url = os.environ.get("IMGTRANS_API_BASE_URL", DEFAULT_BACKEND_URL).strip()
    remote_image_limits = HttpImageLimitsClient(backend_url) if backend_url else None
    image_limits = ImageLimitsCoordinator(
        JsonImageLimitsCache(startup.data_dir / "config" / "image-limits.json"),
        ImageLimits(),
        remote_image_limits,
    )
    import_image = ImportImage(codec, image_limits)
    export_image = ExportImage(codec)
    task_runner = QtTaskRunner()
    model_repository = _with_bundled_models(FileModelRepository(startup.data_dir / "models"))

    # —— OCR ——
    recognize = RecognizeText(
        RapidOcrAdapter(
            model_resolver=InstalledRapidOcrModels(model_repository).resolve,
        )
    )

    # —— 翻译 ——
    activation = None
    if backend_url:
        activation = ActivationCoordinator(
            HttpActivationClient(backend_url),
            create_platform_credential_store(),
            backend_url,
        )
    # —— 品牌词偏好 ——
    preferences_path = startup.data_dir / "config" / "preferences.json"
    brand_terms_prefs = JsonBrandTermsPreferences(preferences_path)
    brand_terms = brand_terms_prefs.load()
    model_terms_prefs = JsonModelTermsPreferences(preferences_path)
    model_terms = model_terms_prefs.load()
    terminology_catalog = TerminologyCatalog(
        JsonTerminologyPreferences(preferences_path).load()
    )
    terminology_prefs = JsonTerminologyPreferences(preferences_path)
    ecommerce_prefs = JsonEcommercePreferences(preferences_path)
    ecommerce_terms, ecommerce_prompt = ecommerce_prefs.load()
    font_prefs = JsonFontPreferences(preferences_path)
    saved_font = font_prefs.load()
    paragraph_mode_prefs = JsonParagraphModePreferences(preferences_path)
    saved_paragraph_mode = paragraph_mode_prefs.load()

    translation_adapter = _create_translation_adapter(
        backend_url,
        activation,
        ecommerce_terms=ecommerce_terms,
        ecommerce_prompt=ecommerce_prompt,
    )
    translate = TranslateRegions(
        translation_adapter,
        ProtectionEngine(),
        terminology_catalog=terminology_catalog,
    )

    # —— 修复 ——
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
    erase_mask_builder = BuildEraseMask(PillowMaskRasterizer())
    repair = RepairTranslatedRegions(erase_mask_builder, inpainting)

    # —— 排版 & 渲染 ——
    layout_adapter = QtBasicTextLayoutAdapter(font_family=saved_font)
    renderer = QtTextRenderer()

    # —— 翻译流水线 ——
    translate_image = TranslateImage(
        recognize,
        translate,
        repair,
        layout_adapter,
        renderer,
    )

    # —— 编辑合成 ——
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
    repair_selection = RepairSelection(inpainting)
    batch_result_store = PngBatchResultStore(
        startup.cache_dir / "batch-results",
        codec,
    )
    run_batch = RunBatch(
        import_image,
        translate_image,
        batch_result_store,
        max_active_items=2,
    )
    export_batch_selection = ExportBatchSelection(
        batch_result_store,
        export_image,
    )

    return EditorMainWindow(
        import_image=import_image,
        export_image=export_image,
        codec=codec,
        task_runner=task_runner,
        translate_image=translate_image,
        create_composition_editor=create_composition_editor,
        recognize_text=recognize,
        process_manual_region=process_manual_region,
        repair_selection=repair_selection,
        mask_rasterizer=PillowMaskRasterizer(),
        erase_mask_builder=erase_mask_builder,
        text_layout_adapter=layout_adapter,
        brand_terms=brand_terms,
        model_terms=model_terms,
        brand_terms_preferences=brand_terms_prefs,
        model_terms_preferences=model_terms_prefs,
        run_batch=run_batch,
        batch_result_store=batch_result_store,
        export_batch_selection=export_batch_selection,
        terminology_catalog=terminology_catalog,
        terminology_preferences=terminology_prefs,
        ecommerce_preferences=ecommerce_prefs,
        font_preferences=font_prefs,
        translation_font=saved_font,
        paragraph_mode=saved_paragraph_mode,
        paragraph_mode_preferences=paragraph_mode_prefs,
        update_ecommerce_translation=getattr(
            translation_adapter,
            "set_ecommerce_override",
            None,
        ),
        translation_service_label=(
            "翻译服务：服务端代理已配置"
            if translation_adapter.adapter_id != "mock-local"
            else "翻译服务：模拟模式"
        ),
        translation_service_available=True,
        manual_translation_adapter=translation_adapter,
        activate_device=activation.activate if activation is not None else None,
        activation_status=(
            activation.current_session if activation is not None else None
        ),
        verify_activation=activation.verify if activation is not None else None,
        clear_activation=activation.clear if activation is not None else None,
        payment_client=_create_payment_client(backend_url),
        quota_client=_create_quota_client(backend_url),
        access_token=(
            activation.access_token if activation is not None else None
        ),
        refresh_image_limits=image_limits.refresh,
        backend_url=backend_url,
    )


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
