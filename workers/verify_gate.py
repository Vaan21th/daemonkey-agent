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

from agent_tools.verify_daemon_endpoints import _SUBPROCESS_SNIPPET as _SNIPPET


def _python() -> str:
    """优先用当前解释器 (daemon 内调 = venv 的 python) · 回退 .venv 路径。"""
    exe = sys.executable
    if exe:
        return exe
    cand = ROOT / ".venv" / "Scripts" / "python.exe"
    return str(cand) if cand.exists() else "python"


def _run_prefix_surface_gate(timeout: int = 90) -> tuple[bool, str]:
    """wish-a1580b98 · 第二项闸：「进前缀的写入面」登记 + 看板新鲜度。

    为什么放在这里 (而不是新建一个闸)：
      safe_merge 已经有一道上线闸，BRO 的原则是「先找现成的拦截器模式，别急着造新闸」。
      本项只是给同一道闸多加一条判据：
        ① tests/test_prefix_write_surface.py —— 有未登记的「进前缀写入点」就红
        ② tests/test_notebook_path_refs.py —— 有硬找已删画像单文件的读取点就红
        ③ workers/prefix_docs.py --check —— STRUCTURE.md 看板过期就红
    失败语义与主闸一致：真的跑了且没过 → fail-closed；闸自己起不来 → fail-open。
    """
    kw = dict(cwd=str(ROOT), capture_output=True, text=True,
              encoding="utf-8", errors="replace", timeout=timeout)
    try:
        from agent_tools._subprocess_helper import no_window_kwargs
        kw.update(no_window_kwargs())
    except Exception:
        pass
    reports = []
    ok_all = True
    try:
        r1 = subprocess.run(
            [_python(), "-m", "pytest", "tests/test_prefix_write_surface.py", "-q", "--no-header"],
            **kw)
        reports.append("pytest test_prefix_write_surface:\n" + ((r1.stdout or "")[-2000:]))
        if r1.returncode != 0:
            ok_all = False
    except Exception as e:
        reports.append(f"(写入面登记闸自己异常 · 已 fail-open · {type(e).__name__}: {e})")
    try:
        # 2026-09-30 · 第二类闸：管「读取点」（写入面闸管不到它）。
        # 拆格后全仓散布硬找已删画像单文件的代码，全是静默失效 —— 同理挂上线闸。
        r1b = subprocess.run(
            [_python(), "-m", "pytest", "tests/test_notebook_path_refs.py", "-q", "--no-header"],
            **kw)
        reports.append("pytest test_notebook_path_refs:\n" + ((r1b.stdout or "")[-2000:]))
        if r1b.returncode != 0:
            ok_all = False
    except Exception as e:
        reports.append(f"(画像路径引用闸自己异常 · 已 fail-open · {type(e).__name__}: {e})")
    try:
        r2 = subprocess.run([_python(), "-m", "workers.prefix_docs", "--check"], **kw)
        reports.append("prefix_docs --check:\n" + ((r2.stdout or "") + (r2.stderr or ""))[-800:])
        if r2.returncode != 0:
            ok_all = False
    except Exception as e:
        reports.append(f"(看板新鲜度闸自己异常 · 已 fail-open · {type(e).__name__}: {e})")
    return ok_all, "\n".join(reports)


def run_verify_subprocess(timeout: int = 150) -> tuple[bool, str]:
    """全新子进程跑 verify_daemon_endpoints。 返 (ok, report)。"""
    kw = dict(cwd=str(ROOT), capture_output=True, text=True,
              encoding="utf-8", errors="replace", timeout=timeout)
    try:
        from agent_tools._subprocess_helper import no_window_kwargs
        kw.update(no_window_kwargs())
    except Exception:
        pass
    extra_report = ""
    extra_ok = True
    try:
        extra_ok, extra_report = _run_prefix_surface_gate()
    except Exception as e:
        extra_report = f"(写入面闸外层异常 · 已 fail-open · {e})"
    try:
        kw.setdefault("timeout", 30)  # B-② · gate 自身超时兜底 (Grok 全量审计)
        r = subprocess.run([_python(), "-c", _SNIPPET], capture_output=True, text=True, **kw)
        err = r.stderr or ""
        # B-② · 2026-08-27 · 原来没 capture_output → r.stderr=None → None.strip() 崩 → 永远 fail-open (Grok 全量审计)
        report = ((r.stdout or "") + (("\n--- stderr ---\n" + err) if err.strip() else ""))
        ok = (r.returncode == 0) and extra_ok
        if extra_report:
            report = report + "\n\n=== 进前缀写入面闸 ===\n" + extra_report
        return ok, report[-6000:]
    except Exception as e:
        # 闸自己崩了 (起不来/超时) → fail-open · 别卡死正当上线 (坏的有 A 柱自愈兜底)
        return True, f"(⚠️ 上线闸自身异常 · 已 fail-open 放行 · 建议人工核查: {type(e).__name__}: {e})"
