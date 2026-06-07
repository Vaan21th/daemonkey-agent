"""
agent_tools/analyze_feasibility.py
===================================

 · 可行性分析工具

把 OPUS 一句话推荐的"掘金机会"·深度展开成完整可行性分析。

档位：AUTO
  只读 opportunities.json + OWNER-NOTEBOOK · 只写 data/feasibility/ · 不外联
  一次 LLM ~$0.05-0.1 · 风险足够低走 AUTO

NLP 触发：
  - "分析一下第 N 个机会的可行性" → action=analyze, opp_index=N
  - "评估第 X 个机会能不能干" → action=analyze, opp_id=...
  - "看下所有分析过的机会" → action=list
"""
from __future__ import annotations

from . import TIER_AUTO, ToolResult, ToolSpec, register_tool


def _summarize(args: dict) -> str:
    action = (args.get("action") or "analyze").lower()
    if action == "list":
        return "analyze_feasibility · 列出所有已分析"
    opp_ref = args.get("opp_id") or args.get("opp_index") or "?"
    return f"analyze_feasibility · opp={opp_ref}"


_VERDICT_LABELS = {
    "go":          "🟢 推荐做",
    "conditional": "🟡 有条件可做",
    "wait":        "⏸  先等等",
    "skip":        "🔴 不建议",
}


def _format_analysis(analysis: dict) -> str:
    """渲染可行性分析成 markdown · 给对话里展示"""
    lines = [
        f"# 📊 可行性分析: {analysis.get('opp_title', '?')}",
        "",
        f"**综合可行性**: **{analysis.get('feasibility_score', 0)}/100** · "
        f"**判断**: {_VERDICT_LABELS.get(analysis.get('verdict'), '?')}",
        "",
        f"> {analysis.get('verdict_reason', '')}",
        "",
    ]

    # 补丁 · 信源段（宪法第 5 条 · 人机认知对齐）
    # 把信源**放在最前面**——用户 应该先看到"这次分析基于什么信源"·再读 OPUS 的判断
    sources = analysis.get("sources") or {}
    radar_items = sources.get("radar_items") or []
    report_items = sources.get("reports") or []
    if radar_items or report_items:
        lines.append("## 📚 信源（这次分析基于的原始信息·用户 可顺着同一根线看原文）")
        if radar_items:
            lines.append("**雷达条目**:")
            for r in radar_items:
                src = r.get("source_display") or r.get("source") or "?"
                title = (r.get("title") or "")[:60]
                url = r.get("url") or ""
                if url:
                    lines.append(f"- **[{r.get('ref_id','?')}]** [{src}] [{title}]({url})")
                else:
                    lines.append(f"- **[{r.get('ref_id','?')}]** [{src}] {title}")
        if report_items:
            lines.append("**同主题报告**:")
            for d in report_items:
                lines.append(
                    f"- **[{d.get('ref_id','?')}]** [{d.get('name','?')}]({d.get('download_url','#')})"
                )
        lines.append("")
    elif analysis.get("ok") and not sources.get("error"):
        # 信源真的没找到·明确告诉 用户·别藏起来
        lines.append("## 📚 信源")
        lines.append("> **没找到相关雷达条目 / 报告** · 这次分析信源不足。 "
                     "用户 建议：先让 OPUS 跑一份相关报告·或扩大雷达源·再回来重新分析。")
        lines.append("")

    risks = analysis.get("risks") or []
    if risks:
        lines.append("## 风险评估")
        for r in risks:
            level = r.get("level", "?")
            icon = {"low": "🟢", "medium": "🟡", "high": "🔴"}.get(level, "⚪")
            lines.append(
                f"- {icon} **{r.get('type', '?')}** ({level}): {r.get('detail', '')}"
            )
        lines.append("")

    #  · SWOT
    swot = analysis.get("swot") or {}
    if any(swot.get(k) for k in ("strengths", "weaknesses", "opportunities", "threats")):
        lines.append("## SWOT 分析")
        for key, label, icon in [
            ("strengths",     "S · 优势", "💪"),
            ("weaknesses",    "W · 劣势", "⚠"),
            ("opportunities", "O · 机会", "🌱"),
            ("threats",       "T · 威胁", "🌪"),
        ]:
            items = swot.get(key) or []
            if items:
                lines.append(f"**{icon} {label}**")
                for x in items:
                    lines.append(f"- {x}")
        lines.append("")

    #  · 未来预期
    outlook = analysis.get("future_outlook") or {}
    if any(outlook.get(k) for k in ("three_months", "six_months", "one_year")):
        lines.append("## 未来预期 · 按 用户 现实节奏")
        if outlook.get("three_months"):
            lines.append(f"- **3 个月**: {outlook['three_months']}")
        if outlook.get("six_months"):
            lines.append(f"- **6 个月**: {outlook['six_months']}")
        if outlook.get("one_year"):
            lines.append(f"- **12 个月**: {outlook['one_year']}")
        lines.append("")

    #  · 成功路径
    path = analysis.get("success_path") or {}
    stages = path.get("stages") or []
    if stages or path.get("end_state"):
        lines.append("## 成功路径")
        for i, st in enumerate(stages, 1):
            weeks = st.get("weeks", "")
            wk_part = f" · {weeks}周" if weeks else ""
            lines.append(
                f"{i}. **{st.get('name', '?')}**{wk_part} "
                f"→ {st.get('milestone', '')} · 判断: {st.get('criteria', '')}"
            )
        if path.get("end_state"):
            lines.append(f"\n**终态**: {path['end_state']}")
        lines.append("")

    have = analysis.get("resources_have") or []
    need = analysis.get("resources_need") or []
    if have or need:
        lines.append("## 资源")
        if have:
            lines.append("**已有**:")
            for x in have:
                lines.append(f"- ✅ {x}")
        if need:
            lines.append("**还需要**:")
            for x in need:
                lines.append(f"- 🔍 {x}")
        lines.append("")

    caps = analysis.get("capability_match") or []
    if caps:
        lines.append("## 能力对照")
        for c in caps:
            mark = {"yes": "✅", "partial": "🟡", "no": "❌"}.get(c.get("bro_has"), "?")
            lines.append(f"- {mark} **{c.get('capability', '?')}** — {c.get('evidence', '')}")
        lines.append("")

    cost = analysis.get("cost_breakdown") or {}
    if cost:
        lines.append("## 成本拆解")
        if cost.get("time_hours_min") or cost.get("time_hours_max"):
            lines.append(
                f"- ⏱️ 时间: {cost.get('time_hours_min', '?')} - {cost.get('time_hours_max', '?')} 小时"
            )
        if cost.get("tokens_estimate_usd") is not None:
            lines.append(f"- 💰 LLM token 估算: ${cost.get('tokens_estimate_usd')}")
        if cost.get("subscriptions_monthly_usd") is not None:
            lines.append(f"- 📅 月订阅: ${cost.get('subscriptions_monthly_usd')}")
        if cost.get("opportunity_cost"):
            lines.append(f"- 🔄 机会成本: {cost.get('opportunity_cost')}")
        lines.append("")

    alts = analysis.get("alternatives") or []
    if alts:
        lines.append("## 替代方案")
        for a in alts:
            lines.append(f"- **{a.get('name', '?')}**: {a.get('delta', '')} · {a.get('why_consider', '')}")
        lines.append("")

    if analysis.get("first_30_min"):
        lines.append(f"## 立刻能做的第一步\n\n{analysis.get('first_30_min')}\n")
    if analysis.get("go_no_go"):
        lines.append(f"## Go / No-Go\n\n{analysis.get('go_no_go')}\n")

    #  · 闭环 outcome 状态
    outcome = analysis.get("outcome") or {}
    if outcome:
        st = outcome.get("status", "not_started")
        label = {
            "not_started": "🆕 未启动",
            "in_progress": "▶ 进行中",
            "completed":   "✓ 已完成",
            "abandoned":   "✗ 已放弃",
        }.get(st, st)
        lines.append(f"## 闭环状态: {label}")
        if outcome.get("decision_reason"):
            lines.append(f"- **用户 决定**: {outcome['decision_reason']}")
        if outcome.get("actual_revenue_cny") is not None:
            lines.append(f"- **实际收入**: ¥{outcome['actual_revenue_cny']}")
        if outcome.get("actual_cost_cny") is not None:
            lines.append(f"- **实际成本**: ¥{outcome['actual_cost_cny']}")
        if outcome.get("efficiency_gain"):
            lines.append(f"- **增效**: {outcome['efficiency_gain']}")
        if outcome.get("lessons_learned"):
            lines.append(f"- **经验**: {outcome['lessons_learned']}")
        lines.append("")

    return "\n".join(lines)


def _resolve_opp_id(args: dict) -> tuple[str | None, str | None]:
    """根据 args 找出 opp_id · 返回 (opp_id, error_msg)"""
    from workers.opportunity_miner import load_opportunities

    if args.get("opp_id"):
        return args["opp_id"].strip(), None

    if args.get("opp_index") is not None:
        try:
            idx = int(args["opp_index"])
        except (TypeError, ValueError):
            return None, f"opp_index 必须是整数 · 收到 {args['opp_index']!r}"
        opps = load_opportunities().get("opportunities") or []
        if idx < 1 or idx > len(opps):
            return None, f"opp_index 越界 · 范围 1-{len(opps)}"
        return opps[idx - 1].get("id"), None

    return None, "需要 opp_id 或 opp_index 指定要分析哪个机会"


def _run(args: dict) -> ToolResult:
    from workers.feasibility_analyzer import (
        analyze_feasibility,
        list_feasibility,
        load_feasibility,
    )

    action = (args.get("action") or "analyze").lower().strip()

    try:
        if action == "list":
            data = list_feasibility()
            items = data.get("items") or []
            if not items:
                return ToolResult(
                    ok=True,
                    output="还没分析过任何机会 · 用 action=analyze + opp_index=N 跑一次",
                )
            lines = [f"# 已分析的可行性 · 共 {data['total']} 个", ""]
            for it in items:
                lines.append(
                    f"- [{_VERDICT_LABELS.get(it.get('verdict'), '?')}] "
                    f"{it.get('feasibility_score')}/100 · "
                    f"{it.get('opp_title')} ({it.get('opp_id')})"
                )
                if it.get("verdict_reason"):
                    lines.append(f"    {it['verdict_reason']}")
            return ToolResult(ok=True, output="\n".join(lines))

        if action == "load":
            opp_id, err = _resolve_opp_id(args)
            if err:
                return ToolResult(ok=False, output="", error=err)
            data = load_feasibility(opp_id)
            if not data:
                return ToolResult(
                    ok=True,
                    output=f"opp={opp_id} 还没分析过 · 用 action=analyze 跑一次",
                )
            return ToolResult(ok=True, output=_format_analysis(data))

        if action == "analyze":
            opp_id, err = _resolve_opp_id(args)
            if err:
                return ToolResult(ok=False, output="", error=err)
            result = analyze_feasibility(opp_id)
            if not result.get("ok"):
                return ToolResult(
                    ok=False,
                    output="",
                    error=result.get("error") or "分析失败",
                )
            return ToolResult(
                ok=True,
                output=(
                    _format_analysis(result)
                    + "\n\n---\n"
                    + f"已落 data/feasibility/{opp_id}.json · WebUI 📊 可行性分析维度可见。"
                ),
            )

        return ToolResult(
            ok=False, output="",
            error=f"未知 action: {action} · 可选: analyze / list / load",
        )

    except Exception as e:
        return ToolResult(ok=False, output="", error=f"分析失败: {e}")


SPEC = ToolSpec(
    name="analyze_feasibility",
    description=(
        " · 把一个掘金机会展开成完整可行性分析: "
        "风险 / 资源 / 能力对照 / 成本拆解 / 替代方案 / Go-No-Go。\n\n"
        "**调用时机** (OPUS 主动判断):\n"
        "  - 用户 问'分析第 N 个机会能不能干'/'XX 这事可行性怎么样' → action=analyze\n"
        "  - 用户 点机会卡里'💰估算成本'按钮自动调 (BI 看板 / 💎 维度) → action=analyze\n"
        "  - 用户 问'之前分析过哪些机会' → action=list (不调 LLM)\n\n"
        "**actions**:\n"
        "  - analyze · 跑一次 LLM 深度分析 (~5s ~$0.05-0.1) · 落 data/feasibility/<id>.json\n"
        "  - list · 列所有已分析的机会\n"
        "  - load · 看某个机会的已有分析 (不重新调 LLM)\n\n"
        "**输入**: opp_id 或 opp_index (1-based 从 opportunities.json 数)\n"
        "**输出**: 综合可行性 0-100 + verdict (go/conditional/wait/skip) + 完整结构化分析"
    ),
    tier=TIER_AUTO,
    input_schema={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["analyze", "list", "load"],
                "description": "analyze=跑 LLM 新分析 / list=列已有 / load=读某个不重新算",
            },
            "opp_id": {
                "type": "string",
                "description": "机会的 id (形如 opp-xxxxxx) · 从 opportunities.json 的 id 字段",
            },
            "opp_index": {
                "type": "integer",
                "description": "机会的 1-based 序号 · 用户 说'第 3 个机会'即 3 · 比 opp_id 更人性化",
                "minimum": 1,
                "maximum": 20,
            },
        },
        "required": ["action"],
    },
    run=_run,
    summarize=_summarize,
)
register_tool(SPEC)
