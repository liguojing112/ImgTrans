import importlib.util
import os
from pathlib import Path


prototype_dir = Path(SPECPATH).parent
target = os.environ.get("PLATFORM_BOOTSTRAP_TARGET", "macos-arm64")
profile = os.environ.get("PLATFORM_BOOTSTRAP_PROFILE", "ui")
if target != "macos-arm64":
    raise ValueError(f"unsupported macOS target: {target}")
target_arch = "arm64"
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
    upx=False,
    console=False,
    target_arch=target_arch,
    codesign_identity=os.environ.get("PLATFORM_BOOTSTRAP_CODESIGN_IDENTITY"),
    entitlements_file=os.environ.get("PLATFORM_BOOTSTRAP_ENTITLEMENTS"),
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=app_name,
)
app = BUNDLE(
    coll,
    name=f"{app_name}.app",
    icon=None,
    bundle_identifier="com.imgtrans.platform-bootstrap",
)
