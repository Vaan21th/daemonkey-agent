"""
agent_tools/rerun_flow_step.py
==============================

0.2.0 · 单步重跑 (用户痛点: 某一环节产出不行 · 只想重做那一步)

跟 run_flow(action=resume) 的区别:
  - resume 默认从【失败步】续跑 · 用于"挂在某步 · 修了 app 再继续"场景
  - rerun_flow_step 是用户主动"第 N 步图片不满意 · 重做" · 即使那步 status=done 也强制重跑

调用时机:
  - 用户看完 step 3 输出说 "图不行 · 重新生" → 助手调 rerun_flow_step(run_id, step_idx=3)
  - 用户说 "倒回第 2 步重做"  → 同上

行为:
  - flow_runner.resume_run(run_id, from_step=N) 已经支持 · 这是包装
  - 信任 flow 自动继承 (run_flow 启动时设的 ContextVar 在这条新 run_tool_loop turn 已散 ·
    所以这里要重新查 flow 的 trust_level + 设 ContextVar)

AUTO tier · 行为跟 run_flow resume 等价 · 信任过的 flow 不打断
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
    # 跟 run_flow.start 同款 · 信任 flow 入口降级 AUTO
    try:
        from workers.flow_runner import load_run
        from workers.workshop_assets import load_flow
        state = load_run(args.get("run_id") or "")
        if state and state.get("flow_id"):
            flow = load_flow(state["flow_id"])
            if flow and int(flow.get("trust_level") or 0) >= 1:
                return TIER_AUTO
    except Exception:
        pass
    return TIER_CONFIRM


def _summarize(args: dict) -> str:
    rid = args.get("run_id") or "?"
    idx = args.get("step_idx") or "?"
    reason = args.get("reason") or ""
    extra = f" · 原因: {reason[:30]}" if reason else ""
    return f"重跑 run {rid} 第 {idx} 步{extra}"


def _run(args: dict) -> ToolResult:
    from workers import flow_runner
    from workers.workshop_assets import load_flow

    rid = (args.get("run_id") or "").strip()
    if not rid:
        return ToolResult(ok=False, output="", error="run_id 必填 · 找不到就先 run_flow(action=list)")

    step_idx = args.get("step_idx")
    if step_idx is None:
        return ToolResult(ok=False, output="", error="step_idx 必填 · 从第几步重跑 (1-based)")
    try:
        step_idx_int = int(step_idx)
    except Exception:
        return ToolResult(ok=False, output="", error=f"step_idx 必须是整数 · 收到 {step_idx!r}")
    if step_idx_int < 1:
        return ToolResult(ok=False, output="", error=f"step_idx 必须 ≥ 1 · 收到 {step_idx_int}")

    state = flow_runner.load_run(rid)
    if not state:
        return ToolResult(ok=False, output="", error=f"run 不存在: {rid}")

    total = int(state.get("total_steps") or 0)
    if step_idx_int > total:
        return ToolResult(ok=False, output="", error=f"step_idx={step_idx_int} 超过总步数 {total}")

    from daemon_runtime import RUNTIME
    if RUNTIME.client is None:
        return ToolResult(ok=False, output="", error="RUNTIME.client 未就绪")

    # 查 flow 信任度 · 决定整条 run 期间是否设信任 ContextVar
    flow = load_flow(state.get("flow_id") or "")
    trust_level = int((flow or {}).get("trust_level") or 0)
    token = None
    if trust_level >= 2 and flow:
        token = set_trusted_flow_context(flow["id"])

    reason = (args.get("reason") or "").strip()
    try:
        # 在 run state 里留个用户重跑的痕迹 · 闭环复盘用
        state["last_rerun"] = {
            "step_idx": step_idx_int,
            "reason": reason or "(未填)",
            "by": "用户",
        }
        flow_runner._save_state(state)  # noqa: SLF001 · 内部状态 · 标记原因即可
        new_state = flow_runner.resume_run(rid, runtime=RUNTIME, from_step=step_idx_int)
    except ValueError as e:
        return ToolResult(ok=False, output="", error=str(e))
    finally:
        if token is not None:
            reset_trusted_flow_context(token)

    # bump trust (跟 run_flow 一致)
    if flow and flow.get("id"):
        try:
            from workers.workshop_assets import bump_flow_trust, reset_flow_trust
            if new_state.get("status") == "done":
                bump_flow_trust(flow["id"])
            elif new_state.get("status") == "failed":
                reset_flow_trust(flow["id"], reason=str(new_state.get("error") or ""))
        except Exception:
            pass

    report = flow_runner.format_run(new_state)
    head = f"# ↩ 从第 {step_idx_int} 步重跑"
    if reason:
        head += f" · 原因: {reason}"
    trust_note = f"\n\n🟢 信任 flow (lvl {trust_level}) · CONFIRM 已自动放行" if trust_level >= 2 else ""
    return ToolResult(ok=True, output=f"{head}\n{report}{trust_note}")


SPEC = ToolSpec(
    name="rerun_flow_step",
    description=(
        "从某条 run 的指定步重跑 (用户看到某步产出不满意 · 主动要求重做时调)。\n\n"
        "跟 run_flow(action=resume) 的区别:\n"
        "  - resume 默认从【失败步】续跑 · 那是修 bug 场景\n"
        "  - rerun_flow_step 是用户主动 '第 N 步不行重做' · 即使该步状态是 done 也强制重\n\n"
        "调用时机 (典型对话):\n"
        "  - 用户看 banner: '第 3 步图不好 · 重新生一遍' → rerun_flow_step(run_id, step_idx=3, reason='图不好')\n"
        "  - 用户: '回到第 2 步重做' → rerun_flow_step(run_id, step_idx=2)\n\n"
        "信任 flow (trust_level≥2) 调本工具不打断·跟 run_flow 行为一致。"
    ),
    tier=TIER_CONFIRM,
    classify=_classify,
    input_schema={
        "type": "object",
        "properties": {
            "run_id": {"type": "string", "description": "run-xxx · 用 run_flow(action=list) 找"},
            "step_idx": {"type": "integer", "description": "从第几步重跑 · 1-based"},
            "reason": {"type": "string", "description": "用户为啥要重跑这步 · 闭环复盘用"},
        },
        "required": ["run_id", "step_idx"],
    },
    run=_run,
    summarize=_summarize,
)

register_tool(SPEC)
