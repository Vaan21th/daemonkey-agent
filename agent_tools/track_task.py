"""
agent_tools/track_task.py
=========================

任务账本工具 —— 让 OPUS 把"哪条路通了/死了/做了什么决策"沉淀进 data/ledgers/<slug>.json，
每轮自动回灌进上下文(见 workers/task_ledger + closure_check.ledger_hint)，抗"套娃"。

档位：AUTO
  记账是纯沉淀、无破坏(只往 data/ledgers/ 写 json)。误记也只是多一条，可改可删。

NLP 触发场景(OPUS 自己判断时机)：
  - 多步调试/搭建任务里，某方案【验证通了】→ track_task(action='note', kind='verified', ...)
  - 某思路【走死了】→ kind='ruledout'(带原因，下次别再走)
  - 定了个【关键决策】→ kind='decision'
  - 【开始/接手】一个任务(尤其新窗口续任务)→ track_task(action='open', task='...')先把旧账拉回来

用法：
  action='open'  · task=任务名 → 建/取该任务账本，设为本会话活跃账本，返回当前进展
  action='note'  · kind + text → 往活跃(或指定 task)账本追加一条
  action='list'  · 列出所有任务账本
"""
from __future__ import annotations

from . import TIER_AUTO, ToolResult, ToolSpec, current_session_id, register_tool


def _summarize(args: dict) -> str:
    action = (args.get("action") or "note").strip()
    if action == "open":
        return f"打开任务账本《{(args.get('task') or '?').strip()}》"
    if action == "list":
        return "列出任务账本"
    kind = (args.get("kind") or "note").strip()
    text = (args.get("text") or "").strip()
    preview = text[:40] + ("…" if len(text) > 40 else "")
    return f"记一条账本[{kind}]: {preview}"


def _run(args: dict) -> ToolResult:
    try:
        from workers import task_ledger as tl
    except Exception as e:
        return ToolResult(ok=False, output="", error=f"task_ledger 不可用: {e}")

    sid = current_session_id()
    action = (args.get("action") or "note").strip().lower()

    if action == "list":
        rows = tl.list_ledgers()
        if not rows:
            return ToolResult(ok=True, output="还没有任何任务账本。用 action='open' task='任务名' 开一本。")
        lines = ["任务账本:"]
        for r in rows:
            lines.append(f"  · {r['title']} (slug={r['slug']} · {r['count']} 条 · 更新 {r['updated']})")
        return ToolResult(ok=True, output="\n".join(lines))

    if action == "open":
        task = (args.get("task") or "").strip()
        if not task:
            return ToolResult(ok=False, output="", error="action='open' 需要 task(任务名)")
        led = tl.open_ledger(task, session_id=sid, title=task)
        body = tl.render_ledger(led)
        if body:
            out = f"已接上任务账本(本会话后续自动回灌):\n{body}"
        else:
            out = f"已开新任务账本《{led.get('title')}》(空)。后续用 note 记 ✓已验证/✗已排除/决策。"
        return ToolResult(ok=True, output=out)

    # 默认 note
    kind = args.get("kind") or "note"
    text = (args.get("text") or "").strip()
    if not text:
        return ToolResult(ok=False, output="", error="note 需要 text(记什么)")
    task = (args.get("task") or "").strip() or None
    led = tl.add_entry(sid, kind, text, slug=task, title=task)
    if led is None:
        return ToolResult(
            ok=False, output="",
            error="没有活跃账本 · 先 action='open' task='任务名' 开一本，或在 note 里带上 task 参数。",
        )
    norm = tl.resolve_kind(kind)
    return ToolResult(
        ok=True,
        output=f"已记进《{led.get('title')}》[{norm}] · 当前 {len(led.get('entries', []))} 条 · 后续每轮自动回灌。",
    )


SPEC = ToolSpec(
    name="track_task",
    description=(
        "任务账本 · 把多步任务里【已验证✓/已排除✗/待验证/关键决策】沉淀下来 · 每轮自动回灌进上下文 · "
        "防止(尤其开新窗口/长会话被压缩后)重复验证已通的、重走已排除的死路。\n"
        "时机(自己判断)：某方案验证通了 / 某思路走死了 / 定了关键决策 → 立刻 note 一条;"
        "开始或接手一个任务(尤其新窗口续上次)→ 先 open 把旧账拉回来。\n"
        "action='open'(task=任务名·建或取+设活跃+返回进展) / 'note'(kind+text·追加) / 'list'。"
    ),
    tier=TIER_AUTO,
    input_schema={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["open", "note", "list"],
                "description": "open=建/取任务账本并设为活跃; note=追加一条; list=列出所有账本。默认 note。",
            },
            "task": {
                "type": "string",
                "description": "任务名(open 必填 · note 可选·不填用当前活跃账本)。同名跨窗口共享一本。",
            },
            "kind": {
                "type": "string",
                "enum": ["verified", "ruledout", "pending", "decision", "note"],
                "description": "note 用: verified=✓验证通; ruledout=✗死路(带原因); pending=待验证; decision=关键决策; note=其它要点。",
            },
            "text": {
                "type": "string",
                "description": "note 的正文 · 一句话说清'什么通了/什么死了(为什么)/决定了什么'。",
            },
        },
        "required": ["action"],
        "additionalProperties": False,
    },
    run=_run,
    summarize=_summarize,
)

register_tool(SPEC)
