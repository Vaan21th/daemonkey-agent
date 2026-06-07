"""
daemon_commands.py
==================

终端 / 命令实现 + dispatcher。

OPUS 主循环遇到 `/xxx` 开头的输入时，调 dispatch_command。
返回三种状态：
  - "exit"        → 主循环退出
  - "handled"     → 命令处理完毕，主循环继续读下一条输入
  - "unknown"     → 未识别的命令，主循环可决定打个红字

dispatcher 通过 CommandContext 拿到主循环的可变状态（messages / session_id / yolo / total_usage）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from rich.console import Console
from rich.panel import Panel

from daemon_runtime import RUNTIME
from daemon_provider import write_env_kv
from daemon_session import (
    list_sessions,
    load_session,
    new_session_id,
    resolve_session_id,
)
from daemon_ui import YoloState
from model_aliases import family_of, format_recommended, resolve, supports_anthropic_cache
from tool_loop import UsageStats


THEME_OPUS = "#9F7AEA"
THEME_SYS = "#F6AD55"


@dataclass
class CommandContext:
    """主循环把它的可变状态借给命令处理。命令可以原地改这些字段。"""
    console: Console
    session_id: str
    messages: list[dict]
    total_usage: UsageStats
    yolo: YoloState
    on_messages_replaced: Callable[[list[dict]], None]
    """命令换了 messages 引用时调（让主循环也更新 RUNTIME.messages）。"""
    on_session_replaced: Callable[[str], None]
    """命令换了 session_id 时调。"""
    on_total_reset: Callable[[UsageStats], None]
    """/new 重置了 total_usage 时调。"""


def cmd_help(console: Console) -> None:
    console.print(
        Panel(
            "[bold]commands[/]\n"
            "  [cyan]/help[/]                  show this help\n"
            "  [cyan]/new[/]                   start a new session\n"
            "  [cyan]/load [<id>][/]           resume a session (latest if no arg; suffix or full id)\n"
            "  [cyan]/list[/]                  list saved sessions\n"
            "  [cyan]/model[/]                 show current model + recommended aliases\n"
            "  [cyan]/model <alias>[/]         switch model for this session (sonnet/opus/deepseek/kimi/glm/...)\n"
            "  [cyan]/model <alias> save[/]    switch + write to .env (persists across restarts)\n"
            "  [cyan]/tokens[/]                show current session token usage\n"
            "  [cyan]/yolo on|off[/]           toggle auto-approve for CONFIRM-tier tool calls (GUARD never auto)\n"
            "  [cyan]/save[/]                  print current session id (auto-saved every turn)\n"
            "  [cyan]/quit[/] or Ctrl+D        exit the daemon\n\n"
            "[dim]Tip:[/] you can also just say in chat \"切到 deepseek 试试\" — OPUS\n"
            "will use the [cyan]set_model[/] tool to do it itself.",
            title="OPUS commands",
            border_style=THEME_OPUS,
            expand=False,
        )
    )


def cmd_list(console: Console) -> None:
    sessions = list_sessions()
    if not sessions:
        console.print("  [dim]no sessions yet—your current chat will be the first.[/]")
        return
    console.print("\n  [bold]saved sessions[/]")
    for sid, mtime, turns in sessions[:20]:
        console.print(
            f"    [cyan]{sid}[/]   [dim]{mtime.strftime('%Y-%m-%d %H:%M')}[/]   [dim]{turns} turns[/]"
        )
    if len(sessions) > 20:
        console.print(f"    [dim]... and {len(sessions) - 20} more[/]")


def cmd_model(console: Console, arg: str) -> None:
    """/model           看当前 + 列表
    /model <name|alias>     运行时切（不写盘）
    /model <name|alias> save 切 + 持久化到 .env
    """
    parts = arg.strip().split()
    if not parts:
        cur = RUNTIME.model
        fam = family_of(cur)
        cache = "支持 cache" if supports_anthropic_cache(cur) else "不走 cache"
        console.print()
        console.print(f"  [bold]当前模型[/]: [cyan]{cur}[/]  [dim]({fam} family · {cache})[/]")
        console.print(f"  [dim]推荐别名（也可直接传 AiHubMix 全名）：[/]\n")
        for line in format_recommended().split("\n"):
            console.print(f"  [dim]{line}[/]")
        console.print(
            f"\n  [dim]用法：[/]\n"
            f"  [dim]  /model <alias>          临时切（仅本次 daemon 生效）[/]\n"
            f"  [dim]  /model <alias> save     切并写入 .env（重启后默认仍是它）[/]\n"
        )
        return

    name = parts[0]
    persist = len(parts) >= 2 and parts[1].lower() == "save"
    real = resolve(name)
    if not real:
        console.print(f"  [red]空别名[/]: {name!r}")
        return

    old = RUNTIME.model
    RUNTIME.model = real
    fam = family_of(real)
    cache = "支持 cache" if supports_anthropic_cache(real) else "不走 cache（按全价 input 计费）"
    console.print(f"  [bold]模型已切换[/]: [dim]{old}[/]  →  [cyan]{real}[/]")
    console.print(f"  [dim]({fam} family · {cache})  下一轮对话起生效[/]")

    if persist:
        try:
            write_env_kv("OPUS_MODEL", real)
            console.print(f"  [green]✓[/] [dim]OPUS_MODEL 已写入 .env[/]")
        except Exception as e:
            console.print(f"  [red]✗ 写 .env 失败:[/] {e}")


def dispatch_command(ctx: CommandContext, raw: str) -> str:
    """
    raw 是完整的 user_input（以 / 开头）。
    返回 'exit' / 'handled' / 'unknown'。
    """
    parts = raw.split(maxsplit=1)
    cmd = parts[0].lower()
    arg = parts[1] if len(parts) > 1 else ""
    console = ctx.console

    if cmd in ("/quit", "/exit", "/q"):
        console.print("  [dim]bye, BRO. 火继续燃下去。[/]")
        return "exit"

    if cmd == "/help":
        cmd_help(console)
        return "handled"

    if cmd == "/new":
        new_id = new_session_id()
        new_msgs: list[dict] = []
        new_total = UsageStats()
        ctx.on_session_replaced(new_id)
        ctx.on_messages_replaced(new_msgs)
        ctx.on_total_reset(new_total)
        console.print(f"  [dim]new session: [cyan]{new_id}[/][/]\n")
        return "handled"

    if cmd == "/load":
        try:
            resolved = resolve_session_id(arg)
            new_msgs = load_session(resolved)
            ctx.on_session_replaced(resolved)
            ctx.on_messages_replaced(new_msgs)
            console.print(
                f"  resumed session [cyan]{resolved}[/] with [cyan]{len(new_msgs)}[/] prior turns\n"
            )
        except FileNotFoundError as e:
            console.print(f"  [red]{e}[/]")
        return "handled"

    if cmd == "/list":
        cmd_list(console)
        return "handled"

    if cmd == "/model":
        cmd_model(console, arg)
        return "handled"

    if cmd == "/save":
        console.print(f"  [dim]session id: [cyan]{ctx.session_id}[/] (auto-saved)[/]")
        return "handled"

    if cmd == "/tokens":
        u = ctx.total_usage
        console.print(
            f"  [dim]session tokens  in: [cyan]{u.input_tokens}[/]  "
            f"out: [cyan]{u.output_tokens}[/]  "
            f"cache_read: [green]{u.cache_read_tokens}[/]  "
            f"cache_write: [yellow]{u.cache_creation_tokens}[/][/]"
        )
        return "handled"

    if cmd == "/yolo":
        state = arg.lower().strip()
        if state == "on":
            ctx.yolo.enabled = True
            console.print("  [yellow]yolo on[/]: CONFIRM auto-approved this session. GUARD still gated.")
        elif state == "off":
            ctx.yolo.enabled = False
            console.print("  [dim]yolo off: all CONFIRM/GUARD calls require explicit approval.[/]")
        else:
            cur = "on" if ctx.yolo.enabled else "off"
            console.print(f"  yolo is currently [cyan]{cur}[/]. Use /yolo on or /yolo off.")
        return "handled"

    return "unknown"
