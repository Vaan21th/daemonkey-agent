"""
agent_tools/list_flows.py
=========================

修补 · 让 AI 看见工坊里有什么工作流 (沉淀闭环 v2 · 修用户看到的"0 个 flow"假象)

为什么需要这个工具 (背景):
  跟 list_apps 同根 — .gitignore 把 flows/*.json 排除了 (第 39 行)
  glob_files 用 rg --files 看不到 · 但 daemon 内部 list_flows() 全在
  → 用户在 WebUI 左侧能看到一堆 flow · AI 在对话里却说"0 个 flow" · 直接精神分裂

正确做法:
  这个工具就是 list_flows() 的 thin wrapper · 输出对 LLM 友好的速查清单
  默认输出 steps 的人话清单 (1. 内容制作 → 2. 分镜稿审稿 → ...) · LLM 一眼就知道每条 flow 干啥

AUTO tier · 纯读 · 不动任何状态
"""

from __future__ import annotations

from . import TIER_AUTO, ToolResult, ToolSpec, register_tool


def _summarize(args: dict) -> str:
    q = args.get("query")
    extras = []
    if q:
        extras.append(f"q={q!r}")
    if args.get("detailed"):
        extras.append("detailed")
    suffix = " · ".join(extras)
    return f"list_flows · 列工坊所有工作流" + (f" ({suffix})" if suffix else "")


def _run(args: dict) -> ToolResult:
    try:
        from workers.workshop_assets import list_flows, list_apps
    except Exception as e:
        return ToolResult(ok=False, output="", error=f"workshop_assets import failed: {e!r}")

    query = (args.get("query") or "").strip().lower()
    detailed = bool(args.get("detailed"))
    limit = int(args.get("limit") or 50)

    try:
        flows = list_flows(max_items=200)
    except Exception as e:
        return ToolResult(ok=False, output="", error=f"list_flows failed: {e!r}")

    # app id → name 字典 (steps 里只存 id · 渲染时拼人名)
    name_map: dict[str, str] = {}
    try:
        for a in list_apps(max_items=200):
            aid = a.get("id") or ""
            if aid:
                name_map[aid] = a.get("name") or aid
    except Exception:
        pass

    if query:
        def _hit(f: dict) -> bool:
            blob = " ".join([
                f.get("id") or "", f.get("name") or "", f.get("description") or "",
            ]).lower()
            return query in blob
        flows = [f for f in flows if _hit(f)]

    if not flows:
        hint = f" (筛选: query={query!r})" if query else ""
        return ToolResult(ok=True, output=f"(工坊里目前没有匹配的工作流{hint})")

    total = len(flows)
    truncated = total > limit
    flows = flows[:limit]

    lines = [f"# 工坊 · 共 {total} 个工作流" + (f" (显示前 {limit} 个)" if truncated else "")]
    for f in flows:
        fid = f.get("id") or "?"
        name = f.get("name") or "(未命名)"
        runs = f.get("runs") or 0
        steps = f.get("steps") or []
        flow_kind = f.get("flow_kind") or "?"
        desc = (f.get("description") or "").strip().replace("\n", " ")
        if len(desc) > 80:
            desc = desc[:78] + "…"

        kind_tag = "[steps]" if flow_kind == "steps" else "[legacy]"
        head = f"- {kind_tag} **{name}** · `{fid}` · {len(steps)} 步 · 跑过 {runs} 次"
        lines.append(head)
        if desc:
            lines.append(f"  · {desc}")

        # steps 链 (人话名)
        if steps:
            chain = []
            for st in steps:
                aid = st.get("app", "?")
                app_name = name_map.get(aid, aid)
                chain.append(app_name)
            chain_str = " → ".join(chain)
            if len(chain_str) > 180:
                chain_str = chain_str[:178] + "…"
            lines.append(f"  · 流程: {chain_str}")

        if detailed and steps:
            for i, st in enumerate(steps, 1):
                aid = st.get("app", "?")
                app_name = name_map.get(aid, aid)
                goal = (st.get("goal") or "").strip().replace("\n", " ")
                if len(goal) > 100:
                    goal = goal[:98] + "…"
                substeps = st.get("substeps") or []
                lines.append(f"    {i}. {app_name} (`{aid}`)")
                if goal:
                    lines.append(f"       目标: {goal}")
                if substeps:
                    for j, ss in enumerate(substeps, 1):
                        ss_text = ss if isinstance(ss, str) else ss.get("goal", str(ss))
                        if len(ss_text) > 80:
                            ss_text = ss_text[:78] + "…"
                        lines.append(f"       {i}-{j} {ss_text}")

    lines.append("")
    lines.append("提示:")
    lines.append("  - 跑某条 flow: 用 run_flow(flow_id=...)")
    lines.append("  - 想看每步细节 (goal/substeps): 加 detailed=true")
    lines.append("  - [steps] = 新版步骤工作流 · [legacy] = 老画布工作流")
    return ToolResult(ok=True, output="\n".join(lines), truncated=truncated)


SPEC = ToolSpec(
    name="list_flows",
    description=(
        "List all workflows (flows) in the workshop (data/workshop/flows/*.json). "
        "Use whenever you want to know what flows exist — DO NOT use glob_files for this "
        "(.gitignore hides flows/*.json from rg). "
        "Returns id / name / steps chain (with app names, not ids). "
        "Filter by query (substring match) or detailed=true for per-step goals + substeps. Read-only."
    ),
    tier=TIER_AUTO,
    input_schema={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Optional substring filter (matches in id / name / description, case-insensitive).",
            },
            "detailed": {
                "type": "boolean",
                "description": "If true, also show goal + substeps for each step. Default false.",
            },
            "limit": {
                "type": "integer",
                "description": "Max flows to return. Default 50.",
            },
        },
        "required": [],
    },
    run=_run,
    summarize=_summarize,
)


register_tool(SPEC)
