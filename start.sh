#!/usr/bin/env bash
# Daemonkey · macOS / Linux 一键启动 (POSIX)
# ---------------------------------------------------------------
# 对标 Windows 的 run.ps1 + GUI 启动器：备环境 → 起 daemon → 开浏览器。
# 用法：  chmod +x start.sh && ./start.sh
# 说明：  剪贴板 / 开应用 / 浏览器手眼已对齐；桌宠可从启动器开（穿透弱于 Windows）。
# ---------------------------------------------------------------
set -u
cd "$(dirname "$0")"

say() { printf '  %s\n' "$1"; }

echo ""
echo "  ============================================"
echo "   Daemonkey · 启动 (macOS / Linux)"
echo "  ============================================"
echo ""

# 1) Python 3.10+
PY="$(command -v python3 || true)"
if [ -z "$PY" ]; then
  echo "  [X] 没找到 python3。请先安装 Python 3.10+："
  echo "      macOS : brew install python"
  echo "      Ubuntu: sudo apt install -y python3 python3-venv python3-pip"
  exit 1
fi
say "Python: $("$PY" --version 2>&1)"

# 2) 虚拟环境
if [ -f ".venv/Scripts/python.exe" ] && [ ! -x ".venv/bin/python" ]; then
  say "检测到 Windows 的 .venv · 重建 Mac 环境..."
  rm -rf .venv
fi
if [ ! -d ".venv" ]; then
  say "创建虚拟环境 .venv ..."
  "$PY" -m venv .venv || { echo "  [X] venv 创建失败"; exit 1; }
fi
# shellcheck disable=SC1091
source .venv/bin/activate

# 3) 依赖（核心必装；桌宠 PyQt6 可选，装不上也不挡 WebUI）
if ! python -c "import fastapi, uvicorn, openai, anthropic" 2>/dev/null; then
  say "安装依赖（首次约 1-2 分钟）..."
  MIRROR="https://pypi.tuna.tsinghua.edu.cn/simple"
  grep -viE 'pyqt6' requirements.txt > /tmp/dk-req-core.txt
  python -m pip install -q --upgrade pip -i "$MIRROR" 2>/dev/null || python -m pip install -q --upgrade pip
  if ! python -m pip install -q -i "$MIRROR" -r /tmp/dk-req-core.txt 2>/dev/null; then
    say "镜像不可用·改用默认 PyPI ..."
    python -m pip install -q -r /tmp/dk-req-core.txt || { echo "  [X] 依赖安装失败·检查网络"; exit 1; }
  fi
  python -m pip install -q PyQt6 -i "$MIRROR" >/dev/null 2>&1 \
    || python -m pip install -q PyQt6 >/dev/null 2>&1 \
    || say "(桌宠 PyQt6 未装·不影响 WebUI)"
  say "依赖就绪"
else
  say "依赖已就绪"
fi

# 3b) 没有本机 Chrome/Edge 时拉 Playwright Chromium（浏览器手/眼）
if [ ! -x "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" ] \
   && [ ! -x "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge" ]; then
  say "未发现 Chrome/Edge · 尝试 Playwright Chromium..."
  python -m playwright install chromium >/dev/null 2>&1 \
    || say "(Chromium 未拉下 · 可 brew install --cask google-chrome)"
fi
if ! command -v ffmpeg >/dev/null 2>&1; then
  say "(录屏需要 ffmpeg · brew install ffmpeg，并打开系统「屏幕录制」权限)"
fi

# 4) .env（没有就从模板建；key 启动后在网页里填）
if [ ! -f .env ]; then
  cp .env.example .env 2>/dev/null && say ".env 已从模板创建（key 在网页里填）"
fi

# 5) 起 daemon + 开浏览器
PORT="${OPUS_API_PORT:-7860}"
URL="http://127.0.0.1:${PORT}/ui"
say "启动 daemon ... → $URL"
python tools/run_api_only.py --port "$PORT" &
DPID=$!
sleep 4
if command -v open >/dev/null 2>&1; then
  open "$URL" 2>/dev/null || true
elif command -v xdg-open >/dev/null 2>&1; then
  xdg-open "$URL" 2>/dev/null || true
else
  echo "  请在浏览器打开：$URL"
fi
echo ""
echo "  Daemonkey 正在运行。停止：在本终端按 Ctrl-C。"
wait "$DPID"
