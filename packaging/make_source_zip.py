import os
import zipfile

src = r"C:\Workspace\PythonProjects\ImgTrans-desktop-v1"
out = os.path.join(src, "ImgTrans-source-v1.1.6.zip")

EXCLUDE_DIRS = {
    ".git", ".claude", ".idea", ".vscode", ".pytest_cache",
    "build", "dist", ".venv", "artifacts", "tmp-models",
    "__pycache__", "imgtrans.egg-info",
    "bundled_models",  # packaging 下的内置模型（273M，不入库）
}
EXCLUDE_FILES = {
    ".git",              # gitdir 指针文件，暴露本地路径
    "settings-key.bin",  # 运行时加密密钥，绝不能交付
    "dbg_tmp.py",        # 调试临时文件
}
EXCLUDE_SUFFIX = {".pyc", ".log", ".zip"}

count = 0
total = 0
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    for root, dirs, files in os.walk(src):
        dirs[:] = sorted(d for d in dirs if d not in EXCLUDE_DIRS)
        for f in sorted(files):
            if f in EXCLUDE_FILES:
                continue
            if os.path.splitext(f)[1].lower() in EXCLUDE_SUFFIX:
                continue
            p = os.path.join(root, f)
            rel = os.path.relpath(p, src).replace("\\", "/")
            z.write(p, rel)
            count += 1
            total += os.path.getsize(p)

size_mb = os.path.getsize(out) / 1024 / 1024
print(f"files={count} total={total} zip={size_mb:.1f}MB")
