"""听懂换挡：对她说话方式的要求 → 当天临时 / 30 天满 3 次永久。"""
from __future__ import annotations

from . import TIER_AUTO, ToolResult, ToolSpec, register_tool


def _summarize(args: dict) -> str:
    return f"note_style_shift → {args.get('dim') or ''} {args.get('direction') or ''}"


def _run(args: dict) -> ToolResult:
    from workers.style_shift import apply_shift

    out = apply_shift(
        str(args.get("dim") or ""),
        str(args.get("direction") or ""),
        str(args.get("quote") or ""),
    )
    if not out.get("ok"):
        return ToolResult(ok=False, output="", error=str(out.get("error") or "跳档失败"))
    return ToolResult(ok=True, output=out["notice"])


SPEC = ToolSpec(
    name="note_style_shift",
    description=(
        "Only when this user turn tells you how to speak (less/more talk, "
        "sharper/softer, formal/casual). quote=his words. "
        "dim=话量|调性|语气|礼节|表现力. direction=down|up. "
        "Not about a document or other people. Do not change 口吻."
    ),
    tier=TIER_AUTO,
    input_schema={
        "type": "object",
        "properties": {
            "quote": {"type": "string", "description": "他的原话"},
            "dim": {
                "type": "string",
                "enum": ["话量", "调性", "语气", "力度", "礼节", "表现力"],
            },
            "direction": {
                "type": "string",
                "enum": ["down", "up"],
                "description": "down=少/冷端 up=多/暖端",
            },
        },
        "required": ["quote", "dim", "direction"],
    },
    run=_run,
    summarize=_summarize,
)

register_tool(SPEC)
