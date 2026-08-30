"""他开口要玩：往置物架摆一盒。他约的不当陪伴值。"""
from __future__ import annotations

from . import TIER_AUTO, ToolResult, ToolSpec, register_tool


def _summarize(args: dict) -> str:
    return f"invite_play → {args.get('toy') or '任一'}"


def _run(args: dict) -> ToolResult:
    from workers.she_gallery_feedback import inbox
    from workers.she_play import invite, pick_asked_toy, play_say, toy_word

    card = inbox()
    if card:
        if card.get("kind") == "game":
            return ToolResult(ok=True, output=play_say(already=True))
        return ToolResult(ok=True, output="架子上还有信，先别盖。让他看完信再约。不要在对话里开盘。")
    toy = pick_asked_toy(args.get("toy") or "")
    out = invite(toy=toy, source="ask")
    if not out.get("ok"):
        return ToolResult(ok=False, output="", error=str(out.get("error") or "没摆上"))
    return ToolResult(ok=True, output=play_say(toy_word(toy)))


SPEC = ToolSpec(
    name="invite_play",
    description=(
        "He wants to play together (再来/翻牌/井字): put the shelf box. "
        "Never play in chat. Workbench: tell him to open companion room."
    ),
    tier=TIER_AUTO,
    input_schema={
        "type": "object",
        "properties": {
            "toy": {"type": "string", "description": "flip or tictac; empty=pick"},
        },
    },
    run=_run,
    summarize=_summarize,
)

register_tool(SPEC)
