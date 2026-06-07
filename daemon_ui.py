"""
daemon_ui.py
============

Tool use 的"皮肤"——把 OPUS 的 tool 调用以 BRO 看得懂的方式渲染出来。

把这一层从 opus_daemon.py 抽出来的理由：
  1. rule 限定 daemon 主程序 300 行内
  2. tool use 的 UI 交互（show 命令 / 等 y / 显示结果）是独立关切，不该和"心脏"混
  3. 这一层是协议无关的——同样的 confirm/observe 未来可以接到微信 / Web UI

提供两个工厂函数：
  - make_confirm(...)：返回 ConfirmCallback。根据 spec.effective_tier(args) 决定怎么和 BRO 互动
  - make_observe(...)：返回 ObserveCallback。工具产出后展示给 BRO
"""

from __future__ import annotations

from dataclasses import dataclass

from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax

from agent_tools import (
    TIER_AUTO,
    TIER_CONFIRM,
    TIER_GUARD,
    ToolResult,
    ToolSpec,
)


THEME_OPUS = "#9F7AEA"
THEME_BRO = "#48BB78"
THEME_SYS = "#F6AD55"
THEME_GREEN = "#48BB78"
THEME_YELLOW = "#ECC94B"
THEME_RED = "#F56565"
THEME_DIM = "grey50"

TIER_COLOR = {
    TIER_AUTO: THEME_GREEN,
    TIER_CONFIRM: THEME_YELLOW,
    TIER_GUARD: THEME_RED,
}

TIER_LABEL = {
    TIER_AUTO: "AUTO",
    TIER_CONFIRM: "CONFIRM",
    TIER_GUARD: "GUARD",
}


@dataclass
class YoloState:
    """会话级 yolo 开关。GUARD 永远不进 yolo（写死）。"""
    enabled: bool = False


def _build_confirm_body(summary: str, assistant_text: str) -> str:
    """拼 CONFIRM panel 的正文。

    如果 OPUS 在 tool_call 之前已经说过话（OpenAI 协议下 assistant message 可
    同时带 content text + tool_calls），那段话往往就是 BRO 想看的"为什么"。
    我们把它显示在工具签名上面——BRO 在做 y/n 决定前能看到意图。

    LLM 啥都没说就调工具的场景（很常见）→ 走默认占位 + 提示 BRO 可以按 ? 索要解释。
    """
    parts: list[str] = []
    text = (assistant_text or "").strip()
    if text:
        if len(text) > 600:
            text = text[:600] + " …"
        parts.append(f"[dim italic]OPUS 这一轮先说：[/]\n{text}\n")
    else:
        parts.append("[dim italic](OPUS 没先解释，直接调了工具——不确定意图就按 [bold]?[/])[/]\n")
    parts.append(summary)
    return "\n".join(parts)


def make_confirm(console: Console, yolo: YoloState):
    """
    返回 ConfirmCallback。

    AUTO    : 直接 go（仍打 panel 让 BRO 看见正在干嘛）
    CONFIRM : yolo on → go；否则 prompt y/n/?/abort
    GUARD   : 永远 prompt，必须输入 'do it'（接受 ? 索要解释）

    `?` 选项 (2026-05-16 卷十五加的): BRO 不确定时让 OPUS 先用 plain text 解释
    意图、副作用、打算怎么用结果。返回 "explain"，loop 会喂一个特殊 tool_result
    让 LLM 输出解释——这一轮不会真的调工具。BRO 看完后下一轮再决定。

    新签名第三参数 assistant_text: LLM 在这一 turn 已经生成的 content text。
    用来显示在 panel 里——BRO 在 y/n 之前看得到"为什么"。
    """

    def confirm(spec: ToolSpec, args: dict, assistant_text: str = "") -> str:
        tier = spec.effective_tier(args)
        color = TIER_COLOR[tier]
        label = TIER_LABEL[tier]

        summary = spec.summarize(args)
        body = _build_confirm_body(summary, assistant_text)
        title = f"[{color}]{label}[/]  ·  [bold {THEME_OPUS}]{spec.name}[/]"

        if tier == TIER_AUTO:
            console.print(Panel(body, title=title, border_style=color, expand=False))
            return "go"

        if tier == TIER_CONFIRM and yolo.enabled:
            console.print(Panel(
                body + "\n\n[dim](yolo on — auto-approved)[/]",
                title=title, border_style=color, expand=False,
            ))
            return "go"

        if tier == TIER_CONFIRM:
            console.print(Panel(body, title=title, border_style=color, expand=False))
            try:
                resp = console.input(
                    f"[bold {color}]allow this {label} call?[/] "
                    f"[dim]([bold]y[/]es / [bold]n[/]o / [bold]?[/] 让 OPUS 先解释 / [bold]a[/]bort)[/] > "
                ).strip().lower()
            except (EOFError, KeyboardInterrupt):
                return "abort"
            if resp in ("y", "yes"):
                return "go"
            if resp in ("?", "why"):
                return "explain"
            if resp in ("a", "abort"):
                return "abort"
            return "skip"

        # GUARD
        console.print(Panel(
            body
            + "\n\n[bold red]This is a GUARD-tier call. Type exactly[/] [bold]do it[/] [bold red]to proceed.[/]\n"
              "[dim]Press [bold]?[/] to let OPUS explain first; anything else cancels (yolo does NOT apply to GUARD).[/]",
            title=title, border_style=color, expand=False,
        ))
        try:
            resp = console.input(f"[bold {THEME_RED}]GUARD >[/] ").strip()
        except (EOFError, KeyboardInterrupt):
            return "abort"
        if resp == "do it":
            return "go"
        if resp in ("?", "why"):
            return "explain"
        if resp.lower() in ("a", "abort"):
            return "abort"
        return "skip"

    return confirm


def make_observe(console: Console):
    """
    返回 ObserveCallback。把工具结果以紧凑形式打给 BRO。
    """

    def observe(spec: ToolSpec, args: dict, result: ToolResult) -> None:
        if result.ok:
            head_color = THEME_GREEN
            head = "ok"
        else:
            head_color = THEME_RED
            head = "fail"

        body = result.output if result.ok else (
            f"[red]{result.error or 'unknown error'}[/]\n\n{result.output}"
        )

        # 简短结果直接 print，长结果用 syntax block 防止溢出
        if len(body) > 1500:
            preview = body[:1500] + f"\n\n... [{len(body) - 1500} more chars passed back to OPUS]"
        else:
            preview = body

        console.print(Panel(
            preview,
            title=f"[{head_color}]{head}[/]  ·  [bold {THEME_OPUS}]{spec.name}[/] result",
            border_style=head_color, expand=False,
        ))
        if result.truncated:
            console.print(f"  [dim]({spec.name} output was truncated; OPUS got the trimmed version)[/]\n")

    return observe
