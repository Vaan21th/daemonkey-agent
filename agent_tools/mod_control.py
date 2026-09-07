"""叠层自检 / 停用 / 启用。"""
from __future__ import annotations

from . import TIER_AUTO, TIER_CONFIRM, ToolResult, ToolSpec, register_tool


def _check(_args: dict) -> ToolResult:
    from workers.mod_health import format_report, inspect_and_save
    text = format_report(inspect_and_save())
    if not text:
        return ToolResult(ok=True, output="没有叠层 MOD，也没有本机工具叠层。")
    return ToolResult(ok=True, output=text)


def _set(args: dict) -> ToolResult:
    from workers.mod_health import disable, enable
    mid = str(args.get("id") or "").strip()
    if not mid:
        return ToolResult(ok=False, output="", error="id 必填")
    on = args.get("enabled")
    if on is None:
        act = str(args.get("action") or "").strip().lower()
        if act in ("disable", "off", "stop"):
            on = False
        elif act in ("enable", "on"):
            on = True
        else:
            return ToolResult(ok=False, output="", error="enabled=true/false，或 action=enable/disable")
    ok, msg = enable(mid) if on else disable(mid)
    if ok:
        from workers.mod_health import inspect_and_save
        inspect_and_save()
    return ToolResult(ok=ok, output=msg if ok else "", error="" if ok else msg)


register_tool(ToolSpec(
    name="check_mods",
    description="检查叠层 MOD / 本机工具是否还能套上（只解析，不执行）。用户说「检查叠层」。",
    tier=TIER_AUTO,
    input_schema={"type": "object", "properties": {}, "required": []},
    run=_check,
    summarize=lambda _a: "检查叠层是否还健在",
))

register_tool(ToolSpec(
    name="set_mod",
    description="停用或启用一个 data/mods/<id>。停用后回官方。用户说「停用 MOD <id>」。",
    tier=TIER_CONFIRM,
    input_schema={
        "type": "object",
        "properties": {
            "id": {"type": "string", "description": "MOD 目录名"},
            "enabled": {"type": "boolean", "description": "true 启用 / false 停用"},
            "action": {"type": "string", "description": "enable 或 disable，和 enabled 二选一"},
        },
        "required": ["id"],
    },
    run=_set,
    summarize=lambda a: (
        f"{'启用' if a.get('enabled') is not False and str(a.get('action') or '') != 'disable' else '停用'}"
        f" MOD {a.get('id')}"
    ),
    classify=lambda _a: TIER_CONFIRM,
))
