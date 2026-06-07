"""
daemon 内部 git 操作串行化 · 防多 session 同时动 git 仓库打架

一把 threading.Lock · 全 daemon 单例。
所有 git 子进程调用前包 `with daemon_git_lock(...)` 拿锁排队。

 V · wish-125d4e4b · 2026-05-27
"""

import threading
from contextlib import contextmanager

_DAEMON_GIT_LOCK = threading.Lock()

# ── public ──────────────────────────────────────────

@contextmanager
def daemon_git_lock(label: str = "", timeout: float = 30.0):
    """跨 session git 操作串行化 · 同一时刻只让一根毛动 git

    Args:
        label: 谁在拿锁 (例 "shell_exec:git checkout -b" / "wish_update:create_branch")
        timeout: 最多等多少秒 · 超时抛 RuntimeError (默认 30)

    Raises:
        RuntimeError: 超时 · 说明有 git 操作卡死或锁泄漏
    """
    acquired = _DAEMON_GIT_LOCK.acquire(timeout=timeout)
    if not acquired:
        raise RuntimeError(
            f"git 锁超时 ({timeout}s) · {label or 'unknown'}"
            f" — 上一个 git 操作可能卡死或锁未释放"
        )
    try:
        yield
    finally:
        _DAEMON_GIT_LOCK.release()
