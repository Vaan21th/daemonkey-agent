#!/bin/bash
# ─────────────────────────────────────────────────────────────
# Daemonkey · macOS 启动器打包脚本 (PyInstaller)
# 用法: bash build_mac_app.sh [版本号]     ← 在 Mac 上执行
#   前提: 已 clone Daemonkey 仓库 (含 mac_launcher.py + assets/)
# 产物: dist/Daemonkey.app (双击即用 · 无需用户装 Python/pywebview)
#        dist/Daemonkey-<ver>-arm64.dmg (可选 · 分发用)
# ─────────────────────────────────────────────────────────────
# 为什么必须 Mac 上跑: PyInstaller 不支持交叉编译 · Mac .app 只能在 Mac 构建。
# 为什么小白能用: pywebview + launcher.html + 全部资产打进 app ·
#   用户双击 → WKWebView 渲染启动器 (和 Windows WebView2 同一份 HTML)。
# 当前架构: arm64 (Apple Silicon) · Intel Mac 用户多了再补 universal2。
# ─────────────────────────────────────────────────────────────
set -euo pipefail
cd "$(dirname "$0")/.."

VER="${1:-0.9.5}"
echo "==> Daemonkey macOS 打包 v$VER"

# 1. 依赖检查 (只装 pyinstaller + pywebview · daemon 本体依赖由首次引导装)
command -v python3 >/dev/null 2>&1 || { echo "❌ 需要 Python3 (brew install python)"; exit 1; }
python3 -m pip show pyinstaller >/dev/null 2>&1 || { echo "==> 装 pyinstaller..."; python3 -m pip install --user pyinstaller; }
python3 -m pip show webview >/dev/null 2>&1 || { echo "==> 装 pywebview..."; python3 -m pip install --user pywebview; }

# 2. 资产齐全检查
[ -f mac_launcher.py ] || { echo "❌ 缺 mac_launcher.py (在仓库根?)"; exit 1; }
[ -f assets/launcher.html ] || { echo "❌ 缺 assets/launcher.html"; exit 1; }
[ -f assets/guard-panel.html ] || { echo "❌ 缺 assets/guard-panel.html"; exit 1; }

# 3. 打包 (windowed=无控制台 · add-data 带 assets · hidden-import 显式带 webview)
rm -rf build dist Daemonkey.spec
python3 -m PyInstaller \
  --windowed \
  --name "Daemonkey" \
  --add-data "assets:assets" \
  --hidden-import "webview" \
  --hidden-import "webview.platforms.cocoa" \
  --osx-bundle-identifier "com.vaan21th.daemonkey" \
  mac_launcher.py

# 4. 版本号写进 Info.plist
/usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString $VER" \
  "dist/Daemonkey.app/Contents/Info.plist" 2>/dev/null || true

echo "==> ✅ 产物: dist/Daemonkey.app"
ls -d "$PWD/dist/Daemonkey.app" 2>/dev/null && echo "    双击即用 · 用户无需装任何东西"

# 5. 可选 dmg (分发更友好 · 架构名动态: macos-14 runner=x86_64 · 以后 arm runner 自动 arm64)
if command -v hdiutil >/dev/null 2>&1; then
  ARCH="$(uname -m)"
  echo "==> 打包 dmg (分发用 · $ARCH)..."
  hdiutil create -volname "Daemonkey" -srcfolder "dist/Daemonkey.app" \
    -ov -format UDZO "dist/Daemonkey-$VER-$ARCH.dmg" 2>/dev/null \
    && echo "==> ✅ dmg: dist/Daemonkey-$VER-$ARCH.dmg" || echo "   (dmg 失败不影响 app)"
fi

echo ""
echo "==> 下一步: 把 dist/Daemonkey.app 或 .dmg 上传到 gitee/github Release 附件"
echo "==> 注意: mac_launcher.py 首次引导 (自动 clone daemon + 装依赖) 是下一批增强 ·"
echo "==>       当前 .app 假设 daemon 代码已 clone 在 ~/Daemonkey"
