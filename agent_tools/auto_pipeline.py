"""
agent_tools/auto_pipeline.py
============================

 · OPUS 自主巡航

一句话跑完整链路：
  refresh_radar (抓所有信源·含 GitHub 同类工程)
    ↓
  generate_trends (LLM 提炼今日趋势)
    ↓
  mine_opportunities (LLM 找掘金点)

让 用户 不再"每一环都手动点一次"·一句"OPUS 你巡一圈" 就跑完全链路。

档位：CONFIRM
  跑完整链路要 ~60-180s + 多次 LLM 调用·应该给 用户 确认一下

NLP 触发：
  - 用户: "你巡一圈" / "OPUS 自主跑一遍" / "自动巡航" → 调本工具
  - 用户: "今天什么都没看·你帮我跑一遍" → 调本工具
"""
from __future__ import annotations

import logging
import time

from . import TIER_CONFIRM, ToolResult, ToolSpec, push_tool_progress, register_tool

logger = logging.getLogger("opus.auto_pipeline")


def _summarize(args: dict) -> str:
    skip = []
    if not args.get("refresh_radar", True): skip.append("radar")
    if not args.get("regen_trends", True):  skip.append("trends")
    if not args.get("mine_opps", True):     skip.append("opps")
    if skip:
        return f"auto_pipeline · 跳过 {','.join(skip)}"
    return "auto_pipeline · radar→trends→opps 全链路"


def _run(args: dict) -> ToolResult:
    do_radar = bool(args.get("refresh_radar", True))
    do_trends = bool(args.get("regen_trends", True))
    do_opps = bool(args.get("mine_opps", True))

    result: dict = {"steps": [], "ok": True}
    t0 = time.time()
    lines: list[str] = []
    lines.append("# 🛰️ OPUS 自主巡航 · 链路总览")
    lines.append("")

    # ─── Step 1 · refresh_radar ───
    push_tool_progress("📡 正在抓取信息雷达…", "1/3")
    if do_radar:
        from workers.info_radar import refresh_radar
        step_t = time.time()
        try:
            r = refresh_radar(progress=push_tool_progress)
            elapsed = int((time.time() - step_t) * 1000)
            result["steps"].append({
                "step": "refresh_radar",
                "ok": True,
                "elapsed_ms": elapsed,
                "items": r.get("total"),
                "ok_sources": r.get("ok_sources"),
                "total_sources": r.get("sources"),
            })
            lines.append(
                f"## ✓ Step 1 · 信息雷达 "
                f"· {r.get('ok_sources', '?')}/{r.get('sources', '?')} 源 OK "
                f"· 抓到 **{r.get('total', '?')}** 条 · {elapsed}ms"
            )
        except Exception as e:
            result["ok"] = False
            result["steps"].append({"step": "refresh_radar", "ok": False, "error": str(e)})
            lines.append(f"## ✗ Step 1 · 信息雷达 失败: {e}")
            lines.append("")
            return ToolResult(ok=False, output="\n".join(lines), error=str(e))
    else:
        lines.append("## ⊝ Step 1 · 信息雷达 (跳过)")
        result["steps"].append({"step": "refresh_radar", "skipped": True})
    lines.append("")

    # ─── Step 2 · generate_trends ───
    push_tool_progress("🌊 正在提炼今日趋势…", "2/3")
    if do_trends:
        from workers.trend_finder import generate_trends
        step_t = time.time()
        try:
            t = generate_trends()
            elapsed = int((time.time() - step_t) * 1000)
            n_trends = len(t.get("trends") or [])
            result["steps"].append({
                "step": "generate_trends",
                "ok": True,
                "elapsed_ms": elapsed,
                "trends": n_trends,
                "usage": t.get("usage"),
            })
            lines.append(
                f"## ✓ Step 2 · 今日趋势 · 提炼出 **{n_trends}** 个方向 · {elapsed}ms"
            )
            for tr in (t.get("trends") or [])[:5]:
                intensity = tr.get("intensity", 3)
                lines.append(f"  - 强度 {intensity}/5 · 《{tr.get('title', '?')}》")
        except Exception as e:
            result["ok"] = False
            result["steps"].append({"step": "generate_trends", "ok": False, "error": str(e)})
            lines.append(f"## ✗ Step 2 · 今日趋势 失败: {e}")
            lines.append("")
    else:
        lines.append("## ⊝ Step 2 · 今日趋势 (跳过)")
        result["steps"].append({"step": "generate_trends", "skipped": True})
    lines.append("")

    # ─── Step 3 · mine_opportunities ───
    push_tool_progress("💎 正在挖掘掘金机会…", "3/3")
    if do_opps:
        from workers.opportunity_miner import mine_opportunities
        step_t = time.time()
        try:
            o = mine_opportunities()
            elapsed = int((time.time() - step_t) * 1000)
            opps = o.get("opportunities") or []
            result["steps"].append({
                "step": "mine_opportunities",
                "ok": True,
                "elapsed_ms": elapsed,
                "opportunities": len(opps),
                "usage": o.get("usage"),
            })
            lines.append(
                f"## ✓ Step 3 · 掘金机会 · LLM 找出 **{len(opps)}** 个机会 · {elapsed}ms"
            )
            for op in opps[:5]:
                rec = op.get("recommend", 0)
                fit = op.get("fit", "?")
                dom = op.get("domain", "?")
                title = op.get("title", "?")
                lines.append(
                    f"  - {'⭐' * rec} [{dom}] {title} (fit={fit})"
                )
        except Exception as e:
            result["ok"] = False
            result["steps"].append({"step": "mine_opportunities", "ok": False, "error": str(e)})
            lines.append(f"## ✗ Step 3 · 掘金机会 失败: {e}")
            lines.append("")
    else:
        lines.append("## ⊝ Step 3 · 掘金机会 (跳过)")
        result["steps"].append({"step": "mine_opportunities", "skipped": True})

    lines.append("")
    total_elapsed = int((time.time() - t0) * 1000)
    lines.append(f"---")
    lines.append(f"总耗时 **{total_elapsed/1000:.1f}s** · ")
    if result["ok"]:
        lines.append(
            "**下一步建议**：用户 去 BI 看板看下新出炉的掘金机会"
            "·或者跟我说「展开第 N 个机会」让我做深度分析。"
        )
    else:
        lines.append("⚠ 部分步骤失败 · 链路没跑完 · 看上面的 ✗ 了解原因")

    return ToolResult(ok=result["ok"], output="\n".join(lines))


SPEC = ToolSpec(
    name="auto_pipeline",
    description=(
        " · OPUS 自主巡航 · 一句话跑完整链路。\n\n"
        "**调用时机** (主动 + 被动两条路)：\n"
        "  - 用户 说 '巡一圈' / '自主跑一遍' / '自动巡航' / '帮我看看今天有什么' → 调本工具\n"
        "  - 早上 用户 上线第一句问候 → 主动提议 '我巡一圈给你看?' 等他确认再调\n"
        "  - 每隔几小时·用户 没有明确任务时·OPUS 可以主动调一次（confirm）\n\n"
        "**链路**:\n"
        "  Step 1 · refresh_radar (抓 17+ 信源·含 GitHub 同类工程·30-60s)\n"
        "  Step 2 · generate_trends (LLM 提炼今日趋势·15-40s)\n"
        "  Step 3 · mine_opportunities (LLM 找掘金机会·20-50s)\n"
        "  总耗时 60-180s\n\n"
        "**红线**:\n"
        "  - 任一步骤失败不影响已完成的步骤·会返回 partial result\n"
        "  - 跑完后·用户 直接去 💎 掘金机会 / 🌊 今日趋势 / 📡 信息雷达 看新数据\n"
        "  - **不要在 用户 没空时跑**——这是 ~60-180s 的事·会占用 LLM 配额"
    ),
    tier=TIER_CONFIRM,
    input_schema={
        "type": "object",
        "properties": {
            "refresh_radar": {
                "type": "boolean",
                "description": "是否跑 Step 1 信息雷达刷新 · 默认 true",
            },
            "regen_trends": {
                "type": "boolean",
                "description": "是否跑 Step 2 趋势重新生成 · 默认 true",
            },
            "mine_opps": {
                "type": "boolean",
                "description": "是否跑 Step 3 掘金机会挖掘 · 默认 true",
            },
        },
    },
    run=_run,
    summarize=_summarize,
)
register_tool(SPEC)
