"""agent_tools/run_app.py
=========================

沉淀闭环 v2 · 刀② · 主对话直接执行工坊 app (2026-06-10)

为什么有这个工具
------------------
2026-06-09 事故根因之一: 主对话里的 AI 想用现成 app 也没手——工具箱里没有
"运行某个 app" 的工具 · 只能 python_exec 从零手搓 · 标准全靠脑子记 · 每版漂移。
有了 run_app · "用现成的" 终于比 "现搓一个" 更省力。

执行 = workers/app_runner.run_app (跟工坊『测试』tab 点 ▶ 同一条路) ·
带 app 自己的 system_prompt + 工具白名单 + 刀①运行时纪律 (产出隔离/资产必读)。
"""

from __future__ import annotations

from . import TIER_AUTO, ToolResult, ToolSpec, register_tool


def _summarize(args: dict) -> str:
    ref = args.get("app_id") or args.get("app_name") or "(?)"
    goal = (args.get("goal") or "").strip()
    return f"跑工坊 app · {ref}" + (f" · 目标: {goal[:60]}" if goal else "")


def _run(args: dict) -> ToolResult:
    from daemon_runtime import RUNTIME
    from workers.app_runner import run_app as _run_app
    from workers.flow_runner import _resolve_app

    ref = (args.get("app_id") or args.get("app_name") or "").strip()
    if not ref:
        return ToolResult(ok=False, output="", error="app_id 或 app_name 必填")

    app = _resolve_app(ref)
    if app is None:
        return ToolResult(
            ok=False, output="",
            error=f"app 解析失败: {ref!r} · 不存在或名字命中多个 · 用 glob_files data/workshop/apps/*.json 查 id",
        )

    inputs = dict(args.get("inputs") or {})
    goal = (args.get("goal") or "").strip()
    if goal:
        inputs.setdefault("step_goal", goal)

    if RUNTIME.client is None:
        return ToolResult(ok=False, output="", error="RUNTIME.client 未就绪 (daemon 未完全启动?)")

    result = _run_app(
        app=app,
        inputs=inputs,
        runtime=RUNTIME,
        upstream_outputs=args.get("upstream_outputs") or None,
    )

    if not result.get("ok"):
        return ToolResult(
            ok=False, output="",
            error=f"app {app.get('id')} 跑挂了: {result.get('error')}",
        )

    text = result.get("text") or ""
    usage = result.get("usage") or {}
    lines = [
        f"# ✓ app 已执行 · {app.get('icon', '')} {app.get('name')} (`{app.get('id')}`)",
        f"  - 迭代: {result.get('iterations')} 轮 · tokens in/out: "
        f"{usage.get('input_tokens', 0)}/{usage.get('output_tokens', 0)}",
        f"  - 产出目录: data/workshop/outputs/{app.get('id')}/",
        "",
        "## app 的回答",
        text,
    ]
    return ToolResult(ok=True, output="\n".join(lines))


SPEC = ToolSpec(
    name="run_app",
    description=(
        "执行一个工坊 app（与工坊测试按钮同路）。工坊已有能干活的 app 时必须调它，禁止 python_exec 手搓同样的活。多步接力用 run_flow。产出在 data/workshop/outputs/<app_id>/。"
    ),
    tier=TIER_AUTO,
    input_schema={
        "type": "object",
        "properties": {
            "app_id": {"type": "string", "description": "app-xxxxxxxx · 精确引用 (推荐)"},
            "app_name": {"type": "string", "description": "app 名字 · 唯一命中才行 · 命中多个会报错"},
            "goal": {"type": "string", "description": "这次执行的一句话目标 · 会作为 step_goal 传给 app"},
            "inputs": {
                "type": "object",
                "description": "表单输入 · 字段对应 app 的 ui_form_schema · 额外字段 app 的 LLM 自己看着办",
            },
            "upstream_outputs": {
                "type": "object",
                "description": "可选 · 上游产出 (手动串两个 app 时把上一个的结果传进来)",
            },
        },
    },
    run=_run,
    summarize=_summarize,
)
register_tool(SPEC)
