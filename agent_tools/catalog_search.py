"""延期工具目录检索。只读，不改 tools[]。"""
from __future__ import annotations

import json

from . import TIER_AUTO, ToolResult, ToolSpec, register_tool
from ._tool_catalog import search


def _run(args: dict) -> ToolResult:
    q = str(args.get("query") or "").strip()
    if not q:
        return ToolResult(ok=False, output="", error="catalog_search 需要 query")
    try:
        limit = int(args.get("limit") or 8)
    except (TypeError, ValueError):
        limit = 8
    hits = search(q, limit=limit)
    if not hits:
        return ToolResult(
            ok=True,
            output="没有匹配的延期工具。核心手（读/写/搜/终端/记忆）可直接调，不必搜。",
        )
    return ToolResult(
        ok=True,
        output=json.dumps(hits, ensure_ascii=False, indent=2),
    )


def _summarize(args: dict) -> str:
    return f"catalog_search {args.get('query') or ''}".strip()


SPEC = ToolSpec(
    name="catalog_search",
    description=(
        "Search deferred tools by capability or exact name. "
        "Core file/shell/memory tools are already in tools[] — do not search for those. "
        "Exact name returns full input_schema. Then catalog_call."
    ),
    tier=TIER_AUTO,
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Capability or exact tool name"},
            "limit": {"type": "integer", "description": "Max hits, default 8"},
        },
        "required": ["query"],
    },
    run=_run,
    summarize=_summarize,
)

register_tool(SPEC)
