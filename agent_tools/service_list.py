"""agent_tools/service_list.py
================================

 K stage 2c++ · wish-8d6b76a6 · 列所有 OPUS 起过的后台服务

调用时机:
    - 用户 问 "你后台跑着哪些服务?"
    - OPUS 起新服务前先看一下当前有谁
    - daemon 重启后想知道之前的服务还在不在 (services.json 持久化)

tier: TIER_AUTO (只读)
"""
from __future__ import annotations

from . import TIER_AUTO, ToolResult, ToolSpec, register_tool


def _summarize(args: dict) -> str:
    return "列出所有已知后台服务 (alive/stopped 都列)"


def _run(args: dict) -> ToolResult:
    from workers.service_runner import list_services

    services = list_services()
    if not services:
        return ToolResult(
            ok=True,
            output="service_list: 当前没有任何服务记录\n\n💡 用 service_start 启动一个 (例如 GPT-SoVITS api.py)",
        )

    alive = [s for s in services if s.get("alive")]
    dead = [s for s in services if not s.get("alive")]

    lines = [f"service_list · 共 {len(services)} 条记录 · {len(alive)} 活 · {len(dead)} 死/停"]
    lines.append("")
    if alive:
        lines.append(f"=== 活着 ({len(alive)}) ===")
        for s in alive:
            meta = s.get("meta") or {}
            cpu = meta.get("cpu_percent", "?")
            rss = meta.get("rss_mb", "?")
            port = s.get("port")
            port_part = f" :{port}" if port else ""
            lines.append(
                f"  ✓ {s['name']:20s}{port_part:8s}  pid={s.get('pid'):<6}  "
                f"rss={rss}MB  cpu={cpu}%  started={s.get('started_at')}"
            )
            cmd = (s.get("command") or "")[:80]
            lines.append(f"      cmd: {cmd}")
            if s.get("healthcheck_url"):
                lines.append(f"      healthcheck: {s.get('healthcheck_url')}")
        lines.append("")

    if dead:
        lines.append(f"=== 已停 / 已死 ({len(dead)}) ===")
        for s in dead:
            stopped = "stopped" if s.get("stopped") else "dead"
            lines.append(
                f"  × {s['name']:20s}  pid={s.get('pid'):<6}  {stopped}  started={s.get('started_at')}"
            )
        lines.append("")

    lines.append("💡 详情用 service_status name=<name>")
    return ToolResult(ok=True, output="\n".join(lines))


SPEC = ToolSpec(
    name="service_list",
    description=(
        "列所有 OPUS 起过的后台服务 (从 data/runtime/services.json) · 含 alive 状态 + 元信息。\n\n"
        "调用时机:\n"
        "  - 用户 问\"你后台跑着哪些服务?\" / \"刚才那个 SOVITS 还在吗?\"\n"
        "  - OPUS 起新服务前先看现有 (避免端口冲突)\n"
        "  - daemon 重启后想知道之前服务还在不在\n\n"
        "tier: TIER_AUTO (只读)"
    ),
    tier=TIER_AUTO,
    input_schema={"type": "object", "properties": {}},
    run=_run,
    summarize=_summarize,
)


register_tool(SPEC)
