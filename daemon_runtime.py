"""
daemon_runtime.py
=================

Daemon 进程级单例。

为什么需要它——
  set_model 这种工具要在调用结束后**改变 daemon 的运行状态**（model 字段），
  下一轮对话 daemon 才能用新值。但 ToolSpec.run(args) 的签名是纯函数（只接受 args），
  没有"daemon context"参数。

折中：把可变的运行时状态放进一个进程级单例。
  - daemon 启动时 set RUNTIME.model / RUNTIME.base_url / RUNTIME.persist_callback
  - 主循环每轮发请求前从 RUNTIME 读最新 model
  - set_model 工具直接改 RUNTIME

不优雅，但比"给所有工具加 context 参数"动作小且直达目的。
未来如果要做多 daemon 实例共存，再做依赖注入。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


@dataclass
class DaemonRuntime:
    model: str = ""
    base_url: Optional[str] = None
    persist_callback: Optional[Callable[[str], None]] = None
    """把 model 写到 .env 的回调。daemon 启动时注入；set_model(persist=True) 时调用。"""

    client: Any = None
    """LLM client (openai.OpenAI / anthropic.Anthropic 实例)——summarize_session 等工具需要直接调 LLM。"""

    provider: str = ""
    """'openai' | 'anthropic'——决定怎么调 client。"""

    messages: list[dict] = field(default_factory=list)
    """当前会话 messages 的引用。summarize_session 工具会原地修改它。"""

    session_id: str = ""
    """当前 session id (chat handler 入口处 set)·让工具能拿到当前 session
    用于 request_restart 续场注入定位 session。 卷四十六 III · wish-ed5553d5 hookup."""

    system_prompt: str = ""
    """当前 system prompt（拼装好的）。summarize_session 调 LLM 时可能用到（一般传空让总结独立）。"""

    started_at: float = 0.0
    """daemon 进程启动时刻 (time.time())。wish-1d286099 · dynamic_telemetry 用。"""


RUNTIME = DaemonRuntime()


def reload_soul_into_runtime() -> Optional[int]:
    """卷五十四 · 同会话热重载灵魂 (Hermes '建立对你的深度模型' 那一环)。

    update_bro_note / update_self_evolution 写完画像/日记后调它 · 重建
    RUNTIME.system_prompt → daemon API 路径下一轮 chat 立刻带上刚写的画像
    (daemon_api 每轮从 RUNTIME.system_prompt 现拼)。 之前要等重启/手动 reload-soul。

    best-effort: 任何异常都吞掉 (终端 REPL 不读 RUNTIME · 跨进程时无副作用)。
    返回新 system_prompt 字符数 · 失败返 None。
    """
    try:
        from soul_loader import load_soul
        soul = load_soul()
        RUNTIME.system_prompt = soul.system_prompt
        return len(RUNTIME.system_prompt)
    except Exception:
        return None
