"""本轮 abort 传给正在跑的子进程。tool_loop 设置，shell/python_exec 读取。"""
from __future__ import annotations

import contextvars
from typing import Callable

_cancel_cv: contextvars.ContextVar[Callable[[], bool] | None] = contextvars.ContextVar(
    "tool_cancel_check", default=None
)


def set_cancel_check(fn: Callable[[], bool] | None) -> contextvars.Token:
    return _cancel_cv.set(fn)


def reset_cancel_check(token: contextvars.Token) -> None:
    _cancel_cv.reset(token)


def cancelled() -> bool:
    fn = _cancel_cv.get()
    try:
        return bool(fn and fn())
    except Exception:
        return False
