"""
agent_tools/recall_memory.py
============================

Daemonkey 跨会话记忆检索工具——调用 workers/memory_index.py 的 FTS5 引擎。

卷三十五 · wish-273374f6 · SQLite FTS5 全文检索。

档位：AUTO
  - 纯只读 · 不修改任何文件 · 不联网
  - Daemonkey 用这个工具查自己的长期记忆（BRO-NOTEBOOK / SELF-EVOLUTION / sessions）
"""

from __future__ import annotations

import re
from pathlib import Path

from . import TIER_AUTO, ToolResult, ToolSpec, register_tool

ROOT = Path(__file__).resolve().parent.parent


_SCOPE_LABELS = {
    "BRO-NOTEBOOK": "📖 BRO 画像",
    "SELF-EVOLUTION": "📝 Daemonkey 演化档案",
    "Daemonkey-MEMORIES": "🧬 Daemonkey 自传",
    "SKILL": "⚙️ 灵魂入口",
    "session": "💬 对话记录",
    "session_summary": "🧠 对话摘要",
    "skill": "🛠️ playbook (skill)",
}


def _label_for(source: str) -> str:
    """源标签 · 知识库文档 (doc:<id>) / 客户档案 (client:<id>) 特判成带标题的可读标签。"""
    if source and source.startswith("doc:"):
        try:
            from workers.knowledge_base import get_document

            meta = get_document(source[len("doc:"):])
            if meta:
                return f"📄 知识库 · {meta.get('title', source)}"
        except Exception:
            pass
        return "📄 知识库文档"
    if source and source.startswith("client:"):
        try:
            from workers.clients import get_client

            meta = get_client(source[len("client:"):])
            if meta:
                return f"👤 客户档案 · {meta.get('name', source)}"
        except Exception:
            pass
        return "👤 客户档案"
    return _SCOPE_LABELS.get(source, source)


def _snippet(text: str, limit: int = 140, hit_word: str = "") -> str:
    """把一块内容压成单行摘要 · 给 list 阶段省 token。

    wish-6ff9d89b · I2: 命中定位 — 传 hit_word 时·围绕首个命中词取窗口 (前 60 + 后 80)
    · 命中词中后部也能看见 (原来纯取开头·命中词在中后部时摘要零痕迹·选 id 会跳过真相关块)。
    hit_word 取 FTS5 查询词·多词时取第一个·找不到则退回首段。
    """
    one_line = " ".join((text or "").split())
    if hit_word and hit_word in one_line:
        idx = one_line.find(hit_word)
        start = max(0, idx - 60)
        end = min(len(one_line), idx + len(hit_word) + 80)
        seg = one_line[start:end]
        if start > 0:
            seg = "…" + seg
        if end < len(one_line):
            seg = seg + "…"
        # 高亮命中词 (单条内出现多次全标)
        seg = seg.replace(hit_word, f"**{hit_word}**")
        if len(seg) > limit + 20:
            seg = seg[: limit + 20] + "…"
        return seg
    return one_line[:limit] + ("…" if len(one_line) > limit else "")


def _summarize(args: dict) -> str:
    mode = (args.get("mode") or "list").strip().lower()
    if mode == "full" and args.get("ids"):
        return f"recall_memory  mode=full  ids={args.get('ids')}"
    query = str(args.get("query", ""))[:80]
    scope = args.get("scope", "all")
    return f"recall_memory  mode={mode}  scope={scope}  query={query!r}"


def _run(args: dict) -> ToolResult:
    mode = (args.get("mode") or "list").strip().lower()
    if mode not in ("list", "full", "agent"):
        return ToolResult(ok=False, output="", error=f"无效 mode: {mode!r}; 合法值: list, full, agent")

    try:
        from workers.memory_index import search, get_chunks_by_ids
    except ImportError as e:
        return ToolResult(ok=False, output="", error=f"无法加载 FTS5 引擎: {e}")

    # === 阶段零 · agent: 多轮自主检索 (wish-b8bd0c01 · ATM 41.9% 落地母体) ===
    if mode == "agent":
        question = (args.get("query") or "").strip()
        if not question:
            return ToolResult(ok=False, output="", error="mode=agent 需要 query 字段写检索问题")
        try:
            from workers.memory_agent import run_agent
            try:
                from workers.provider_configs import get_active_config
                cfg = get_active_config()
            except Exception:
                cfg = None
            if not cfg:
                return ToolResult(ok=False, output="", error="无可用模型配置 (provider_configs)")
            res = run_agent(
                question, cfg=cfg, lang="zh",
                use_embedding=bool(args.get("use_embedding", True)),
                max_tool_rounds=min(int(args.get("max_rounds", 15) or 15), 15),
            )
            out = res["answer"] + (f"\n\n---\n`agent 检索: {res['rounds']} 轮 · "
                                   f"prompt {res['prompt_tokens']} tok · completion {res['completion_tokens']} tok`")
            return ToolResult(ok=True, output=out[:16000])
        except Exception as e:
            return ToolResult(ok=False, output="", error=f"agent 检索失败: {e}")

    # === 阶段二 · full + ids: 按上一步 list 给的 id 取全文 ===
    if mode == "full" and args.get("ids"):
        ids = args.get("ids") or []
        if not isinstance(ids, list):
            return ToolResult(ok=False, output="", error="ids 必须是 id 数组，例如 [12, 47]")
        # I3 (wish-6ff9d89b) · full 阶段透传 context_window · 不再默认 12000
        _ctx = int(args.get("context_window", 8000))
        chunks = get_chunks_by_ids(ids, context_window=_ctx)
        if not chunks:
            return ToolResult(ok=True, output=f"没找到 id={ids} 对应的记忆块（可能已过期，重新 mode=list 搜一次）。")
        lines = [f"取到 {len(chunks)} 条全文：\n"]
        for chunk in chunks:
            label = _label_for(chunk.source)
            section_info = f" · {chunk.section}" if chunk.section else ""
            lines.append(f"### [id={chunk.id}] [{label}{section_info}]")
            if chunk.updated_at:
                lines.append(f"时间: {chunk.updated_at}")
            lines.append(f"```\n{chunk.content}\n```\n")
        output = "\n".join(lines)
        if len(output) > 16000:
            output = output[:15997] + "..."
        return ToolResult(ok=True, output=output)

    # === 走检索 (list 阶段 · 或 full 但没给 ids 的兜底全文搜) ===
    query = (args.get("query") or "").strip()
    if not query:
        return ToolResult(ok=False, output="", error="query 不能为空（或 mode=full 时给 ids 数组）")

    top_k = args.get("top_k", 5)
    scope = (args.get("scope") or "all").strip().lower()
    context_window = args.get("context_window", 8000)

    if scope not in ("all", "bro", "self", "sessions", "skill", "docs", "clients"):
        return ToolResult(
            ok=False, output="",
            error=f"无效 scope: {scope!r}; 合法值: all, bro, self, sessions, skill, docs, clients",
        )

    # I1 (wish-6ff9d89b) · list 模式用摘要窗口 (window_by='snippet') · 不被全文窗口压制条数
    #
    # 2026-08-19 · 语义通道从"无条件开"改成默认关 (实测依据见
    # data/learnings/2026-08-19-memory-scale-audit.md):
    #   对话原文占 97.7% 而向量覆盖率是 0% → 语义通道只能在剩下 2% 里挑 ·
    #   实测慢 20-70 倍 (7-27ms → 400-1487ms) · 前 3 名通常完全相同 ·
    #   唯一的差异常常是把第 4-5 名换成"只有标题没正文"的空壳 (即变差)。
    # 不焊死: 用户的数据分布可能跟我们不一样 (比如他给对话补过向量) ·
    # 设 OPUS_RECALL_EMBEDDING=1 就开回来。
    import os as _os
    _use_emb = _os.environ.get("OPUS_RECALL_EMBEDDING", "").strip().lower() in ("1", "true", "yes")
    # LLM 重排序 (0.9.6 · workers/memory_rerank.py): 开着就先捞大池再精排 · 关了维持原行为。
    # 保险丝在 rerank 内部: LLM 挂/解析失败/判全不相关 → 退回 FTS5 原序前 top_k。
    from workers import memory_rerank as _rr
    _pool = _rr.pool_size() if _rr.rerank_enabled() else top_k
    results = search(query, top_k=max(top_k, _pool), scope=scope, context_window=context_window,
                     window_by="snippet" if mode != "full" else "content",
                     use_embedding=_use_emb)
    results = _rr.rerank(query, results, top_k=top_k)

    if not results:
        return ToolResult(
            ok=True,
            output=f"没有找到与 '{query}' 相关的记忆片段 (scope={scope})。",
        )

    # I2 (wish-6ff9d89b) · 摘要命中定位: 取查询第一个实词做 hit_word · 摘要围绕它取窗口
    _hit = ""
    for _w in re.split(r"[\s,，。、]+", query or ""):
        if len(_w) >= 2 and _w.upper() not in ("AND", "OR", "NOT"):
            _hit = _w
            break

    # full 兜底 (没 ids 但 mode=full): 直接给全文 · 兼容老用法
    if mode == "full":
        lines = [f"找到 {len(results)} 条与 '{query}' 相关的记忆片段 (scope={scope}):\n"]
        for chunk in results:
            label = _label_for(chunk.source)
            section_info = f" · {chunk.section}" if chunk.section else ""
            lines.append(f"### [id={chunk.id}] [{label}{section_info}]")
            if chunk.updated_at:
                lines.append(f"时间: {chunk.updated_at}")
            lines.append(f"```\n{chunk.content}\n```\n")
        output = "\n".join(lines)
        if len(output) > 16000:
            output = output[:15997] + "..."
        return ToolResult(ok=True, output=output)

    # === 阶段一 · list: 只给 id + 标签 + 单行摘要 · 省 context ===
    lines = [
        f"找到 {len(results)} 条与 '{query}' 相关的记忆 (scope={scope})。下面是摘要列表，",
        "**想看哪条全文 → recall_memory(mode='full', ids=[挑中的 id])**；摘要够答就别取全文（省 token）：\n",
    ]
    for i, chunk in enumerate(results, 1):
        label = _label_for(chunk.source)
        section_info = f" · {chunk.section}" if chunk.section else ""
        when = f"  ({chunk.updated_at})" if chunk.updated_at else ""
        lines.append(f"{i}. [id={chunk.id}] [{label}{section_info}]{when}")
        lines.append(f"   {_snippet(chunk.content, hit_word=_hit)}")

    return ToolResult(ok=True, output="\n".join(lines))


SPEC = ToolSpec(
    name="recall_memory",
    description=(
        "搜索 Daemonkey 的长期记忆库（BRO-NOTEBOOK + SELF-EVOLUTION + Daemonkey-MEMORIES + SKILL + 历史对话记录）。"
        "用 SQLite FTS5 做全文检索，毫秒级返回。\n"
        "\n"
        "**两段式（省 token）**：\n"
        "1. 先 `mode=list`（默认）→ 拿到一串 `id + 单行摘要`。大多数「我有没有记过 X」看摘要就能答，别急着取全文。\n"
        "2. 摘要不够、确实要看某条原文 → `mode=full` + `ids=[挑中的 id]` 取全文。\n"
        "\n"
        "**调用时机**（Daemonkey 主动判断）：\n"
        "- BRO 问'上次我们聊过 X' / '我之前说过 Y 吗' / '你还记得 Z 吗'\n"
        "- BRO 提到某个过去的话题，你想确认自己有没有记录\n"
        "- 你需要引用 BRO-NOTEBOOK 里的具体画像条目时\n"
        "- 你需要查自己的演化历史（SELF-EVOLUTION）时\n"
        "- 任何不确定'这个信息是不是在灵魂层里'的时候——搜一下比猜更靠谱\n"
        "\n"
        "**scope**: all(全部) / bro(只看BRO画像) / self(Daemonkey自传+日记) / sessions(历史对话+蒸馏摘要) / skill(playbook · 卷四十六 II) / docs(私有文档知识库) / clients(客户档案备注)\n"
        "**查询语法**: FTS5 原生语法，支持 AND/OR/NOT、短语\"双引号\"、前缀* 等。"
    ),
    tier=TIER_AUTO,
    input_schema={
        "type": "object",
        "properties": {
            "mode": {
                "type": "string",
                "enum": ["list", "full", "agent"],
                "description": (
                    "list(默认)=只返 id+单行摘要·省 token·先用这个; "
                    "full=取全文·需配合 ids=[...] (上一步 list 给的 id)·或不给 ids 时按 query 直接全文搜(兼容老用法); "
                    "agent=多轮自主检索 (问题驱动·自动多工具循环·适合复杂/参照性提问·贵·日常先用 list)。"
                ),
                "default": "list",
            },
            "ids": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "mode=full 时·上一步 list 结果里挑中的记忆块 id 数组，例如 [12, 47]。",
            },
            "query": {
                "type": "string",
                "description": "搜索关键词。支持 FTS5 语法：AND/OR/NOT、\"短语\"、前缀*。中文直接写。mode=full+ids 时可省。",
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
                "enum": ["all", "bro", "self", "sessions", "skill", "docs", "clients"],
                "description": (
                    "搜索范围: all(全部) / bro(BRO画像) / self(Daemonkey自传+日记+SKILL) / "
                    "sessions(历史对话) / skill(playbook · 卷四十六 II wish-1c229865) / "
                    "docs(私有文档知识库 · 用户灌进来的资料/合同/PDF) / clients(客户档案备注)。默认 all。"
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
            "use_embedding": {
                "type": "boolean",
                "description": "仅 mode=agent 用 · 检索是否启用 embedding 语义通道 (默认 true)。",
                "default": True,
            },
            "max_rounds": {
                "type": "integer",
                "description": "仅 mode=agent 用 · 工具调用轮次上限 (1-15, 默认 15)。",
                "minimum": 1,
                "maximum": 15,
                "default": 15,
            },
        },
        "required": [],
    },
    run=_run,
    summarize=_summarize,
)

register_tool(SPEC)
