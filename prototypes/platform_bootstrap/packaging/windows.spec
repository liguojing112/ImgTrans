import importlib.util
import os
from pathlib import Path


prototype_dir = Path(SPECPATH).parent
target = os.environ.get("PLATFORM_BOOTSTRAP_TARGET", "windows-x64")
profile = os.environ.get("PLATFORM_BOOTSTRAP_PROFILE", "ui")
app_name = f"PlatformBootstrap-{target}"

hidden_imports = ["PIL", "PIL.Image", "cv2"]
if profile == "native":
    hidden_imports.extend(
        module
        for module in ("rapidocr_onnxruntime", "rapidocr", "onnxruntime", "torch")
        if importlib.util.find_spec(module) is not None
    )

a = Analysis(
    [str(prototype_dir / "main.py")],
    pathex=[str(prototype_dir)],
    binaries=[],
    datas=[],
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=app_name,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name=app_name,
)
