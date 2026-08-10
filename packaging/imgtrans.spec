from pathlib import Path
import os
import platform
import sys

from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_dynamic_libs,
)


root = Path(SPECPATH).parent
target = os.environ.get("IMGTRANS_BUILD_TARGET", "")
machine = platform.machine().lower()

if target == "windows-x64":
    if sys.platform != "win32" or machine not in {"amd64", "x86_64"}:
        raise ValueError("windows-x64 must be built natively on Windows x64")
    target_arch = None
elif target == "macos-arm64":
    if sys.platform != "darwin" or machine not in {"arm64", "aarch64"}:
        raise ValueError("macos-arm64 must be built natively on Apple Silicon")
    target_arch = "arm64"
else:
    raise ValueError(f"unsupported or missing IMGTRANS_BUILD_TARGET: {target}")

rapidocr_datas = collect_data_files(
    "rapidocr",
    excludes=["models/*.onnx", "**/*.onnx"],
)
rapidocr_binaries = collect_dynamic_libs("rapidocr")
rapidocr_hidden = [
    "rapidocr.inference_engine.onnxruntime",
    "rapidocr.inference_engine.onnxruntime.main",
    "rapidocr.inference_engine.onnxruntime.provider_config",
]
onnx_binaries = collect_dynamic_libs("onnxruntime")

bundled_models_dir = root / "packaging" / "bundled_models"
bundled_datas = []
if bundled_models_dir.is_dir():
    for model_dir in bundled_models_dir.iterdir():
        if model_dir.is_dir():
            for file in model_dir.iterdir():
                if file.is_file():
                    bundled_datas.append(
                        (str(file), f"bundled_models/{model_dir.name}")
                    )

# Playwright chromium（1688/淘宝等需浏览器渲染的链接解析）
playwright_datas = []
if sys.platform == "win32":
    playwright_root = (
        Path(os.environ.get("LOCALAPPDATA", "")) / "ms-playwright"
    )
    for name in ("chromium-1208", "chromium_headless_shell-1208"):
        browser_dir = playwright_root / name
        if browser_dir.is_dir():
            playwright_datas.append((str(browser_dir), f"ms-playwright/{name}"))
    # playwright driver（node.exe + 脚本）必须随包分发
    playwright_datas.extend(collect_data_files("playwright"))

analysis = Analysis(
    [str(root / "src" / "__main__.py")],
    pathex=[str(root)],
    binaries=[*rapidocr_binaries, *onnx_binaries],
    datas=[*rapidocr_datas, *bundled_datas, *playwright_datas, (str(root / "packaging" / "assets" / "imgtrans.png"), "assets")],
    hiddenimports=[
        *rapidocr_hidden,
        "onnxruntime",
        "onnxruntime.capi._pybind_state",
        "cv2",
        "PIL.Image",
        "PIL.ImageCms",
        "PIL.ImageQt",
        "qrcode",
        "png",
        # 商品链接解析：Playwright（1688 等需浏览器渲染/人工验证）
        "playwright",
        "playwright.sync_api",
        "playwright.async_api",
        "playwright._impl._driver",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "server",
        "tests",
        "prototypes",
        "rapidocr.inference_engine.mnn",
        "rapidocr.inference_engine.openvino",
        "rapidocr.inference_engine.paddle",
        "rapidocr.inference_engine.pytorch",
        "rapidocr.inference_engine.tensorrt",
        "torch",
        "functorch",
        "jax",
        "jaxlib",
        "matplotlib",
        "pandas",
        "pyarrow",
        "numba",
        "llvmlite",
        "scipy",
        "sqlalchemy",
        "psycopg",
        "psycopg2",
        "boto3",
        "botocore",
        "fastapi",
        "uvicorn",
        "jinja2",
        "lxml",
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(analysis.pure)

executable = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="ImgTrans",
    icon=str(root / "packaging" / "assets" / "imgtrans.ico"),
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    target_arch=target_arch,
    codesign_identity=None,
    entitlements_file=None,
)
collection = COLLECT(
    executable,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    name="ImgTrans",
)

if target == "macos-arm64":
    application = BUNDLE(
        collection,
        name="ImgTrans.app",
        icon=None,
        bundle_identifier="com.imgtrans.desktop",
        target_arch="arm64",
        codesign_identity=None,
        entitlements_file=None,
        info_plist={
            "CFBundleDisplayName": "ImgTrans",
            "LSMinimumSystemVersion": "13.0",
            "NSHighResolutionCapable": True,
        },
    )
