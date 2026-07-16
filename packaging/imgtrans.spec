from pathlib import Path
import os
import platform
import sys

from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
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
rapidocr_hidden = collect_submodules("rapidocr")
onnx_binaries = collect_dynamic_libs("onnxruntime")

analysis = Analysis(
    [str(root / "src" / "__main__.py")],
    pathex=[str(root)],
    binaries=[*rapidocr_binaries, *onnx_binaries],
    datas=rapidocr_datas,
    hiddenimports=[
        *rapidocr_hidden,
        "onnxruntime",
        "onnxruntime.capi._pybind_state",
        "cv2",
        "PIL.Image",
        "PIL.ImageCms",
        "PIL.ImageQt",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "server",
        "tests",
        "prototypes",
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
