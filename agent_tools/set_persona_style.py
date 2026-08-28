"""对话里改相处口吻。不做设置页：他说要换，就写身份本并重蒸档位包。"""
from __future__ import annotations

from . import TIER_AUTO, ToolResult, ToolSpec, register_tool


def _summarize(args: dict) -> str:
    return f"set_persona_style  →  {(args.get('persona_style') or '').strip()[:40]}"


def _run(args: dict) -> ToolResult:
    style = (args.get("persona_style") or "").strip()
    if not style:
        return ToolResult(ok=False, output="", error="persona_style 为空")
    from identity import set_persona_style
    out = set_persona_style(style)
    if not out.get("ok"):
        return ToolResult(ok=False, output="", error=str(out.get("error") or "写入失败"))
    old = out.get("old") or "（空）"
    return ToolResult(
        ok=True,
        output=(
            f"口吻已改：{old} → {out['style']}\n"
            f"档位包：{'已重蒸' if out.get('has_band') else '沿用兜底'}\n"
            "下一轮开始按新口吻说。这一轮尾巴可能还是旧的。"
        ),
    )


SPEC = ToolSpec(
    name="set_persona_style",
    description=(
        "他明确要求改相处口吻时用（例如「以后用猫娘/霸总/像朋友那样说话」）。"
        "写入身份并重蒸档位包。他没说要改，不要自己换。"
    ),
    tier=TIER_AUTO,
    input_schema={
        "type": "object",
        "properties": {
            "persona_style": {
                "type": "string",
                "description": "他要的新口吻，原话收短即可",
            },
        },
        "required": ["persona_style"],
    },
    run=_run,
    summarize=_summarize,
)

register_tool(SPEC)
