"""
agent_tools/session_search.py
==============================

 II · wish-2a92774d · session 聚合搜索 (hermes 风格 L2)

跟 recall_memory 的区别:
  - recall_memory · 通用 memory 搜索 (OWNER-NOTEBOOK + SELF-EVOLUTION + sessions)
    返 message-level 碎片 · 不区分 session 边界
  - session_search · 专搜 sessions/*.jsonl · 按 session 聚合 (1 session 多 hits)
    + 时间过滤 + session metadata · 用户 想"找跟 X 主题相关的对话"时用

档位: TIER_AUTO (纯读 · 不修改任何文件)

actions:
  - list   · 列最近 sessions (按 mtime / created_at / msg_count 排序)
  - search · 聚合搜索 · 按 session 分组返
  - get    · 拉取单个 session 完整 messages
  - stats  · sessions/ 全局统计 (个数 / 总 message / 索引覆盖率)
"""

from __future__ import annotations

from pathlib import Path

from . import TIER_AUTO, ToolResult, ToolSpec, register_tool


ROOT = Path(__file__).resolve().parent.parent


def _summarize(args: dict) -> str:
    action = (args.get("action") or "search").lower()
    if action == "search":
        q = (args.get("query") or "").strip()[:60]
        return f"session_search · 聚合搜 sessions/*.jsonl · query={q!r}"
    if action == "list":
        return f"session_search · list · 列最近 {args.get('limit', 30)} sessions"
    if action == "get":
        return f"session_search · get · 拉取 {args.get('session_id', '?')} 完整 messages"
    if action == "stats":
        return "session_search · stats · sessions/ 全局统计"
    return f"session_search · {action}"


def _run(args: dict) -> ToolResult:
    from workers.session_search import (
        list_sessions,
        get_session_messages,
        search_in_sessions,
        get_session_stats,
        get_session_meta,
    )

    action = (args.get("action") or "search").lower().strip()

    try:
        if action == "stats":
            s = get_session_stats()
            if not s.get("sessions_dir_exists"):
                return ToolResult(ok=True, output="(sessions/ 目录不存在 · 还没起任何对话)")
            idx = s.get("index", {})
            output = (
                f"# sessions/ 全局统计\n\n"
                f"- 总 session 数: **{s['total_sessions']}**\n"
                f"- 总 message 数: **{s['total_messages']}**\n"
                f"- 总大小: {s['size_mb']} MB ({s['total_bytes']} bytes)\n"
                f"- 最早 session: {s['earliest_session_at'] or '(未知)'}\n"
                f"- 最新 session: {s['latest_session_at'] or '(未知)'}\n"
                f"\n"
                f"## FTS5 索引覆盖\n"
                f"- 已 index: {idx.get('indexed', False)}\n"
                f"- session chunks: {idx.get('session_chunks', 0)}\n"
                f"- session tokens (估): {idx.get('session_tokens', 0)}\n"
                f"\n"
                f"_用 search 跑 query · 用 list 列最近 session · 用 get 拉单个 session 全 messages_"
            )
            return ToolResult(ok=True, output=output)

        if action == "list":
            limit = int(args.get("limit", 30))
            since = args.get("since")
            until = args.get("until")
            sort_by = (args.get("sort_by") or "mtime_desc").lower().strip()
            metas = list_sessions(limit=limit, since=since, until=until, sort_by=sort_by)
            if not metas:
                return ToolResult(ok=True, output="(没匹配的 session · sessions/ 可能为空 / 时间过滤过严)")
            lines = [
                f"# sessions/ 列表 ({len(metas)} 个 · sort_by={sort_by})",
                "",
            ]
            for m in metas:
                excerpt = m.first_user_msg.replace("\n", " ")[:100]
                lines.append(
                    f"- **{m.session_id}** · created={m.created_at[:19]} · {m.msg_count} msgs · {m.size_bytes // 1024}KB"
                )
                lines.append(f"  > {excerpt}")
            return ToolResult(ok=True, output="\n".join(lines))

        if action == "get":
            sid = (args.get("session_id") or "").strip()
            if not sid:
                return ToolResult(ok=False, output="", error="get 必须传 session_id")
            limit_msg = int(args.get("limit", 200))
            meta = get_session_meta(sid)
            if meta is None:
                return ToolResult(ok=False, output="", error=f"session 不存在: {sid}")
            msgs = get_session_messages(sid, limit=limit_msg)
            lines = [
                f"# session {sid}",
                "",
                f"- created: {meta.created_at}",
                f"- last_msg: {meta.last_msg_at}",
                f"- 总 message: {meta.msg_count} (本次返 {len(msgs)})",
                f"- 大小: {meta.size_bytes // 1024} KB",
                "",
                "---",
                "",
            ]
            for m in msgs:
                role = m["role"]
                ts = m["ts"][:19] if m["ts"] else ""
                content = m["content"]
                if len(content) > 2000:
                    content = content[:2000] + "...(截断)"
                lines.append(f"## [{role}] {ts}")
                lines.append("")
                lines.append(content)
                lines.append("")
            output = "\n".join(lines)
            # 防超大返回
            if len(output) > 30000:
                output = output[:29990] + "\n\n...(截断 · 用 limit 减少 message 数)"
            return ToolResult(ok=True, output=output)

        if action == "search":
            q = (args.get("query") or "").strip()
            if not q:
                return ToolResult(ok=False, output="", error="search 必须传 query")
            since = args.get("since")
            until = args.get("until")
            sid_filter = args.get("session_id")
            limit_sessions = int(args.get("limit_sessions", 10))
            top_per = int(args.get("top_messages_per_session", 3))
            max_total = int(args.get("max_total_messages", 30))

            results = search_in_sessions(
                query=q,
                since=since,
                until=until,
                session_id=sid_filter,
                limit_sessions=limit_sessions,
                top_messages_per_session=top_per,
                max_total_messages=max_total,
            )
            if not results:
                return ToolResult(
                    ok=True,
                    output=(
                        f"# 没有匹配的 session\n\n"
                        f"query: {q!r}\n"
                        f"since: {since or '(无)'} · until: {until or '(无)'}\n"
                        f"session_id 过滤: {sid_filter or '(全部)'}\n\n"
                        f"建议: 1) 拓宽时间窗口 · 2) 换 FTS5 query · 3) 用 action=list 看 sessions 概览"
                    ),
                )

            lines = [
                f"# session 聚合搜索结果",
                "",
                f"query: `{q}` · 命中 **{len(results)}** 个 session · "
                f"共 {sum(r.matched_count for r in results)} 条 message",
                "",
            ]
            for agg in results:
                m = agg.session
                lines.append(f"## {m.session_id} ({agg.matched_count} 条命中)")
                lines.append("")
                lines.append(f"- created: {m.created_at[:19]} · last_msg: {m.last_msg_at[:19]} · 总 msg: {m.msg_count}")
                excerpt = m.first_user_msg.replace("\n", " ")[:120]
                lines.append(f"- 首句 用户: > {excerpt}")
                lines.append("")
                lines.append("**top hits**:")
                lines.append("")
                for h in agg.hits:
                    ts_short = h.ts[:19] if h.ts else ""
                    content = h.content
                    if len(content) > 500:
                        content = content[:500] + "...(截断)"
                    lines.append(f"- [{h.role}] {ts_short} · rank={h.rank:.2f}")
                    lines.append(f"  > {content}")
                lines.append("")
                lines.append("---")
                lines.append("")
            lines.append("")
            lines.append("_想看某 session 完整对话: 调 `session_search` action=get + session_id=<id>_")
            return ToolResult(ok=True, output="\n".join(lines))

        return ToolResult(
            ok=False,
            output="",
            error=f"未知 action: {action} · 可选: search / list / get / stats",
        )

    except Exception as e:
        return ToolResult(ok=False, output="", error=f"session_search 内部错误: {e}")


SPEC = ToolSpec(
    name="session_search",
    description=(
        " II · wish-2a92774d · session 聚合搜索 (hermes 风格 L2)\n\n"
        "**跟 recall_memory 的区别**:\n"
        "  - recall_memory · 通用 memory 搜 (OWNER-NOTEBOOK + SELF-EVOLUTION + sessions) · 返 message 碎片\n"
        "  - session_search · 专搜 sessions/*.jsonl · 按 session 聚合 (1 session 多 hits) + 时间过滤\n\n"
        "**调用时机** (LLM 主动判断):\n"
        "  - 用户 问『上次我们聊过 X 是哪个 session』『5/24 那次对话讨论的什么』『XX 主题在哪些 session 提过』\n"
        "  - 用户 提某个具体话题 · 你想找历史上 OPUS 跟 用户 怎么谈过\n"
        "  - 你要拉某个 session 完整上下文还原决策路径 (action=get)\n"
        "  - 想看 sessions/ 整体概况 (action=stats)\n\n"
        "**actions**:\n"
        "  - search · query 聚合搜 · 按 session 分组返 + 每 session 前 N 命中\n"
        "  - list · 列最近 N 个 session · 含创建时间 / msg 数 / 首句 用户\n"
        "  - get · 拉取单个 session 全 messages (limit 默认 200)\n"
        "  - stats · sessions/ 全局统计 (个数 / 总 msg / FTS5 索引覆盖率)\n\n"
        "**FTS5 语法**: 支持 AND/OR/NOT · 短语用双引号 · 中文直接写 · 前缀 *\n\n"
        "**时间过滤**: since/until 接 ISO date (e.g. '2026-05-23' or '2026-05-23T18:00:00')"
    ),
    tier=TIER_AUTO,
    input_schema={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["search", "list", "get", "stats"],
                "description": "search=聚合搜 / list=列最近 / get=拉单 session / stats=全局统计",
            },
            "query": {
                "type": "string",
                "description": "search 时必填 · FTS5 query · 中文直接写",
            },
            "session_id": {
                "type": "string",
                "description": (
                    "get 时必填 · search 时可选 (限定单 session)。 格式: 'api-2026-05-26_014022_697694' (不带扩展名)"
                ),
            },
            "since": {
                "type": "string",
                "description": "时间过滤下限 · ISO date · search 与 list 用",
            },
            "until": {
                "type": "string",
                "description": "时间过滤上限 · ISO date · search 与 list 用",
            },
            "limit": {
                "type": "integer",
                "description": "list 时返多少 session (默认 30) · get 时返多少 message (默认 200)",
            },
            "sort_by": {
                "type": "string",
                "enum": ["mtime_desc", "created_desc", "msg_count_desc"],
                "description": "list 时排序 · 默认 mtime_desc",
            },
            "limit_sessions": {
                "type": "integer",
                "description": "search 时返多少 session (默认 10)",
            },
            "top_messages_per_session": {
                "type": "integer",
                "description": "search 时每 session 返多少 top message (默认 3)",
            },
            "max_total_messages": {
                "type": "integer",
                "description": "search 时全局 message 上限 (默认 30 · 防超大返回)",
            },
        },
        "required": ["action"],
    },
    run=_run,
    summarize=_summarize,
)

register_tool(SPEC)
