"""
agent_tools/lint_check.py
=========================

OPUS 的"逻辑体检"——不只是语法·还抓未定义名 / 未用导入 / 重定义 / 参数打错 等。

为什么 (续 · 盲区③):
  edit_selfcheck / frontend_check 只验【语法崩没崩】(ast.parse / node --check)。
  但很多 BUG 是"语法对·逻辑错": 用了没定义的变量、import 了没用、函数名打错、
  后一个函数定义把前一个覆盖了…… Cursor 的 ReadLints 能看见这些·daemon 一直是瞎的。
  本工具补这一层。

后端优先级 (优雅降级·任何环境都能跑出点东西):
  Python:  ruff (--select F,E9 = pyflakes 逻辑错 + 语法错·噪音低) → pyflakes → ast 纯语法
  JS/TS:   node --check (语法·deeper eslint 需 config·留待以后)

AUTO tier · 纯诊断 · 不改任何文件。
"""

from __future__ import annotations

import ast
import shutil
import subprocess
import sys
from pathlib import Path

from . import TIER_AUTO, ToolResult, ToolSpec, register_tool
from ._subprocess_helper import no_window_kwargs


ROOT = Path(__file__).resolve().parent.parent
MAX_OUTPUT_CHARS = 20000
_PY_EXT = {".py"}
_JS_EXT = {".js", ".mjs", ".ts", ".jsx", ".tsx"}


def _resolve(path_str: str) -> Path:
    p = Path(path_str)
    if not p.is_absolute():
        p = ROOT / p
    return p.resolve()


def _summarize(args: dict) -> str:
    return f"lint_check  {args.get('path', '?')}"


def _ruff_cmd() -> list[str] | None:
    """找一个能跑的 ruff 调用方式·找不到返 None。"""
    exe = Path(sys.executable).parent / ("ruff.exe" if sys.platform == "win32" else "ruff")
    if exe.exists():
        return [str(exe)]
    which = shutil.which("ruff")
    if which:
        return [which]
    # python -m ruff (新版 ruff 支持)
    try:
        r = subprocess.run([sys.executable, "-m", "ruff", "--version"],
                           capture_output=True, timeout=8, **no_window_kwargs())
        if r.returncode == 0:
            return [sys.executable, "-m", "ruff"]
    except Exception:
        pass
    return None


def _lint_python_ruff(base: list[str], path: Path) -> tuple[bool, str, str]:
    """returns (ran, tool_label, output)。ran=False = ruff 没跑成 (调用方降级)。"""
    cmd = base + ["check", "--select", "F,E9", "--output-format", "concise", str(path)]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=40, **no_window_kwargs())
    except Exception as e:
        return False, "", f"ruff 跑不起来: {type(e).__name__}: {e}"
    out = (r.stdout or "").strip()
    # ruff: returncode 0 = clean · 1 = 有问题 · >1 = 工具本身错
    if r.returncode == 0:
        return True, "ruff --select F,E9", ""
    if r.returncode == 1:
        return True, "ruff --select F,E9", out or "(ruff 报了问题但无输出)"
    return False, "", f"ruff exit {r.returncode}: {(r.stderr or '').strip()[:300]}"


def _lint_python_pyflakes(path: Path) -> tuple[bool, str, str]:
    try:
        import pyflakes.api, pyflakes.reporter  # noqa: F401
    except Exception:
        return False, "", "pyflakes 未安装"
    import io
    buf_out, buf_err = io.StringIO(), io.StringIO()
    try:
        from pyflakes.reporter import Reporter
        rep = Reporter(buf_out, buf_err)
        if path.is_dir():
            from pyflakes.api import checkRecursive
            checkRecursive([str(path)], rep)
        else:
            from pyflakes.api import checkPath
            checkPath(str(path), rep)
    except Exception as e:
        return False, "", f"pyflakes 异常: {e}"
    out = (buf_out.getvalue() + buf_err.getvalue()).strip()
    return True, "pyflakes", out


def _lint_python_ast(path: Path) -> tuple[bool, str, str]:
    """最后兜底·只验语法。"""
    files = list(path.rglob("*.py")) if path.is_dir() else [path]
    problems = []
    for f in files:
        try:
            ast.parse(f.read_text(encoding="utf-8"), filename=str(f))
        except SyntaxError as e:
            problems.append(f"{f}:{e.lineno}: SyntaxError: {e.msg}")
        except Exception:
            pass
    return True, "ast (仅语法·装 ruff 可看逻辑错)", "\n".join(problems)


def _lint_js(path: Path) -> tuple[bool, str, str]:
    node = shutil.which("node")
    if not node:
        return True, "(node 缺失·跳过 JS)", ""
    files = [path] if path.is_file() else [p for p in path.rglob("*") if p.suffix.lower() in _JS_EXT]
    problems = []
    for f in files:
        try:
            r = subprocess.run([node, "--check", str(f)], capture_output=True,
                              timeout=20, **no_window_kwargs())
        except Exception:
            continue
        if r.returncode != 0:
            err = (r.stderr or b"").decode("utf-8", "replace").strip()
            problems.append(f"{f.name}: {err[:300]}")
    return True, "node --check (语法)", "\n".join(problems)


def _run(args: dict) -> ToolResult:
    raw = args.get("path")
    if not raw:
        return ToolResult(ok=False, output="", error="missing 'path' (文件或目录)")
    path = _resolve(raw)
    if not path.exists():
        return ToolResult(ok=False, output="", error=f"path not found: {path}")

    suffix = path.suffix.lower()
    is_js = (path.is_file() and suffix in _JS_EXT)

    if is_js:
        _, tool, problems = _lint_js(path)
    else:
        # Python (文件 .py 或 目录) · ruff → pyflakes → ast
        base = _ruff_cmd()
        ran = False
        tool = problems = ""
        if base:
            ran, tool, problems = _lint_python_ruff(base, path)
        if not ran:
            ran, tool, problems = _lint_python_pyflakes(path)
        if not ran:
            ran, tool, problems = _lint_python_ast(path)

    if not problems:
        return ToolResult(ok=True, output=f"# lint: {path}  (tool={tool})\n✅ clean — 没扫到逻辑/语法问题")

    lines = problems.splitlines()
    n = len(lines)
    body = f"# lint: {path}  (tool={tool})\n{n} 个问题:\n" + "\n".join(f"  {ln}" for ln in lines)
    truncated = False
    if len(body) > MAX_OUTPUT_CHARS:
        body = body[:MAX_OUTPUT_CHARS] + "\n\n... [truncated]"
        truncated = True
    body += "\n\n→ 这些是 lint 警告 (语法对但可能是 bug)·逐条核·改用 edit_file·别整文件 overwrite。"
    return ToolResult(ok=True, output=body, truncated=truncated)


SPEC = ToolSpec(
    name="lint_check",
    description=(
        "Lint a Python file/dir (or a JS/TS file) for LOGIC problems beyond mere syntax — "
        "undefined names, unused imports, redefinitions, etc. (the 'syntax-valid but buggy' class). "
        "Python uses ruff --select F,E9 (falls back to pyflakes, then ast syntax-only); "
        "JS uses node --check (syntax). Run this after editing your own .py code, before request_restart, "
        "to catch bugs that node --check / ast.parse can't see. Read-only."
    ),
    tier=TIER_AUTO,
    input_schema={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Python file or directory, or a single JS/TS file. Relative resolves from Daemonkey root.",
            },
        },
        "required": ["path"],
    },
    run=_run,
    summarize=_summarize,
)


register_tool(SPEC)
