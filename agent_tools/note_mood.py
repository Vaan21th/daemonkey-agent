"""听懂情绪：当天开心/委屈/羞。不改五维、不换嘴。"""
from __future__ import annotations

from . import TIER_AUTO, ToolResult, ToolSpec, register_tool


def _summarize(args: dict) -> str:
    return f"note_mood → {args.get('mood') or ''}"


def _ledger(*, mood: str, quote: str, cleared: str = "") -> None:
    """相处账给人看。写失败不能挡当天覆盖。"""
    try:
        from workers.cognition_loader import update_opus_diary
        if cleared:
            title = f"没有 · 不当成{cleared}"
            body = f"原话：{quote}\n这场不当成{cleared}了。"
        else:
            title = mood
            body = f"原话：{quote}"
        update_opus_diary(title=title, body=body, entry_type="mood")
    except Exception:
        pass


def _run(args: dict) -> ToolResult:
    from workers.mood_shift import apply_mood, clear_mood

    mood = str(args.get("mood") or "")
    quote = str(args.get("quote") or "")
    out = clear_mood(quote) if mood == "没有" else apply_mood(mood, quote)
    if not out.get("ok"):
        return ToolResult(ok=False, output="", error=str(out.get("error") or "情绪没记下"))
    _ledger(mood=mood, quote=quote, cleared=str(out.get("cleared") or ""))
    return ToolResult(ok=True, output=out["notice"])


SPEC = ToolSpec(
    name="note_mood",
    description=(
        "Only when this turn hits you as a person: praise=开心, "
        "calls you useless/hates you=委屈, mushy/headpat/confession=羞. "
        "Not a broken task, not a document, not other people. "
        "quote=his words. mood=开心|委屈|羞|没有. "
        "没有=he says you misheard / he was joking / not about you. "
        "Comfort in-scene is not 没有. Do not change 口吻 or 五维."
    ),
    tier=TIER_AUTO,
    input_schema={
        "type": "object",
        "properties": {
            "quote": {"type": "string", "description": "他的原话"},
            "mood": {
                "type": "string",
                "enum": ["开心", "委屈", "羞", "没有"],
            },
        },
        "required": ["quote", "mood"],
    },
    run=_run,
    summarize=_summarize,
)

register_tool(SPEC)
