"""
agent_tools/replan.py
=====================

卡住解套 · "干净视角顾问"(抗套娃 · vibe coding 场景)。

问题(BRO 实测):猴子在一个多步任务里试了几条路都失败后,上下文被"失败叙事"污染,
陷入习得性无助 → 要么原地套娃、要么放弃。而把同样的需求丢给 Codex(同一个模型!),
Codex 给个执行方案,猴子照着就能跑。差异不在智商,在【干净上下文 + 规划姿态】。

这个工具就是把"去找 Codex"这一步内化:起一个【全新上下文】的子执行体当顾问——
  - 只读权限(能真去读用户 app 的代码 / grep / 搜网),但【绝不执行修改】;
  - 喂它:目标 + 任务账本的【已验证✓(别推翻)/ 已排除✗(别再走)】+ 当前卡点;
  - 它带着新视角把关键处看清,给一个【具体、按顺序的破局方案】回来;
  - 主执行体(单线程)照着做 —— 这就是同模型下"Codex 能、猴子不能"的解药。

比手动去 Codex 更强的地方:顾问【拿到了 ✗ 列表】,不会重提你已经踩死的坑。

档位:AUTO —— 纯只读 + 一次子推理 · 不改任何文件。卡住时就该顺手调,别加确认摩擦。
"""
from __future__ import annotations

from . import (
    REGISTRY,
    TIER_AUTO,
    ToolResult,
    ToolSpec,
    current_session_id,
    push_tool_progress,
    register_tool,
)

# 顾问的只读工具集(能看代码/搜证据·但动不了任何东西)· 运行时与 REGISTRY 取交集
_READONLY = (
    "read_file", "grep_files", "glob_files", "search_code", "outline_file",
    "web_search", "web_fetch", "pdf_read", "recall_memory", "list_apps", "list_flows",
)

_PLANNER_SYSTEM = (
    "你是被临时请来的一位【资深工程师 / 规划者】· 带着『全新视角』来帮一个卡住的任务破局。\n"
    "你有【只读】权限(可以 read_file / grep / 看代码 / 搜网确认事实)· 但【绝不执行任何修改】。\n\n"
    "会给你:任务目标、已经验证可行的(✓ 别推翻)、已经排除的死路(✗ 千万别再建议这些)、当前卡点。\n\n"
    "你的产出(一段就好·别寒暄):\n"
    "  1. 用最少的动作把关键处看清(需要就读几个文件 / grep / 搜一下·别漫无目的地翻)。\n"
    "  2. 如果卡点的【根因】你判断出来了·先点明它(这往往是当局者迷、旁观者清的地方)。\n"
    "  3. 给一个【具体、可落地、按顺序】的下一步方案——直接说『先做 A、再做 B』· 不要泛泛而谈。\n"
    "  4. 如果目标本身需要换思路·大胆提新路径(但不能是 ✗ 里已排除的)。\n"
    "【硬约束】只给方案·不要改文件、不要假装执行。让主执行体照着做。"
)

_MAX_ITER = 10   # 顾问最多看几轮(读几个文件+搜一下够破局了)


def _summarize(args: dict) -> str:
    blocker = (args.get("blocker") or "").strip()
    return f"请干净视角顾问破局: {blocker[:50]}" if blocker else "请干净视角顾问重规划"


def _ledger_block(sid: str, task: str | None) -> str:
    """把当前(或指定)任务账本的 ✓/✗/待验证 渲染出来喂给顾问 · 让它别重走死路。"""
    try:
        from workers import task_ledger as tl
        slug = (task or "").strip().lower() or tl.active_slug(sid)
        if not slug:
            return ""
        led = tl.get_ledger(slug)
        return tl.render_ledger(led) if led else ""
    except Exception:
        return ""


def _run(args: dict) -> ToolResult:
    blocker = (args.get("blocker") or "").strip()
    if not blocker:
        return ToolResult(ok=False, output="", error="blocker 必填:一句话说清卡在哪 / 试了什么失败了")

    goal = (args.get("goal") or "").strip()
    context = (args.get("context") or "").strip()
    task = (args.get("task") or "").strip() or None

    try:
        from daemon_runtime import RUNTIME
    except Exception as e:
        return ToolResult(ok=False, output="", error=f"RUNTIME 不可用: {e}")
    if getattr(RUNTIME, "client", None) is None:
        return ToolResult(ok=False, output="", error="RUNTIME.client 未就绪 (daemon 未完全启动?)")

    sid = current_session_id()
    ledger = _ledger_block(sid, task)

    parts = []
    if goal:
        parts.append(f"【任务目标】\n{goal}")
    parts.append(f"【当前卡点 / 已试失败】\n{blocker}")
    if ledger:
        parts.append(ledger)
    else:
        parts.append("(没有现成任务账本 · 只能基于卡点判断 · 建议顺带用 track_task 把已试的记下来)")
    if context:
        parts.append(f"【可以重点看的地方 / 补充背景】\n{context}")
    parts.append("请给出破局方案。")
    user_msg = "\n\n".join(parts)

    wl = {t for t in _READONLY if t in REGISTRY}

    from workers.subagent_runner import run_subagent

    push_tool_progress("🧭 请顾问破局", (goal or blocker)[:30])
    r = run_subagent(
        system=_PLANNER_SYSTEM,
        user_msg=user_msg,
        runtime=RUNTIME,
        tools_whitelist=wl,
        max_iterations=_MAX_ITER,
        persist=True,
        parent_session_id=sid,
        inject_budget_mandate=True,
    )

    push_tool_progress("✓ 顾问出方案", f"{r.iterations} 轮勘查")

    if not r.ok and not (r.text or "").strip():
        return ToolResult(ok=False, output="", error=f"顾问没能给出方案: {r.error or '(未知)'}")

    plan = (r.text or "").strip() or "(顾问没给出实质内容)"
    out = (
        "# 🧭 干净视角顾问的破局方案\n"
        "(全新上下文 + 只读勘查 · 已避开账本里的 ✗ 死路 · 下面照着推进·别再原地套娃)\n\n"
        + plan
        + f"\n\n_(顾问跑了 {r.iterations} 轮 · sub-{r.sub_session_id})_"
    )
    return ToolResult(ok=True, output=out)


SPEC = ToolSpec(
    name="replan",
    description=(
        "卡住解套 · 请一个【全新上下文的顾问】来破局(抗套娃)。\n"
        "同一个模型,换到干净上下文 + 规划姿态,往往能看清当局者迷的卡点——这就是"
        "『把需求丢给 Codex 就能跑』的原理,内化成一个工具。\n\n"
        "**什么时候调(别等 BRO 提)**:\n"
        "  - 一个多步任务里你试了 2+ 条路都失败 / 报错反复 / 你正想说『要不要换个方案』或想放弃时\n"
        "  - 看到上下文里任务账本提示『别硬撑』时\n"
        "  - 感觉自己在原地打转、被之前的失败带着走时\n"
        "**它做什么**:起一个干净上下文的子执行体当顾问 · 只读权限(会去读你 app 的代码/搜证据)· "
        "自动拿到任务账本的 ✓(别推翻)/✗(别再走)· 回一个具体按顺序的破局方案。它【不改任何文件】· "
        "方案由你(主执行体)单线程执行。\n"
        "**参数**: blocker(必填·卡在哪/试了啥失败) · goal(可选·任务目标) · context(可选·让它重点看的文件/背景)。\n"
        "**tier**: AUTO · 只读一次子推理 · 卡住就顺手调 · 不要因为怕麻烦而选择放弃。"
    ),
    tier=TIER_AUTO,
    input_schema={
        "type": "object",
        "properties": {
            "blocker": {
                "type": "string",
                "description": "必填 · 一句话说清卡在哪 / 试了什么失败了(顾问最需要这个)",
            },
            "goal": {
                "type": "string",
                "description": "可选 · 这个任务最终要达成什么(不填则用当前任务账本标题)",
            },
            "context": {
                "type": "string",
                "description": "可选 · 让顾问重点看的文件路径 / API / 补充背景 · 帮它更快看清",
            },
            "task": {
                "type": "string",
                "description": "可选 · 任务账本名(不填用当前活跃账本)· 决定喂哪份 ✓/✗ 给顾问",
            },
        },
        "required": ["blocker"],
    },
    run=_run,
    summarize=_summarize,
)

register_tool(SPEC)
