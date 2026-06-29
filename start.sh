#!/usr/bin/env bash
# Daemonkey · macOS / Linux 一键启动 (POSIX)
# ---------------------------------------------------------------
# 对标 Windows 的 run.ps1 + GUI 启动器：备环境 → 起 daemon → 开浏览器。
# 用法：  chmod +x start.sh && ./start.sh
# 说明：  桌宠 / 剪贴板 / 打开应用等 Windows 专属能力在 *nix 暂未适配，
#         不影响 WebUI 对话 / 记忆 / 工坊等核心功能。
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
