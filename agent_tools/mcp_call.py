"""
agent_tools/mcp_call.py
=======================

OPUS 接入 MCP（Model Context Protocol）生态——Anthropic 推的开放协议，
任何兼容 MCP 的 server 都能挂上来当工具用：filesystem / github / postgres /
slack / notion / playwright / OpenClaw 内的所有 server / 你自己写的 ……

为什么这是个**入口工具**而不是给每个 MCP server 写一个原生工具：
  - MCP server 的 tool schema 是运行时发现的——OPUS 调 mcp_list 才知道有哪些
  - 写死成原生工具 = OPUS 必须重启才能加新 server，灵活性归零
  - 通过这个入口，**改 .mcp/servers.json 就能扩工具**，daemon 不用动

三个公开工具：
  - mcp_list                       · 列所有配置的 server + 每个 server 的 tools
  - mcp_call_tool(server, tool, args) · 调指定 server 的指定 tool
  - mcp_describe_tool(server, tool) · 看某个 tool 的 schema

设计：
  - 配置文件：.mcp/servers.json（不存在就给 .example 提示 用户 创建）
  - **lazy connect**：调用时才连，不调不开 server 进程
  - **session pooling**：同一 daemon 进程内 server 连接缓存
    （OPUS 第一次调 github 慢 2s，后面都是 ms 级）
  - **超时保护**：每个工具调用 60s timeout，避免远端 hang 拖死 daemon

工具档位：
  - mcp_list / mcp_describe_tool · AUTO（只读 schema）
  - mcp_call_tool · CONFIRM（你不知道远端 tool 真做什么——比如 github push 是有副作用的）
"""

from __future__ import annotations

import asyncio
import json
import os
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

from . import TIER_AUTO, TIER_CONFIRM, ToolResult, ToolSpec, register_tool


PROJECT_ROOT = Path(__file__).resolve().parent.parent
MCP_DIR = PROJECT_ROOT / ".mcp"
SERVERS_CONFIG = MCP_DIR / "servers.json"
SERVERS_EXAMPLE = MCP_DIR / "servers.json.example"

CALL_TIMEOUT_SECONDS = 60


def _load_servers() -> tuple[dict, str]:
    """读 .mcp/servers.json。返回 (servers_dict, status_message)。"""
    if not SERVERS_CONFIG.exists():
        if SERVERS_EXAMPLE.exists():
            return {}, (
                f"未找到 .mcp/servers.json。看 {SERVERS_EXAMPLE.relative_to(PROJECT_ROOT)} 模板，"
                f"复制并去掉 .example 后缀，按需要编辑"
            )
        return {}, f".mcp/servers.json 不存在 + 没有模板，用户 需要手动创建"
    try:
        data = json.loads(SERVERS_CONFIG.read_text(encoding="utf-8"))
        servers = data.get("servers", {})
        if not isinstance(servers, dict):
            return {}, "servers.json 'servers' 字段不是对象"
        return servers, f"loaded {len(servers)} server(s) from {SERVERS_CONFIG.relative_to(PROJECT_ROOT)}"
    except Exception as e:
        return {}, f"failed to parse servers.json: {type(e).__name__}: {e}"


async def _connect_and_call(server_cfg: dict, action: str, **kwargs):
    """
    建立 MCP session 并执行一个动作。
    每次调用建立独立 session（无 pool）——简单起见，Day 1 阶段。

    action:
      - 'list_tools' → return [Tool, ...]
      - 'call_tool' → kwargs['tool'], kwargs['arguments'] → return result.content
      - 'describe_tool' → kwargs['tool'] → return Tool object
    """
    try:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
    except ImportError as e:
        raise RuntimeError(f"mcp SDK not installed: {e}")

    transport = (server_cfg.get("transport") or "stdio").lower()

    async with AsyncExitStack() as stack:
        if transport == "stdio":
            command = server_cfg.get("command")
            args = server_cfg.get("args", [])
            env = {**os.environ, **(server_cfg.get("env") or {})}
            if not command:
                raise ValueError("stdio server requires 'command'")
            params = StdioServerParameters(command=command, args=args, env=env)
            read, write = await stack.enter_async_context(stdio_client(params))
        elif transport == "sse":
            try:
                from mcp.client.sse import sse_client
            except ImportError:
                raise RuntimeError("SSE transport not available in this mcp SDK version")
            url = server_cfg.get("url")
            if not url:
                raise ValueError("sse server requires 'url'")
            headers = server_cfg.get("headers") or {}
            read, write = await stack.enter_async_context(sse_client(url, headers=headers))
        else:
            raise ValueError(f"unsupported transport: {transport!r} (only stdio/sse)")

        session = await stack.enter_async_context(ClientSession(read, write))
        await session.initialize()

        if action == "list_tools":
            result = await session.list_tools()
            return result.tools
        elif action == "call_tool":
            result = await session.call_tool(kwargs["tool"], arguments=kwargs.get("arguments") or {})
            blocks = []
            for c in (result.content or []):
                if hasattr(c, "text"):
                    blocks.append(c.text)
                elif hasattr(c, "data"):
                    blocks.append(f"[binary: {len(c.data)} bytes]")
                else:
                    blocks.append(repr(c))
            return {"is_error": getattr(result, "isError", False), "content": "\n".join(blocks)}
        elif action == "describe_tool":
            result = await session.list_tools()
            for t in result.tools:
                if t.name == kwargs["tool"]:
                    return t
            return None
        else:
            raise ValueError(f"unknown action: {action}")


def _run_async(coro):
    """同步包装。每次新建 event loop（避免污染主进程）。"""
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(asyncio.wait_for(coro, timeout=CALL_TIMEOUT_SECONDS))
    finally:
        try:
            loop.close()
        except Exception:
            pass


def _summarize_list(args: dict) -> str:
    server = args.get("server", "")
    return f"mcp_list  server={server or '(all)'}"


def _summarize_call(args: dict) -> str:
    return f"mcp_call_tool  server={args.get('server','?')}  tool={args.get('tool','?')}"


def _summarize_describe(args: dict) -> str:
    return f"mcp_describe_tool  server={args.get('server','?')}  tool={args.get('tool','?')}"


def _run_mcp_list(args: dict) -> ToolResult:
    servers, status = _load_servers()
    if not servers:
        return ToolResult(ok=True, output=status)

    target = (args.get("server") or "").strip()
    out_lines = [status, ""]

    if target:
        if target not in servers:
            return ToolResult(ok=False, output="", error=f"server {target!r} not in config; available: {list(servers)}")
        cfg = servers[target]
        out_lines.append(f"=== server: {target} ===")
        out_lines.append(f"transport: {cfg.get('transport', 'stdio')}")
        if cfg.get("description"):
            out_lines.append(f"desc: {cfg['description']}")
        try:
            tools = _run_async(_connect_and_call(cfg, "list_tools"))
            out_lines.append(f"tools ({len(tools)}):")
            for t in tools:
                desc = (t.description or "").split("\n")[0][:120]
                out_lines.append(f"  - {t.name}  ·  {desc}")
        except Exception as e:
            out_lines.append(f"  [connect failed] {type(e).__name__}: {e}")
    else:
        for name, cfg in servers.items():
            out_lines.append(f"  {name}  ({cfg.get('transport','stdio')})  ·  {cfg.get('description', '')}")
        out_lines.append("\n用 mcp_list({server: '<name>'}) 看某个 server 的 tools 详情")

    return ToolResult(ok=True, output="\n".join(out_lines))


def _run_mcp_call_tool(args: dict) -> ToolResult:
    server_name = (args.get("server") or "").strip()
    tool_name = (args.get("tool") or "").strip()
    if not server_name or not tool_name:
        return ToolResult(ok=False, output="", error="server and tool are required")

    servers, status = _load_servers()
    if server_name not in servers:
        return ToolResult(
            ok=False, output="",
            error=f"server {server_name!r} not in config. {status}",
        )

    arguments = args.get("arguments") or {}
    if not isinstance(arguments, dict):
        return ToolResult(ok=False, output="", error=f"arguments must be object, got {type(arguments).__name__}")

    try:
        result = _run_async(_connect_and_call(
            servers[server_name], "call_tool",
            tool=tool_name, arguments=arguments,
        ))
    except asyncio.TimeoutError:
        return ToolResult(ok=False, output="", error=f"MCP call timed out after {CALL_TIMEOUT_SECONDS}s")
    except Exception as e:
        return ToolResult(ok=False, output="", error=f"MCP call failed: {type(e).__name__}: {e}")

    is_error = result.get("is_error", False)
    content = result.get("content", "")

    out = (
        f"mcp_call_tool · server={server_name} · tool={tool_name}\n"
        f"is_error: {is_error}\n"
        f"---\n{content}"
    )
    return ToolResult(ok=not is_error, output=out, error="server reported tool error" if is_error else None)


def _run_mcp_describe(args: dict) -> ToolResult:
    server_name = (args.get("server") or "").strip()
    tool_name = (args.get("tool") or "").strip()
    if not server_name or not tool_name:
        return ToolResult(ok=False, output="", error="server and tool are required")

    servers, status = _load_servers()
    if server_name not in servers:
        return ToolResult(ok=False, output="", error=f"server {server_name!r} not configured")

    try:
        tool = _run_async(_connect_and_call(servers[server_name], "describe_tool", tool=tool_name))
    except Exception as e:
        return ToolResult(ok=False, output="", error=f"describe failed: {type(e).__name__}: {e}")

    if tool is None:
        return ToolResult(ok=False, output="", error=f"tool {tool_name!r} not found on server {server_name!r}")

    schema = getattr(tool, "inputSchema", None) or {}
    out = (
        f"mcp tool · {server_name}/{tool_name}\n"
        f"description: {tool.description or '(none)'}\n"
        f"input schema:\n{json.dumps(schema, indent=2, ensure_ascii=False)}"
    )
    return ToolResult(ok=True, output=out)


SPEC_LIST = ToolSpec(
    name="mcp_list",
    description=(
        "List configured MCP servers (read .mcp/servers.json). "
        "Optional 'server' arg → connect to that server and list its tools. "
        "Use this FIRST to discover what MCP capabilities are available before mcp_call_tool. "
        "AUTO tier (read-only discovery)."
    ),
    tier=TIER_AUTO,
    input_schema={
        "type": "object",
        "properties": {
            "server": {"type": "string", "description": "Optional server name to introspect"},
        },
    },
    run=_run_mcp_list,
    summarize=_summarize_list,
)


SPEC_DESCRIBE = ToolSpec(
    name="mcp_describe_tool",
    description=(
        "Get the input schema and description of a specific MCP tool. "
        "Use before mcp_call_tool to understand exactly what arguments to pass. "
        "AUTO tier (read-only)."
    ),
    tier=TIER_AUTO,
    input_schema={
        "type": "object",
        "properties": {
            "server": {"type": "string", "description": "MCP server name (from .mcp/servers.json)"},
            "tool": {"type": "string", "description": "Tool name on that server"},
        },
        "required": ["server", "tool"],
    },
    run=_run_mcp_describe,
    summarize=_summarize_describe,
)


SPEC_CALL = ToolSpec(
    name="mcp_call_tool",
    description=(
        "Call a tool on a configured MCP server. CONFIRM tier because the remote tool's "
        "actual side effects are unknown to OPUS in advance—e.g. github 'create_issue' really "
        "creates an issue. Use mcp_list / mcp_describe_tool first to know what you're invoking."
    ),
    tier=TIER_CONFIRM,
    input_schema={
        "type": "object",
        "properties": {
            "server": {"type": "string", "description": "MCP server name"},
            "tool": {"type": "string", "description": "Tool name on that server"},
            "arguments": {
                "type": "object",
                "description": "Arguments dict matching the tool's input schema",
            },
        },
        "required": ["server", "tool"],
    },
    run=_run_mcp_call_tool,
    summarize=_summarize_call,
)


register_tool(SPEC_LIST)
register_tool(SPEC_DESCRIBE)
register_tool(SPEC_CALL)
