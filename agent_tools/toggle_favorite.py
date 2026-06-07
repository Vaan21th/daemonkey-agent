"""
agent_tools/toggle_favorite.py
==============================

 · 统一收藏 / 取消收藏 NLP 工具

支持收藏 2 类（雷达 ⭐ 走 tag_radar_item·这里不重复）：
  - opportunity · 掘金机会
  - feasibility · 可行性分析

档位：AUTO · 只写 data/favorites.json · 没什么风险

NLP 触发：
  - "收藏第 2 个机会" → action=toggle, kind=opportunity, ref_index=2
  - "把那个 MCP 可行性收藏起来" → action=toggle, kind=feasibility, query="MCP"
  - "看看我收藏了哪些机会" → action=list, kind=opportunity
  - "取消收藏 opp-xxx" → action=remove, kind=opportunity, ref_id="opp-xxx"
"""
from __future__ import annotations

from . import TIER_AUTO, ToolResult, ToolSpec, register_tool


_KIND_LABEL = {
    "opportunity": "💎 掘金机会",
    "feasibility": "📊 可行性分析",
}


def _summarize(args: dict) -> str:
    action = (args.get("action") or "toggle").lower()
    kind = args.get("kind") or "?"
    if action == "list":
        return f"toggle_favorite · list {kind}"
    ref = args.get("ref_id") or args.get("ref_index") or args.get("query") or "?"
    return f"toggle_favorite · {action} {kind} · {ref}"


def _resolve_opp(args: dict, kind: str) -> tuple[str | None, dict | None, str | None]:
    """从 args 解析出 opp 实体 · 适用 opportunity / feasibility 两种 kind
    返回 (ref_id, opp_record_or_None, error_msg)"""
    if args.get("ref_id"):
        ref_id = args["ref_id"].strip()
        # 反查 opportunity 拿快照
        try:
            from workers.opportunity_miner import load_opportunities
            opps = load_opportunities().get("opportunities") or []
            for o in opps:
                if o.get("id") == ref_id:
                    return ref_id, o, None
        except Exception:
            pass
        return ref_id, None, None  # 找不到也允许 · 用 hint 兜底

    if args.get("ref_index") is not None:
        try:
            idx = int(args["ref_index"])
        except (TypeError, ValueError):
            return None, None, f"ref_index 必须是整数·收到 {args['ref_index']!r}"
        try:
            from workers.opportunity_miner import load_opportunities
            opps = load_opportunities().get("opportunities") or []
        except Exception as e:
            return None, None, f"读机会失败: {e}"
        if idx < 1 or idx > len(opps):
            return None, None, f"ref_index 越界·范围 1-{len(opps)}"
        o = opps[idx - 1]
        return o.get("id"), o, None

    if args.get("query"):
        q = (args["query"] or "").strip().lower()
        if not q:
            return None, None, "query 不能为空"
        try:
            from workers.opportunity_miner import load_opportunities
            opps = load_opportunities().get("opportunities") or []
        except Exception as e:
            return None, None, f"读机会失败: {e}"
        matches = [o for o in opps if q in (o.get("title") or "").lower()]
        if not matches:
            return None, None, f"没找到标题含「{args['query']}」的机会"
        if len(matches) > 1:
            preview = "\n".join(
                f"  - {(m.get('title') or '?')[:60]} (id={m.get('id')})"
                for m in matches[:5]
            )
            return None, None, (
                f"匹配到 {len(matches)} 条 · 请用 ref_id 精确指定：\n{preview}"
            )
        o = matches[0]
        return o.get("id"), o, None

    return None, None, "需要 ref_id / ref_index / query 之一"


def _run(args: dict) -> ToolResult:
    from workers.favorites import (
        VALID_KINDS,
        list_favorites,
        remove_favorite,
        toggle_favorite,
    )

    action = (args.get("action") or "toggle").lower().strip()

    if action == "list":
        kind = args.get("kind")
        if kind and kind not in VALID_KINDS:
            return ToolResult(ok=False, output="",
                              error=f"kind 必须是 {sorted(VALID_KINDS)} 之一")
        data = list_favorites(kind=kind)
        items = data.get("items") or []
        if not items:
            return ToolResult(ok=True, output=f"没有收藏 · {kind or '全部'} 类目下空")
        by = data.get("by_kind") or {}
        lines = [
            f"# 收藏夹 · 共 {data['total']} 条",
            f"统计: {_KIND_LABEL.get('opportunity','opp')} {by.get('opportunity',0)} · "
            f"{_KIND_LABEL.get('feasibility','feas')} {by.get('feasibility',0)}",
            "",
        ]
        for it in items[:30]:
            label = _KIND_LABEL.get(it.get("kind", ""), it.get("kind", "?"))
            title = (it.get("title_snap") or "?")[:70]
            dom = it.get("domain") or "-"
            lines.append(f"- {label} · `{it.get('ref_id')}` · [{dom}] {title}")
            if it.get("note"):
                lines.append(f"    用户 备注：{it['note']}")
        return ToolResult(ok=True, output="\n".join(lines))

    kind = (args.get("kind") or "").strip()
    if kind not in VALID_KINDS:
        return ToolResult(ok=False, output="",
                          error=f"kind 必须是 {sorted(VALID_KINDS)}·收到 {kind!r}")

    ref_id, opp_rec, err = _resolve_opp(args, kind)
    if err:
        return ToolResult(ok=False, output="", error=err)
    if not ref_id:
        return ToolResult(ok=False, output="", error="解析不到 ref_id")

    title_snap = ""
    domain = ""
    if opp_rec:
        title_snap = (opp_rec.get("title") or "")[:200]
        domain = opp_rec.get("domain") or ""
    elif args.get("title_hint"):
        title_snap = (args["title_hint"] or "")[:200]

    if action == "remove":
        r = remove_favorite(kind, ref_id)
        return ToolResult(
            ok=True,
            output=(
                f"已取消收藏 · {_KIND_LABEL.get(kind, kind)} `{ref_id}`"
                if not r.get("no_op")
                else f"本来就没收藏 · no-op"
            ),
        )

    # toggle 主路径
    r = toggle_favorite(
        kind, ref_id,
        title_snap=title_snap, domain=domain, note=args.get("note"),
    )
    now = r.get("now_starred")
    icon = "⭐ 已收藏" if now else "○ 已取消收藏"
    return ToolResult(
        ok=True,
        output=(
            f"{icon} · {_KIND_LABEL.get(kind, kind)} `{ref_id}`\n"
            f"  标题：{title_snap or '（没标题快照）'}\n"
            f"  在收藏夹左侧栏「⭐ 收藏」入口可以一处看全 · 可能加这个入口"
        ),
    )


SPEC = ToolSpec(
    name="toggle_favorite",
    description=(
        " · 收藏 / 取消收藏掘金机会 + 可行性分析。\n\n"
        "**注意**：雷达条目的 ⭐ 走 `tag_radar_item` (feedback=starred) · 这里不重复。\n\n"
        "**调用时机**:\n"
        "  - 用户 说'收藏第 2 个机会' → action=toggle, kind=opportunity, ref_index=2\n"
        "  - 用户 说'把那个 MCP 可行性收藏起来' → action=toggle, kind=feasibility, query='MCP'\n"
        "  - 用户 说'看看收藏了什么' → action=list (默认全部) 或 action=list, kind=opportunity\n\n"
        "**actions**: toggle(默认) / remove / list\n"
        "**kinds**: opportunity / feasibility"
    ),
    tier=TIER_AUTO,
    input_schema={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["toggle", "remove", "list"],
                "description": "toggle=切换(默认) / remove=取消 / list=列",
            },
            "kind": {
                "type": "string",
                "enum": ["opportunity", "feasibility"],
                "description": "收藏类型 · opportunity=掘金机会 / feasibility=可行性分析",
            },
            "ref_id": {
                "type": "string",
                "description": "精确 id · opportunity 用 opp-xxx · feasibility 也用 opp-xxx",
            },
            "ref_index": {
                "type": "integer",
                "description": "在最近 load_opportunities() 输出里的 1-based 序号",
                "minimum": 1,
                "maximum": 50,
            },
            "query": {
                "type": "string",
                "description": "按标题模糊匹配 · 唯一命中时使用",
            },
            "title_hint": {
                "type": "string",
                "description": "标题兜底·当 ref_id 反查不到机会时存这个",
                "maxLength": 200,
            },
            "note": {
                "type": "string",
                "description": "可选备注",
                "maxLength": 200,
            },
        },
        "required": ["action"],
    },
    run=_run,
    summarize=_summarize,
)
register_tool(SPEC)
