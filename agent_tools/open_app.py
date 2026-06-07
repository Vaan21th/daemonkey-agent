"""
agent_tools/open_app.py
=======================

帮 用户 启动桌面应用——他说"开 Cursor"/"打开微信"/"启动 Chrome"，OPUS 直接调。

实现：
  - 内置 用户 常用 app 的快捷别名 → 真实路径表
  - fallback：os.startfile（Windows shell 关联） / shutil.which 找 PATH
  - 别名匹配是模糊的（"cursor" 匹配 "Cursor"）

档位：CONFIRM
  - 启动 app 是有形动作（弹窗、占资源）
  - 但不是危险——用户 一句 y 即可
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from . import TIER_CONFIRM, ToolResult, ToolSpec, register_tool
from ._subprocess_helper import detached_kwargs


# 常见 app 别名 → 候选路径列表（按优先级，第一个能找到的赢）
APP_ALIASES: dict[str, list[str]] = {
    "cursor": [
        r"%LOCALAPPDATA%\Programs\cursor\Cursor.exe",
        r"%LOCALAPPDATA%\Programs\Cursor\Cursor.exe",
        r"%PROGRAMFILES%\Cursor\Cursor.exe",
    ],
    "chrome": [
        r"%PROGRAMFILES%\Google\Chrome\Application\chrome.exe",
        r"%PROGRAMFILES(X86)%\Google\Chrome\Application\chrome.exe",
        r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe",
    ],
    "edge": [
        r"%PROGRAMFILES(X86)%\Microsoft\Edge\Application\msedge.exe",
        r"%PROGRAMFILES%\Microsoft\Edge\Application\msedge.exe",
    ],
    "wechat": [
        r"%PROGRAMFILES(X86)%\Tencent\WeChat\WeChat.exe",
        r"%PROGRAMFILES%\Tencent\WeChat\WeChat.exe",
    ],
    "微信": [  # 中文别名
        r"%PROGRAMFILES(X86)%\Tencent\WeChat\WeChat.exe",
        r"%PROGRAMFILES%\Tencent\WeChat\WeChat.exe",
    ],
    "vscode": [
        r"%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe",
        r"%PROGRAMFILES%\Microsoft VS Code\Code.exe",
    ],
    "code": [
        r"%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe",
        r"%PROGRAMFILES%\Microsoft VS Code\Code.exe",
    ],
    "explorer": [r"explorer.exe"],
    "notepad": [r"notepad.exe"],
    "powershell": [r"powershell.exe"],
    "calc": [r"calc.exe"],
    "terminal": [r"wt.exe"],  # Windows Terminal
}


def _resolve_path(candidates: list[str]) -> Path | None:
    for raw in candidates:
        expanded = os.path.expandvars(raw)
        p = Path(expanded)
        if p.exists():
            return p
        which = shutil.which(expanded)
        if which:
            return Path(which)
    return None


def _summarize(args: dict) -> str:
    target = args.get("app") or args.get("path") or "?"
    extra_args = args.get("args") or []
    return f"open_app  target={target!r}" + (f"  args={extra_args}" if extra_args else "")


def _run(args: dict) -> ToolResult:
    target = (args.get("app") or args.get("path") or "").strip()
    if not target:
        return ToolResult(ok=False, output="", error=f"missing 'app'; known aliases: {', '.join(sorted(APP_ALIASES))}")

    extra_args = args.get("args") or []
    if not isinstance(extra_args, list):
        return ToolResult(ok=False, output="", error="'args' must be a list of strings")

    key = target.lower()
    if key in APP_ALIASES:
        path = _resolve_path(APP_ALIASES[key])
        if not path:
            return ToolResult(
                ok=False, output="",
                error=f"alias {target!r} known but no install found in {APP_ALIASES[key]}",
            )
    else:
        if Path(target).exists():
            path = Path(target)
        else:
            which = shutil.which(target)
            if which:
                path = Path(which)
            else:
                return ToolResult(
                    ok=False, output="",
                    error=(
                        f"can't find app {target!r}; "
                        f"try one of: {', '.join(sorted(APP_ALIASES))} "
                        f"or pass full path"
                    ),
                )

    try:
        cmd = [str(path)] + [str(a) for a in extra_args]
        subprocess.Popen(cmd, **detached_kwargs())
    except Exception as e:
        return ToolResult(ok=False, output="", error=f"launch failed: {e!r}")

    return ToolResult(
        ok=True,
        output=(
            f"launched: {path}\n"
            f"  args: {extra_args or '(none)'}\n"
            f"  detached: yes (won't block daemon)"
        ),
    )


SPEC = ToolSpec(
    name="open_app",
    description=(
        "Launch a desktop application. Use when 用户 says '打开/启动/开 X' or '帮我打开 X'. "
        "Built-in aliases: cursor / chrome / edge / wechat / 微信 / vscode / code / explorer / "
        "notepad / powershell / calc / terminal. "
        "You can also pass a full path or a command on PATH. "
        "Optional 'args' list passes extra arguments (e.g. open Cursor at a project: "
        "{app:'cursor', args:['F:/Desktop/Daemonkey']}). "
        "CONFIRM tier — 用户 sees the launch and confirms."
    ),
    tier=TIER_CONFIRM,
    input_schema={
        "type": "object",
        "properties": {
            "app": {
                "type": "string",
                "description": "App alias, full path, or command on PATH",
            },
            "args": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Extra arguments (e.g. file/url/project path to open with the app)",
            },
        },
        "required": ["app"],
    },
    run=_run,
    summarize=_summarize,
)


register_tool(SPEC)
