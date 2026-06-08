"""
agent_tools/grep_files.py
=========================

OPUS 的"找"——在项目里搜文本。

实现策略：
  1. 优先调外部 ripgrep (`rg`)——又快又懂 .gitignore
  2. 没装 rg 就退回 Python 实现（对小项目够用）

GIVEN 这是一个纯查询工具——AUTO tier，不需要 BRO 介入。

Bug 修复（2026-05-15 15:35）：
  之前 _python_fallback 用 path.rglob("*") 处理路径——如果 path 是 *单文件*，
  rglob 返回空（文件没有子文件），导致一切搜索"no matches"。
  本次新增：path.is_file() 时直接搜该文件。
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from . import TIER_AUTO, ToolResult, ToolSpec, register_tool
from ._subprocess_helper import no_window_kwargs


ROOT = Path(__file__).resolve().parent.parent
MAX_RESULTS = 200
MAX_OUTPUT_CHARS = 20000

_SKIP_DIR_PARTS = {".git", ".venv", "node_modules", "__pycache__", "site-packages"}


def _summarize(args: dict) -> str:
    pattern = args.get("pattern", "?")
    path = args.get("path", ".")
    glob = args.get("glob", "")
    return f"grep_files  '{pattern}'  in {path}" + (f"  glob={glob}" if glob else "")


def _try_rg(pattern: str, path: Path, glob: str | None, case_insensitive: bool) -> tuple[bool, str]:
    """Returns (ok, output). ok=False means rg unavailable / errored."""
    cmd = ["rg", "--no-heading", "-n", "--color=never", "-M", "300"]
    if case_insensitive:
        cmd.append("-i")
    if glob:
        cmd.extend(["-g", glob])
    cmd.append(pattern)
    cmd.append(str(path))

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=20, **no_window_kwargs())
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        return False, f"rg failed: {e}"

    if proc.returncode == 1:
        return True, "(no matches)"
    if proc.returncode > 1:
        return False, f"rg exit {proc.returncode}: {proc.stderr or '(no stderr)'}"
    return True, proc.stdout or "(no output)"


def _grep_one_file(p: Path, regex: re.Pattern, label: Path | None = None) -> list[str]:
    """Search a single file. Returns list of formatted match lines."""
    out: list[str] = []
    show = label or p
    try:
        with p.open("r", encoding="utf-8", errors="ignore") as f:
            for lineno, line in enumerate(f, 1):
                if regex.search(line):
                    out.append(f"{show}:{lineno}: {line.rstrip()}")
                    if len(out) >= MAX_RESULTS:
                        out.append(f"... [stopped at {MAX_RESULTS} matches]")
                        break
    except (OSError, UnicodeDecodeError):
        pass
    return out


def _python_fallback(pattern: str, path: Path, glob: str | None, case_insensitive: bool) -> tuple[bool, str]:
    flags = re.IGNORECASE if case_insensitive else 0
    try:
        regex = re.compile(pattern, flags)
    except re.error as e:
        return False, f"invalid regex: {e}"

    matched: list[str] = []

    if path.is_file():
        # 单文件直接搜（glob 在单文件场景下被忽略）
        matched = _grep_one_file(path, regex)
    elif path.is_dir():
        iter_paths = path.rglob(glob) if glob else path.rglob("*")
        for p in iter_paths:
            if not p.is_file():
                continue
            if any(part in _SKIP_DIR_PARTS for part in p.parts):
                continue
            sub = _grep_one_file(p, regex)
            matched.extend(sub)
            if len(matched) >= MAX_RESULTS:
                break
    else:
        return False, f"path is neither file nor directory: {path}"

    if not matched:
        return True, "(no matches)"
    return True, "\n".join(matched)


def _run(args: dict) -> ToolResult:
    pattern = args.get("pattern")
    if not pattern:
        return ToolResult(ok=False, output="", error="missing 'pattern'")

    path_arg = args.get("path") or "."
    p = Path(path_arg)
    if not p.is_absolute():
        p = ROOT / p
    p = p.resolve()
    if not p.exists():
        return ToolResult(ok=False, output="", error=f"path not found: {p}")

    glob = args.get("glob") or None
    case_insensitive = bool(args.get("case_insensitive", False))

    ok, out = _try_rg(pattern, p, glob, case_insensitive)
    if not ok:
        ok, out = _python_fallback(pattern, p, glob, case_insensitive)

    truncated = False
    if len(out) > MAX_OUTPUT_CHARS:
        out = out[:MAX_OUTPUT_CHARS] + f"\n\n... [truncated; full was {len(out)} chars]"
        truncated = True

    return ToolResult(ok=ok, output=out, truncated=truncated, error=None if ok else "search failed")


SPEC = ToolSpec(
    name="grep_files",
    description=(
        "Search for a regex pattern across files OR within a single file. "
        "Path can be a directory (recursive search) or a single file. "
        "Uses ripgrep if installed, falls back to a Python implementation. "
        "Skips .git/.venv/node_modules/__pycache__/site-packages. "
        "Returns at most 200 matches and 20000 chars of output."
    ),
    tier=TIER_AUTO,
    input_schema={
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Regex pattern to search for.",
            },
            "path": {
                "type": "string",
                "description": "File or directory to search. Default: project root.",
            },
            "glob": {
                "type": "string",
                "description": "Optional glob filter (only applies when path is a directory), e.g. '*.py' or '**/*.md'.",
            },
            "case_insensitive": {
                "type": "boolean",
                "description": "Case-insensitive search. Default false.",
            },
        },
        "required": ["pattern"],
    },
    run=_run,
    summarize=_summarize,
)


register_tool(SPEC)
