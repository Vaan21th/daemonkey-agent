# -*- coding: utf-8 -*-
"""agent_tools/wakeups.py · 会话内延迟唤醒（计时器）工具 · wish-1b00ca00

Daemonkey 自己用：把"我 N 分钟后回来取结果"这件事交给 daemon 记着。
到点 daemon 会在这个会话里自动注入一轮（走 workers/proactive_call._run_bg_turn），
前端对话输入栏上方有倒计时卡，可见可取消。

跟 create_scheduled_task 的分工:
  - create_scheduled_task = 天/周级日程(长期反复·住在管理列表)
  - set_wakeup           = 本轮任务的一次性计时器(分钟级·跑完即销·住在对话栏)
分表存储是刻意的 —— 混一张表会让日程页被一次性计时器淹没。
"""
from __future__ import annotations

from . import TIER_AUTO, ToolResult, ToolSpec, current_session_id, register_tool


def _sid() -> str:
    """当前会话 id · 拿不到、或退化成线程 id(t12345)就返空 —— 那不是真 session。"""
    try:
        raw = str(current_session_id() or "").strip()
    except Exception:
        return ""
    return raw if raw.startswith("api-") else ""


# ── set ────────────────────────────────────────────────────────────────
def _set_run(args: dict) -> ToolResult:
    sid = _sid()
    if not sid:
        return ToolResult(ok=False, output="",
                          error="拿不到当前会话 id · 不能设唤醒(这活必须在真对话里做)")
    from workers import wakeups as wk
    w = wk.add_wakeup(sid, args.get("delay_sec"), args.get("label"), args.get("reason") or "",
                   args.get("kind") or "notify")
    if not w:
        return ToolResult(ok=False, output="", error="注册失败: delay_sec / label 不合法")
    mins = w["delay_sec"] / 60.0
    eta = f"{w['delay_sec']} 秒" if w["delay_sec"] < 90 else f"{mins:.1f} 分钟"
    return ToolResult(ok=True, output=(
        f"⏱ 已设延迟唤醒 [{w['id']}]\n"
        f"  {eta}后(约 {w['fire_at']})自动回到本会话 · 取「{w['label']}」\n"
        f"  到点我会自己去把结果拿回来汇报, 这之前你干别的都行。\n"
        f"  前端对话栏上方会显示倒计时 · 随时能取消。"))


SPEC_SET = ToolSpec(
    name="set_wakeup",
    description=(
        "设置延迟唤醒:N 秒后自动在当前会话注入一轮, 让你回来取结果并汇报。"
        "适合把活交给后台后自己去收(长跑测试/构建/下载/批处理)。"
        "跟 create_scheduled_task 别搞混: 那个是天/周级日程, 这个是一次性分钟级计时器。"),
    tier=TIER_AUTO,
    input_schema={
        "type": "object",
        "properties": {
            "delay_sec": {"type": "integer", "description": "N 秒后唤醒 · 最少 20 · 最多 24 小时"},
            "kind": {"type": "string", "description": "notify(默认·取结果/交作业·用户插话不影响·到点照醒) / ask(主动搭话类·用户已开口就不再打扰)"},
            "label": {"type": "string", "description": "一句话: 回来取什么结果(前端卡片显示)"},
            "reason": {"type": "string", "description": "给未来的自己的备注: 唤醒后具体做什么"},
        },
        "required": ["delay_sec", "label"],
    },
    run=_set_run,
    summarize=lambda a: f"set_wakeup: {a.get('delay_sec')}s · {(a.get('label') or '')[:30]}",
)
register_tool(SPEC_SET)


# ── cancel ─────────────────────────────────────────────────────────────
def _cancel_run(args: dict) -> ToolResult:
    from workers import wakeups as wk
    wid = str(args.get("wakeup_id") or "").strip()
    if not wid:
        armed = wk.list_armed(_sid())
        if not armed:
            return ToolResult(ok=True, output="当前会话没有待唤醒的计时器。")
        lines = ["当前会话的唤醒计时器(传 wakeup_id 取消某一条):"]
        for w in armed:
            lines.append(f"  [{w['id']}] 还剩 {w['remaining_sec']}s · {w['label']}")
        return ToolResult(ok=True, output="\n".join(lines))
    ok = wk.cancel_wakeup(wid)
    return ToolResult(ok=ok, output=(f"已取消延迟唤醒 [{wid}]" if ok else ""),
                      error=None if ok else f"没找到 [{wid}] 这条 armed 唤醒(可能已到点/已取消)")


SPEC_CANCEL = ToolSpec(
    name="cancel_wakeup",
    description="取消一条延迟唤醒。不传 wakeup_id 则列出当前会话所有待唤醒的计时器。",
    tier=TIER_AUTO,
    input_schema={
        "type": "object",
        "properties": {
            "wakeup_id": {"type": "string", "description": "要取消的 id(形如 wk-xxxxxxxxxx) · 可选"},
        },
    },
    run=_cancel_run,
    summarize=lambda a: f"cancel_wakeup: {a.get('wakeup_id') or '(列表)'}",
)
register_tool(SPEC_CANCEL)
