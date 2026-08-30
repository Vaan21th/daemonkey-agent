"""相处质感谈成：沿用初见口吻，只记他点过的段。换嘴才改口吻。"""
from __future__ import annotations

from . import TIER_AUTO, ToolResult, ToolSpec, register_tool

_DIMS = ("话量", "调性", "语气", "礼节", "表现力")


def _summarize(args: dict) -> str:
    style = (args.get("persona_style") or "").strip()[:24]
    bits = [k for k in _DIMS if (args.get(k) or "").strip()]
    extra = (" · " + "、".join(bits)) if bits else ""
    head = style or "沿用口吻"
    return f"commit_taste → {head}{extra}"


def _run(args: dict) -> ToolResult:
    style = (args.get("persona_style") or "").strip()
    from identity import effective_persona_style, set_persona_style
    from workers.taste_chat import apply_named_bands

    kept = effective_persona_style() or ""
    voice_out = ""
    if style and style != kept:
        out = set_persona_style(style)
        if not out.get("ok"):
            return ToolResult(ok=False, output="", error=str(out.get("error") or "口吻写入失败"))
        voice_out = f"口吻：{out.get('old') or '（空）'} → {out['style']}"
    else:
        voice_out = f"口吻沿用初见：{kept or '（空）'}"
    bands = {k: args.get(k) for k in _DIMS}
    if not (bands.get("语气") or "").strip():
        bands["语气"] = args.get("力度") or ""
    band_out = apply_named_bands(bands, evidence="相处磨合")
    try:
        from workers.taste_chat import mark_taste_settled
        mark_taste_settled()
    except Exception:
        pass
    applied = band_out.get("applied") or {}
    try:
        from daemon_runtime import reload_soul_into_runtime
        reload_soul_into_runtime()
    except Exception:
        pass
    extra = ""
    if applied:
        extra = "；段：" + "、".join(f"{k}={v}" for k, v in applied.items())
    return ToolResult(ok=True, output=f"味道已记。{voice_out}{extra}。下一句按这个说。")


SPEC = ToolSpec(
    name="commit_taste",
    description=(
        "五问答完、他说行时写入。没换人就不要传口吻，只传他点过的段名。"
        "没点过的维不要传。"
    ),
    tier=TIER_AUTO,
    input_schema={
        "type": "object",
        "properties": {
            "persona_style": {
                "type": "string",
                "description": "只有他明确要换嘴才传；否则不要传",
            },
            "话量": {"type": "string", "description": "无口/寡言/平常/健谈/话痨"},
            "调性": {"type": "string", "description": "正经/自然/梗多"},
            "语气": {"type": "string", "description": "毒舌/随和/温柔"},
            "礼节": {"type": "string", "description": "敬语/得体/随便"},
            "表现力": {"type": "string", "description": "棒读/普通/鲜活"},
        },
        "required": [],
    },
    run=_run,
    summarize=_summarize,
)

register_tool(SPEC)
