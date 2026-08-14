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
    if action == "revise":
        return f"修订 playbook · {args.get('playbook_id', '?')}"
    return f"extract_playbook · {action}"


def _run(args: dict) -> ToolResult:
    from workers.playbooks import (
        save_playbook,
        search_playbooks,
        load_playbook,
        list_playbooks,
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

        if action == "feedback":
            # wish-0ecdbbd8 (墨言 094 wish-b6a837da) · 执行反馈闭环:
            #  命中即用后模型反馈结果 → 更新可信度 (success 刷新 verified_at · 失败 stale_hits+1)
            pid = str(args.get("playbook_id") or "").strip()
            success = bool(args.get("success"))
            note = str(args.get("note") or "").strip()
            if not pid:
                return ToolResult(ok=False, output="", error="feedback 需要 playbook_id")
            try:
                from workers.playbooks import record_playbook_result
                res = record_playbook_result(pid, success, note)
                if not res:
                    return ToolResult(ok=False, output="", error=f"playbook {pid} 不存在")
                st = res.get("stale_state", "正常")
                return ToolResult(
                    ok=True,
                    output=(f"✅ 已记录反馈 · {pid} · success={success} · 当前状态 [{st}] · "
                            f"stale_hits={res.get('stale_hits', 0)} · use_success={res.get('use_success', 0)} · "
                            f"use_fail={res.get('use_fail', 0)}" + (f" · note: {note}" if note else "")),
                )
            except Exception as e:
                return ToolResult(ok=False, output="", error=f"feedback 失败: {type(e).__name__}: {e}")

        # ── revise (墨言 094-2 · wish-2b43ffe7 · 反馈闭环内容链路 · 走通新路 → 修订原册) ──
        if action == "revise":
            pid_raw = args.get("playbook_id")
            if pid_raw is not None and not isinstance(pid_raw, str):
                return ToolResult(ok=False, output="", error=f"playbook_id 必须是字符串 · 收到 {pid_raw!r}")
            pid = (pid_raw or "").strip()
            if not pid:
                return ToolResult(ok=False, output="", error="playbook_id 必填")

            # 可改字段逐个校验类型
            for _k in ("title", "task_type", "steps", "confidence"):
                _v = args.get(_k)
                if _v is not None and not isinstance(_v, str):
                    return ToolResult(ok=False, output="", error=f"{_k} 必须是字符串 · 收到 {_v!r}")
            tags_raw = args.get("tags")
            if tags_raw is not None and not isinstance(tags_raw, list):
                return ToolResult(ok=False, output="", error=f"tags 必须是数组 · 收到 {tags_raw!r}")
            if tags_raw and not all(isinstance(x, str) for x in tags_raw):
                return ToolResult(ok=False, output="", error="tags 元素必须全是字符串")

            # 显式传空值 = 明确报错 · 防静默忽略让用户以为已清空 (P2-1)
            for _k in ("title", "task_type", "steps", "prerequisites", "pitfalls", "lessons", "confidence"):
                _v = args.get(_k)
                if _v is not None and (isinstance(_v, str) and not _v.strip()):
                    return ToolResult(ok=False, output="", error=f"{_k} 不能传空字符串 · 不支持'清空字段'语义 · 想清空请手动编辑 .md")

            # 至少传一个可改字段
            if all(args.get(k) is None for k in ("title", "task_type", "steps", "prerequisites", "pitfalls", "lessons", "tags", "confidence")):
                return ToolResult(ok=False, output="", error="revise 至少要传一个要改的字段 (title/task_type/steps/prerequisites/pitfalls/lessons/tags/confidence)")

            try:
                from workers.playbooks import revise_playbook
                res = revise_playbook(
                    playbook_id=pid,
                    title=args.get("title"),
                    task_type=args.get("task_type"),
                    steps=args.get("steps"),
                    prerequisites=args.get("prerequisites"),
                    pitfalls=args.get("pitfalls"),
                    lessons=args.get("lessons"),
                    tags=args.get("tags"),
                    confidence=args.get("confidence"),
                )
                if not res:
                    return ToolResult(ok=False, output="", error=f"playbook {pid} 不存在")
                if "error" in res:
                    return ToolResult(ok=False, output="", error=f"revise 中止: {res['error']}")
                prev = res.get("prev_stale_state", "正常")
                note_prev = f" · 状态 {prev} → {res.get('stale_state', '正常')}" if prev != res.get("stale_state", "正常") else ""
                return ToolResult(
                    ok=True,
                    output=(f"✅ 已修订 {res.get('title', pid)} · v{res.get('agentskills_version')} · "
                            f"状态 {res.get('stale_state', '正常')}{note_prev}"),
                )
            except Exception as e:
                return ToolResult(ok=False, output="", error=f"revise 失败: {type(e).__name__}: {e}")

        return ToolResult(
            ok=False, output="", error=f"unknown action: {action}. options: extract / import / search / load / list / feedback / revise"
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
        "  - feedback: report execution result of a playbook (playbook_id + success + note) → \n"
        "    updates confidence (wish-0ecdbbd8): success refreshes verified_at · failure bumps stale_hits → stale state.\n"
        "Once saved or imported, memory_index auto-indexes it and closure_check auto-recalls it on relevant "
        "tasks (no manual search needed). Output is plain markdown files, not new tool infrastructure."
    ),
    tier=TIER_CONFIRM,
    input_schema={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["extract", "import", "revise", "search", "load", "list", "feedback"],
                "description": "extract=save your own summary / import=absorb external skill MD / revise=update an existing playbook's content / search=find / load=read / list=all / feedback=report execution result",
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
