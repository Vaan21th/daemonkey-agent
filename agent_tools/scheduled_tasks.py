# -*- coding: utf-8 -*-
"""agent_tools/scheduled_tasks.py · 定时任务工具 (0.5.0)

BRO 用自然语言说("每天9点扫AI行情" / "每周五提醒复盘" / "每2小时刷雷达")→
OPUS(LLM)把它解析成结构化 schedule + action → 调 create_scheduled_task 落档。
工具只落档 · 不做 NLP 解析(解析是 LLM 的活 · 符合 NLP First)。

落档后 workers/task_scheduler.py 的后台线程到点执行(pipeline 跑 LLM turn / reminder 发提醒)。
"""
from __future__ import annotations

from datetime import datetime

from . import TIER_AUTO, TIER_CONFIRM, ToolResult, ToolSpec, register_tool

_WD = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def _local(iso_utc) -> str:
    if not iso_utc:
        return "—"
    try:
        return datetime.fromisoformat(iso_utc).astimezone().strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(iso_utc)


def _sched_summary(sch: dict) -> str:
    t = sch.get("type")
    if t == "daily":
        return f"每天 {sch.get('time', '09:00')}"
    if t == "weekly":
        i = sch.get("weekday")
        wd = _WD[i] if isinstance(i, int) and 0 <= i < 7 else "周?"
        return f"每{wd} {sch.get('time', '09:00')}"
    if t == "interval":
        return f"每 {sch.get('interval_min', '?')} 分钟"
    if t == "once":
        return f"一次性 @ {_local(sch.get('once_at'))}"
    return t or "?"


def _fmt_task(t: dict) -> str:
    a = t.get("action") or {}
    head = (f"[{t.get('id')}] {'✅启用' if t.get('enabled') else '⏸停用'} · "
            f"{_sched_summary(t.get('schedule') or {})} · {a.get('kind')}")
    lines = [head]
    if t.get("raw_text"):
        lines.append(f"  原话: {t['raw_text']}")
    lines.append(f"  指令: {(a.get('prompt') or '')[:80]}")
    lines.append(f"  下次: {_local(t.get('next_run_at'))} · 已跑 {t.get('runs_completed', 0)} 次 · "
                 f"微信通知: {'是' if a.get('notify_wechat') else '否'}")
    if t.get("last_run_at"):
        lines.append(f"  上次: {_local(t.get('last_run_at'))} [{t.get('last_run_status')}] "
                     f"{(t.get('last_run_summary') or '')[:60]}")
    return "\n".join(lines)


def _build_schedule(args: dict) -> dict:
    return {
        "type": args.get("schedule_type"),
        "time": args.get("time"),
        "weekday": args.get("weekday"),
        "interval_min": args.get("interval_min"),
        "once_at": args.get("once_at"),
    }


# ── create ─────────────────────────────────────────────────────────────
def _create_run(args: dict) -> ToolResult:
    from workers import task_scheduler as ts
    action = {
        "kind": args.get("action_kind"),
        "prompt": args.get("prompt"),
        "notify_wechat": bool(args.get("notify_wechat", False)),
    }
    try:
        task = ts.add_task(args.get("raw_text") or args.get("prompt") or "",
                           _build_schedule(args), action,
                           enabled=bool(args.get("enabled", True)))
    except ValueError as e:
        return ToolResult(ok=False, output="", error=str(e))
    except Exception as e:
        return ToolResult(ok=False, output="", error=f"建任务失败: {type(e).__name__}: {e}")
    return ToolResult(ok=True, output="已建定时任务:\n" + _fmt_task(task))


SPEC_CREATE = ToolSpec(
    name="create_scheduled_task",
    description=(
        "建一个定时任务。 BRO 用自然语言说(\"每天早上9点帮我扫AI行情\" / \"每周五下午5点提醒我复盘\" / "
        "\"每2小时刷一次雷达\")→ 你(LLM)负责把它解析成结构化参数再调本工具——工具不做 NLP 解析。\n"
        "schedule_type: daily(每天·配 time) / weekly(每周·配 time+weekday) / interval(每N分钟·配 interval_min) / "
        "once(一次性·配 once_at)。\n"
        "time 是本地时区 HH:MM(BRO 说的'9点'=本地)。 weekday: 0=周一..6=周日。\n"
        "action_kind: pipeline(到点跑一个 LLM turn 执行 prompt·你会在 turn 里自己选工具) / "
        "reminder(到点用你的话提醒 BRO)。\n"
        "prompt: pipeline 型=执行目标(\"扫一遍AI行情并汇总\") · reminder 型=提醒内容(\"该复盘了\")。\n"
        "notify_wechat: 执行完是否微信通知 BRO(默认 false)。"
    ),
    tier=TIER_CONFIRM,
    input_schema={
        "type": "object",
        "properties": {
            "raw_text": {"type": "string", "description": "BRO 的原话(留档用·可选)"},
            "schedule_type": {"type": "string", "enum": ["daily", "weekly", "interval", "once"]},
            "time": {"type": "string", "description": "HH:MM 本地时区 · daily/weekly 用"},
            "weekday": {"type": "integer", "description": "0=周一..6=周日 · weekly 用"},
            "interval_min": {"type": "integer", "description": "间隔分钟 · interval 用"},
            "once_at": {"type": "string", "description": "ISO 时间 · once 用"},
            "action_kind": {"type": "string", "enum": ["pipeline", "reminder"]},
            "prompt": {"type": "string", "description": "执行目标 / 提醒内容"},
            "notify_wechat": {"type": "boolean"},
        },
        "required": ["schedule_type", "action_kind", "prompt"],
    },
    run=_create_run,
    summarize=lambda a: f"create_scheduled_task: {a.get('schedule_type')} · {a.get('action_kind')} · {(a.get('prompt') or '')[:40]}",
)
register_tool(SPEC_CREATE)


# ── list ───────────────────────────────────────────────────────────────
def _list_run(args: dict) -> ToolResult:
    from workers import task_scheduler as ts
    tasks = ts.list_tasks()
    if not tasks:
        return ToolResult(ok=True, output="还没有定时任务。 BRO 说一句\"每天X点做Y\"我就能建。")
    alive = ts.is_task_scheduler_alive()
    head = f"共 {len(tasks)} 个定时任务 · 调度线程: {'运行中' if alive else '未运行'}\n\n"
    return ToolResult(ok=True, output=head + "\n\n".join(_fmt_task(t) for t in tasks))


SPEC_LIST = ToolSpec(
    name="list_scheduled_tasks",
    description="列出所有定时任务(含状态 / 下次执行 / 上次结果)。 BRO 问\"有哪些定时任务\" / \"定时任务跑得怎么样\"时用。",
    tier=TIER_AUTO,
    input_schema={"type": "object", "properties": {}},
    run=_list_run,
    summarize=lambda a: "list_scheduled_tasks",
)
register_tool(SPEC_LIST)


# ── update (含开关) ─────────────────────────────────────────────────────
def _update_run(args: dict) -> ToolResult:
    from workers import task_scheduler as ts
    tid = (args.get("task_id") or "").strip()
    if not tid:
        return ToolResult(ok=False, output="", error="缺 task_id")
    schedule = _build_schedule(args) if args.get("schedule_type") else None
    action = None
    if args.get("prompt") is not None or args.get("action_kind") or "notify_wechat" in args:
        action = {}
        if args.get("action_kind"):
            action["kind"] = args["action_kind"]
        if args.get("prompt") is not None:
            action["prompt"] = args["prompt"]
        if "notify_wechat" in args:
            action["notify_wechat"] = bool(args["notify_wechat"])
    try:
        t = ts.update_task(tid, raw_text=args.get("raw_text"), schedule=schedule,
                           action=action, enabled=args.get("enabled"))
    except ValueError as e:
        return ToolResult(ok=False, output="", error=str(e))
    if not t:
        return ToolResult(ok=False, output="", error=f"没找到任务 {tid}")
    return ToolResult(ok=True, output="已更新:\n" + _fmt_task(t))


SPEC_UPDATE = ToolSpec(
    name="update_scheduled_task",
    description=(
        "改一个已有定时任务: 开关(enabled) / 改时间(schedule_*) / 改指令(prompt) / 改微信通知。 "
        "BRO 说\"停用那个雷达任务\"→ enabled=false; \"把复盘改到周六\"→ schedule_type=weekly weekday=5。 "
        "只传要改的字段。 先 list_scheduled_tasks 拿 task_id。"
    ),
    tier=TIER_CONFIRM,
    input_schema={
        "type": "object",
        "properties": {
            "task_id": {"type": "string"},
            "enabled": {"type": "boolean"},
            "raw_text": {"type": "string"},
            "schedule_type": {"type": "string", "enum": ["daily", "weekly", "interval", "once"]},
            "time": {"type": "string"},
            "weekday": {"type": "integer"},
            "interval_min": {"type": "integer"},
            "once_at": {"type": "string"},
            "action_kind": {"type": "string", "enum": ["pipeline", "reminder"]},
            "prompt": {"type": "string"},
            "notify_wechat": {"type": "boolean"},
        },
        "required": ["task_id"],
    },
    run=_update_run,
    summarize=lambda a: f"update_scheduled_task: {a.get('task_id')}",
)
register_tool(SPEC_UPDATE)


# ── delete ─────────────────────────────────────────────────────────────
def _delete_run(args: dict) -> ToolResult:
    from workers import task_scheduler as ts
    tid = (args.get("task_id") or "").strip()
    if not tid:
        return ToolResult(ok=False, output="", error="缺 task_id")
    if not ts.delete_task(tid):
        return ToolResult(ok=False, output="", error=f"没找到任务 {tid}")
    return ToolResult(ok=True, output=f"已删除定时任务 {tid}")


SPEC_DELETE = ToolSpec(
    name="delete_scheduled_task",
    description="删一个定时任务。 BRO 说\"删掉那个任务\"时用。 先 list_scheduled_tasks 拿 task_id。",
    tier=TIER_CONFIRM,
    input_schema={
        "type": "object",
        "properties": {"task_id": {"type": "string"}},
        "required": ["task_id"],
    },
    run=_delete_run,
    summarize=lambda a: f"delete_scheduled_task: {a.get('task_id')}",
)
register_tool(SPEC_DELETE)
