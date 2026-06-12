"""
agent_tools/trust_flow.py
=========================

0.2.0 · 信任账本手动控制 (用户一句话信任/收回信任)

调用时机:
  - 用户在主对话说"信任这条 flow · 别再问我" → 助手调 trust_flow(flow_id=..., level=3)
  - 用户说"这条 flow 不靠谱 · 重新审一遍" → 助手调 trust_flow(flow_id=..., level=0)

信任等级:
  0 ⚪⚪⚪⚪ 完全审 · 每步 CONFIRM 都要 y/n (默认 · 新 flow)
  1 ⚪⚪⚪🟢 入口不打断 · 内部 CONFIRM 仍要 y/n (跑过 1 次成功自动到这)
  2 ⚪⚪🟢🟢 入口 + 内部 CONFIRM 全自动放行 (跑过 3 次成功自动到这)
  3 ⚪🟢🟢🟢 同 2 但带用户钦定 🌟 标记 · 不会被自动逻辑覆盖

GUARD tier 工具永远不在信任降级范围内 (保命线)。

AUTO tier · 改 flow 元数据 · 不动 step / app 本体
"""

from __future__ import annotations

from . import TIER_AUTO, ToolResult, ToolSpec, register_tool


_LEVEL_BADGE = {0: "⚪⚪⚪⚪", 1: "⚪⚪⚪🟢", 2: "⚪⚪🟢🟢", 3: "⚪🟢🟢🟢"}
_LEVEL_DESC = {
    0: "完全审 · 每步 CONFIRM 都要 y/n",
    1: "入口不打断 · 内部 CONFIRM 仍要 y/n",
    2: "整条 run 内 CONFIRM 全自动放行 (GUARD 仍拦截)",
    3: "用户钦定 · 同 lvl 2 + 不会被失败逻辑自动降级",
}


def _summarize(args: dict) -> str:
    fid = args.get("flow_id") or "?"
    level = args.get("level")
    if level is None:
        return f"看 flow 信任态 · {fid}"
    return f"设 flow 信任度 · {fid} → lvl {level} {_LEVEL_BADGE.get(int(level), '')}"


def _run(args: dict) -> ToolResult:
    from workers.workshop_assets import load_flow, set_flow_trust

    fid = (args.get("flow_id") or "").strip()
    if not fid or not fid.startswith("flow-"):
        return ToolResult(ok=False, output="", error="flow_id 必填 · 格式 flow-xxxxxxxx")

    flow = load_flow(fid)
    if not flow:
        return ToolResult(ok=False, output="", error=f"flow 不存在: {fid}")

    level = args.get("level")
    if level is None:
        # 查询模式 · 不改 · 只回报当前状态
        cur = int(flow.get("trust_level") or 0)
        runs_ok = int(flow.get("success_runs") or 0)
        by = flow.get("trusted_by") or "(未设)"
        return ToolResult(
            ok=True,
            output=(
                f"# 🔍 flow 信任态\n"
                f"- **{flow.get('name')}** · `{fid}`\n"
                f"- 当前信任度: lvl {cur} {_LEVEL_BADGE.get(cur, '')} · {_LEVEL_DESC.get(cur, '?')}\n"
                f"- 累计成功跑过: {runs_ok} 次\n"
                f"- 信任来源: {by}\n"
                f"- 最近失败: {flow.get('last_failure_at') or '(无)'}\n\n"
                f"想改信任度: trust_flow(flow_id='{fid}', level=0/1/2/3)"
            ),
        )

    try:
        level_int = int(level)
    except Exception:
        return ToolResult(ok=False, output="", error=f"level 必须是 0-3 的整数 · 收到 {level!r}")
    if level_int < 0 or level_int > 3:
        return ToolResult(ok=False, output="", error=f"level 必须是 0/1/2/3 · 收到 {level_int}")

    updated = set_flow_trust(fid, level=level_int, by=args.get("by") or "用户")
    if not updated:
        return ToolResult(ok=False, output="", error=f"set_flow_trust 失败: {fid}")

    badge = _LEVEL_BADGE.get(level_int, "")
    desc = _LEVEL_DESC.get(level_int, "")
    return ToolResult(
        ok=True,
        output=(
            f"# ✓ 信任度已更新\n"
            f"- **{updated.get('name')}** · `{fid}`\n"
            f"- 新信任度: lvl {level_int} {badge}\n"
            f"- 含义: {desc}\n"
            f"- 下次 run_flow 启动这条 flow · 行为按上面规则。"
        ),
    )


SPEC = ToolSpec(
    name="trust_flow",
    description=(
        "信任账本 (trust ledger) 手动控制 · 用户一句话信任 / 收回信任某条 flow。\n\n"
        "level 含义:\n"
        "  0 = 完全审 · 每步 CONFIRM 都要 y/n (默认)\n"
        "  1 = 入口不打断 · 内部 CONFIRM 仍要 y/n\n"
        "  2 = 整条 run 内 CONFIRM 全自动放行 (推荐 · 用户一句话信任)\n"
        "  3 = 用户钦定 · 不会被自动失败逻辑降级\n\n"
        "GUARD tier 工具 (shell_exec rm / 改 .env / 重启 daemon) 永远不在信任范围内。\n"
        "调用时机:\n"
        "  - 用户说'信任这条 flow' / '别再问我' / '直接跑' → level=2 或 3\n"
        "  - 用户说'重新审' / '不靠谱' → level=0\n"
        "  - 不传 level · 只查当前状态。"
    ),
    tier=TIER_AUTO,
    input_schema={
        "type": "object",
        "properties": {
            "flow_id": {"type": "string", "description": "flow-xxxxxxxx · 精确 id"},
            "level": {"type": "integer", "description": "0/1/2/3 · 不传 = 查当前态"},
            "by": {"type": "string", "description": "设这个信任的人 · 默认 用户"},
        },
        "required": ["flow_id"],
    },
    run=_run,
    summarize=_summarize,
)

register_tool(SPEC)
