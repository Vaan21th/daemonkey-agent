"""
agent_tools/python_exec.py
==========================

OPUS 跑 Python 代码的手——绕过 shell 转义地狱。

为什么造这个工具——
  扫最近 30 个 session 的 224 次 shell_exec · 42 次 (18.8%) 失败 ·
  其中 **78.6% 是 `python -c "<多行脚本>"` 类型** ·
  原因都是 PowerShell + cmd line + Python 三层转义嵌套 · LLM 写不对。
  
  这工具直接接 Python 源码 · 落 _tmp_<uuid>.py · 用 .venv 跑 ·
  不走 shell · 没引号嵌套问题。

跟 shell_exec 的关系:
  - 跑命令 / git / curl 等 → 还是用 shell_exec
  - 跑 Python 代码 (检查文件 / 算东西 / 调 Python 库) → 用 python_exec

安全:
  - tier=CONFIRM (能跑任意 Python · 跟 shell_exec 同档)
  - GUARD 检测 (粗筛 · 命中关键字升档): os.system / subprocess / shutil.rmtree / 进程操作
  - 真正的『自杀防护』(防 daemon 杀自己) 在另一根 wish 修

输出: 同 shell_exec · 含 --- stdout --- / --- stderr --- / --- exit code: X ---

超时: 默认 30s · 最长 300s
输出截断: 8000 chars
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

from . import (
    TIER_AUTO,
    TIER_CONFIRM,
    TIER_GUARD,
    ToolResult,
    ToolSpec,
    register_tool,
)
from ._subprocess_helper import no_window_kwargs


ROOT = Path(__file__).resolve().parent.parent
VENV_PY = ROOT / ".venv" / "Scripts" / "python.exe" if sys.platform.startswith("win") else ROOT / ".venv" / "bin" / "python"

DEFAULT_TIMEOUT_SEC = 30
MAX_TIMEOUT_SEC = 300
MAX_OUTPUT_CHARS = 8000


_GUARD_PATTERNS = [
    r"\bos\.system\s*\(",
    r"\bsubprocess\.(run|call|Popen|check_output|check_call)\s*\(",
    r"\bshutil\.rmtree\s*\(",
    r"\bfrom\s+shutil\s+import\s+[\w\s,]*\brmtree\b",
    r"\brmtree\s*\(",
    r"\bos\.remove\s*\([\s'\"]*[/\\]",
    r"\bos\.unlink\s*\([\s'\"]*[/\\]",
    r"\bos\.kill\s*\(",
    r"\bfrom\s+os\s+import\s+[\w\s,]*\bkill\b",
    r"signal\.SIGKILL|signal\.SIGTERM",
    r"\bsocket\.(socket|create_server)\s*\(",
    r"\bopen\s*\([^)]*['\"][a-zA-Z]:\\\\[^)]*['\"](\s*,\s*['\"][wxa])",
    r"^\s*import\s+os\s*;\s*os\.",
    r"__import__\s*\(\s*['\"]subprocess",
]
_GUARD_RE = re.compile("|".join(f"(?:{p})" for p in _GUARD_PATTERNS), re.IGNORECASE | re.MULTILINE)


def _classify_code(code: str) -> str:
    if not code.strip():
        return TIER_CONFIRM
    if _GUARD_RE.search(code):
        return TIER_GUARD
    return TIER_CONFIRM


def _summarize(args: dict) -> str:
    code = (args.get("code") or "").strip()
    first_line = code.split("\n", 1)[0][:120] if code else "(empty)"
    n_lines = len(code.splitlines())
    timeout = args.get("timeout") or DEFAULT_TIMEOUT_SEC
    return f"python_exec  lines={n_lines}  timeout={timeout}s\n  >>> {first_line}"


def _run(args: dict) -> ToolResult:
    code = args.get("code") or ""
    if not code.strip():
        return ToolResult(ok=False, output="", error="empty code")

    used_secrets: dict[str, str] = {}
    try:
        from workers import app_secrets as _app_secrets
        if "${secret:" in code:
            code, used_secrets = _app_secrets.resolve_placeholders(code)
    except Exception:
        _app_secrets = None  # type: ignore

    cwd_arg = args.get("cwd")
    if cwd_arg:
        cwd = Path(cwd_arg)
        if not cwd.is_absolute():
            cwd = ROOT / cwd
    else:
        cwd = ROOT
    if not cwd.exists() or not cwd.is_dir():
        return ToolResult(ok=False, output="", error=f"cwd not a directory: {cwd}")

    timeout = int(args.get("timeout") or DEFAULT_TIMEOUT_SEC)
    if timeout <= 0:
        timeout = DEFAULT_TIMEOUT_SEC
    timeout = min(timeout, MAX_TIMEOUT_SEC)

    if not VENV_PY.exists():
        py_path = sys.executable
    else:
        py_path = str(VENV_PY)

    #  · B4 · 跑代码前拍 surface 文件 mtime 快照 · 用于精准定位本次改动 (告警级自检)
    _pre_snapshot: dict = {}
    try:
        from workers.edit_selfcheck import snapshot_mtimes
        _pre_snapshot = snapshot_mtimes()
    except Exception:
        _pre_snapshot = {}

    tmp_dir = ROOT / ".python_exec_tmp"
    tmp_dir.mkdir(exist_ok=True)
    tmp_name = f"_pyexec_{uuid.uuid4().hex[:8]}.py"
    tmp_path = tmp_dir / tmp_name
    try:
        tmp_path.write_text(code, encoding="utf-8")

        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"

        argv = [py_path, "-X", "utf8", str(tmp_path)]

        # 续 IV · 用统一 helper · 防黑框 (Windows 父无 console 时 spawn 子进程默认弹新 console)
        try:
            proc = subprocess.run(
                argv,
                cwd=str(cwd),
                timeout=timeout,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
                **no_window_kwargs(),
            )
        except subprocess.TimeoutExpired:
            return ToolResult(ok=False, output="", error=f"code timed out after {timeout}s")
        except FileNotFoundError as e:
            return ToolResult(ok=False, output="", error=f"python not found: {e}")
        except Exception as e:
            return ToolResult(ok=False, output="", error=f"{type(e).__name__}: {e}")

        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
        rc = proc.returncode

        if used_secrets and _app_secrets is not None:
            stdout = _app_secrets.redact_in_text(stdout, used_secrets)
            stderr = _app_secrets.redact_in_text(stderr, used_secrets)

        parts = []
        if stdout:
            parts.append(f"--- stdout ---\n{stdout}")
        if stderr:
            parts.append(f"--- stderr ---\n{stderr}")
        parts.append(f"--- exit code: {rc} ---")
        output = "\n".join(parts)

        #  · B4 · 编辑后即时自检: 本次若改动过 daemon 表面 .py / static js 且语法坏了 → 告警 (不拦)
        try:
            from workers.edit_selfcheck import selfcheck_changed
            sc_ok, sc_warn = selfcheck_changed(_pre_snapshot)
            if not sc_ok:
                output = f"{output}\n\n{sc_warn}"
        except Exception:
            pass

        truncated = False
        if len(output) > MAX_OUTPUT_CHARS:
            output = output[:MAX_OUTPUT_CHARS] + f"\n\n... [truncated by python_exec; full was {len(output)} chars]"
            truncated = True

        return ToolResult(
            ok=(rc == 0),
            output=output,
            truncated=truncated,
            error=None if rc == 0 else f"exit code {rc}",
        )
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass


SPEC = ToolSpec(
    name="python_exec",
    description=(
        "Execute Python code in Daemonkey's .venv. Use this INSTEAD of `shell_exec python -c '...'` "
        "whenever you'd write multi-line Python.\n\n"
        "**Why this tool exists** — `shell_exec python -c \"<multi-line script>\"` is the #1 cause of "
        "exit-code-1 in this daemon (78.6% of all shell_exec failures in last 30 sessions are inline Python "
        "with PS / cmd / Python triple-escape mess). python_exec takes raw source code · zero shell escaping · "
        "writes to a .venv-launched temp file · returns stdout/stderr/exit code identical format to shell_exec.\n\n"
        "**When to use**:\n"
        "  - Check file content with Python (json.load, ast.parse, pathlib.Path operations)\n"
        "  - Compute / aggregate / format data\n"
        "  - Call any Python library available in .venv (numpy, requests, etc.)\n"
        "  - Run quick syntax / type checks (py_compile, ast.parse)\n\n"
        "**When NOT to use** (use shell_exec instead):\n"
        "  - Running git / curl / npm / shell commands\n"
        "  - File operations that just need ls/cat (use read_file or shell_exec ls)\n"
        "  - Anything that's actually a one-liner in PowerShell\n\n"
        "**Secret 用法** (铁律 7 · 同 shell_exec):\n"
        "  - 不要把 KEY 真值粘到 code · 用 placeholder `${secret:<app_id>:<name>}`\n"
        "  - daemon 子进程启动前 inline 替换 · LLM history 永远只看到 placeholder\n"
        "  - 例: `import requests; r = requests.post(url, headers={'Authorization': 'Bearer ${secret:app-xxx:api_key}'})`\n\n"
        "**Tips**:\n"
        "  - Code 是纯 Python · 不需要 PowerShell 转义\n"
        "  - 输出走 print() · 标准 stdout / stderr\n"
        "  - 默认 cwd 是项目根 (data/ workshop/ 等相对路径直接能用)\n"
        "  - utf-8 强制 (PYTHONUTF8=1 + PYTHONIOENCODING=utf-8) · 中文 / emoji 不会乱码"
    ),
    tier=TIER_CONFIRM,
    input_schema={
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": "The Python code to execute. Multi-line is fine. No need to escape anything for shell.",
            },
            "cwd": {
                "type": "string",
                "description": "Working directory (relative paths resolve from Daemonkey root). Default: project root.",
            },
            "timeout": {
                "type": "integer",
                "description": f"Timeout in seconds. Default {DEFAULT_TIMEOUT_SEC}, max {MAX_TIMEOUT_SEC}.",
            },
        },
        "required": ["code"],
    },
    run=_run,
    summarize=_summarize,
    classify=lambda args: _classify_code(args.get("code") or ""),
)


register_tool(SPEC)
