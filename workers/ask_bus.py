"""workers/ask_bus.py

「在对话里问一句、等人点一下」的通道 —— ask_user 工具的底座。

它跟 confirm 闸是**两件事**，只共用同一套管道（阻塞等待 / 超时 / SSE 事件）：

    confirm   问「要不要让我执行这个」  → 答案是 批准 / 拒绝 / 信任
    ask       问「你要哪个」            → 答案是 第几个选项

为什么必须分家（2026-09-10 BRO 拍板 ·共用管道·分开语义）：

1. **信任机制会静默吃掉提问**。审批卡上有「信任 30min / 24h / 永久」。
   ask_user 要是蹭上这套，用户手一滑点了「永久信任」→ 这工具以后**再也不弹卡**·
   直接静默过去。不报错、不崩、日志干净，只在某天发现"怎么不问了"。

2. **信任 flow 里 CONFIRM 会被直接放行**（daemon_api.py:714-720：
   `if rank == 2 and trusted_fid: return "go"`）。ask_user 走同一条路的话，
   跑 flow 时它会被静默跳过 —— 问都不问就往下跑。

3. 审批卡的语义是「风险 / 规避 / 批准」，提问没有"风险"这回事，
   硬塞就要在后端伪造字段、前端再特判过滤，往后每改一次审批都要回头想会不会碰坏提问。

怎么接线：
    daemon_api 在每个**有前台 SSE** 的 turn 上调一次 set_ask_channel(...)·
    工具层只管 ask_blocking(...)。拿不到通道（后台续场 / 定时任务 / 无人值守）
    时**快速失败**，绝不假等 —— 那种 turn 里问了也没人看得见。
"""
from __future__ import annotations

import contextvars
from typing import Callable, Optional, Sequence

__all__ = [
    "AskUnavailable",
    "AskAborted",
    "ask_blocking",
    "clear_ask_channel",
    "set_ask_channel",
]


class AskUnavailable(RuntimeError):
    """当前 turn 没有前台 SSE —— 问了也没人看得见（后台续场 / 定时任务）。"""


class AskAborted(RuntimeError):
    """用户在等待期间点了停止。"""


_ASK_CHANNEL: contextvars.ContextVar[Optional[Callable]] = contextvars.ContextVar(
    "ask_channel", default=None
)


def set_ask_channel(fn: Optional[Callable]) -> None:
    """装一条通道。fn(question, options, timeout) -> dict · 由 daemon_api 提供。"""
    _ASK_CHANNEL.set(fn)


def clear_ask_channel() -> None:
    """turn 结束时拆掉 —— 别让下个 turn 蹭到上一条已死的通道。"""
    _ASK_CHANNEL.set(None)


def has_ask_channel() -> bool:
    return _ASK_CHANNEL.get() is not None


def ask_blocking(
    question: str,
    options: Optional[Sequence[str]] = None,
    timeout: int = 0,
) -> dict:
    """在对话里问一句 · 阻塞等回答。

    返回：{"answered": bool, "choice": str, "index": int, "reason": str}
      - answered=False = 超时 / 被跳过 → 调用方**按"没回答"继续**，不要当成拒绝
      - choice 是被选中的选项原文（自由回答时是用户打的字）
    """
    fn = _ASK_CHANNEL.get()
    if fn is None:
        raise AskUnavailable(
            "当前 turn 没有前台 SSE（后台续场 / 定时任务里）· 提问没人看得见。"
            " → 改成把选项直接写进回复里问，或留给用户在前台跑一次。"
        )
    return fn(str(question or ""), [str(o) for o in (options or [])], int(timeout or 0))
