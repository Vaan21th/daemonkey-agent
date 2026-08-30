"""听懂他对刚寄的那张画：对 / 别这样。下一张要吃到。"""
from __future__ import annotations

from . import TIER_AUTO, ToolResult, ToolSpec, register_tool


def _summarize(args: dict) -> str:
    return f"note_gallery → {args.get('verdict') or ''}"


def _run(args: dict) -> ToolResult:
    from workers.she_gallery_feedback import apply_feedback

    out = apply_feedback(str(args.get("verdict") or ""), str(args.get("quote") or ""))
    if not out.get("ok"):
        return ToolResult(ok=False, output="", error=str(out.get("error") or "没记下"))
    return ToolResult(ok=True, output=out["notice"])


SPEC = ToolSpec(
    name="note_gallery",
    description=(
        "Only when he is judging the postcard she just sent: "
        "likes it=对, hates this kind=别这样. "
        "quote=his words. verdict=对|别这样. "
        "Not a task, not a document. Do not inspect the repo."
    ),
    tier=TIER_AUTO,
    input_schema={
        "type": "object",
        "properties": {
            "quote": {"type": "string", "description": "他的原话"},
            "verdict": {"type": "string", "enum": ["对", "别这样"]},
        },
        "required": ["quote", "verdict"],
    },
    run=_run,
    summarize=_summarize,
)

register_tool(SPEC)
