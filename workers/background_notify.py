"""workers/background_notify.py · 后台任务钩子唤醒 (wish-68f35226)

任务完成/失败/阻塞 → 合并窗口内 → 触发一个后台 LLM turn 唤醒 daemon。
daemon 被唤醒后自己决策: 继续下一步 / 处理失败 / 该告诉用户才推飞书微信。

设计定案 (2026-08-13):
- 无账本: 钩子唤醒直接替代持久化 (任务状态当场交给唤醒 turn · 不需要存)
- 成功/失败/阻塞都唤醒 · 同时完成合并成一次 · 不同时完成逐个唤醒 (3s 合并窗口)
- 唤醒走 proactive 专用会话 · 不混进用户工作对话 · 不查用户静默 (内部处理非打扰)

配套:
- run_flow (flow_runner) 子线程跑完 → task_done
- run_background_process() 起 Popen 长任务 → 线程 wait + task_done
"""

from __future__ import annotations

import logging
import subprocess
import threading
from typing import Optional

logger = logging.getLogger(__name__)

_WAKE_WINDOW_SEC = 3.0      # 合并窗口: 窗口内完成的任务合并成一次唤醒
_WAKE_MAX_ITEMS = 10        # 单次唤醒最多带几条 · 防消息爆炸
_WAKE_MAX_TOKENS = 600      # 唤醒 turn 输出额度 · 状态感知不需要长输出

_wake_lock = threading.Lock()
_wake_timer: Optional[threading.Timer] = None
_wake_pending: list[dict] = []
_wake_busy = False          # 上次唤醒 turn 还在跑 · 防并发唤醒 (审查 P2-1)


def task_done(name: str, *, status: str, summary: str = "") -> None:
    """任务结束钩子 (Argo onExit) · 触发唤醒 (合并窗口 · 同时合并 · 不同时逐个)。

    status: success / failed / blocked / cancelled。
    3s 窗口内完成的多个任务合并成一次后台唤醒 · 窗口外每个任务各唤醒一次。
    """
    _schedule_wake({"name": name, "status": status, "summary": (summary or "")[:200]})


def _schedule_wake(rec: dict) -> None:
    global _wake_timer, _wake_pending
    with _wake_lock:
        _wake_pending.append(rec)
        if _wake_timer is None:
            _wake_timer = threading.Timer(_WAKE_WINDOW_SEC, _fire_wake)
            _wake_timer.daemon = True
            _wake_timer.start()


def _fire_wake() -> None:
    global _wake_timer, _wake_pending, _wake_busy
    with _wake_lock:
        if _wake_busy:
            return  # 上次唤醒还在跑 · 留给收尾补发 (审查 P2-1)
        pending = list(_wake_pending)
        _wake_pending = []
        _wake_timer = None
    if not pending:
        return
    _wake_busy = True
    try:
        _wake_daemon(pending)
    finally:
        _wake_busy = False
        # 收尾补发: 唤醒 turn 期间新到的任务 · 再排一轮
        with _wake_lock:
            if _wake_pending and _wake_timer is None:
                _wake_timer = threading.Timer(_WAKE_WINDOW_SEC, _fire_wake)
                _wake_timer.daemon = True
                _wake_timer.start()


def _wake_daemon(pending: list[dict]) -> None:
    """合并成一条消息 · 后台 turn 唤醒 daemon。 全 try 静默 (唤醒失败不影响任务)。"""
    lines = ["【后台任务状态更新】"]
    for rec in pending[:_WAKE_MAX_ITEMS]:
        icon = {"success": "✅", "failed": "❌", "blocked": "⛔", "cancelled": "⊘"}.get(
            rec.get("status", ""), "·"
        )
        lines.append(f"- {icon} {rec.get('name', '?')} [{rec.get('status', '?')}] · {rec.get('summary', '')[:100]}")
    if len(pending) > _WAKE_MAX_ITEMS:
        lines.append(f"- …还有 {len(pending) - _WAKE_MAX_ITEMS} 条")
    lines.append("你自己判断: 继续下一步 / 处理失败 / 该告诉用户才推飞书微信")
    message = "\n".join(lines)
    try:
        from workers.resume_runner import _wait_runtime_ready
        if not _wait_runtime_ready():
            logger.warning("[bg_notify] RUNTIME 未就绪 · 本次唤醒跳过 (任务状态不丢·下次注入兜底)")
            return
        from workers.proactive_call import _proactive_session, _run_bg_turn
        sid = _proactive_session()
        _run_bg_turn(message, sid, reason=f"bg-notify:{len(pending)}", max_tokens=_WAKE_MAX_TOKENS)
    except Exception as e:
        logger.warning("[bg_notify] 唤醒失败 (不影响任务): %s", e)


def run_background_process(command, name: str, *, timeout: Optional[float] = None,
                           cwd: Optional[str] = None) -> None:
    """起后台进程 · 完成/超时/异常时 task_done 触发唤醒 (治 08-13 评测失联坑)。

    command: list (argv) 或 str (经 shell)。 空命令 → 直接 failed 唤醒。
    timeout: 可选墙钟上限 (秒) · 超时 kill 并记 failed (不传 = 无限等·任务该跑完就跑完)。
    局限: 宿主 daemon 退出时子进程可能仍存活 (进程级失联 · 不在本模块处理)。
    """
    if isinstance(command, str):
        empty = not command.strip()
    else:
        empty = not command
    if empty:
        task_done(name, status="failed", summary="空命令")
        return

    def _wait() -> None:
        try:
            from agent_tools._subprocess_helper import no_window_kwargs
            kw = no_window_kwargs()
        except Exception:
            kw = {}
        if cwd:
            kw["cwd"] = cwd
        proc = None
        try:
            if isinstance(command, str):
                proc = subprocess.Popen(command, shell=True, **kw)
            else:
                proc = subprocess.Popen(list(command), **kw)
            rc = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            # 超时 kill · Windows 用 taskkill /T /F 杀进程树 (shell=True 只杀 shell 不够 · 审查 P2-2)
            try:
                import sys
                if sys.platform == "win32":
                    subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                                   capture_output=True, timeout=10)
                else:
                    proc.kill()
            except Exception:
                pass
            task_done(name, status="failed", summary=f"超时 ({timeout}s) 已 kill 进程树")
            return
        except Exception as e:
            task_done(name, status="failed", summary=f"{type(e).__name__}: {e}")
            return
        task_done(name, status="success" if rc == 0 else "failed", summary=f"exit={rc}")

    threading.Thread(target=_wait, daemon=True, name=f"bg-{name[:20]}").start()
