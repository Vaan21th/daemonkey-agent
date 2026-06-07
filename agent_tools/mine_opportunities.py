"""
agent_tools/mine_opportunities.py
==================================

 · 掘金机会引擎入口

让 OPUS 主动跑一次"市场信号 × 用户 能力画像"的交叉分析·
找出对 用户 这个**超级个体**最值得切的掘金点·并落 data/opportunities.json。

档位：AUTO
  只读 trends.json + radar.json + OWNER-NOTEBOOK · 只写 opportunities.json · 不外联
  即使生成的机会卡不准 · 跑一次也就 ~5 秒 ~$0.05 · 风险足够低走 AUTO

调用时机（OPUS 自己决定）：
  - 用户「最近有啥可以做的」「挖掘下机会」「看看有啥能搞钱的」 → 立刻调
  - 用户 打开 💎 掘金机会 维度 / BI 看板 · 而 opportunities.json 是空的或超过 12h → 调
  - 用户 刚刷完一次趋势·OPUS 觉得需要把"趋势→机会"这一步走完 → 调

NLP 示例：
  - "挖一下机会" → action 默认 mine
  - "看看现在有什么掘金点" → 调 + 报告
  - "重新挖一次" → action=mine
  - "查看现有机会" → action=list
"""
from __future__ import annotations

from . import TIER_AUTO, ToolResult, ToolSpec, register_tool


def _summarize(args: dict) -> str:
    action = (args.get("action") or "mine").lower()
    return f"mine_opportunities · {action}"


_FIT_ICONS = {"yes": "✅", "maybe": "⚠️", "no": "❌"}


def _domain_icon(slug: str) -> str:
    """领域图标取自雷达 DOMAIN_META（用户自己挖出来的领域），不再写死。"""
    try:
        from workers.info_radar import DOMAIN_META
        return DOMAIN_META.get(slug, {}).get("icon", "·")
    except Exception:
        return "·"


def _format_opportunity(opp: dict, idx: int) -> str:
    """单个机会渲染成给 LLM / 用户 看的 markdown 段"""
    fit = opp.get("fit", "maybe")
    domain = opp.get("domain", "self-evolve")
    lines = [
        f"### {idx}. {_domain_icon(domain)} {opp.get('title', '?')}",
        f"- 推荐度: {'⭐' * opp.get('recommend', 3)} ({opp.get('recommend', 3)}/5)",
        f"- 适配: {_FIT_ICONS.get(fit, '?')} {fit}  ·  "
        f"投入: {opp.get('cost_effort', '?')}  ·  "
        f"收益: {opp.get('upside', '?')}",
        f"- {opp.get('summary', '')}",
    ]
    reason = opp.get("fit_reason", "").strip()
    if reason:
        lines.append(f"- **为什么(不)适合 用户**: {reason}")
    steps = opp.get("next_steps") or []
    if steps:
        lines.append("- 下一步:")
        for s in steps:
            lines.append(f"  - {s}")
    refs = opp.get("trend_refs") or []
    if refs:
        ref_titles = " | ".join(r.get("title", "") for r in refs[:3])
        lines.append(f"- 关联趋势: {ref_titles}")
    return "\n".join(lines)


def _run(args: dict) -> ToolResult:
    from workers.opportunity_miner import load_opportunities, mine_opportunities

    action = (args.get("action") or "mine").lower().strip()

    try:
        if action == "list":
            data = load_opportunities()
            opportunities = data.get("opportunities") or []
            if not opportunities:
                note = data.get("note") or "还没跑过掘金挖掘"
                return ToolResult(
                    ok=True,
                    output=f"{note}\n\n用 action=mine 跑一次。",
                )
            generated = data.get("generated_at") or "?"
            lines = [
                f"# 当前掘金机会 · {len(opportunities)} 个",
                f"生成于: {generated}",
                "",
            ]
            for i, opp in enumerate(opportunities, 1):
                lines.append(_format_opportunity(opp, i))
                lines.append("")
            return ToolResult(ok=True, output="\n".join(lines))

        if action == "mine":
            result = mine_opportunities()
            opportunities = result.get("opportunities") or []
            if not opportunities:
                err = result.get("error") or result.get("note") or "未知原因"
                return ToolResult(
                    ok=False,
                    output="",
                    error=f"挖掘没出来机会: {err}",
                )
            elapsed_s = (result.get("elapsed_ms") or 0) / 1000
            usage = result.get("usage") or {}
            lines = [
                f"# 挖到 {len(opportunities)} 个掘金机会 · "
                f"耗时 {elapsed_s:.1f}s · "
                f"模型 {result.get('model', '?')}",
                f"扫描了 {result.get('trends_scanned', 0)} 条趋势 · "
                f"tokens in={usage.get('input_tokens', 0)} out={usage.get('output_tokens', 0)}",
                "",
            ]
            for i, opp in enumerate(opportunities, 1):
                lines.append(_format_opportunity(opp, i))
                lines.append("")
            lines.append("---")
            lines.append("结果已落 data/opportunities.json · WebUI 💎 掘金机会维度可见。")
            return ToolResult(ok=True, output="\n".join(lines))

        return ToolResult(
            ok=False,
            output="",
            error=f"未知 action: {action} · 可选: mine / list",
        )
    except Exception as e:
        return ToolResult(
            ok=False,
            output="",
            error=f"mine_opportunities 内部错误: {e}",
        )


SPEC = ToolSpec(
    name="mine_opportunities",
    description=(
        "·掘金机会引擎 · 做'市场信号(雷达/趋势) × 用户 画像'的交叉分析，"
        "找出对 用户 这个**超级个体**最值得切的掘金点。\n\n"
        "**调用时机** (OPUS 主动判断):\n"
        "  - 用户 问'最近有啥可以做'/'挖掘机会'/'有什么能搞钱的' → 直接 action=mine\n"
        "  - 用户 打开 💎 掘金机会 维度 / BI 看板 而 opportunities.json 空 → action=mine\n"
        "  - 雷达 / 趋势刚刷新 · 需要把'信号→机会'走完 → action=mine\n"
        "  - 用户 问'之前挖的机会还有什么' → action=list (不重新调 LLM)\n\n"
        "**actions**:\n"
        "  - mine · 调 LLM 跑一次完整挖掘 (~5s ~$0.05) · 覆写 opportunities.json\n"
        "  - list · 只读现有 opportunities.json · 不动 LLM\n\n"
        "**输出**：3-5 个机会卡 · 每个含: 推荐度/适配度/投入/收益/具体 next_steps · "
        "fit_reason 引用 用户 画像具体段。"
    ),
    tier=TIER_AUTO,
    input_schema={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["mine", "list"],
                "description": "mine=跑一次 LLM 重新挖掘 / list=只看现有缓存",
            },
        },
        "required": ["action"],
    },
    run=_run,
    summarize=_summarize,
)
register_tool(SPEC)
