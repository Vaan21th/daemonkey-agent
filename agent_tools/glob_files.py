"""
agent_tools/glob_files.py
=========================

OPUS 的"按名字找文件"——通配符列文件。补 Cursor Glob 那块盲区 (续 ④)。

为什么 (grep_files / shell 都不顺手):
  grep_files 要先有"内容 pattern"·想按【文件名】找 (chat.* / **/*.py / 所有 test_*)
  只能绕 shell_exec dir·跨平台还不一致。 glob_files 一步到位·按 mtime 排 (最近改的在前)。

实现:
  1. 优先 `rg --files` (快·懂 .gitignore) + Python fnmatch 过滤
  2. 没 rg 退回 Path.rglob

AUTO tier · 纯读。
"""

from __future__ import annotations

import fnmatch
import subprocess
from pathlib import Path

from . import TIER_AUTO, ToolResult, ToolSpec, register_tool
from ._subprocess_helper import no_window_kwargs


ROOT = Path(__file__).resolve().parent.parent
MAX_RESULTS = 300

_SKIP_PARTS = {
    ".git", ".venv", "node_modules", "__pycache__", "site-packages",
    "_backups", "browser_profile_standalone", ".pytest_cache",
}


def _summarize(args: dict) -> str:
    return f"glob_files  {args.get('pattern', '?')}  in {args.get('path', '.')}"


def _norm(pattern: str) -> str:
    """'*.py' → '**/*.py' (不带目录分隔的纯名字模式默认递归全树)。"""
    p = pattern.replace("\\", "/")
    if "/" not in p and not p.startswith("**"):
        return f"**/{p}"
    return p


def _skip(rel: str) -> bool:
    return any(part in _SKIP_PARTS for part in Path(rel).parts)


def _try_rg(base: Path, pattern: str) -> tuple[bool, list[str]]:
    """rg --files 列全部文件 · Python 侧 fnmatch 过滤 (rg 的 -g 语义跟 Path.glob 不完全一致·统一交给 fnmatch)。"""
    try:
        proc = subprocess.run(
            ["rg", "--files", str(base)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=20, **no_window_kwargs(),
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False, []
    if proc.returncode not in (0, 1):
        return False, []
    files = [ln.strip() for ln in (proc.stdout or "").splitlines() if ln.strip()]
    return True, files


def _rglob_fallback(base: Path) -> list[str]:
    out = []
    for p in base.rglob("*"):
        if p.is_file():
            out.append(str(p))
    return out


def _run(args: dict) -> ToolResult:
    pattern = args.get("pattern")
    if not pattern:
        return ToolResult(ok=False, output="", error="missing 'pattern' (如 '*.py' / '**/test_*.js' / 'chat.*')")

    base_arg = args.get("path") or "."
    base = Path(base_arg)
    if not base.is_absolute():
        base = ROOT / base
    base = base.resolve()
    if not base.exists():
        return ToolResult(ok=False, output="", error=f"path not found: {base}")

    norm = _norm(pattern)

    ok, files = _try_rg(base, pattern)
    if not ok:
        files = _rglob_fallback(base)

    # 统一用 fnmatch 过滤 (相对 base 的 posix 路径 + 纯文件名两种都试·命中其一即可)
    matched: list[Path] = []
    for f in files:
        fp = Path(f)
        try:
            rel = fp.relative_to(base).as_posix()
        except ValueError:
            rel = fp.name
        if _skip(rel):
            continue
        if fnmatch.fnmatch(rel, norm) or fnmatch.fnmatch(fp.name, pattern):
            matched.append(fp)

    if not matched:
        return ToolResult(ok=True, output=f"(no files match {pattern!r} under {base})")

    # 按 mtime 倒序 (最近改的在前·跟 Cursor Glob 一致)
    def _mtime(p: Path) -> float:
        try:
            return p.stat().st_mtime
        except OSError:
            return 0.0
    matched.sort(key=_mtime, reverse=True)

    truncated = len(matched) > MAX_RESULTS
    shown = matched[:MAX_RESULTS]
    lines = [f"# glob_files {pattern!r}  ({len(matched)} matches, newest first)"]
    for p in shown:
        try:
            rel = p.relative_to(ROOT).as_posix()
        except ValueError:
            rel = str(p)
        lines.append(rel)
    if truncated:
        lines.append(f"... [{len(matched) - MAX_RESULTS} more · 收窄 pattern 或 path]")
    return ToolResult(ok=True, output="\n".join(lines), truncated=truncated)


SPEC = ToolSpec(
    name="glob_files",
    description=(
        "Find files by NAME / glob pattern (complements grep_files which searches file CONTENT). "
        "Use for 'all *.py', '**/test_*.js', 'chat.*', 'where is the file called outline_file'. "
        "Bare patterns without a slash search the whole tree recursively. Results sorted newest-first. "
        "Skips .git/.venv/node_modules/__pycache__. Read-only."
    ),
    tier=TIER_AUTO,
    input_schema={
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Glob pattern, e.g. '*.py', '**/*.tsx', 'test_*.py', 'chat.*'.",
            },
            "path": {
                "type": "string",
                "description": "Directory to search under. Default: project root.",
            },
        },
        "required": ["pattern"],
    },
    run=_run,
    summarize=_summarize,
)


register_tool(SPEC)
