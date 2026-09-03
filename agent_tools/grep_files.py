"""
agent_tools/grep_files.py
=========================

Daemonkey 的"找"——在项目里搜文本。

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
import time
from pathlib import Path

from . import TIER_AUTO, ToolResult, ToolSpec, register_tool
from ._subprocess_helper import no_window_kwargs


ROOT = Path(__file__).resolve().parent.parent
MAX_RESULTS = 200
MAX_OUTPUT_CHARS = 20000

_SKIP_DIR_PARTS = {
    ".git", ".venv", "node_modules", "__pycache__", "site-packages",
    "edge_cdp_profile", "webview2_main", "EBWebView", ".npm-cache",
}
_RG_SKIP_GLOBS = (
    "!.git/**", "!.venv/**", "!node_modules/**", "!**/__pycache__/**",
    "!sessions/edge_cdp_profile/**", "!**/webview2_main/**", "!**/EBWebView/**",
    "!**/.npm-cache/**",
)
_PY_FALLBACK_SEC = 15


def _summarize(args: dict) -> str:
    pattern = args.get("pattern", "?")
    path = args.get("path", ".")
    glob = args.get("glob", "")
    return f"grep_files  '{pattern}'  in {path}" + (f"  glob={glob}" if glob else "")


def _try_rg(pattern: str, path: Path, glob: str | None, case_insensitive: bool) -> tuple[str, str]:
    """返回 (status, output)。status: ok / missing / timeout / error。

    timeout 绝不能落到 Python 整树硬扫 —— 两个 grep 并行时会把 daemon 卡死几分钟,
    下一轮 self_heal 还写成「异常退出」。
    """
    cmd = ["rg", "--no-heading", "-n", "--color=never", "-M", "300"]
    if case_insensitive:
        cmd.append("-i")
    if glob:
        cmd.extend(["-g", glob])
    cmd.extend(["-g", "!.env", "-g", "!.env.*"])
    for g in _RG_SKIP_GLOBS:
        cmd.extend(["-g", g])
    cmd.append(pattern)
    cmd.append(str(path))

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=20, **no_window_kwargs())
    except FileNotFoundError:
        return "missing", "rg not installed"
    except subprocess.TimeoutExpired:
        return "timeout", "rg timed out after 20s"

    if proc.returncode == 1:
        return "ok", "(no matches)"
    if proc.returncode > 1:
        return "error", f"rg exit {proc.returncode}: {proc.stderr or '(no stderr)'}"
    return "ok", proc.stdout or "(no output)"


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
    deadline = time.monotonic() + _PY_FALLBACK_SEC

    if path.is_file():
        # 单文件直接搜（glob 在单文件场景下被忽略）
        matched = _grep_one_file(path, regex)
    elif path.is_dir():
        iter_paths = path.rglob(glob) if glob else path.rglob("*")
        for p in iter_paths:
            if time.monotonic() > deadline:
                matched.append(f"... [python fallback stopped at {_PY_FALLBACK_SEC}s · 把 path 收到子目录]")
                break
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
    try:
        p.relative_to(ROOT.resolve())
    except ValueError:
        return ToolResult(ok=False, output="", error="path 必须在工程根内")
    if p.name.startswith(".env") or p.name in {".env", ".env.local"}:
        return ToolResult(ok=False, output="", error="拒绝扫描密钥文件")
    if not p.exists():
        return ToolResult(ok=False, output="", error=f"path not found: {p}")

    glob = args.get("glob") or None
    case_insensitive = bool(args.get("case_insensitive", False))

    status, out = _try_rg(pattern, p, glob, case_insensitive)
    if status == "timeout":
        return ToolResult(ok=False, output="", error="search timed out (20s) · 把 path 收到子目录再搜")
    if status == "missing":
        ok, out = _python_fallback(pattern, p, glob, case_insensitive)
    elif status == "error":
        ok, out = False, out
    else:
        ok = True

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
