"""agent_tools/service_stop.py
================================

 K stage 2c++ · wish-8d6b76a6 · 停一个 OPUS 起的后台服务

策略:
    - 先发 SIGTERM (Unix) / Process.terminate (Windows) — 优雅退出 5s
    - 5s 后还活就 SIGKILL / Process.kill — 强制
    - 标 services.json 里 stopped=true · log 保留 (用户 排错用)

调用时机:
    - 用户 说\"把那个 sovits 停了\" / \"停掉所有 service\"
    - OPUS 自己起的临时 service 用完了 (例如测试某个 API 后)
    - 端口冲突 · 要重启某个服务前先 stop

tier: TIER_CONFIRM (停服务有副作用 · 用户 ✓ 才执行)
"""
from __future__ import annotations

from . import TIER_CONFIRM, ToolResult, ToolSpec, register_tool


def _summarize(args: dict) -> str:
    return f"停止后台服务 `{(args.get('name') or '?').strip()}` (先 SIGTERM 5s · 不停就 SIGKILL)"


def _run(args: dict) -> ToolResult:
    from workers.service_runner import stop_service, get_service

    name = (args.get("name") or "").strip()
    if not name:
        return ToolResult(ok=False, output="", error="name 必填")
    timeout_sec = float(args.get("timeout_sec") or 5.0)
    if not (0.5 <= timeout_sec <= 30):
        return ToolResult(ok=False, output="", error=f"timeout_sec 越界 [0.5, 30]: {timeout_sec}")

    # 让 LLM 确认服务存在
    info = get_service(name)
    if not info:
        return ToolResult(
            ok=False, output="",
            error=f"service `{name}` 不在记录里 · 调 service_list 看现有",
        )

    result = stop_service(name, timeout_sec=timeout_sec)
    if not result.get("ok"):
        return ToolResult(ok=False, output="", error=result.get("message") or "service_stop 失败")

    msg = result.get("message", "")
    forced = result.get("forced", False)
    lines = [f"service_stop ok · {msg}"]
    if forced:
        lines.append("⚠️ 服务对 SIGTERM 不响应 · 走了 SIGKILL · log 看是不是子进程卡死")
    lines.append("")
    lines.append(f"💡 log 仍保留 (data/runtime/service_logs/{name}.log)")
    lines.append(f"💡 要重起调 service_start · 要彻底删记录调 service_remove (不存在的话以后加)")
    return ToolResult(ok=True, output="\n".join(lines))


SPEC = ToolSpec(
    name="service_stop",
    description=(
        "停一个 OPUS 起的后台服务 · 先 SIGTERM 等 5s · 不停就 SIGKILL 兜底 · log 保留。\n\n"
        "调用时机:\n"
        "  - 用户 说\"把那个 sovits 停了\"\n"
        "  - OPUS 起的临时 service 用完了\n"
        "  - 端口冲突要重启服务前\n\n"
        "tier: TIER_CONFIRM (停服务有副作用)"
    ),
    tier=TIER_CONFIRM,
    input_schema={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "service 名"},
            "timeout_sec": {
                "type": "number",
                "description": "graceful 等多久才 force kill (默认 5.0 · 范围 0.5-30)",
            },
        },
        "required": ["name"],
    },
    run=_run,
    summarize=_summarize,
)


register_tool(SPEC)
