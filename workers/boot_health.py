# -*- coding: utf-8 -*-
"""workers/boot_health.py · 启动健康自检 + last-good 自愈 (卷五十四 · A 柱)

────────────────────────────────────────────────────────────────────
A1 · last-good 语义修对
────────────────────────────────────────────────────────────────────
老逻辑 (daemon_lifecycle.mark_graceful_shutdown) 在**停机那一刻**给 master HEAD 打
opus-last-good —— 但那一刻新代码还没证明自己能跑。 结果今天 (2026-06-03) 把砍断
chat.js 的坏 commit 55d27cd 标成了 known-good (restart_history 实锤)。 一旦那会儿
回档 + reset --hard opus-last-good · 会精准回到白屏的坏版本。

改成: daemon 启动后**撑过 grace window 且自检健康** (在 master · 前端 JS 没坏) 才把
当前 master HEAD 前移成 last-good。 语义 = "这版活着撑过了启动窗口 · 配当回退目标"。
进程若在窗口内崩 · 计时线程随之消失 · tag 不前移 (保守 · 旧的好版本仍是回退点)。

────────────────────────────────────────────────────────────────────
A2 · 启动自检失败 → 自动回退 last-good
────────────────────────────────────────────────────────────────────
build_app 抛错 (Python 级起不来) 或前端 JS 语法坏 → 若有可信 last-good 且 HEAD≠last-good ·
自动 git reset --hard 回 last-good (先 stash 兜底·不丢任何东西) + spawn 新 daemon 接管。
防循环靠两层: ① HEAD==last-good 就不 revert (回退目标就是自己·没意义) —— 天然终止 ·
revert 后 HEAD 变成 last-good · 下次 boot 不会再 revert; ② marker 文件留痕 + 时间窗。
逃生门: OPUS_NO_AUTO_REVERT=1 关掉整个自愈 (BRO 想手动处理时)。

这个模块刻意自包含 (自带极简 git 调用) —— 恢复代码不该依赖 daemon 内部那套锁/runtime ·
否则 daemon 半死时恢复逻辑自己也跑不动。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
RUNTIME_DIR = ROOT / "data" / "runtime"
REVERT_MARKER = RUNTIME_DIR / "auto_revert_marker.json"

LAST_GOOD_GRACE_SEC = int(os.environ.get("OPUS_LASTGOOD_GRACE_SEC") or 90)
REVERT_LOOP_GUARD_SEC = 600


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _git(args: list[str], timeout: int = 20) -> tuple[int, str, str]:
    """自包含 git 调用 · 显式 utf-8 (Windows 默认 GBK 会崩) · 不弹 console。"""
    kw = dict(cwd=str(ROOT), capture_output=True, text=True,
              encoding="utf-8", errors="replace", timeout=timeout)
    try:
        from agent_tools._subprocess_helper import no_window_kwargs
        kw.update(no_window_kwargs())
    except Exception:
        pass
    try:
        r = subprocess.run(["git"] + args, **kw)
        return r.returncode, (r.stdout or ""), (r.stderr or "")
    except Exception as e:
        return 1, "", f"{type(e).__name__}: {e}"


def _log_event(record: dict) -> None:
    """落到统一的 restart_history.jsonl · 跟 daemon_lifecycle 同一条时间线。"""
    try:
        from workers import daemon_lifecycle
        daemon_lifecycle._append_history(record)
    except Exception:
        try:
            RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
            record["timestamp"] = _now_iso()
            with (RUNTIME_DIR / "restart_history.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception:
            pass


def _head_sha() -> Optional[str]:
    rc, out, _ = _git(["rev-parse", "--short", "HEAD"], timeout=5)
    return out.strip() if rc == 0 else None


def _on_master() -> bool:
    rc, out, _ = _git(["rev-parse", "--abbrev-ref", "HEAD"], timeout=5)
    return rc == 0 and out.strip() == "master"


# ── 健康自检 ──────────────────────────────────────────────────────────

def preflight_health() -> tuple[bool, str]:
    """启动期轻量自检 (build_app 之前能跑的部分): 前端 JS 语法。
    返 (ok, 给日志/BRO 看的说明)。 node 缺失会降级·绝不硬崩 (见 frontend_check)。"""
    try:
        from workers.frontend_check import check_static_js, format_report
        fe = check_static_js()
        return fe["ok"], format_report(fe)
    except Exception as e:
        # 自检器自己崩了 → 不阻断启动 (宁可放行也不要因为检查器把 daemon 拦死)
        return True, f"(前端自检跳过: {type(e).__name__}: {e})"


# ── A2 · 自动回退 ─────────────────────────────────────────────────────

def _read_revert_marker() -> Optional[dict]:
    try:
        return json.loads(REVERT_MARKER.read_text(encoding="utf-8"))
    except Exception:
        return None


def _recent(ts_iso: Optional[str], window_sec: int) -> bool:
    if not ts_iso:
        return False
    try:
        return (datetime.now().timestamp() - datetime.fromisoformat(ts_iso).timestamp()) < window_sec
    except Exception:
        return False


def try_auto_revert(reason: str) -> bool:
    """启动自检失败时调 · 尝试回退到 last-good 并 spawn 新 daemon。

    返 True = 已发起回退 (调用方应立刻退出·别再 build_app); False = 没回退 (继续启动·降级服务)。
    """
    if (os.environ.get("OPUS_NO_AUTO_REVERT") or "").strip() == "1":
        _log_event({"event": "auto_revert_skipped", "reason": "OPUS_NO_AUTO_REVERT=1", "trigger": reason})
        return False

    try:
        from workers.git_ops import last_good_ref
        lg = last_good_ref()
    except Exception:
        lg = None
    if not lg:
        _log_event({"event": "auto_revert_skipped", "reason": "no opus-last-good tag", "trigger": reason})
        return False

    head = _head_sha()
    if head and head == lg:
        # HEAD 就是 last-good · 回退到自己没意义 (天然防循环): last-good 本身就坏时落到这里 ·
        # 不再 revert · 交给 crash-loop 熔断进 SAFE MODE。
        _log_event({"event": "auto_revert_skipped", "reason": "HEAD already == last-good (target itself may be bad)",
                    "head": head, "last_good": lg, "trigger": reason})
        return False

    marker = _read_revert_marker()
    if marker and marker.get("from") == head and marker.get("to") == lg and _recent(marker.get("at"), REVERT_LOOP_GUARD_SEC):
        _log_event({"event": "auto_revert_skipped", "reason": "loop guard (just reverted this HEAD recently)",
                    "head": head, "last_good": lg, "trigger": reason})
        return False

    # stash 兜底 (不丢未提交改动) → reset --hard last-good
    rc_dirty, dirty, _ = _git(["status", "--porcelain"], timeout=10)
    if rc_dirty == 0 and dirty.strip():
        _git(["stash", "push", "-u", "-m", f"auto_revert {_now_iso()}"], timeout=30)
    rc_reset, _, reset_err = _git(["reset", "--hard", lg], timeout=30)
    if rc_reset != 0:
        _log_event({"event": "auto_revert_failed", "reason": f"git reset failed: {reset_err.strip()[:160]}",
                    "head": head, "last_good": lg, "trigger": reason})
        return False

    try:
        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        REVERT_MARKER.write_text(json.dumps(
            {"from": head, "to": lg, "at": _now_iso(), "reason": reason}, ensure_ascii=False, indent=2),
            encoding="utf-8")
    except Exception:
        pass
    _log_event({"event": "auto_revert", "from": head, "to": lg, "trigger": reason})
    print(f"[boot_health] ⛑️  启动自检失败 · 已自动回退 {head} -> last-good {lg} · 即将 spawn 新 daemon", flush=True)
    print(f"[boot_health]     触发原因: {reason}", flush=True)

    _spawn_replacement_and_exit()
    return True


def _spawn_replacement_and_exit() -> None:
    """reset 到 last-good 后 · spawn 一个新 daemon 接管 (takeover) · 然后本进程优雅退出。

    跟 request_restart / /restart-daemon 同一套 takeover spawn: 子进程带
    OPUS_DAEMON_TAKEOVER_PID env · acquire_pid_lock 会等本进程 (parent) 死再 acquire。
    """
    try:
        from agent_tools._subprocess_helper import detached_kwargs, pythonw_path
        argv = [pythonw_path()] + sys.argv
        env = os.environ.copy()
        env["OPUS_DAEMON_TAKEOVER_PID"] = str(os.getpid())
        out_f = open(ROOT / "data" / "daemon.out", "ab")
        err_f = open(ROOT / "data" / "daemon.err", "ab")
        subprocess.Popen(argv, close_fds=False, stdin=subprocess.DEVNULL,
                         stdout=out_f, stderr=err_f, cwd=str(ROOT), env=env, **detached_kwargs())
        time.sleep(1.0)
    except Exception as e:
        print(f"[boot_health] spawn 替代 daemon 失败 (BRO 需手动 start.bat): {type(e).__name__}: {e}", flush=True)

    try:
        from workers.daemon_lifecycle import mark_graceful_shutdown
        mark_graceful_shutdown("auto_revert_reexec")
    except Exception:
        pass
    os._exit(0)


# ── A1 · 健康存活后前移 last-good ─────────────────────────────────────

def schedule_last_good_advance(grace_sec: int = LAST_GOOD_GRACE_SEC, safe_mode: bool = False) -> None:
    """后台计时线程: daemon 撑过 grace_sec 且仍健康 · 把当前(启动时) master HEAD 前移成 last-good。

    若进程在窗口内崩 · 这个 daemon 线程随进程消失 · tag 不前移 (这正是我们要的: 崩的版本不配当 known-good)。
    safe_mode 下不前移 (崩溃循环中·别把可疑版本标成 good)。
    """
    if safe_mode:
        return
    boot_head = _head_sha()
    if not boot_head or not _on_master():
        return  # 不在 master / 拿不到 HEAD · 不碰 last-good

    def _worker():
        time.sleep(grace_sec)
        # 撑过窗口了 (线程还活=进程还活)。 提级前再确认: 仍在 master · HEAD 没变 · 前端没坏。
        if not _on_master():
            return
        if _head_sha() != boot_head:
            return  # 窗口内 HEAD 变了 (又 commit 了) · 让下次 boot 的计时器去提级
        ok, _msg = preflight_health()
        if not ok:
            _log_event({"event": "last_good_advance_skipped", "reason": "frontend unhealthy at promote time",
                        "head": boot_head})
            return
        try:
            from workers.git_ops import tag_last_good
            tg = tag_last_good(require_master=True)
            if tg.get("tagged"):
                _log_event({"event": "last_good_advanced", "ref": tg.get("sha"),
                            "grace_sec": grace_sec, "note": "survived grace window healthy"})
                print(f"[boot_health] ✅ 撑过 {grace_sec}s 且自检健康 · last-good 前移到 {tg.get('sha')}", flush=True)
        except Exception as e:
            _log_event({"event": "last_good_advance_error", "error": f"{type(e).__name__}: {e}"})

    threading.Thread(target=_worker, daemon=True, name="opus-lastgood-advance").start()
