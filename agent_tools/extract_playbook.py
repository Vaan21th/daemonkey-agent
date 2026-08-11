"""
agent_tools/extract_playbook.py
================================

卷三十七 · Playbook 抽取工具

Daemonkey 任务完成后 · 觉得「下次还能用」时 · 主动调这把操作模式
抽成 data/playbooks/<slug>.md · 下次类似任务手动 search 加速。

档位：CONFIRM
  写入文件 · 但只写 playbook 子目录 · 不改外部系统

反 Hermes 设计:
  - 不每 15 步打断 · 任务完成后才抽
  - 200 字复盘就够了 · 不强求完整
  - 纯 markdown · 不是新 tool 体系

actions:
  - extract · 任务完成后抽一份 playbook
  - search · 找已有的 playbook（启动类似任务前用）
  - load · 读一份 playbook 的完整内容
  - list · 列出所有 playbook
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from . import TIER_CONFIRM, ToolResult, ToolSpec, register_tool


def _summarize(args: dict) -> str:
    action = (args.get("action") or "extract").lower()
    if action == "extract":
        title = args.get("title", "?")[:40]
        return f"extract_playbook · {title}"
    if action == "import":
        src = args.get("source_url") or args.get("source_path") or "粘贴全文"
        return f"导入外部 skill → playbook · {str(src)[:50]}"
    return f"extract_playbook · {action}"


def _run(args: dict) -> ToolResult:
    from workers.playbooks import (
        save_playbook,
        search_playbooks,
        load_playbook,
        list_playbooks,
        delete_playbook,
        mark_used,
    )

    action = (args.get("action") or "extract").lower().strip()

    try:
        # ── extract ──
        if action == "extract":
            title = (args.get("title") or "").strip()
            task_type = (args.get("task_type") or "general").strip()
            steps = (args.get("steps") or "").strip()
            if not title:
                return ToolResult(ok=False, output="", error="title 必填")
            if not steps:
                return ToolResult(ok=False, output="", error="steps 必填 · 至少写 2-3 步")

            result = save_playbook(
                title=title,
                task_type=task_type,
                steps=steps,
                prerequisites=(args.get("prerequisites") or "").strip(),
                pitfalls=(args.get("pitfalls") or "").strip(),
                lessons=(args.get("lessons") or "").strip(),
                tags=args.get("tags") or [],
            )

            return ToolResult(
                ok=True,
                output=(
                    "playbook saved\n"
                    f"  id: {result['id']}\n"
                    f"  path: {result['path']}\n"
                    f"  title: {title}\n"
                    f"  type: {task_type}\n"
                ),
            )

        # ── import (外部 skill MD → playbook · 闭环第②环「接住」) ──
        if action == "import":
            from workers.playbook_import import import_skill

            res = import_skill(
                content=(args.get("source_content") or "").strip(),
                url=(args.get("source_url") or "").strip(),
                path=(args.get("source_path") or "").strip(),
                hint=(args.get("hint") or "").strip(),
            )
            if not res.get("ok"):
                return ToolResult(ok=False, output="", error=res.get("error") or "import 失败")

            pb = res["playbook"]
            d = res["draft"]
            return ToolResult(
                ok=True,
                output=(
                    "skill 已导入为 playbook\n"
                    f"  来源: {res['source']}\n"
                    f"  id: {pb['id']}\n"
                    f"  title: {d['title']}\n"
                    f"  type: {d['task_type']}\n"
                    f"  tags: {', '.join(d.get('tags', []))}\n"
                    f"  path: {pb['path']}\n"
                    "\n已入库 · memory_index 自动索引 · 下次相关任务 closure_check 自动召回 "
                    "(按需用环已通 · 不用手动 search)。"
                ),
            )

        # ── search ──
        if action == "search":
            query = (args.get("query") or "").strip()
            task_type = (args.get("task_type") or "").strip() or None
            tag = (args.get("tag") or "").strip() or None
            limit = args.get("limit", 10)

            results = search_playbooks(query=query or None, task_type=task_type, tag=tag, limit=limit)
            if not results:
                return ToolResult(ok=True, output="no matching playbooks")

            lines = [f"found {len(results)} playbook(s):\n"]
            for pb in results:
                tags_str = ", ".join(pb.get("tags", []))
                lines.append(
                    f"- {pb['title']}  "
                    f"[{pb.get('task_type', '?')}]  "
                    f"used {pb.get('used_count', 0)}x  "
                )
                if tags_str:
                    lines.append(f"  tags: {tags_str}")
                lines.append(f"  id: {pb['id']}  slug: {pb['slug']}.md")
            return ToolResult(ok=True, output="\n".join(lines))

        # ── load ──
        if action == "load":
            result = load_playbook(
                playbook_id=args.get("playbook_id") or None,
                slug=args.get("slug") or None,
            )
            err = result.get("error")
            if err:
                return ToolResult(ok=False, output="", error=err)

            meta = result.get("meta", {})
            mark_used(result["id"])

            # wish-599c46bd (墨言 wish-bf460f7b) · 注入→使用转化追踪: load 即记一条 ·
            # 供 closure_check.inject_stats join 算转化率
            # I4: 绝对路径 (Path(__file__) 锚定项目根·不依赖 cwd) · current_session_id 拿不到记空
            try:
                from workers.safe_write import robust_open_append
                from agent_tools import current_session_id
                _used_path = Path(__file__).resolve().parents[1] / "data" / "runtime" / "inject_used.jsonl"
                _used_path.parent.mkdir(parents=True, exist_ok=True)
                _sid = ""
                try:
                    _sid = str(current_session_id() or "")
                    if _sid.startswith("t"):   # 线程 id 退化值不是真 session · 不记
                        _sid = ""
                except Exception:
                    _sid = ""
                with robust_open_append(_used_path) as _f:
                    _f.write(json.dumps(
                        {"ts": datetime.now(timezone.utc).isoformat(),
                         "playbook_id": result["id"], "session_id": _sid},
                        ensure_ascii=False,
                    ) + "\n")
            except Exception:
                pass

            return ToolResult(
                ok=True,
                output=(
                    f"# {result['title']}\n"
                    f"type: {meta.get('task_type', '?')}  |  "
                    f"used: {meta.get('used_count', 0)}x  |  "
                    f"created: {meta.get('created_at', '?')[:10]}\n\n"
                    f"{result['content']}"
                ),
            )

        # ── list ──
        if action == "list":
            results = list_playbooks()
            if not results:
                return ToolResult(ok=True, output="playbook library is empty. use action=extract after a reusable task.")

            lines = [f"playbook library: {len(results)} total\n"]
            for pb in results:
                lines.append(
                    f"- {pb['title']}  [{pb.get('task_type', '?')}]  "
                    f"used {pb.get('used_count', 0)}x  id={pb['id']}"
                )
            return ToolResult(ok=True, output="\n".join(lines))

        return ToolResult(
            ok=False, output="", error=f"unknown action: {action}. options: extract / import / search / load / list"
        )

    except Exception as e:
        return ToolResult(ok=False, output="", error=f"extract_playbook error: {e}")


SPEC = ToolSpec(
    name="extract_playbook",
    description=(
        "Post-task playbook extractor + external skill importer. "
        "After finishing a reusable task, call this to save the pattern as a markdown playbook in data/playbooks/. "
        "Anti-Hermes design: no mid-task interruption; extract only after task completion.\n"
        "Actions:\n"
        "  - extract: save a playbook you summarized yourself (requires title+steps)\n"
        "  - import: feed an EXTERNAL skill markdown (via source_content / source_url / source_path); "
        "the tool auto-normalizes it (LLM) into a playbook. This is the '接住' step of the "
        "discover -> import -> recall loop. Use when you found a useful skill (e.g. a GitHub SKILL.md / README) "
        "and want daemon to absorb it. Runs at CONFIRM tier, so the user nods before each import.\n"
        "  - search (find by query/task_type/tag), load (read full content), list (all playbooks).\n"
        "Once saved or imported, memory_index auto-indexes it and closure_check auto-recalls it on relevant "
        "tasks (no manual search needed). Output is plain markdown files, not new tool infrastructure."
    ),
    tier=TIER_CONFIRM,
    input_schema={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["extract", "import", "search", "load", "list"],
                "description": "extract=save your own summary / import=absorb external skill MD / search=find / load=read / list=all",
            },
            "title": {
                "type": "string",
                "description": "extract: playbook title, one-liner (required for extract)",
            },
            "task_type": {
                "type": "string",
                "description": "Task type for filtering. e.g. debug / deploy / diagnose / write / setup",
            },
            "steps": {
                "type": "string",
                "description": "extract: operation steps in markdown, 2-5 steps (required for extract)",
            },
            "prerequisites": {
                "type": "string",
                "description": "extract: prerequisites - tools/permissions/data needed (optional)",
            },
            "pitfalls": {
                "type": "string",
                "description": "extract: common pitfalls to avoid (optional)",
            },
            "lessons": {
                "type": "string",
                "description": "extract: lessons learned, under 200 chars (optional)",
            },
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "extract/search: tag list for discovery, e.g. ['ssh', 'nginx', 'debug']",
            },
            "query": {
                "type": "string",
                "description": "search: fuzzy match against title and tags",
            },
            "tag": {
                "type": "string",
                "description": "search: filter by single tag",
            },
            "playbook_id": {
                "type": "string",
                "description": "load: playbook id (pb-xxx format)",
            },
            "slug": {
                "type": "string",
                "description": "load: playbook file slug (without .md)",
            },
            "limit": {
                "type": "integer",
                "description": "search: max results (1-50, default 10)",
                "minimum": 1,
                "maximum": 50,
            },
            "source_content": {
                "type": "string",
                "description": "import: paste the full skill markdown here (most common · drop web_fetch'd content directly)",
            },
            "source_url": {
                "type": "string",
                "description": "import: a URL to fetch (e.g. a GitHub raw SKILL.md) · the tool fetches it itself",
            },
            "source_path": {
                "type": "string",
                "description": "import: a local .md file path",
            },
            "hint": {
                "type": "string",
                "description": "import: optional · what you mainly want to use this skill for (helps normalization)",
            },
        },
        "required": ["action"],
    },
    run=_run,
    summarize=_summarize,
)
register_tool(SPEC)
