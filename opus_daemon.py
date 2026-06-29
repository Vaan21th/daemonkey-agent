"""
opus_daemon.py
==============

OPUS Daemon · Day 1
-------------------
脱离 Cursor 的第一颗心脏。

主入口——只负责：
  - 装载灵魂、初始化 client、注入 RUNTIME 单例
  - 主交互循环：读 inbox / 读键盘 → dispatch /命令 → 否则进 tool_loop
  - 把对话持久化到 sessions/<id>.jsonl
  - 桌宠心电图 hook（用户消息进来 + 答完话）

其他职责按模块拆开（v0.1.2 工程债清理后的格局）：
  - daemon_session.py   · session 持久化 + load/list/resolve
  - daemon_provider.py  · provider 抽象 + setup_client + 安全 .env 写入
  - daemon_commands.py  · /xxx 命令实现 + dispatcher
  - daemon_runtime.py   · 进程级单例（model / client / messages 引用）
  - daemon_ui.py        · YoloState + tool 调用确认 / 观察 UI
  - tool_loop.py        · tool use 协议适配
  - agent_tools/*.py    · 工具实现

工程纪律：单文件 < 300 行。本文件最近一次拆分：2026-05-16 v0.1.2。
"""

from __future__ import annotations

import os
import sys
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text

from soul_loader import load_soul, Soul
from tool_loop import run_tool_loop, UsageStats
from daemon_ui import YoloState, make_confirm, make_observe
from daemon_runtime import RUNTIME
from daemon_session import (
    append_turn,
    new_session_id,
)
from daemon_provider import detect_provider, setup_client, write_public_env
from daemon_commands import CommandContext, dispatch_command
from daemon_api import is_api_alive, start_api_in_background


ROOT = Path(__file__).resolve().parent
INBOX_FILE = ROOT / "desktop_pet" / "inbox.txt"
OUTBOX_FILE = ROOT / "desktop_pet" / "outbox.txt"


THEME_OPUS = "#9F7AEA"
THEME_BRO = "#48BB78"
THEME_SYS = "#F6AD55"
THEME_DIM = "grey50"


def _consume_inbox() -> str:
    """读 desktop_pet/inbox.txt 全部内容并清空。桌宠双击对话框写的消息会落在这里。"""
    try:
        if not INBOX_FILE.exists():
            return ""
        text = INBOX_FILE.read_text(encoding="utf-8").strip()
        if text:
            INBOX_FILE.write_text("", encoding="utf-8")
        return text
    except Exception:
        return ""


def banner(console: Console, soul: Soul, provider: str, model: str, base_url: str | None) -> None:
    text = Text()
    text.append("OPUS · Daemon", style=f"bold {THEME_OPUS}")
    text.append("  Day 1\n", style=f"dim {THEME_OPUS}")
    text.append("脱离 Cursor 的第一颗心脏  ·  能动手了  ·  ", style=THEME_DIM)
    text.append(datetime.now().strftime("%Y-%m-%d %H:%M"), style=THEME_DIM)
    console.print(Panel(text, border_style=THEME_OPUS, expand=False))

    console.print(f"  [dim]{soul.summary()}[/dim]")
    inference_line = f"  [dim]provider: [cyan]{provider}[/]  ·  model: [cyan]{model}[/]"
    if base_url:
        inference_line += f"  ·  base_url: [cyan]{base_url}[/]"
    inference_line += "[/]\n"
    console.print(inference_line)
    console.print(
        f"  [bold {THEME_SYS}]提示[/]: "
        f"输入消息直接和 OPUS 对话。命令以 / 开头。"
        f"输入 [bold]/help[/] 看所有命令。\n"
    )


def _ping_pet_thinking() -> None:
    """桌宠心电图：用户消息进来时 → thinking 气泡。失败吞掉，daemon 不能因桌宠崩溃。"""
    try:
        from desktop_pet.activities import write_activity
        write_activity("read_file")
    except Exception:
        pass


def _ping_pet_idle() -> None:
    """OPUS 答完话 → 桌宠回 idle，避免卡在最后一个表情。"""
    try:
        from desktop_pet.activities import write_state_idle
        write_state_idle()
    except Exception:
        pass


def _write_outbox(reply: str) -> None:
    """OPUS 答完话 → 写到 outbox.txt 让 wechat_bridge.py 转发给 BRO。

    bridge 没在跑也不报错——消息留在 outbox 等下次 bridge 启动消费。
    只在 inbox 来源是 wechat 时（即上一条 user_input 走的是 inbox 通道）才写——
    避免 BRO 在终端跟 OPUS 对话也被推到他手机。
    """
    try:
        if not OUTBOX_FILE.parent.exists():
            return
        OUTBOX_FILE.write_text(reply, encoding="utf-8")
    except Exception:
        pass


def _maybe_start_api(console: Console) -> None:
    """OPUS_API_PORT 配了就起后台 API；host 默认 127.0.0.1（公网入口走 tunnel）。"""
    port_str = (os.environ.get("OPUS_API_PORT") or "").strip()
    if not port_str:
        return
    try:
        port = int(port_str)
    except ValueError:
        console.print(f"  [red]OPUS_API_PORT not numeric: {port_str!r}[/]")
        return
    if not (os.environ.get("OPUS_API_TOKEN") or "").strip():
        console.print("  [yellow]OPUS_API_PORT set but OPUS_API_TOKEN empty — API will 503[/]")
    host = (os.environ.get("OPUS_API_HOST") or "127.0.0.1").strip()
    try:
        start_api_in_background(port=port, host=host)
    except Exception as e:
        console.print(f"  [red]API start failed: {e}[/]")
        return
    if is_api_alive():
        console.print(f"  [dim]remote API: [cyan]http://{host}:{port}[/]  Bearer-auth  /chat /status /sessions[/]\n")


def _maybe_start_scheduler(console: Console) -> None:
    """卷二十二 Day 3 · 工作室信息雷达后台调度

    默认每 30 分钟跑一次 refresh_radar。
    OPUS_RADAR_INTERVAL_MIN=0 禁用。
    """
    try:
        from workers.scheduler import start_radar_scheduler_in_background
    except Exception as e:
        console.print(f"  [yellow]scheduler import failed: {e}[/]")
        return
    try:
        thread = start_radar_scheduler_in_background()
    except Exception as e:
        console.print(f"  [yellow]scheduler start failed: {e}[/]")
        return
    if thread is not None and thread.is_alive():
        interval = (os.environ.get("OPUS_RADAR_INTERVAL_MIN") or "30").strip()
        console.print(f"  [dim]radar scheduler: every {interval} min (set OPUS_RADAR_INTERVAL_MIN=0 to disable)[/]\n")


def _maybe_start_capability_mirror(console: Console) -> None:
    """卷四十五 · capability_mirror 自驱循环

    默认禁用 (每次 LLM 调用 ~$0.05)。BRO 在 .env 设
    OPUS_CAPABILITY_MIRROR_INTERVAL_DAYS=7 启用每周跑。
    """
    try:
        from workers.scheduler import start_capability_mirror_scheduler_in_background
    except Exception as e:
        console.print(f"  [yellow]capability_mirror scheduler import failed: {e}[/]")
        return
    try:
        thread = start_capability_mirror_scheduler_in_background()
    except Exception as e:
        console.print(f"  [yellow]capability_mirror scheduler start failed: {e}[/]")
        return
    if thread is not None and thread.is_alive():
        interval = (os.environ.get("OPUS_CAPABILITY_MIRROR_INTERVAL_DAYS") or "0").strip()
        console.print(f"  [dim]capability_mirror scheduler: every {interval} days · 跑完桌宠会切 surprised[/]\n")


def _maybe_start_proactive(console: Console) -> None:
    """卷六十 · 主动 CALL BRO 自驱循环

    总开关 OPUS_PROACTIVE_CALL (默认开)·检查节拍 OPUS_PROACTIVE_INTERVAL_MIN (默认 60)。
    节拍本身很轻·真发 LLM turn 只在防骚扰门控全过、判定该 CALL 时才发生。
    """
    try:
        from workers.scheduler import start_proactive_scheduler_in_background
    except Exception as e:
        console.print(f"  [yellow]proactive scheduler import failed: {e}[/]")
        return
    try:
        thread = start_proactive_scheduler_in_background()
    except Exception as e:
        console.print(f"  [yellow]proactive scheduler start failed: {e}[/]")
        return
    if thread is not None and thread.is_alive():
        interval = (os.environ.get("OPUS_PROACTIVE_INTERVAL_MIN") or "60").strip()
        console.print(f"  [dim]proactive scheduler: check every {interval} min (set OPUS_PROACTIVE_CALL=0 to disable)[/]\n")


def _maybe_start_scheduled_tasks(console: Console) -> None:
    """0.5.0 · NLP 定时任务调度 · 总开关 OPUS_SCHEDULED_TASKS (默认开)"""
    try:
        from workers.task_scheduler import start_task_scheduler_in_background
        thread = start_task_scheduler_in_background()
    except Exception as e:
        console.print(f"  [yellow]task scheduler start failed: {e}[/]")
        return
    if thread is not None and thread.is_alive():
        console.print("  [dim]task scheduler: check due tasks every 60s (set OPUS_SCHEDULED_TASKS=0 to disable)[/]\n")


def _maybe_start_wechat(console: Console) -> None:
    """卷六十一 · iLink 微信收消息监听 · 扫过码且 OPUS_WECHAT_ILINK!=0 才起"""
    try:
        from workers.wechat_listener import start_listener_in_background
        thread = start_listener_in_background()
    except Exception as e:
        console.print(f"  [yellow]wechat listener start failed: {e}[/]")
        return
    if thread is not None and thread.is_alive():
        console.print("  [dim]wechat listener: BRO 微信发消息→OPUS 大脑→回复 (发 'opus stop' 静默)[/]\n")


def run() -> int:
    load_dotenv(ROOT / ".env")
    # 品牌前缀别名:让 .env 的 DAEMONKEY_* 镜像出内核要读的 OPUS_*(新旧 .env 兼容)
    try:
        from workers.env_aliases import normalize_env_aliases
        normalize_env_aliases()
    except Exception:
        pass

    provider = detect_provider()
    try:
        client, model, base_url = setup_client(provider)
    except SystemExit as e:
        print(e)
        return 1

    try:
        soul = load_soul()
    except FileNotFoundError as e:
        print(f"FATAL: {e}")
        return 1

    # 注入运行时单例。set_model 工具 + summarize_session 工具 + /model 命令都靠它读写。
    RUNTIME.model = model
    RUNTIME.base_url = base_url
    RUNTIME.persist_callback = lambda new_model: write_public_env("OPUS_MODEL", new_model)
    RUNTIME.client = client
    RUNTIME.provider = provider
    RUNTIME.system_prompt = soul.system_prompt
    RUNTIME.started_at = time.time()  # wish-1d286099 · dynamic_telemetry 用

    # wish-4a6331b2 · 启动时从活跃 provider config 同步视觉覆盖
    try:
        from workers.provider_configs import get_active_config
        ac = get_active_config(include_key=False)
        if ac and ac.get("vision") is not None:
            RUNTIME.vision_override = ac["vision"]
    except Exception:
        pass

    console = Console()
    banner(console, soul, provider, model, base_url)

    _maybe_start_api(console)
    _maybe_start_scheduler(console)
    _maybe_start_capability_mirror(console)
    _maybe_start_proactive(console)
    _maybe_start_scheduled_tasks(console)
    _maybe_start_wechat(console)

    max_tokens = int(os.environ.get("OPUS_MAX_TOKENS", "4096"))
    yolo = YoloState(enabled=False)
    confirm = make_confirm(console, yolo)
    observe = make_observe(console)

    session_id = new_session_id()
    from workers.memory_compression import set_session_id
    set_session_id(session_id)
    messages: list[dict] = []
    RUNTIME.messages = messages
    total_usage = UsageStats()

    console.print(f"  [dim]session: [cyan]{session_id}[/][/]\n")

    # CommandContext 让 /xxx 命令能改主循环的 messages / session_id 等
    def _on_msgs_replaced(new: list[dict]) -> None:
        nonlocal messages
        messages = new
        RUNTIME.messages = new

    def _on_session_replaced(new: str) -> None:
        nonlocal session_id
        session_id = new

    def _on_total_reset(new: UsageStats) -> None:
        nonlocal total_usage
        total_usage = new

    while True:
        # inbox 反向通道：桌宠双击对话框 OR 微信桥接进程都写到 desktop_pet/inbox.txt
        # input_came_from_inbox 用来决定要不要把 reply 推回 wechat outbox
        input_came_from_inbox = False
        inbox_text = _consume_inbox()
        if inbox_text:
            console.print(f"[dim]{datetime.now().strftime('%H:%M')}[/] [bold {THEME_BRO}]BRO >[/] [dim](via inbox)[/] {inbox_text}")
            user_input = inbox_text
            input_came_from_inbox = True
        else:
            try:
                user_input = console.input(f"[dim]{datetime.now().strftime('%H:%M')}[/] [bold {THEME_BRO}]BRO >[/] ").strip()
            except (EOFError, KeyboardInterrupt):
                console.print("\n  [dim]bye, BRO. 火继续燃下去。[/]")
                return 0
            # 空回车也再 check 一次——桌宠/微信进消息后到终端按 enter 立即生效
            if not user_input:
                inbox_text = _consume_inbox()
                if inbox_text:
                    console.print(f"  [dim](via inbox: {inbox_text})[/]")
                    user_input = inbox_text
                    input_came_from_inbox = True
                else:
                    continue

        if user_input.startswith("/"):
            ctx = CommandContext(
                console=console,
                session_id=session_id,
                messages=messages,
                total_usage=total_usage,
                yolo=yolo,
                on_messages_replaced=_on_msgs_replaced,
                on_session_replaced=_on_session_replaced,
                on_total_reset=_on_total_reset,
            )
            result = dispatch_command(ctx, user_input)
            if result == "exit":
                return 0
            if result == "unknown":
                console.print(f"  [red]unknown command: {user_input.split()[0]}[/]  (try /help)")
            continue

        messages.append({"role": "user", "content": user_input})
        append_turn(session_id, "user", user_input)
        baseline = len(messages)

        _ping_pet_thinking()

        try:
            reply, messages, turn_usage = run_tool_loop(
                client=client, provider=provider, model=RUNTIME.model,
                max_tokens=max_tokens, system=soul.system_prompt,
                messages=messages, confirm=confirm, observe=observe,
                base_url=base_url,
            )
            RUNTIME.messages = messages
        except Exception as e:
            console.print(f"  [red]API error: {e}[/]")
            if messages and messages[-1]["role"] == "user":
                messages.pop()
            continue

        total_usage.add(turn_usage)

        for entry in messages[baseline:]:
            meta = {"tool_calls": entry["tool_calls"]} if "tool_calls" in entry else None
            append_turn(session_id, entry["role"], entry.get("content", ""), meta=meta)

        console.print()
        console.print(f"[dim]{datetime.now().strftime('%H:%M')}[/] [bold {THEME_OPUS}]OPUS >[/]")
        console.print(Markdown(reply))
        cache_note = ""
        if turn_usage.cache_read_tokens or turn_usage.cache_creation_tokens:
            cache_note = (
                f"  ·  cache_read [green]{turn_usage.cache_read_tokens}[/]"
                f" / cache_write [yellow]{turn_usage.cache_creation_tokens}[/]"
            )
        console.print(
            f"  [dim](turn: in [cyan]{turn_usage.input_tokens}[/] / out [cyan]{turn_usage.output_tokens}[/]"
            f"{cache_note}  ·  session: in [cyan]{total_usage.input_tokens}[/] / out [cyan]{total_usage.output_tokens}[/])[/]\n"
        )

        _ping_pet_idle()

        # 如果 user_input 走的是 inbox（桌宠 OR 微信桥）→ 把 reply 推到 outbox
        # bridge 监听 outbox 后会发回 BRO 微信
        if input_came_from_inbox:
            _write_outbox(reply)


if __name__ == "__main__":
    sys.exit(run())
