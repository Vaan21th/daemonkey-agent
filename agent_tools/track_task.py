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
    if action == "plan":
        steps = args.get("steps") or []
        return f"列任务计划 · {len(steps)} 步"
    if action == "step":
        st = (args.get("status") or "done").strip()
        return f"推进第 {args.get('step')} 步 → {st}"
    kind = (args.get("kind") or "note").strip()
    text = (args.get("text") or "").strip()
    preview = text[:40] + ("…" if len(text) > 40 else "")
    return f"记一条账本[{kind}]: {preview}"


def _link_wish(led: dict, wish_id: str) -> tuple[bool, str]:
    """把账本挂到某条 wish 上(双向可见的那根线)。

    校验 wish 真存在 —— 不许挂到编造的 id 上(可追溯红线: 挂错了比不挂更坏,
    因为 wish 面板会显示一份根本不属于它的进度)。
    """
    try:
        from workers import task_ledger as tl
        from workers import wishlist
    except Exception as e:
        return False, f"wish 联动不可用: {e}"
    if wishlist.get_wish(wish_id) is None:
        return False, (f"没有这条 wish: {wish_id} · 先用 wish 工具查真实 id"
                       "(别凭印象填·挂错了 wish 面板会显示别人的进度)。")
    if led.get("wish_id") != wish_id:
        led["wish_id"] = wish_id
        tl.save_ledger(led)
    return True, f" · 已挂到 {wish_id}"


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

    if action in ("plan", "step"):
        try:
            from workers import task_plan as tp
        except Exception as e:
            return ToolResult(ok=False, output="", error=f"task_plan 不可用: {e}")
        task = (args.get("task") or "").strip() or None

        if action == "plan":
            steps = args.get("steps") or []
            if not isinstance(steps, list) or not steps:
                return ToolResult(ok=False, output="",
                                  error="action='plan' 需要 steps(字符串数组·按执行顺序)")
            # 没有活跃账本时用任务名开一本 · 没给任务名就没法落(必须有个 slug)
            if not task and not tl.active_slug(sid):
                return ToolResult(
                    ok=False, output="",
                    error="还没有活跃任务账本 · 请在 plan 里带上 task='任务名'(它同时是跨窗口续接的钥匙)。")
            led = tp.set_steps(sid, steps, slug=task, title=task)
            if led is None:
                return ToolResult(ok=False, output="", error="计划落盘失败(账本不存在且没给 task)")
            wish_note = ""
            wish = (args.get("wish") or "").strip()
            if wish:
                ok, wish_note = _link_wish(led, wish)
                if not ok:
                    # 计划在上一行就已经落盘了 —— 挂 wish 只是个可选的锦上添花·
                    # 挂错了报"整条失败"会让人以为计划没列成·于是重列一遍(真机实测:
                    # AI 因此连列三次·留下一本重复账本)。 降级成提示·别把主动作拖下水。
                    wish_note = f" · ⚠ wish 没挂上: {wish_note.lstrip(' ·')}"
            return ToolResult(
                ok=True,
                output=(f"已列计划《{led.get('title')}》· {len(led.get('steps') or [])} 步 ·"
                        f" 用户在对话框上方能看到进度。{wish_note}\n" + tp.render_steps(led)
                        + "\n做完一步就 action='step' 勾掉。"),
            )

        raw_i = args.get("step")
        try:
            i = int(raw_i)
        except (TypeError, ValueError):
            return ToolResult(ok=False, output="", error="action='step' 需要 step(第几步 · 1 开始的整数)")
        led = tp.update_step(sid, i, status=args.get("status") or "done",
                             text=args.get("text") or None, note=args.get("note") or None,
                             slug=task)
        if led is None:
            return ToolResult(ok=False, output="",
                              error=f"没找到第 {i} 步(或没有活跃计划) · 先 action='plan' 列计划。")
        p = tp.progress(led)
        tail = " · 全部步骤已结算 · 该收尾汇报了" if p["all_done"] else (
            f" · 下一步: 第 {(p.get('current') or {}).get('i')} 步 "
            f"{(p.get('current') or {}).get('text', '')}")
        return ToolResult(ok=True, output=f"第 {i} 步已更新 · 进度 {p['settled']}/{p['total']}{tail}")

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
        "任务账本+计划 · 多步任务的工作记忆。两条腿:【计划】= 有序步骤和进度(用户在对话框上方看得见)·"
        "【结论】= 已验证✓/已排除✗/关键决策。都每轮自动回灌·长会话被压缩或换窗口都不丢。\n"
        "**多步任务(3 步以上 / 预计要跑一阵的)开工前先 action='plan' 把步骤列出来** —— "
        "让用户看见你打算怎么干、干到哪了;也让你自己在长任务里不跑偏。\n"
        "做完一步立刻 action='step' 勾掉(别攒到最后)。计划发现不对就重列或把某步标 skip。\n"
        "时机: 某方案验证通了/走死了/定了关键决策 → action='note';"
        "开始或接手任务(尤其新窗口续上次)→ 先 action='open' 把旧账和旧计划拉回来。\n"
        "action='plan'(steps=步骤数组) / 'step'(step=第几步 + status) / "
        "'open'(task=任务名) / 'note'(kind+text) / 'list'。"
    ),
    tier=TIER_AUTO,
    input_schema={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["open", "note", "list", "plan", "step"],
                "description": (
                    "plan=列/重列有序步骤清单(多步任务开工先做这个); step=推进某一步的状态; "
                    "open=建/取任务账本并设为活跃; note=追加一条结论; list=列出所有账本。默认 note。"
                ),
            },
            "task": {
                "type": "string",
                "description": "任务名(open 必填 · plan 首次必填 · note/step 可选·不填用当前活跃账本)。同名跨窗口共享一本。",
            },
            "steps": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "仅 action='plan' 用 · 按执行顺序的步骤数组(每步一句话·动词开头·别写成大段)。"
                    "重列会整份替换·但文案没变的步骤会保留已有进度。上限 40 步。"
                ),
            },
            "step": {
                "type": "integer",
                "description": "仅 action='step' 用 · 第几步(1 开始 · 就是计划里显示的那个序号)。",
            },
            "status": {
                "type": "string",
                "enum": ["todo", "doing", "done", "skip"],
                "description": (
                    "仅 action='step' 用 · done=做完(默认) / doing=正在做 / todo=退回待做 / "
                    "skip=计划有变不做了(配 note 说原因)。注意: 某步【尝试失败】不是 skip · "
                    "那是结论·用 action='note' kind='ruledout' 记。"
                ),
            },
            "kind": {
                "type": "string",
                "enum": ["verified", "ruledout", "pending", "decision", "note"],
                "description": "note 用: verified=✓验证通; ruledout=✗死路(带原因); pending=待验证; decision=关键决策; note=其它要点。",
            },
            "text": {
                "type": "string",
                "description": "note 的正文(一句话说清什么通了/什么死了/决定了什么) · 或 action='step' 时改这步的文案。",
            },
            "note": {
                "type": "string",
                "description": "仅 action='step' 用 · 给这步加个备注(标 skip 时说清为什么不做了)。",
            },
            "wish": {
                "type": "string",
                "description": (
                    "仅 action='plan' 用 · 这份计划是在做哪条心愿单(wish-xxxxxxxx)。"
                    "做 wish 就带上 —— 计划条会显示归属·心愿单那边也能看到这活干到第几步了。"
                    "必须是真实存在的 wish id(不确定先查·别凭印象填)。"
                ),
            },
        },
        "required": ["action"],
        "additionalProperties": False,
    },
    run=_run,
    summarize=_summarize,
)

register_tool(SPEC)
