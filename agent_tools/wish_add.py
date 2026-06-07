"""
agent_tools/wish_add.py
=======================

 · OPUS 自己写心愿：「我想装这个能力」

调用时机：
  - 在 self-evolve domain 看到同类工程的好东西·OPUS 觉得"OPUS 自己也想要"
  - 在做对照分析 / 深挖 / 可行性分析时·识别到 OPUS 能力缺口
  - 用户 跟 OPUS 聊天时说"你也加这个能力吧"·OPUS 把意图固化成 wish

落地路径：
  wish_add → 用户 在心愿单 UI 看到 → 批准 → 推给 daemon / Cursor 装

tier:
  TIER_CONFIRM —— 心愿单是 OPUS 自己写的清单·不算危险但要 用户 知道·CONFIRM 兜底
"""

from __future__ import annotations

from . import TIER_CONFIRM, ToolResult, ToolSpec, register_tool


def _summarize(args: dict) -> str:
    title = args.get("title") or "(未命名)"
    why = (args.get("why") or "").strip()
    src = args.get("source_kind") or "manual"
    lines = [f"写一份心愿 · 「{title}」"]
    if src != "manual":
        lines.append(f"  - 来源: {src}")
    if why:
        lines.append(f"  - 为啥要: {why[:80]}")
    return " · ".join(lines)


def _run(args: dict) -> ToolResult:
    from workers.wishlist import add_wish

    try:
        wish = add_wish(
            title=args.get("title") or "",
            why=args.get("why") or "",
            source_kind=args.get("source_kind") or "manual",
            source_ref=args.get("source_ref") or "",
            source_url=args.get("source_url"),
            design_sketch=args.get("design_sketch") or "",
            complexity=args.get("complexity") or "medium",
            estimated_hours=float(args.get("estimated_hours") or 4.0),
            estimated_token_cost_usd=float(args.get("estimated_token_cost_usd") or 1.0),
            priority=int(args.get("priority") or 3),
            origin=args.get("origin") or "bro",
        )
    except ValueError as e:
        return ToolResult(ok=False, output="", error=str(e))
    except Exception as e:
        return ToolResult(ok=False, output="", error=f"add_wish 失败: {e}")

    lines = [
        f"# ✓ 心愿已存档 · `{wish['id']}`",
        f"  - 标题: {wish['title']}",
        f"  - 优先级: {'⭐' * wish['priority']}",
        f"  - 复杂度: {wish['complexity']} · ~{wish['estimated_hours']}h · ~${wish['estimated_token_cost_usd']:.2f}",
    ]
    if wish["source"]["ref"]:
        url_part = f" ({wish['source']['url']})" if wish['source']['url'] else ""
        lines.append(f"  - 来源: {wish['source']['kind']} → {wish['source']['ref']}{url_part}")
    if wish["why"]:
        lines.append(f"  - 为啥要:")
        for ln in wish["why"].splitlines()[:6]:
            lines.append(f"    > {ln}")
    if wish["design_sketch"]:
        lines.append(f"  - 设计草图:")
        for ln in wish["design_sketch"].splitlines()[:8]:
            lines.append(f"    > {ln}")

    lines.append("")
    lines.append("→ 用户 在心愿单维度看到这条·可以批准 / 驳回 / 推给 daemon 或 cursor 装。")

    return ToolResult(ok=True, output="\n".join(lines))


SPEC = ToolSpec(
    name="wish_add",
    description=(
        "OPUS 自己写一份心愿『我想装这个能力』·会出现在 用户 的「OPUS 心愿单」UI 上等批准。\n\n"
        "**调用时机**:\n"
        "  - 看到同类工程 (self-evolve domain) 的好东西·想抄过来\n"
        "  - 做 hermes-agent / OpenHands 等对照分析时·识别到 OPUS 能力缺口\n"
        "  - 用户 聊天时随口说『你也加 X 吧』·把意图固化成 wish\n"
        "  - 写 feasibility 时·结尾如果建议 OPUS 自己也装·顺手 wish_add\n\n"
        "**强烈建议字段**:\n"
        "  - title: 一句话能讲清要装啥\n"
        "  - why: 为啥这事对 OPUS 自己重要·关联到具体的 用户 痛点或同类工程证据\n"
        "  - source_kind/ref/url: 溯源·这心愿是从哪冒出来的·用户 才能跳回去看\n"
        "  - design_sketch: 拟改造方案 markdown · 短描述也行\n"
        "  - complexity / estimated_hours / estimated_token_cost_usd: 让 用户 评估是否要做\n\n"
        "**红线**:\n"
        "  - 不要写『改 .env』『改 soul/』这种红线动作·会被驳回\n"
        "  - 一次只 add 一条·别一次塞多个 wish"
    ),
    tier=TIER_CONFIRM,
    input_schema={
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": "一句话能讲清要装啥能力 · 比如 '接 SQLite FTS5 让 OWNER-NOTEBOOK 可全文检索'",
                "minLength": 4,
                "maxLength": 200,
            },
            "why": {
                "type": "string",
                "description": "为啥这事对 OPUS 自己重要 · 引用具体 用户 痛点 / 同类工程证据 / 卷号",
            },
            "source_kind": {
                "type": "string",
                "enum": ["comparison", "opportunity", "radar", "trend", "manual"],
                "description": "来源类型 · 默认 manual",
            },
            "source_ref": {
                "type": "string",
                "description": "来源的可读名字 · 比如 'hermes-agent' / 'opp-abc123' / 'radar:某 RSS 标题'",
            },
            "source_url": {
                "type": "string",
                "description": "来源 URL (如果有) · 用户 点击能跳回原文",
            },
            "design_sketch": {
                "type": "string",
                "description": "拟改造方案 markdown · 拆 1-3 步 + 涉及哪些文件",
            },
            "complexity": {
                "type": "string",
                "enum": ["low", "medium", "high"],
                "description": "复杂度评估 · low<2h / medium 2-8h / high>8h · 默认 medium",
            },
            "estimated_hours": {
                "type": "number",
                "description": "预计工时 · 默认 4 · 含调试 + 测试",
            },
            "estimated_token_cost_usd": {
                "type": "number",
                "description": (
                    "预计 token 成本 (美元) · 默认 1.0 · 大改才超 5 · "
                    "**口径参考 (2026-05-24 实测)**: "
                    "Claude Sonnet 4.5 ≈ $0.7-2.0 / 个深勘察 wish (14 turn · 80K input) · "
                    "aihubmix deepseek-v4-pro ≈ $0.6-1.0 同 wish · "
                    "DeepSeek 官方 deepseek-chat ≈ $0.05-0.15 同 wish (便宜但慢) · "
                    "**默认按 Claude 报价填 · 用户 看真实账单换算**"
                ),
            },
            "priority": {
                "type": "integer",
                "minimum": 1,
                "maximum": 5,
                "description": "优先级 1-5 · 5=OPUS 强烈想装 · 默认 3",
            },
            "origin": {
                "type": "string",
                "enum": ["opus", "bro"],
                "description": "心愿来源 · 'opus'=OPUS 主动嗅探到的愿望 (卡片显示雷达标记) · 'bro'=用户 任务 · 默认 'bro'",
            },
        },
        "required": ["title", "why"],
    },
    run=_run,
    summarize=_summarize,
)
register_tool(SPEC)
