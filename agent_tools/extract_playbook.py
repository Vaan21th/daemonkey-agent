"""
agent_tools/extract_playbook.py
================================

卷三十七 · Playbook 抽取工具

OPUS 任务完成后 · 觉得「下次还能用」时 · 主动调这把操作模式
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
        search_playbooks,
        load_playbook,
        list_playbooks,
        mark_used,
    )

    action = (args.get("action") or "extract").lower().strip()

    try:
        if action == "extract":
            from workers.playbook_case import extract_action
            got = extract_action(args)
            if got.get("ok") and got.get("id"):
                try:
                    from workers.playbook_observe import note_extract
                    note_extract(got["id"], args.get("trials") or "")
                except Exception:
                    pass
            return ToolResult(ok=bool(got.get("ok")), output=got.get("output") or "", error=got.get("error") or "")

        if action == "distill":
            from workers.playbook_distill import distill_action
            got = distill_action(args)
            return ToolResult(ok=bool(got.get("ok")), output=got.get("output") or "", error=got.get("error") or "")

        if action == "distill_confirm":
            from workers.playbook_distill import confirm_action
            got = confirm_action(args)
            return ToolResult(ok=bool(got.get("ok")), output=got.get("output") or "", error=got.get("error") or "")

        if action == "peers":
            from workers.playbook_cluster import peers_action
            got = peers_action(args)
            return ToolResult(ok=bool(got.get("ok")), output=got.get("output") or "", error=got.get("error") or "")

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
            try:
                from workers.playbook_observe import note_loaded
                note_loaded(result["id"])
            except Exception:
                pass

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
            from workers.playbook_case import feedback_action
            got = feedback_action(args)
            return ToolResult(ok=bool(got.get("ok")), output=got.get("output") or "", error=got.get("error") or "")

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
            for _k in ("title", "task_type", "steps", "prerequisites", "pitfalls", "lessons", "confidence", "problem", "trials", "source"):
                _v = args.get(_k)
                if _v is not None and (isinstance(_v, str) and not _v.strip()):
                    return ToolResult(ok=False, output="", error=f"{_k} 不能传空字符串 · 不支持'清空字段'语义 · 想清空请手动编辑 .md")

            # 至少传一个可改字段
            if all(args.get(k) is None for k in ("title", "task_type", "steps", "prerequisites", "pitfalls", "lessons", "tags", "confidence", "problem", "trials", "source")):
                return ToolResult(ok=False, output="", error="revise 至少要传一个要改的字段")

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
                    problem=args.get("problem"),
                    trials=args.get("trials"),
                    source=args.get("source"),
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
            ok=False, output="", error=f"unknown action: {action}. options: extract / import / search / load / list / feedback / revise / distill / distill_confirm / peers"
        )

    except Exception as e:
        return ToolResult(ok=False, output="", error=f"extract_playbook error: {e}")


SPEC = ToolSpec(
    name="extract_playbook",
    description=(
        "任务结束后把经验存进 data/playbooks。extract 必填问题/步骤/试错过。失败用 feedback 写回原册。蒸馏先 distill 再 distill_confirm。不要写到别的文件夹。"
    ),
    tier=TIER_CONFIRM,
    input_schema={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["extract", "import", "revise", "search", "load", "list", "feedback", "distill", "distill_confirm", "peers"],
                "description": "extract 存个案 · import 接外部 · revise 改原册 · feedback 写回成败 · distill 出草稿 · distill_confirm 才入库",
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
                "description": "extract: 可照着做的步骤，2-5 步",
            },
            "problem": {
                "type": "string",
                "description": "extract: 这次在解什么问题（必填）",
            },
            "trials": {
                "type": "string",
                "description": "extract: 试过但没用的路；没有就写「尚无失败路径」",
            },
            "source": {
                "type": "string",
                "description": "extract/revise: 出处。可空，工具会补 session 和 file",
            },
            "playbook_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "distill: 同簇手册 id 列表，至少 2 个",
            },
            "how_now": {
                "type": "string",
                "description": "distill: 「现在怎么做」一页草稿，确认前不入库",
            },
            "draft_id": {
                "type": "string",
                "description": "distill_confirm: 草稿 id（pd-xxx）",
            },
            "proposal_id": {
                "type": "string",
                "description": "distill: 同簇提议 id（pp-xxx），补 how_now 才成草稿",
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
