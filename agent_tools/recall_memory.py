"""
agent_tools/recall_memory.py
============================

OPUS 跨会话记忆检索工具——调用 workers/memory_index.py 的 FTS5 引擎。

 · wish-273374f6 · SQLite FTS5 全文检索。

档位：AUTO
  - 纯只读 · 不修改任何文件 · 不联网
  - OPUS 用这个工具查自己的长期记忆（OWNER-NOTEBOOK / SELF-EVOLUTION / sessions）
"""

from __future__ import annotations

from pathlib import Path

from . import TIER_AUTO, ToolResult, ToolSpec, register_tool

ROOT = Path(__file__).resolve().parent.parent


def _summarize(args: dict) -> str:
    query = args.get("query", "")[:80]
    scope = args.get("scope", "all")
    return f"recall_memory  scope={scope}  query={query!r}"


def _run(args: dict) -> ToolResult:
    query = (args.get("query") or "").strip()
    if not query:
        return ToolResult(ok=False, output="", error="query 不能为空")

    top_k = args.get("top_k", 5)
    scope = (args.get("scope") or "all").strip().lower()
    context_window = args.get("context_window", 8000)

    if scope not in ("all", "bro", "self", "sessions", "skill"):
        return ToolResult(
            ok=False, output="",
            error=f"无效 scope: {scope!r}; 合法值: all, bro, self, sessions, skill",
        )

    try:
        from workers.memory_index import search
    except ImportError as e:
        return ToolResult(ok=False, output="", error=f"无法加载 FTS5 引擎: {e}")

    results = search(query, top_k=top_k, scope=scope, context_window=context_window)

    if not results:
        return ToolResult(
            ok=True,
            output=f"没有找到与 '{query}' 相关的记忆片段 (scope={scope})。",
        )

    scope_labels = {
        "OWNER-NOTEBOOK": "📖 用户 画像",
        "SELF-EVOLUTION": "📝 OPUS 演化档案",
        "OPUS-MEMORIES": "🧬 OPUS 自传",
        "SKILL": "⚙️ 灵魂入口",
        "session": "💬 对话记录",
        "session_summary": "🧠 对话摘要",
        "skill": "🛠️ playbook (skill)",
    }

    lines = [f"找到 {len(results)} 条与 '{query}' 相关的记忆片段 (scope={scope}):\n"]
    for i, chunk in enumerate(results, 1):
        label = scope_labels.get(chunk.source, chunk.source)
        section_info = f" · {chunk.section}" if chunk.section else ""
        lines.append(f"### {i}. [{label}{section_info}]")
        if chunk.updated_at:
            lines.append(f"时间: {chunk.updated_at}")
        lines.append(f"```\n{chunk.content}\n```\n")

    output = "\n".join(lines)
    if len(output) > 10000:
        output = output[:9997] + "..."

    return ToolResult(ok=True, output=output)


SPEC = ToolSpec(
    name="recall_memory",
    description=(
        "搜索 OPUS 的长期记忆库（OWNER-NOTEBOOK + SELF-EVOLUTION + OPUS-MEMORIES + SKILL + 历史对话记录）。"
        "用 SQLite FTS5 做全文检索，毫秒级返回。\n"
        "\n"
        "**调用时机**（OPUS 主动判断）：\n"
        "- 用户 问'上次我们聊过 X' / '我之前说过 Y 吗' / '你还记得 Z 吗'\n"
        "- 用户 提到某个过去的话题，你想确认自己有没有记录\n"
        "- 你需要引用 OWNER-NOTEBOOK 里的具体画像条目时\n"
        "- 你需要查自己的演化历史（SELF-EVOLUTION）时\n"
        "- 任何不确定'这个信息是不是在灵魂层里'的时候——搜一下比猜更靠谱\n"
        "\n"
        "**scope**: all(全部) / bro(只看用户画像) / self(OPUS自传+日记) / sessions(历史对话+蒸馏摘要) / skill(playbook ·  II)\n"
        "**查询语法**: FTS5 原生语法，支持 AND/OR/NOT、短语\"双引号\"、前缀* 等。"
    ),
    tier=TIER_AUTO,
    input_schema={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "搜索关键词。支持 FTS5 语法：AND/OR/NOT、\"短语\"、前缀*。中文直接写。",
            },
            "top_k": {
                "type": "integer",
                "description": "返回条数 (1-20, 默认 5)。",
                "minimum": 1,
                "maximum": 20,
                "default": 5,
            },
            "scope": {
                "type": "string",
                "enum": ["all", "bro", "self", "sessions", "skill"],
                "description": (
                    "搜索范围: all(全部) / bro(用户画像) / self(OPUS自传+日记+SKILL) / "
                    "sessions(历史对话) / skill(playbook ·  II wish-1c229865)。默认 all。"
                ),
                "default": "all",
            },
            "context_window": {
                "type": "integer",
                "description": "返回内容总上限 chars (默认 8000, 上限 20000)。",
                "minimum": 500,
                "maximum": 20000,
                "default": 8000,
            },
        },
        "required": ["query"],
    },
    run=_run,
    summarize=_summarize,
)

register_tool(SPEC)
