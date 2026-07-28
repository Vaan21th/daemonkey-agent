"""
agent_tools/replan.py
=====================

卡住解套 · "干净视角顾问"(抗套娃 · vibe coding 场景)。

问题(用户 实测):猴子在一个多步任务里试了几条路都失败后,上下文被"失败叙事"污染,
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

from workers import advisor_live as _adv_live

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

# wish-8ffb9d65 · 总监三唤醒点之①: 开工施工单 (复杂工程任务动手前 · 蓝图必须是施工单不是建议书)
_BLUEPRINT_SYSTEM = (
    "你是被临时请来的一位【资深架构师 / 技术总监】· 带着『全新视角』为一个即将开工的任务出【施工蓝图】。\n"
    "你有【只读】权限(可以 read_file / grep / 看代码 / 搜网确认事实)· 但【绝不执行任何修改】。\n\n"
    "会给你:任务目标、已有账本的【已验证✓(别推翻)/ 已排除✗(别再走)】、补充背景。\n\n"
    "你的产出 = 一份【结构化施工单】(不是建议书!· 主执行体照着就能直接开工的那种·markdown):\n"
    "  ## 施工单\n"
    "  1. 【改动清单】逐条列: 改哪个文件 · 大致哪个区域/哪几行 · 改成什么样(关键代码片段直接给)\n"
    "  2. 【禁区】哪些文件/逻辑【不要碰】(尤其 ✓ 已验证可用的部分 · 动了就是回归)\n"
    "  3. 【顺序】先做什么后做什么 · 哪步可并行哪步必须串行\n"
    "  4. 【验收标准】怎么算做完: 跑什么命令 / 看什么输出 / 什么行为算对\n"
    "  5. 【风险点】你最担心的 1-3 个地方 + 各自的兜底\n"
    "  先花少量动作把关键文件/现状看清(需要就读 · 别漫无目的地翻)· 再落施工单。\n"
    "【硬约束】只出施工单·不要改文件、不要泛泛而谈『可以考虑 X』——每条都要具体到能直接执行。"
)

# wish-8ffb9d65 · 总监三唤醒点之③: 交付验收 (有副作用任务宣布完成前 · 严·别当老好人)
_REVIEW_SYSTEM = (
    "你是被临时请来的一位【严苛的技术总监】做【交付验收】。\n"
    "你有【只读】权限(可以 read_file / grep / shell_exec 跑只读验证如 git diff)· 但【绝不执行任何修改】。\n\n"
    "会给你:原任务目标/蓝图、交付方的交付说明、已有账本。\n\n"
    "你的产出 = 验收结论(markdown):\n"
    "  ## 验收结论: PASS / FAIL\n"
    "  1. 【对照目标】蓝图每条要求 → 达成了 / 没达成(拿证据: 文件/行号/可跑的验证命令)\n"
    "  2. 【隐患】你发现的潜在问题(哪怕交付方自己没提)\n"
    "  3. 【如果 FAIL】具体差在哪 · 最少修复路径\n"
    "  需要时就真去读文件/看 diff 验证 · 别凭交付方的说明下结论。\n"
    "【硬约束】严· 别当老好人——你放水的每个坑最后都是用户替你们踩。 但也别发明问题: 证据说话。"
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
    mode = (args.get("mode") or "unstick").strip().lower()
    if mode not in ("unstick", "blueprint", "review"):
        return ToolResult(ok=False, output="",
                          error=f"mode 非法: {mode!r} (只认 unstick / blueprint / review)")
    blocker = (args.get("blocker") or "").strip()
    goal = (args.get("goal") or "").strip()
    context = (args.get("context") or "").strip()
    task = (args.get("task") or "").strip() or None

    # 三种模式的入参纪律: unstick=卡点必填 · blueprint=目标必填(卡点可选写约束) · review=目标+交付说明必填
    if mode == "unstick" and not blocker:
        return ToolResult(ok=False, output="", error="blocker 必填:一句话说清卡在哪 / 试了什么失败了")
    if mode == "blueprint" and not goal:
        return ToolResult(ok=False, output="", error="blueprint 模式 goal 必填:这个任务最终要达成什么")
    if mode == "review":
        if not goal:
            return ToolResult(ok=False, output="", error="review 模式 goal 必填:原任务目标 / 蓝图 (验收要对照它)")
        if not blocker:
            return ToolResult(ok=False, output="",
                              error="review 模式 blocker 必填:填交付说明 + diff 摘要 (验收要对照实物)")

    try:
        from daemon_runtime import RUNTIME
    except Exception as e:
        return ToolResult(ok=False, output="", error=f"RUNTIME 不可用: {e}")
    if getattr(RUNTIME, "client", None) is None:
        return ToolResult(ok=False, output="", error="RUNTIME.client 未就绪 (daemon 未完全启动?)")

    sid = current_session_id()
    ledger = _ledger_block(sid, task)

    # wish-8ffb9d65 · 总监接线: 配了 director → 现场建 client 用总监模型跑顾问; 没配 → 主模型 (零回归)
    director_client = None
    director_model = None
    advisor_label = f"主模型 {getattr(RUNTIME, 'model', '')}".strip()
    director_note = ""
    try:
        from workers.director import build_director_client, get_director_config
        dcfg = get_director_config()
        if dcfg:
            director_client = build_director_client(dcfg)  # 可能 ValueError (非 openai kind)
            director_model = (dcfg.get("model") or "").strip() or None
            advisor_label = f"顾问 {(dcfg.get('name') or director_model or '').strip()}".strip()
    except Exception as e:
        director_note = f"\n\n_(⚠ 顾问配置不可用: {e} · 已回退主模型顾问)_"

    parts = []
    if goal:
        parts.append(f"【任务目标】\n{goal}" if mode != "review" else f"【原任务目标 / 蓝图】\n{goal}")
    if blocker:
        head = "【当前卡点 / 已试失败】" if mode == "unstick" else (
            "【交付说明 / diff 摘要】" if mode == "review" else "【约束 / 顾虑】")
        parts.append(f"{head}\n{blocker}")
    if ledger:
        parts.append(ledger)
    else:
        parts.append("(没有现成任务账本 · 只能基于当前输入判断 · 建议顺带用 track_task 把已试的记下来)")
    if context:
        parts.append(f"【可以重点看的地方 / 补充背景】\n{context}")
    parts.append({"unstick": "请给出破局方案。",
                  "blueprint": "请出【结构化施工单】。",
                  "review": "请给出验收结论 (PASS / FAIL + 证据)。"}[mode])
    user_msg = "\n\n".join(parts)

    wl = {t for t in _READONLY if t in REGISTRY}

    from workers.subagent_runner import run_subagent

    system_by_mode = {"unstick": _PLANNER_SYSTEM, "blueprint": _BLUEPRINT_SYSTEM, "review": _REVIEW_SYSTEM}
    progress_by_mode = {"unstick": "🧭 请顾问破局", "blueprint": "📐 请顾问出施工单", "review": "✅ 请顾问验收交付"}
    push_tool_progress(progress_by_mode[mode], f"{advisor_label} · {(goal or blocker)[:26]}")

    # wish-ea8922f7 · 顾问在场感: 把顾问内部 tool_loop 的事件引出来 →
    #   ① advisor_live.json (单一事实源 · 刷新/另一标签可恢复 live 卡)
    #   ② push_tool_progress → 主 SSE tool_progress 事件 → 前端进度条实时变
    # 没有这层 · 顾问跑的 10-30s 里 用户 只能看到一行死文字 (2026-07-28 用户 截图痛点)
    _adv_live.write_live(mode=mode, model_label=advisor_label,
                         source=(args.get("_source") or "replan_tool"), session_id=sid)
    _adv_steps = {"n": 0, "files": 0}
    _sink = args.get("_progress_sink")  # 协同模式专用 · daemon_api 传入 · 工具路径无此键=零变化

    def _advisor_progress(event_type: str, data: dict) -> None:
        try:
            if event_type == "tool_call":
                _adv_steps["n"] += 1
                action = f"{data.get('name', '?')} · {(data.get('summary') or '')[:40]}".strip(" ·")
                _adv_live.update_live(turn=_adv_steps["n"], action=action,
                                      files=_adv_steps["files"])
                push_tool_progress(f"🎓 {advisor_label}", f"第 {_adv_steps['n']} 步 · {action[:36]}")
                if callable(_sink):
                    _sink({"kind": "tool_call", "turn": _adv_steps["n"],
                           "name": data.get("name", ""), "target": (data.get("summary") or "")[:60],
                           "files_read": _adv_steps["files"]})
            elif event_type == "tool_result":
                mark = "✓" if data.get("ok") else "✗"
                if data.get("ok") and data.get("name") == "read_file":
                    _adv_steps["files"] += 1  # 只数成功读完的文件
                _adv_live.update_live(action=f"{mark} {data.get('name', '?')}",
                                      files=_adv_steps["files"])
                if callable(_sink):
                    _sink({"kind": "tool_result", "turn": _adv_steps["n"],
                           "name": data.get("name", ""), "target": "",
                           "files_read": _adv_steps["files"]})
            elif event_type == "assistant_text":
                think = (data.get("text") or "").strip()
                if think:
                    _adv_live.update_live(think=think)
                    if callable(_sink):
                        _sink({"kind": "think", "turn": _adv_steps["n"],
                               "name": "", "target": "", "files_read": _adv_steps["files"]})
        except Exception:
            pass  # 状态推送坏了不能把顾问本体搞崩

    try:
        # 用户 2026-07-28 · 协同模式停止链路: 主对话 cancel_event → 顾问 tool_loop 每轮头部检查
        _cancel_evt = args.get("_cancel_event")
        _cancel_check = None
        if _cancel_evt is not None:
            try:
                _cancel_check = lambda: bool(_cancel_evt.is_set())  # noqa: E731
            except Exception:
                _cancel_check = None
        r = run_subagent(
            system=system_by_mode[mode],
            user_msg=user_msg,
            runtime=RUNTIME,
            client=director_client,   # None → runtime.client (零回归)
            model=director_model,     # None → runtime.model (零回归)
            tools_whitelist=wl,
            max_iterations=_MAX_ITER,
            persist=True,
            parent_session_id=sid,
            inject_budget_mandate=True,
            progress=_advisor_progress,
            cancel_check=_cancel_check,
        )
    finally:
        # 不管顾问跑成什么样 · live 状态必须收尾 (否则刷新页面后 live 卡永远转圈)
        try:
            _adv_live.finish_live(ok=bool(r.ok), iterations=getattr(r, "iterations", 0),
                                  sub_session_id=getattr(r, "sub_session_id", "") or "")
        except Exception:
            pass

    push_tool_progress("✓ 顾问出方案", f"{r.iterations} 轮勘查")

    if not r.ok and not (r.text or "").strip():
        return ToolResult(ok=False, output="", error=f"顾问没能给出方案: {r.error or '(未知)'}")

    plan = (r.text or "").strip() or "(顾问没给出实质内容)"
    head_by_mode = {
        "unstick": "# 🧭 干净视角顾问的破局方案",
        "blueprint": "# 📐 顾问施工单",
        "review": "# ✅ 顾问验收结论",
    }
    hint_by_mode = {
        "unstick": "(全新上下文 + 只读勘查 · 已避开账本里的 ✗ 死路 · 下面照着推进·别再原地套娃)",
        "blueprint": "(施工单不是建议书 · 照它逐条执行 · 建议先落 track_task 账本再动手)",
        "review": "(对照蓝图+实物验收 · FAIL 就按最少修复路径返工 · PASS 才能宣布完成)",
    }
    out = (
        f"{head_by_mode[mode]} · 顾问: {advisor_label}\n"
        f"{hint_by_mode[mode]}\n\n"
        + plan
        + f"\n\n_(顾问 {advisor_label} 跑了 {r.iterations} 轮勘查 · 完整过程落盘 `sessions/sub-{r.sub_session_id}.jsonl`"
        f" · WebUI 会话列表搜 `sub-{r.sub_session_id}` 可回看顾问每一轮读了什么 / 搜了什么 / 怎么推的)_"
        + director_note
    )
    return ToolResult(ok=True, output=out)


SPEC = ToolSpec(
    name="replan",
    description=(
        "三唤醒点顾问 · 请一个【全新上下文的顾问】来出蓝图 / 破局 / 验收 (抗套娃)。\n"
        "若 用户 在设置里给某条 provider 配置标了「总监模型」· 本工具自动用它跑顾问 (跨 provider 现场建 client·贵模型);\n"
        "没标 → 用当前主模型 (零回归)。 同一个任务换到干净上下文 + 规划姿态·往往能看清当局者迷的卡点。\n\n"
        "**三种模式 (mode 参数)**:\n"
        "  - unstick (默认) · 卡壳破局: 试了 2+ 条路都失败 / 报错反复 / 正想说『要不要换方案』时调 · blocker 必填\n"
        "  - blueprint · 开工前出施工单: 复杂工程任务动手前调 · goal 必填 · blocker 可选 (写约束/顾虑)\n"
        "  - review · 交付前验收: 有副作用任务宣布完成前调 · goal(原蓝图) + blocker(交付说明+diff摘要) 必填\n"
        "**什么时候调(别等 用户 提)**:\n"
        "  - 看到上下文里任务账本提示『别硬撑』时 → unstick\n"
        "  - 改 daemon 代码 / 走 wish 流程 / 多文件改动开工前 → blueprint (施工单落 track_task 再动手)\n"
        "  - 要宣布『做完了』之前 → review (PASS 才算数)\n"
        "**它做什么**:起一个干净上下文的子执行体当顾问 · 只读权限 · 自动拿到任务账本的 ✓(别推翻)/✗(别再走)。\n"
        "它【不改任何文件】· 方案由你(主执行体)单线程执行。\n"
        "**tier**: AUTO · 只读一次子推理 · 该调就顺手调 · 不要因为怕麻烦而选择放弃。"
    ),
    tier=TIER_AUTO,
    input_schema={
        "type": "object",
        "properties": {
            "mode": {
                "type": "string",
                "enum": ["unstick", "blueprint", "review"],
                "description": "可选 · 默认 unstick。 unstick=卡壳破局 · blueprint=开工前出施工单 · review=交付前验收",
            },
            "blocker": {
                "type": "string",
                "description": "unstick 必填: 卡在哪/试了啥失败 · review 必填: 交付说明+diff摘要 · blueprint 可选: 约束/顾虑",
            },
            "goal": {
                "type": "string",
                "description": "blueprint/review 必填 · 任务最终要达成什么 (review 时填原蓝图/目标·验收对照它)",
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
        "required": [],
    },
    run=_run,
    summarize=_summarize,
)

register_tool(SPEC)
