"""把已叉进内核的魔改收成 MOD。默认只叠工具。"""
from __future__ import annotations

from . import TIER_AUTO, TIER_CONFIRM, ToolResult, ToolSpec, register_tool


def _fmt(plan: dict) -> str:
    lift, draft, skip = plan["lift"], plan["draft"], plan["skip"]
    if not lift and not draft:
        return "没有可收的内核魔改。装修区 / data/mods 本来就不用收。"
    lines = [
        "预览 · 「把工具魔改收成 MOD」只叠工具（推荐）。",
        "「把魔改全部收成 MOD」才把前端/worker 存进 legacy/ 草稿。",
        "不会改你正在接管的内核文件。",
        "",
    ]
    if lift:
        lines.append(f"① 能叠、说那句就会叠上 ({len(lift)}):")
        for r in lift:
            lines.append(f"  + {r['file']} → {r['dest']}")
    if draft:
        lines.append(f"② 叠不了 ({len(draft)}) · 默认不收；要行为回来走「用回」或「合并」:")
        for r in draft:
            lines.append(f"  · {r['file']}  ({r['depth']})")
    if skip:
        lines.append("不会动（升级机制自身）: " + ", ".join(r["file"] for r in skip))
    return "\n".join(lines)


def _after_apply(res: dict) -> str:
    leftover = res.get("leftover_draft") or []
    lines = [
        f"已收入 MOD `{res['mod_id']}` → data/mods/{res['mod_id']}/",
        f"叠上的工具 {len(res.get('lifted') or [])} 个: " +
        (", ".join(res.get("lifted") or []) or "无"),
    ]
    drafted = res.get("drafted") or []
    if drafted:
        lines.append(f"草稿 {len(drafted)} 个（不会自己跑）: " + ", ".join(drafted))
    lines.append("重启 daemon 后工具叠层生效。已叠上的不要再合并回内核。")
    if leftover:
        one = leftover[0]
        lines.append(
            f"叠不了的还在备份 ({len(leftover)}): " + ", ".join(leftover))
        lines.append(f"要界面/行为回来：说「用回我的 {one}」或「合并 {one}」。")
        lines.append("先用官方这版也行，备份留着。")
    return "\n".join(lines)


def _run(args: dict) -> ToolResult:
    from workers.mod_harvest import apply, preview
    action = (args.get("action") or "preview").strip().lower()
    if action in ("list", "preview"):
        return ToolResult(ok=True, output=_fmt(preview()))
    if action != "apply":
        return ToolResult(ok=False, output="", error="action 用 preview 或 apply")
    spoken = str(args.get("scope") or "tools").strip().lower()
    res = apply(
        str(args.get("id") or "harvest_legacy"),
        scope=spoken,
        exclude=args.get("skip"),
    )
    if not res.get("ok"):
        return ToolResult(ok=False, output="", error=res.get("note") or "收割失败")
    if not res.get("lifted") and not res.get("drafted"):
        extra = res.get("leftover_draft") or []
        note = res.get("note") or "没有可收的"
        if extra:
            one = extra[0]
            note += (
                f"\n叠不了的还在: {', '.join(extra)}\n"
                f"要行为回来：说「用回我的 {one}」或「合并 {one}」。"
            )
        return ToolResult(ok=True, output=note)
    return ToolResult(ok=True, output=_after_apply(res))


register_tool(ToolSpec(
    name="harvest_overrides",
    description=(
        "把升级备份里的内核魔改收成 MOD。默认只叠官方工具（scope=tools）。"
        "前端/worker 不要当已生效的 MOD。scope=all 才存 legacy/ 草稿。"
        "用户说「把工具魔改收成 MOD」→ apply scope=tools；"
        "「把魔改全部收成 MOD」→ apply scope=all。"
    ),
    tier=TIER_CONFIRM,
    input_schema={
        "type": "object",
        "properties": {
            "action": {"type": "string", "description": "preview 或 apply，默认 preview"},
            "id": {"type": "string", "description": "MOD 目录名，默认 harvest_legacy"},
            "scope": {"type": "string",
                      "description": "tools（默认，只叠工具）/ draft / all"},
            "skip": {"type": "string", "description": "不收的文件，逗号分隔"},
        },
        "required": [],
    },
    run=_run,
    summarize=lambda a: "收割旧魔改" if (a.get("action") or "") == "apply" else "预览可收割的魔改",
    classify=lambda a: TIER_AUTO if (a.get("action") or "preview") != "apply" else TIER_CONFIRM,
))
