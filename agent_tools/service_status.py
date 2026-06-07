"""agent_tools/service_status.py
==================================

 K stage 2c++ · wish-8d6b76a6 · 查单个服务的活/状态/资源

调用时机:
    - 起完服务后过一会查活 ("我那个 sovits 还活着吗?")
    - 用户 问"你那个服务现在 CPU / 内存占多少?"
    - 排错前先看状态 + healthcheck

tier: TIER_AUTO (只读 · 顶多 curl 一次 healthcheck)
"""
from __future__ import annotations

from . import TIER_AUTO, ToolResult, ToolSpec, register_tool


def _summarize(args: dict) -> str:
    return f"查 service `{(args.get('name') or '?').strip()}` 状态 (活/资源/healthcheck)"


def _run(args: dict) -> ToolResult:
    from workers.service_runner import get_service, _curl_check  # type: ignore

    name = (args.get("name") or "").strip()
    if not name:
        return ToolResult(ok=False, output="", error="name 必填")

    info = get_service(name)
    if not info:
        return ToolResult(
            ok=False, output="",
            error=f"service `{name}` 不在记录里 · 调 service_list 看现有",
        )

    pid = info.get("pid")
    alive = info.get("alive")
    meta = info.get("meta") or {}
    lines = [
        f"service_status · `{name}`",
        f"  pid: {pid}",
        f"  alive: {alive}",
        f"  stopped (record): {info.get('stopped', False)}",
        f"  started_at: {info.get('started_at')}",
        f"  command: {info.get('command')}",
        f"  working_dir: {info.get('working_dir')}",
        f"  port: {info.get('port')}",
        f"  log_path: {info.get('log_path')}",
    ]
    if alive and meta:
        lines.append(f"  resources: cpu={meta.get('cpu_percent')}% rss={meta.get('rss_mb')}MB · {meta.get('status')}")
        lines.append(f"  proc_create_time: {meta.get('create_time')}")

    # healthcheck (如果给了 + alive)
    hcu = info.get("healthcheck_url")
    if hcu and alive:
        ok, msg = _curl_check(hcu, timeout_s=3.0)
        lines.append(f"  healthcheck ({hcu}): ok={ok} · {msg}")
    elif hcu:
        lines.append(f"  healthcheck ({hcu}): 不查 (服务已死)")

    if alive:
        lines.append("")
        lines.append(f"💡 用 read_file path={info.get('log_path')} 看输出 / 排错")
        lines.append(f"💡 不需要的话调 service_stop name={name}")
    else:
        lines.append("")
        lines.append("⚠️ 服务已死/停 · 看 log 找原因 · 然后可以 service_start 重起")

    return ToolResult(ok=True, output="\n".join(lines))


SPEC = ToolSpec(
    name="service_status",
    description=(
        "查单个后台服务的当前状态 (活/死 · cpu / mem · healthcheck 复测)。\n\n"
        "调用时机:\n"
        "  - 起完服务后过一会查活\n"
        "  - 排错前先看 alive + healthcheck\n"
        "  - 用户 问\"那个服务现在占多少资源?\"\n\n"
        "tier: TIER_AUTO (只读 · 顶多 curl healthcheck)"
    ),
    tier=TIER_AUTO,
    input_schema={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "service 名 · 必须是 service_start 起过的"},
        },
        "required": ["name"],
    },
    run=_run,
    summarize=_summarize,
)


register_tool(SPEC)
