"""延期工具的调用桥。tool_loop 会先拆成目标工具再走原确认/闸。"""
from __future__ import annotations

from . import TIER_AUTO, TIER_CONFIRM, ToolResult, ToolSpec, register_tool
from ._tool_catalog import CATALOG_CALL, resolve_call


def _run(args: dict) -> ToolResult:
    # 正常路径由 tool_loop 拆包后跑目标 SPEC。这里只兜底。
    from agent_tools import REGISTRY
    name, inner = resolve_call(CATALOG_CALL, args)
    if not name:
        return ToolResult(ok=False, output="", error="catalog_call 需要 name")
    spec = REGISTRY.get(name)
    if spec is None:
        return ToolResult(ok=False, output="", error=f"unknown tool: {name}")
    return spec.run(inner)


def _classify(args: dict) -> str:
    from agent_tools import REGISTRY
    name, inner = resolve_call(CATALOG_CALL, args)
    spec = REGISTRY.get(name)
    if spec is None:
        return TIER_CONFIRM
    return spec.effective_tier(inner)


def _summarize(args: dict) -> str:
    name, inner = resolve_call(CATALOG_CALL, args)
    from agent_tools import REGISTRY
    spec = REGISTRY.get(name)
    if spec is not None and hasattr(spec, "summarize"):
        try:
            return spec.summarize(inner)
        except Exception:
            pass
    return f"catalog_call {name}".strip()


SPEC = ToolSpec(
    name="catalog_call",
    description=(
        "Call a deferred tool by name with its args. "
        "Same confirm/guard as a native call. "
        "Use for tools listed under 更多工具. Core tools: call them directly."
    ),
    tier=TIER_CONFIRM,
    input_schema={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Deferred tool name"},
            "args": {"type": "object", "description": "Arguments for that tool"},
        },
        "required": ["name"],
    },
    run=_run,
    classify=_classify,
    summarize=_summarize,
)

register_tool(SPEC)
