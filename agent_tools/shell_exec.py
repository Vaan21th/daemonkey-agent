"""
agent_tools/shell_exec.py
=========================

OPUS 的"跑命令的手"。

为什么这个工具最复杂——
  shell 是 OPUS 触碰这台机器的最大入口。任何破坏性能力都从这里来。
  所以这一个文件比其他工具更长，也更值得反复 review。

三档分类（动态，每次调用根据命令字符串判断）：
  AUTO    : 严格白名单 + 没有 shell 组合操作符 + 没有黑名单关键字
  GUARD   : 命中黑名单关键字（rm -rf / del /f / format / shutdown / git push --force / ...）
  CONFIRM : 其他一切

平台默认：Windows 上走 PowerShell；其他系统走默认 shell。用户 这台是 Windows。

超时：默认 30s（可由 args.timeout 覆盖，最长 300s）。
输出截断：8000 chars。
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import sys
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
from ._git_lock import daemon_git_lock


ROOT = Path(__file__).resolve().parent.parent

DEFAULT_TIMEOUT_SEC = 30
MAX_TIMEOUT_SEC = 300
MAX_OUTPUT_CHARS = 8000


# ---------- AUTO 白名单（"读 / 查询"类的命令前缀） ----------

# 第一个 token 命中这个集合的命令，且没有 shell 组合操作符 / 黑名单关键字，被判为 AUTO。
# 注意这是非常保守的——多 token 命令（如 `git status`）的判定在 _classify_command 里做。
_AUTO_SINGLE_TOKENS = {
    # POSIX-style read commands
    "ls", "pwd", "cat", "head", "tail", "wc", "echo", "printenv", "env",
    "which", "whoami", "date", "uname", "hostname", "uptime",
    # Windows / PowerShell read commands
    "dir", "type", "where",
    "Get-Location", "Get-ChildItem", "Get-Content", "Get-Process",
    "Test-Path", "Resolve-Path", "Get-Date", "Get-Host",
    # search
    "rg", "grep", "find", "Select-String",
    # python / node introspection
    "python", "py", "python3",
}

# `git <subcmd>` 中被认为是只读的 subcmd
_GIT_READ_SUBCMDS = {
    "status", "log", "diff", "show", "branch", "remote", "config",
    "describe", "blame", "rev-parse", "ls-files", "ls-tree",
    "shortlog", "tag", "stash",
    "reflog", "fsck",
}

# `pip <subcmd>` 中被认为是只读的
_PIP_READ_SUBCMDS = {"list", "show", "freeze", "check", "config"}

# `npm <subcmd>` / `pnpm` / `yarn` 中只读的
_PKG_READ_SUBCMDS = {"list", "ls", "view", "info", "outdated", "audit"}


# ---------- GUARD 黑名单关键字（命令任何位置出现都升级到 GUARD） ----------

_GUARD_PATTERNS = [
    r"\brm\s+(-[a-zA-Z]*\s+)*(-rf|-fr|-r\s+-f|-f\s+-r)\b",
    r"\brm\s+-rf\b",
    r"\brm\s+-r\b",
    r"\brmdir\s+/[sq]",
    r"\bdel\s+/[fsq]",
    r"\bformat\s+[a-zA-Z]:",
    r"\bmkfs\b",
    r"\bdd\s+if=",
    r"\b(shutdown|reboot|poweroff|halt)\b",
    r"Remove-Item.*-Recurse",
    r"Remove-Item.*-Force",
    r"\bgit\s+push\s+.*--force\b",
    r"\bgit\s+push\s+.*-f\b",
    r"\bgit\s+reset\s+--hard\b",
    r"\bgit\s+clean\s+-",
    r"\bgit\s+filter-branch\b",
    r"\bpip\s+install\b",
    r"\bpip\s+uninstall\b",
    r"\bpip3?\s+install\b",
    r"\bnpm\s+install\b",
    r"\bnpm\s+uninstall\b",
    r"\bpnpm\s+install\b",
    r"\byarn\s+(add|remove)\b",
    r"^\s*ssh\s+",
    r"\bscp\s+",
    r"\brsync\s+",
    r"\bcurl\s+.*-X\s*(POST|PUT|DELETE|PATCH)\b",
    r"\bwget\s+.*--method=(POST|PUT|DELETE)\b",
    r"\.env\s*$",
    r"opus-soul",
    r"--no-verify\b",
    r"Stop-Process.*[-]Name\s+['\"]?python",
    r"Stop-Process.*python\.exe",
    r"\btaskkill\s+.*\bpython(\.exe)?\b",
    r"Get-Process.*python.*\|\s*Stop-Process",
    r"\bkill\s+-9\s+",
]

_GUARD_RE = re.compile("|".join(f"(?:{p})" for p in _GUARD_PATTERNS), re.IGNORECASE)


# ---------- shell 组合操作符（出现就降级到 CONFIRM 至少） ----------
_COMBINATOR_RE = re.compile(r"(\|\||&&|;|>>|>|<|`|\$\()")


def _classify_command(cmd: str) -> str:
    """根据命令字符串决定 tier。"""
    s = cmd.strip()
    if not s:
        return TIER_CONFIRM

    if _GUARD_RE.search(s):
        return TIER_GUARD

    try:
        from workers.trusted_commands import is_trusted
        if is_trusted(s):
            return TIER_AUTO
    except Exception:
        pass

    if _COMBINATOR_RE.search(s):
        return TIER_CONFIRM

    s_for_head = s.lstrip("([{ \t")
    try:
        tokens = shlex.split(s_for_head, posix=(os.name != "nt"))
    except ValueError:
        return TIER_CONFIRM
    if not tokens:
        return TIER_CONFIRM

    head = tokens[0]
    head_base = os.path.basename(head)

    if head_base in ("git", "git.exe") and len(tokens) >= 2 and tokens[1] in _GIT_READ_SUBCMDS:
        return TIER_AUTO

    if head_base in ("pip", "pip3", "pip.exe") and len(tokens) >= 2 and tokens[1] in _PIP_READ_SUBCMDS:
        return TIER_AUTO

    if head_base in ("npm", "pnpm", "yarn", "npm.cmd", "pnpm.cmd", "yarn.cmd") and len(tokens) >= 2:
        if tokens[1] in _PKG_READ_SUBCMDS:
            return TIER_AUTO

    if head_base in ("python", "py", "python3", "python.exe", "py.exe"):
        if len(tokens) >= 2 and tokens[1] in ("-c", "--version", "-V"):
            return TIER_CONFIRM
        if tokens[1] in ("--version", "-V"):
            return TIER_AUTO
        return TIER_CONFIRM

    if head_base in _AUTO_SINGLE_TOKENS:
        return TIER_AUTO

    return TIER_CONFIRM


# ---------- summarize（给 用户 看的"我打算干什么"） ----------

def _summarize(args: dict) -> str:
    cmd = (args.get("command") or "").strip()
    cwd = args.get("cwd") or "."
    timeout = args.get("timeout") or DEFAULT_TIMEOUT_SEC
    return f"shell_exec  cwd={cwd}  timeout={timeout}s\n  $ {cmd}"


# ---------- run ----------

def _run(args: dict) -> ToolResult:
    cmd = (args.get("command") or "").strip()
    if not cmd:
        return ToolResult(ok=False, output="", error="empty command")

    used_secrets: dict[str, str] = {}
    try:
        from workers import app_secrets as _app_secrets
        if "${secret:" in cmd:
            cmd, used_secrets = _app_secrets.resolve_placeholders(cmd)
    except Exception:
        _app_secrets = None

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

    if sys.platform.startswith("win"):
        for shell_exe in ("pwsh", "powershell"):
            shell_path = _which(shell_exe)
            if shell_path:
                break
        else:
            return ToolResult(ok=False, output="", error="no powershell found on PATH")
        is_winps51 = "powershell.exe" in shell_path.lower() and "pwsh" not in shell_path.lower()
        if is_winps51:
            cmd = _normalize_for_winps51(cmd)
        argv = [shell_path, "-NoProfile", "-NonInteractive", "-Command", cmd]
    else:
        argv = ["/bin/sh", "-c", cmd]

    # 续 IV · 用统一 helper · 防黑框
    # wish-125d4e4b · 检测 git 命令自动上锁 · 防 daemon 内多 session 打架
    _is_git_cmd = (
        cmd.strip().startswith("git ") or
        " git " in cmd.strip() or
        cmd.strip() == "git"
    )
    try:
        if _is_git_cmd:
            with daemon_git_lock(label=f"shell_exec:{cmd.strip()[:50]}"):
                proc = subprocess.run(
                    argv,
                    cwd=str(cwd),
                    timeout=timeout,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    **no_window_kwargs(),
                )
        else:
            proc = subprocess.run(
                argv,
                cwd=str(cwd),
                timeout=timeout,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                **no_window_kwargs(),
            )
    except subprocess.TimeoutExpired:
        return ToolResult(
            ok=False, output="",
            error=f"command timed out after {timeout}s",
        )
    except FileNotFoundError as e:
        return ToolResult(ok=False, output="", error=f"shell not found: {e}")
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

    truncated = False
    if len(output) > MAX_OUTPUT_CHARS:
        output = output[:MAX_OUTPUT_CHARS] + f"\n\n... [truncated by shell_exec; full was {len(output)} chars]"
        truncated = True

    return ToolResult(ok=(rc == 0), output=output, truncated=truncated, error=None if rc == 0 else f"exit code {rc}")


def _which(exe: str) -> str | None:
    """简化版 shutil.which。"""
    from shutil import which
    return which(exe)


def _normalize_for_winps51(cmd: str) -> str:
    """PowerShell 5.1 不支持 && / || 短路链 · 改写成 ;if($?){}/;if(-not $?){} 形式。"""
    has_and = "&&" in cmd
    has_or = "||" in cmd
    if not has_and and not has_or:
        return cmd
    if has_and and has_or:
        return cmd

    if has_and:
        parts = [p.strip() for p in cmd.split("&&")]
        parts = [p for p in parts if p]
        if len(parts) <= 1:
            return cmd
        out = parts[0]
        for p in parts[1:]:
            out += f"; if ($?) {{ {p} "
        out += "}" * (len(parts) - 1)
        return out

    parts = [p.strip() for p in cmd.split("||")]
    parts = [p for p in parts if p]
    if len(parts) <= 1:
        return cmd
    out = parts[0]
    for p in parts[1:]:
        out += f"; if (-not $?) {{ {p} "
    out += "}" * (len(parts) - 1)
    return out


SPEC = ToolSpec(
    name="shell_exec",
    description=(
        "Execute a shell command on the host. "
        "On Windows runs via PowerShell 5.1; on POSIX via /bin/sh. "
        "Use for: git / curl / npm / file ops / process queries / running tests.\n\n"
        "**🔴 写多行 Python? 改用 `python_exec` 工具**:\n"
        "  - 不要写 `shell_exec python -c \"<多行脚本>\"` · 这是 daemon 失败案例 #1 (78.6% 的 shell_exec exit-1 来自 inline -c)\n"
        "  - 改用 `python_exec` 工具 · 接受原生 Python 源码 · 零 shell 转义\n"
        "  - 单行简单 `python --version` / `python script.py` 还在 shell_exec\n\n"
        "**🔴 PowerShell 5.1 经典坑 (用户 这台 Win + PS 5.1)**:\n"
        "  - **`2>&1` + git/npm = NativeCommandError** · PS 把进度信息当 PS error · 即使命令成功也 exit 1 → 别加 `2>&1` · 或用 `--quiet`\n"
        "  - **heredoc `<<EOF` 不支持** → 多行内容 write_file 落临时文件再 shell_exec 跑\n"
        "  - **JSON body 嵌 curl `-d \"{\\\"x\\\":\\\"y\\\"}\"`** · 引号嵌套 PS 解不开 → 用 Invoke-RestMethod -Body (Get-Content tmp.json) 或落 _tmp.json 再 `curl @tmp.json`\n"
        "  - **反斜杠 `\\` 不是转义符** · PS 里 ` (反引号) 才是 · 写文件路径用正斜杠 `/` 最稳\n"
        "  - **`&&` / `||` 短路链 PS 5.1 不支持** · daemon 已自动改写纯 && 或纯 || · 但**混合 `&&` + `||` 不处理** → 拆成两步\n\n"
        "**🔴 自杀防护 (你跑在 daemon 进程里)**:\n"
        "  - **不要 `Stop-Process` / `taskkill` python 或 daemon 自身** · 你就在那个进程里 · 杀 = 自爆\n"
        "  - **不要 restart daemon** · 让 用户 手动重启\n"
        "  - 改了 daemon .py 代码后 · 提示 用户 重启即可 · 不要自己跑命令重启\n\n"
        "**🔴 Secret 用法 (铁律 7)**:\n"
        "  - 不要把 KEY 真值粘到 command · 用 placeholder `${secret:<app_id>:<name>}`\n"
        "  - 例: `Invoke-RestMethod -Headers @{ Authorization = 'Bearer ${secret:app-xxx:api_key}' } ...`\n"
        "  - 真值在子进程启动前 inline 替换 · LLM messages 永远只看到 placeholder · 不污染历史"
    ),
    tier=TIER_CONFIRM,
    input_schema={
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The shell command to run. Must be a complete one-liner.",
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
        "required": ["command"],
    },
    run=_run,
    summarize=_summarize,
    classify=lambda args: _classify_command(args.get("command") or ""),
)


register_tool(SPEC)
