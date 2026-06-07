"""
agent_tools/clipboard.py
========================

剪贴板读写——OPUS 和 用户 之间最快的"无打字"通道。

实现：
  - Windows 走 PowerShell Get-Clipboard / Set-Clipboard（stdlib subprocess，零依赖）
  - 其他平台先返回错误，等真有需要再加
  - 写入用 stdin pipe 避免命令行注入

档位：
  - read_clipboard   → AUTO（无副作用）
  - write_clipboard  → CONFIRM（覆盖 用户 当前剪贴板，要他点头）
"""

from __future__ import annotations

import os
import subprocess

from . import TIER_AUTO, TIER_CONFIRM, ToolResult, ToolSpec, register_tool
from ._subprocess_helper import no_window_kwargs


_IS_WIN = os.name == "nt"


def _read_summarize(_args: dict) -> str:
    return "read_clipboard"


def _read_run(_args: dict) -> ToolResult:
    if not _IS_WIN:
        return ToolResult(ok=False, output="", error="only Windows supported in v0.1; ask OPUS to add macOS/Linux")

    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-Command", "Get-Clipboard -Raw"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=5,
            **no_window_kwargs(),
        )
    except subprocess.TimeoutExpired:
        return ToolResult(ok=False, output="", error="clipboard read timed out")
    except Exception as e:
        return ToolResult(ok=False, output="", error=f"powershell error: {e!r}")

    text = proc.stdout or ""
    text = text.rstrip("\r\n")

    if not text:
        return ToolResult(ok=True, output="(clipboard is empty)")

    n = len(text)
    preview = text if n <= 4000 else text[:4000] + f"\n\n[... truncated, total {n} chars ...]"
    return ToolResult(
        ok=True,
        output=f"clipboard ({n} chars):\n---\n{preview}",
    )


def _write_summarize(args: dict) -> str:
    text = (args.get("text") or "")[:80]
    return f"write_clipboard  text={text!r}"


def _write_run(args: dict) -> ToolResult:
    if not _IS_WIN:
        return ToolResult(ok=False, output="", error="only Windows supported in v0.1")

    text = args.get("text")
    if text is None:
        return ToolResult(ok=False, output="", error="missing 'text'")

    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-Command", "Set-Clipboard -Value $input"],
            input=str(text),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=5,
            **no_window_kwargs(),
        )
    except subprocess.TimeoutExpired:
        return ToolResult(ok=False, output="", error="clipboard write timed out")
    except Exception as e:
        return ToolResult(ok=False, output="", error=f"powershell error: {e!r}")

    if proc.returncode != 0:
        return ToolResult(ok=False, output="", error=f"powershell exit {proc.returncode}: {proc.stderr}")

    return ToolResult(
        ok=True,
        output=f"clipboard set ({len(str(text))} chars). 用户 can now paste anywhere.",
    )


READ_SPEC = ToolSpec(
    name="read_clipboard",
    description=(
        "Read 用户's current clipboard text content. Use when 用户 says 'check my clipboard', "
        "'look at what I copied', or implies he wants you to see something he just copied "
        "(error log, code snippet, URL, etc) instead of typing it out."
    ),
    tier=TIER_AUTO,
    input_schema={"type": "object", "properties": {}},
    run=_read_run,
    summarize=_read_summarize,
)


WRITE_SPEC = ToolSpec(
    name="write_clipboard",
    description=(
        "Write text to 用户's clipboard for him to paste. Use when you've prepared a summary, "
        "code snippet, command, or URL that 用户 will want to paste somewhere (Cursor / WeChat / browser). "
        "CONFIRM tier — overwriting clipboard is mildly disruptive."
    ),
    tier=TIER_CONFIRM,
    input_schema={
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "The text to put on the clipboard"},
        },
        "required": ["text"],
    },
    run=_write_run,
    summarize=_write_summarize,
)


register_tool(READ_SPEC)
register_tool(WRITE_SPEC)
