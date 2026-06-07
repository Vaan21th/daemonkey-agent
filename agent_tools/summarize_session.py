"""
agent_tools/summarize_session.py
================================

手动触发的 session 摘要工具——thin wrapper，核心逻辑在 workers/memory_compression.py。

wish-58af621e 重构（）：
  原来的 _safe_split_index / _generate_summary / _stringify_message / _is_tool_pair_msg
  都搬到了 workers/memory_compression.py。
  这个工具现在只做：args 解析 → 调 auto_compress() → 原地替换 RUNTIME.messages → 组装 ToolResult。
"""

from __future__ import annotations

from daemon_runtime import RUNTIME
from workers.memory_compression import (
    DEFAULT_KEEP_LAST_N,
    MIN_MESSAGES_TO_COMPRESS,
    auto_compress,
)

from . import TIER_AUTO, ToolResult, ToolSpec, register_tool


def _summarize(args: dict) -> str:
    keep_n = int(args.get("keep_last_n") or DEFAULT_KEEP_LAST_N)
    return f"summarize_session  keep_last_n={keep_n}  (压缩当前会话历史，省 token)"


def _run(args: dict) -> ToolResult:
    keep_last_n = int(args.get("keep_last_n") or DEFAULT_KEEP_LAST_N)
    keep_last_n = max(2, min(keep_last_n, 50))

    messages = RUNTIME.messages
    if not messages:
        return ToolResult(
            ok=False, output="",
            error="RUNTIME.messages 为空——daemon 没注入或会话刚开始",
        )

    n_before = len(messages)
    if n_before < MIN_MESSAGES_TO_COMPRESS:
        return ToolResult(
            ok=True,
            output=f"会话才 {n_before} 条，不足以压缩（阈值 {MIN_MESSAGES_TO_COMPRESS}）。当前完整保留。",
        )

    new_messages = auto_compress(
        messages,
        client=RUNTIME.client,
        model=RUNTIME.model,
        provider=RUNTIME.provider,
        keep_last_n=keep_last_n,
        model_id=RUNTIME.model,
    )

    # auto_compress 返回新列表 → 原地替换 RUNTIME.messages
    if new_messages is not messages:
        n_after = len(new_messages)
        saved = n_before - n_after
        RUNTIME.messages.clear()
        RUNTIME.messages.extend(new_messages)

        # 从第一条 summary 消息里截预览
        preview = ""
        if new_messages and "summary" in (new_messages[0].get("content", "") or ""):
            preview = (new_messages[0]["content"] or "")[:500]

        return ToolResult(
            ok=True,
            output=(
                f"summarize_session 完成\n"
                f"  压缩前: {n_before} 条消息\n"
                f"  压缩后: {n_after} 条\n"
                f"  节省:   {saved} 条（完整历史仍在 sessions/<id>.jsonl）\n"
                f"\n摘要预览：\n{preview}{'...' if len(preview) >= 500 else ''}"
            ),
        )
    else:
        return ToolResult(
            ok=True,
            output=f"找不到安全切割点。维持原状（{n_before} 条消息）。",
        )


SPEC = ToolSpec(
    name="summarize_session",
    description=(
        "Compress earlier messages in the current session into a single summary, "
        "to free up context window for long sessions. Use when:\n"
        "  - You notice messages are >30 turns and input tokens climbing\n"
        "  - 用户 says 'summarize' / 'compress' / 'free up context'\n"
        "  - You feel earlier context is no longer relevant to current work\n"
        "Keeps the last N messages (default 8) intact, summarizes everything before. "
        "Disk session file is NOT modified—full history stays for later /load. "
        "Tier AUTO (in-memory only, no side effects)."
    ),
    tier=TIER_AUTO,
    input_schema={
        "type": "object",
        "properties": {
            "keep_last_n": {
                "type": "integer",
                "description": "How many recent messages to keep uncompressed (2-50, default 8)",
            },
        },
    },
    run=_run,
    summarize=_summarize,
)


register_tool(SPEC)
