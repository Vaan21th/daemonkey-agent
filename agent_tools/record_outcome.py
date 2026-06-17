"""
agent_tools/record_outcome.py
==============================

 · 闭环反馈工具

让 用户 在对话里就能记录某个掘金机会的真实结果——
"我不做 #1 因为已经有 3 个大厂在做了" → status=abandoned, reason=...
"#2 已经完成 · 第一个月收入 ¥800" → status=completed, revenue=800
"#3 开干了 · 卡在 Playwright" → status=in_progress, note=...

档位：AUTO
  只写 data/outcomes/<opp_id>.json · 不外联 · 不调 LLM
  这种"用户 主动反馈"的记录 · 没什么风险 · AUTO

数据闭环：
  record_outcome →  outcomes/<id>.json
                 ↓
       mine_opportunities / analyze_feasibility 下次跑 LLM 时读 outcomes
                 ↓
       OPUS 越来越知道 用户 真的会做什么 / 不会做什么
"""
from __future__ import annotations

from . import TIER_AUTO, ToolResult, ToolSpec, register_tool


_STATUS_LABEL = {
    "not_started": "🆕 未启动",
    "in_progress": "▶ 进行中",
    "completed":   "✓ 已完成",
    "abandoned":   "✗ 已放弃",
}


def _summarize(args: dict) -> str:
    action = (args.get("action") or "record").lower()
    if action == "list":
        return "record_outcome · 列闭环反馈"
    if action == "load":
        return f"record_outcome · load opp={args.get('opp_id') or args.get('opp_index') or '?'}"
    opp_ref = args.get("opp_id") or args.get("opp_index") or "?"
    status = args.get("status") or "?"
    return f"record_outcome · opp={opp_ref} · {status}"


def _resolve_opp_id(args: dict) -> tuple[str | None, str | None]:
    """复用 analyze_feasibility 的解析逻辑"""
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

    return None, "需要 opp_id 或 opp_index 指定要记录哪个机会"


def _format_outcome(outcome: dict) -> str:
    """把单条 outcome 渲染成 markdown 段"""
    if not outcome:
        return "（暂无）"
    st = outcome.get("status", "not_started")
    label = _STATUS_LABEL.get(st, st)
    lines = [
        f"### {label} · {outcome.get('opp_title') or outcome.get('opp_id') or '?'}",
        "",
        f"- **领域**: {outcome.get('opp_domain', '?')}",
        f"- **opp_id**: `{outcome.get('opp_id', '?')}`",
        f"- **最后更新**: {outcome.get('updated_at', '?')}",
    ]
    if outcome.get("decision_reason"):
        lines.append(f"- **决策原因**: {outcome['decision_reason']}")
    if outcome.get("actual_revenue_cny") is not None:
        lines.append(f"- **实际收入**: ¥{outcome['actual_revenue_cny']}")
    if outcome.get("actual_cost_cny") is not None:
        lines.append(f"- **实际成本**: ¥{outcome['actual_cost_cny']}")
    if outcome.get("efficiency_gain"):
        lines.append(f"- **增效**: {outcome['efficiency_gain']}")
    if outcome.get("lessons_learned"):
        lines.append(f"- **经验**: {outcome['lessons_learned']}")
    updates = outcome.get("updates") or []
    if updates:
        lines.append("")
        lines.append(f"_共 {len(updates)} 次变更_")
    return "\n".join(lines)


def _run(args: dict) -> ToolResult:
    from workers.outcomes import (
        list_outcomes,
        load_outcome,
        record_outcome,
    )

    action = (args.get("action") or "record").lower().strip()

    try:
        if action == "list":
            data = list_outcomes()
            items = data.get("items") or []
            if not items:
                return ToolResult(
                    ok=True,
                    output="还没有任何 outcome 反馈 · 等 用户 做完或拒了机会再记。",
                )
            lines = [
                f"# 闭环反馈 · 共 {data['total']} 条",
                "",
                "| 状态 | 机会 | 决策原因 | 更新时间 |",
                "|---|---|---|---|",
            ]
            for it in items[:20]:
                reason = (it.get("decision_reason") or "").replace("|", "/")[:60]
                lines.append(
                    f"| {it.get('status_label', '?')} "
                    f"| {(it.get('opp_title') or '?')[:30]} "
                    f"| {reason} "
                    f"| {(it.get('updated_at') or '')[:10]} |"
                )
            return ToolResult(ok=True, output="\n".join(lines))

        if action == "load":
            opp_id, err = _resolve_opp_id(args)
            if err:
                return ToolResult(ok=False, output="", error=err)
            outcome = load_outcome(opp_id)
            if not outcome:
                return ToolResult(
                    ok=True,
                    output=f"opp={opp_id} 还没有反馈 · 用 action=record 记一条",
                )
            return ToolResult(ok=True, output=_format_outcome(outcome))

        # action=record · 主路径
        opp_id, err = _resolve_opp_id(args)
        if err:
            return ToolResult(ok=False, output="", error=err)

        # 必须至少有一个字段更新
        any_field = any(
            args.get(k) is not None
            for k in (
                "status", "decision_reason",
                "actual_revenue_cny", "actual_cost_cny",
                "efficiency_gain", "lessons_learned", "note",
            )
        )
        if not any_field:
            return ToolResult(
                ok=False, output="",
                error="至少要提供 status / decision_reason / actual_revenue_cny "
                      "/ actual_cost_cny / efficiency_gain / lessons_learned / note 之一",
            )

        result = record_outcome(
            opp_id,
            status=args.get("status"),
            opp_title=args.get("opp_title"),
            decision_reason=args.get("decision_reason"),
            actual_revenue_cny=args.get("actual_revenue_cny"),
            actual_cost_cny=args.get("actual_cost_cny"),
            efficiency_gain=args.get("efficiency_gain"),
            lessons_learned=args.get("lessons_learned"),
            note=args.get("note"),
        )
        if not result.get("ok"):
            return ToolResult(
                ok=False, output="",
                error=result.get("error") or "记录失败",
            )
        outcome = result.get("outcome") or {}
        prefix = (
            "ℹ 没有字段变化 · 没写盘\n\n"
            if result.get("no_op")
            else "✓ 已记录 · 下次 mine_opportunities 时 OPUS 会读到这条反馈\n\n"
        )
        return ToolResult(ok=True, output=prefix + _format_outcome(outcome))

    except Exception as e:
        return ToolResult(ok=False, output="", error=f"record_outcome 失败: {e}")


SPEC = ToolSpec(
    name="record_outcome",
    description=(
        " · 闭环反馈 · 记录一个掘金机会的真实状态/产出。\n\n"
        "**调用时机**（OPUS 主动判断）:\n"
        "  - 用户 说'我不做 #1 因为...' → action=record, status=abandoned, decision_reason=...\n"
        "  - 用户 说'#2 我开干了' → action=record, status=in_progress\n"
        "  - 用户 说'#3 完成了·上线一周收入 800' → action=record, status=completed, actual_revenue_cny=800\n"
        "  - 用户 问'之前我都做了 / 拒了哪些机会' → action=list\n"
        "  - 用户 问'#N 我之前怎么决定的' → action=load\n\n"
        "**actions**:\n"
        "  - record · 写入/更新一条反馈（主路径）\n"
        "  - list · 列出所有反馈记录\n"
        "  - load · 读单条反馈\n\n"
        "**输入**:\n"
        "  - opp_id 或 opp_index（必填·指定哪个机会）\n"
        "  - status: not_started/in_progress/completed/abandoned\n"
        "  - decision_reason: 文本 · 为什么做/不做（**最关键字段** · 抓 用户 的能力边界）\n"
        "  - actual_revenue_cny / actual_cost_cny: 数字 · 完成后填\n"
        "  - efficiency_gain: 文字 · 节省了多少时间/带来了什么效率\n"
        "  - lessons_learned: 文字 · 经验教训\n"
        "  - note: 文字 · 自由备注（也会写进 updates 历史）\n\n"
        "**反馈机制**: outcomes 会自动塞进 mine_opportunities / analyze_feasibility 的 prompt·"
        "让 OPUS 越用越懂 用户·避免重复推已经拒过的机会。"
    ),
    tier=TIER_AUTO,
    input_schema={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["record", "list", "load"],
                "description": "record=记录反馈（默认） / list=列所有 / load=读单条",
            },
            "opp_id": {
                "type": "string",
                "description": "机会的 id（形如 opp-xxxxxx）",
            },
            "opp_index": {
                "type": "integer",
                "description": "机会的 1-based 序号 · 用户 说'第 N 个机会'即 N",
                "minimum": 1,
                "maximum": 20,
            },
            "status": {
                "type": "string",
                "enum": ["not_started", "in_progress", "completed", "abandoned"],
                "description": "机会的当前状态",
            },
            "opp_title": {
                "type": "string",
                "description": "机会标题快照·建议带上(尤其机会可能已被新一轮 mine 挤出当前列表时)·"
                               "这样执行反馈卡片永远有标题·不会显示成 '?'",
                "maxLength": 120,
            },
            "decision_reason": {
                "type": "string",
                "description": "为什么做/不做·**抓 用户 的真实能力边界**·LLM 下次跑会读到",
                "maxLength": 600,
            },
            "actual_revenue_cny": {
                "type": "number",
                "description": "实际收入·人民币·允许 0",
            },
            "actual_cost_cny": {
                "type": "number",
                "description": "实际成本·人民币·token + 订阅 + 时间换算",
            },
            "efficiency_gain": {
                "type": "string",
                "description": "增效部分·比如'每周省 4 小时'/'写文档速度 3 倍'",
                "maxLength": 400,
            },
            "lessons_learned": {
                "type": "string",
                "description": "经验教训·这条做完/失败后学到了什么",
                "maxLength": 600,
            },
            "note": {
                "type": "string",
                "description": "自由备注·会写进 updates 历史",
                "maxLength": 400,
            },
        },
        "required": ["action"],
    },
    run=_run,
    summarize=_summarize,
)
register_tool(SPEC)
