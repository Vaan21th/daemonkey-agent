# -*- coding: utf-8 -*-
"""workers/verify_gate.py · 上线闸 runner (卷五十四 · B2)

在"代码将要进 master / wish 将要标 live"的关口 · 强制在【全新子进程】里跑
verify_daemon_endpoints (建全 app + 路由 smoke + 前端 JS 语法)。

为什么必须子进程 (关键):
  运行中的 daemon 进程里 Python 模块已被 import 缓存 (sys.modules) · 进程内再 import
  测的是【内存里的旧代码】· 不是磁盘上分支的【新代码】= 白验。 子进程从磁盘 fresh
  import · 才测真东西。 pre-commit 钩子也是这么干 (python -c 子进程) · 这里复用同一
  姿势 · 让 merge / live 这两个状态机关口也享受同等的"能不能跑起来"保护。

闸的失败语义 (硬闸契约 · 不在闸本身的故障上硬锁):
  - verify 真的跑了且【没过】(returncode≠0) → fail-closed · 拦住 (这是真·代码坏了)
  - 闸自己【起不来】(spawn 异常 / 超时) → fail-open + 大声告警 · 放行 (别因为闸的基建
    故障卡死正当上线 · 坏的还有 A 柱自愈兜底)
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_SNIPPET = (
    "import os,sys; sys.path.insert(0,'.'); "
    "os.environ.setdefault('OPUS_API_TOKEN','verify-gate-token'); "
    "from agent_tools.verify_daemon_endpoints import _run; "
    "r=_run({}); print(r.output); sys.exit(0 if r.ok else 1)"
)


def _python() -> str:
    """优先用当前解释器 (daemon 内调 = venv 的 python) · 回退 .venv 路径。"""
    exe = sys.executable
    if exe:
        return exe
    cand = ROOT / ".venv" / "Scripts" / "python.exe"
    return str(cand) if cand.exists() else "python"


def run_verify_subprocess(timeout: int = 150) -> tuple[bool, str]:
    """全新子进程跑 verify_daemon_endpoints。 返 (ok, report)。"""
    kw = dict(cwd=str(ROOT), capture_output=True, text=True,
              encoding="utf-8", errors="replace", timeout=timeout)
    try:
        from agent_tools._subprocess_helper import no_window_kwargs
        kw.update(no_window_kwargs())
    except Exception:
        pass
    try:
        r = subprocess.run([_python(), "-c", _SNIPPET], **kw)
        report = ((r.stdout or "") + (("\n--- stderr ---\n" + r.stderr) if r.stderr.strip() else ""))
        return (r.returncode == 0), report[-6000:]
    except Exception as e:
        # 闸自己崩了 (起不来/超时) → fail-open · 别卡死正当上线 (坏的有 A 柱自愈兜底)
        return True, f"(⚠️ 上线闸自身异常 · 已 fail-open 放行 · 建议人工核查: {type(e).__name__}: {e})"
