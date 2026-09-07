"""把已叉进内核的魔改收成 MOD。"""
from __future__ import annotations

from . import TIER_AUTO, TIER_CONFIRM, ToolResult, ToolSpec, register_tool


def _fmt(plan: dict) -> str:
    lift, draft, skip = plan["lift"], plan["draft"], plan["skip"]
    if not lift and not draft:
        return "没有可收的内核魔改。装修区 / data/mods 本来就不用收。"
    lines = ["预览 · 说「把魔改收成 MOD」才真写盘（不会改你正在接管的内核文件）:", ""]
    if lift:
        lines.append(f"会叠上去、以后不用再合并 ({len(lift)}):")
        for r in lift:
            lines.append(f"  + {r['file']} → {r['dest']}")
    if draft:
        lines.append(f"只能进草稿，不能自动跑 ({len(draft)}):")
        for r in draft:
            lines.append(f"  · {r['file']} → {r['dest']}  ({r['depth']})")
    if skip:
        lines.append("不会动（升级机制自身）: " + ", ".join(r["file"] for r in skip))
    lines.append("")
    lines.append("chat.js 这类进 legacy/ 之后，行为还靠「合并」或「接管」。")
    return "\n".join(lines)


def _run(args: dict) -> ToolResult:
    from workers.mod_harvest import apply, preview
    action = (args.get("action") or "preview").strip().lower()
    if action in ("list", "preview"):
        return ToolResult(ok=True, output=_fmt(preview()))
    if action != "apply":
        return ToolResult(ok=False, output="", error="action 用 preview 或 apply")
    res = apply(str(args.get("id") or "harvest_legacy"))
    if not res.get("ok"):
        return ToolResult(ok=False, output="", error=res.get("note") or "收割失败")
    if not res.get("lifted") and not res.get("drafted"):
        return ToolResult(ok=True, output=res.get("note") or "没有可收的")
    lines = [
        f"已收入 MOD `{res['mod_id']}` → data/mods/{res['mod_id']}/",
        f"叠上的工具 {len(res.get('lifted') or [])} 个: " +
        (", ".join(res.get("lifted") or []) or "无"),
        f"草稿 {len(res.get('drafted') or [])} 个: " +
        (", ".join(res.get("drafted") or []) or "无"),
        "重启 daemon 后工具叠层生效。前端草稿不会自己跑起来。",
    ]
    return ToolResult(ok=True, output="\n".join(lines))


register_tool(ToolSpec(
    name="harvest_overrides",
    description="把升级备份/接管里的内核魔改收成 MOD。工具可叠层；chat.js 只进草稿。preview/apply。",
    tier=TIER_CONFIRM,
    input_schema={
        "type": "object",
        "properties": {
            "action": {"type": "string", "description": "preview 或 apply，默认 preview"},
            "id": {"type": "string", "description": "MOD 目录名，默认 harvest_legacy"},
        },
        "required": [],
    },
    run=_run,
    summarize=lambda a: "收割旧魔改" if (a.get("action") or "") == "apply" else "预览可收割的魔改",
    classify=lambda a: TIER_AUTO if (a.get("action") or "preview") != "apply" else TIER_CONFIRM,
))
