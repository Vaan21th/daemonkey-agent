"""agent_tools/run_flow.py
==========================

沉淀闭环 v2 · 刀② · 沿 steps 工作流执行 + 断点续跑 (2026-06-10)

这是 Plan 模式的"执行"半边:
    create_workflow(steps=[...]) 落档 → 用户认了 → run_flow(action=start) 沿轨道跑。
状态全程落盘 data/workshop/runs/<run_id>.json · 对话再长 LLM 忘了 · 状态文件没忘 ·
workshop_context 每轮把活跃 run 进度重注主对话 (铁律衰减治理第③档)。

action:
    start  · 跑一条 flow (flow_id / flow_name 引用 · from_step 可跳步)
    resume · 断点续跑 (run_id · 默认从失败步 · from_step 显式指定 = 重跑某环)
    status · 看某个 run 进度
    list   · 最近的 runs
"""

from __future__ import annotations

from . import (
    TIER_AUTO,
    TIER_CONFIRM,
    ToolResult,
    ToolSpec,
    register_tool,
    set_trusted_flow_context,
    reset_trusted_flow_context,
)


def _classify(args: dict) -> str:
    # 0.2.0 · trust_level ≥ 1 的 flow 入口降级为 AUTO (不再打断入口)
    # status/list 永远 AUTO; start/resume 默认 CONFIRM · 但信任过的 flow 不再要用户拍 y
    action = (args.get("action") or "").strip()
    if action not in ("start", "resume"):
        return TIER_AUTO
    try:
        from workers.workshop_assets import load_flow, list_flows
        ref = (args.get("flow_id") or args.get("flow_name") or "").strip()
        flow = None
        if ref.startswith("flow-"):
            flow = load_flow(ref)
        elif ref:
            # 名字模糊查 · 命中唯一才算
            exact = [f for f in list_flows() if (f.get("name") or "").strip() == ref]
            if len(exact) == 1:
                flow = load_flow(exact[0]["id"])
        elif action == "resume":
            # resume 时从 run_id 反查 flow
            run_id = args.get("run_id") or ""
            if run_id:
                from workers.flow_runner import load_run
                state = load_run(run_id)
                if state and state.get("flow_id"):
                    flow = load_flow(state["flow_id"])
        if flow and int(flow.get("trust_level") or 0) >= 1:
            return TIER_AUTO
    except Exception:
        pass
    return TIER_CONFIRM


def _summarize(args: dict) -> str:
    action = args.get("action") or "?"
    ref = args.get("flow_id") or args.get("flow_name") or args.get("run_id") or ""
    extra = f" · 从第 {args['from_step']} 步" if args.get("from_step") else ""
    return f"工作流 {action} · {ref}{extra}"


def _resolve_flow(ref: str):
    from workers.workshop_assets import list_flows, load_flow
    ref = (ref or "").strip()
    if ref.startswith("flow-"):
        return load_flow(ref)
    flows = list_flows()
    exact = [f for f in flows if (f.get("name") or "").strip() == ref]
    if len(exact) == 1:
        return load_flow(exact[0]["id"])
    fuzzy = [f for f in flows if ref and ref in (f.get("name") or "")]
    if len(fuzzy) == 1:
        return load_flow(fuzzy[0]["id"])
    return None


def _run(args: dict) -> ToolResult:
    from workers import flow_runner

    action = (args.get("action") or "").strip()

    if action == "list":
        runs = flow_runner.list_runs(max_items=int(args.get("limit") or 10))
        if not runs:
            return ToolResult(ok=True, output="还没有任何工作流 run 记录。")
        lines = ["# 最近的工作流 runs"]
        for r in runs:
            lines.append(
                f"- `{r['run_id']}` · {r['flow_name']} · {r['status']} · "
                f"{r['current_step']}/{r['total_steps']} 步 · {r['updated_at']}"
            )
        return ToolResult(ok=True, output="\n".join(lines))

    if action == "status":
        state = flow_runner.load_run(args.get("run_id") or "")
        if not state:
            return ToolResult(ok=False, output="", error=f"run 不存在: {args.get('run_id')}")
        return ToolResult(ok=True, output=flow_runner.format_run(state))

    if action in ("start", "resume"):
        from daemon_runtime import RUNTIME
        if RUNTIME.client is None:
            return ToolResult(ok=False, output="", error="RUNTIME.client 未就绪 (daemon 未完全启动?)")

        from_step = args.get("from_step")
        # 0.2.0 · 先解出 flow · 看 trust_level · 决定整条 run 期间是否设信任 ContextVar
        flow = None
        if action == "start":
            ref = args.get("flow_id") or args.get("flow_name") or ""
            flow = _resolve_flow(ref)
            if not flow:
                return ToolResult(ok=False, output="", error=f"flow 解析失败: {ref!r} (不存在或名字命中多个)")
            if not flow.get("steps"):
                return ToolResult(
                    ok=False, output="",
                    error=f"flow {flow.get('id')} 是老画布格式 (无 steps) · 在工坊画布里跑 · 或重建为 steps 格式",
                )
        else:  # resume
            run_id = args.get("run_id") or ""
            if run_id:
                state = flow_runner.load_run(run_id)
                if state and state.get("flow_id"):
                    from workers.workshop_assets import load_flow as _lf
                    flow = _lf(state["flow_id"])

        # 信任 ContextVar 现在由 flow_runner.start_run_async/resume_run_async 在 worker
        # 线程内 set + reset · 这里只决定要不要传 trusted_flow_id 进去 (ContextVar 不跨线程)
        trust_level = int((flow or {}).get("trust_level") or 0)
        trusted_flow_id = flow["id"] if (trust_level >= 2 and flow) else None

        try:
            # P0 · 异步启动 · tool 立刻返 run_id · LLM turn 不再 hang 几分钟
            # 子线程后台真跑 · 状态文件持续写 · 前端 2.5s 轮询 + chat banner 实时染色
            if action == "start":
                state = flow_runner.start_run_async(
                    flow,
                    runtime=RUNTIME,
                    trusted_flow_id=trusted_flow_id,
                    from_step=int(from_step or 1),
                )
            else:
                state = flow_runner.resume_run_async(
                    args.get("run_id") or "",
                    runtime=RUNTIME,
                    trusted_flow_id=trusted_flow_id,
                    from_step=int(from_step) if from_step else None,
                )
        except ValueError as e:
            return ToolResult(ok=False, output="", error=str(e))

        # 信任账本 bump/reset 已内化进 flow_runner._execute · worker 跑完自动结算
        # (异步路径下 ToolResult 在这里已经走人 · 没法在 tool 层 bump · 内化到 _execute 才完整)

        report = flow_runner.format_run(state)
        trust_note = ""
        if trust_level >= 2:
            trust_note = f"\n\n🟢 信任 flow (lvl {trust_level}) · 整条 run 内部 CONFIRM 工具已自动放行 · 仅 GUARD 拦截"

        verb = "已启动" if action == "start" else "已从断点续跑"
        return ToolResult(
            ok=True,
            output=(
                f"# ▶ 工作流 {verb} (后台跑中 · 主对话不挨顶)\n{report}{trust_note}\n\n"
                f"→ 看实时进度: chat 顶部 banner / workshop tab 节点染色 (2.5s 轮询)\n"
                f"→ 主动查状态: `run_flow(action=status, run_id={state.get('run_id')})`\n"
                f"→ workshop_context 每轮自动注入活跃 run · 跑完 / 失败下轮 AI 会主动提醒 · "
                f"用户可以继续聊别的"
            ),
        )

    return ToolResult(ok=False, output="", error=f"未知 action: {action!r} · 可用 start/resume/status/list")


SPEC = ToolSpec(
    name="run_flow",
    description=(
        "沿 steps 工作流执行 · 每步状态落盘 · 断点续跑 (Plan 模式的执行半边)\n\n"
        "**🔴 铁律 · 复合任务先排流程再动手**:\n"
        "  任务要 2 个以上 app 接力 (如: 做视频 = 文案→配音→渲染) → 先 create_workflow(steps=[...]) 落档\n"
        "  → 用户认了 → run_flow(action=start) 沿轨道跑。**严禁跳过流程 ad-hoc 手搓接力** ·\n"
        "  那是 2026-06-09 做视频 8 小时混乱的根因。\n\n"
        "**异步语义 (P0 · 2026-06-10 改)**:\n"
        "  - start/resume **立刻返回** · 后台 thread 真跑 · 你拿到的是 status=running 的初始 state\n"
        "  - 不要 LLM 内部等 · 不要追问 'run 完了吗' · 用户在 chat banner 看进度色 / workshop_context\n"
        "    每轮自动注入活跃 run 状态 · 跑完 / 失败下轮你会自然知道 · 主动用 status 查最新进度即可\n"
        "  - 启动后这一轮就给用户报 '已启动 run-xxx · 后台跑中' · 别在原 tool turn 里堵着等\n\n"
        "**断点哲学 (精确到环·不整体重来)**:\n"
        "  - 某步挂了 → run 状态保留 → 修好对应 app (update_app 留版本) → resume 从失败步续跑\n"
        "  - 想单独重跑第 N 环 → resume + from_step=N\n"
        "  - 状态文件: data/workshop/runs/<run_id>.json · 对话忘了它也在\n\n"
        "**只支持 steps 格式 flow** · 老画布 flow 在工坊画布里跑 (或重建为 steps 格式)"
    ),
    tier=TIER_CONFIRM,
    classify=_classify,
    input_schema={
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["start", "resume", "status", "list"]},
            "flow_id": {"type": "string", "description": "start 用 · flow-xxxxxxxx 精确引用 (推荐)"},
            "flow_name": {"type": "string", "description": "start 用 · 名字引用 · 唯一命中才行"},
            "run_id": {"type": "string", "description": "resume/status 用 · run-xxx"},
            "from_step": {"type": "integer", "description": "start: 跳步起跑; resume: 显式从第 N 步重跑 (默认失败步)"},
            "limit": {"type": "integer", "description": "list 用 · 默认 10"},
        },
        "required": ["action"],
    },
    run=_run,
    summarize=_summarize,
)
register_tool(SPEC)
