#!/bin/bash
# 优译图AI — macOS（Apple Silicon）一键编译脚本
# 用法：在 Mac 上打开终端，进入项目目录后运行：
#   bash scripts/build_macos.sh
# 前置条件：
#   1. Apple Silicon Mac（M1/M2/M3/M4），macOS 13.0+
#   2. 已安装 Python 3.11（从 https://www.python.org/downloads/macos/ 下载安装）
#   3. 整个项目目录已复制到 Mac（含 packaging/bundled_models 模型缓存）
set -e
cd "$(dirname "$0")/.."

echo "============================================="
echo " 优译图AI macOS 编译"
echo "============================================="

# 1) 找 Python 3.11
PY=""
for c in python3.11 python3; do
  if command -v "$c" >/dev/null 2>&1; then PY="$c"; break; fi
done
if [ -z "$PY" ]; then
  echo "❌ 未找到 Python 3.11，请先从 https://www.python.org/downloads/macos/ 安装"
  exit 1
fi
echo "✅ 使用 Python: $($PY --version)"

# 2) 安装依赖
echo "---------------------------------------------"
echo "1/4 安装依赖（可能耗时几分钟）"
$PY -m pip install --upgrade pip
$PY -m pip install -e '.[release]'

# 3) 编译 .app
echo "---------------------------------------------"
echo "2/4 编译 macOS .app"
IMGTRANS_BUILD_TARGET=macos-arm64 $PY scripts/build_desktop.py --target macos-arm64

APP="dist/release-candidate/macos-arm64/ImgTrans.app"
if [ ! -d "$APP" ]; then
  echo "❌ 编译失败：未找到 $APP"
  exit 1
fi
echo "✅ 编译成功: $APP"

# 4) 制作 .dmg 安装包
echo "---------------------------------------------"
echo "3/4 制作 .dmg 安装包"
mkdir -p dist/installer
if hdiutil create -volname "优译图AI" -srcfolder "$APP" -ov -format UDZO "dist/installer/ImgTrans-macos-arm64.dmg"; then
  echo "✅ dmg 已生成: dist/installer/ImgTrans-macos-arm64.dmg"
else
  echo "⚠️ dmg 制作失败，可直接分发 .app（压缩成 zip 即可）"
fi

echo "---------------------------------------------"
echo " 完成！"
echo "  App: $APP"
echo "  Dmg: dist/installer/ImgTrans-macos-arm64.dmg"
echo ""
echo " 注：未签名的 .app 首次打开会提示「无法验证开发者」，"
echo "     请右键点击 App → 打开 → 再点「打开」即可运行。"
