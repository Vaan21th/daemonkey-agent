"""
agent_tools/ssh_remote.py
=========================

通过 SSH 到用户自己配置的远程/部署服务器跑只读诊断命令——
让用户在外面问"服务器 X 服务咋样"时能立即得到日志原文 + 系统状态。

档位：CONFIRM
  本机 daemon 跑会弹 CONFIRM 框等用户 y/n。远程模式默认策略 confirm 档自动走，
  但每次执行都通过 SSE 流推送 tool_call 事件到 WebUI——用户在手机上能"看见"
  跑了哪条命令到哪台服务器。

安全姿态（平衡型白名单）：
  - host 必须在 OPUS_SSH_HOST_WHITELIST（默认空·用户自行配置 SSH 别名）
  - command 严格只读 verb 白名单（tail / cat / docker logs / systemctl status / ...）
  - 任何写命令拒绝（rm / mv / chmod / systemctl restart / docker exec / ...）
  - 任何 shell 组合拒绝（; && || > >> < $() 反引号）
  - 仅 pipe (|) 允许，每段都得在白名单里

意义：用户在外接到服务器报 bug → 1-2 分钟拿到原始日志 + 状态。
不取代本机 SSH terminal——写操作必须用户亲手做。
"""

from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path

from . import TIER_CONFIRM, ToolResult, ToolSpec, register_tool
from ._subprocess_helper import no_window_kwargs


PROJECT_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_TIMEOUT_SEC = 30
MAX_TIMEOUT_SEC = 120
MAX_OUTPUT_CHARS = 10000


# Host 白名单——只能 ssh 到这些已配置的别名
# 从 env 覆盖（OPUS_SSH_HOST_WHITELIST 逗号分隔）
def _allowed_hosts() -> set[str]:
    env = os.environ.get("OPUS_SSH_HOST_WHITELIST", "").strip()
    if env:
        return {h.strip() for h in env.split(",") if h.strip()}
    return set()


# 平衡型动词白名单（ 用户 选）
_READ_VERBS = {
    # 日志/查看
    "tail", "head", "cat", "less", "more", "tac", "rev",
    # 搜索
    "grep", "egrep", "fgrep", "rg", "ag",
    # 容器/服务
    "docker", "systemctl", "journalctl", "service",
    # 进程/资源
    "ps", "pgrep", "top", "htop", "iostat", "vmstat", "free",
    "df", "du", "uptime", "uname", "who", "last", "id", "whoami",
    # 文件目录
    "ls", "ll", "find", "locate", "stat", "file", "readlink", "realpath",
    "pwd", "tree",
    # 文本处理
    "sort", "uniq", "awk", "sed", "cut", "tr", "wc", "echo", "printf",
    "xxd", "hexdump", "base64", "od",
    # 网络只读
    "ping", "curl", "wget", "ss", "netstat", "lsof",
    "nslookup", "dig", "host", "ip",
    # 时间
    "date", "cal",
    # 杂项只读
    "env", "printenv", "which", "type", "alias", "history",
}


# 命令对应的只读子命令白名单
_DOCKER_READ_SUBS = {
    "ps", "logs", "inspect", "stats", "top", "version", "info",
    "history", "diff", "events", "port",
    "image", "images", "container", "network", "volume",
}

_SYSTEMCTL_READ_SUBS = {
    "status", "is-active", "is-enabled", "is-failed", "is-system-running",
    "list-units", "list-unit-files", "list-sockets", "list-jobs",
    "list-timers", "list-dependencies", "list-machines",
    "show", "cat", "show-environment", "get-default",
}

_IP_READ_SUBS = {
    "a", "addr", "address", "l", "link", "r", "route",
    "neigh", "n", "show", "monitor", "rule",
}

_SERVICE_READ_SUBS = {"status", "list", "--status-all"}

# 危险关键字（即使在白名单 verb 里，看到这些立即拒绝）
_DANGEROUS_PHRASES = [
    "rm ", "mv ", "cp ", "dd ", "chmod ", "chown ", "chgrp ",
    "shutdown", "reboot", "halt", "poweroff", "init ",
    "kill ", "pkill ", "killall ",
    "ufw ", "iptables ", "nft ",
    "eval ", "source ", ". /",
    "su ", "sudo ", "doas ",
    "systemctl start", "systemctl stop", "systemctl restart", "systemctl reload",
    "systemctl enable", "systemctl disable", "systemctl mask", "systemctl unmask",
    "systemctl daemon-reload", "systemctl edit", "systemctl set-",
    "docker run", "docker exec", "docker rm", "docker kill", "docker stop",
    "docker start", "docker restart", "docker pause", "docker unpause",
    "docker pull", "docker push", "docker build", "docker tag",
    "docker commit", "docker save", "docker load", "docker create",
    "docker compose up", "docker compose down", "docker compose restart",
    "docker compose stop", "docker compose start", "docker compose build",
    "docker-compose up", "docker-compose down", "docker-compose restart",
    "service start", "service stop", "service restart", "service reload",
    "iptables ", "useradd", "userdel", "passwd",
    "mkfs", "mount ", "umount ",
    "crontab -e", "crontab -r", "at ", "batch",
]

# shell 组合操作符（pipe | 单独允许，每段验证）
_FORBIDDEN_SHELL_TOKENS = [";", "&&", "||", ">>", ">", "<<", "<", "$(", "`"]


def _validate_host(host: str) -> tuple[bool, str]:
    if not host or not isinstance(host, str):
        return False, "host is required (non-empty string)"
    if not all(c.isalnum() or c in "-_." for c in host):
        return False, f"host '{host}' contains illegal characters; only alphanumerics + - _ . allowed"
    if host not in _allowed_hosts():
        return False, (
            f"host '{host}' not in OPUS_SSH_HOST_WHITELIST; "
            f"allowed: {sorted(_allowed_hosts())}. "
            "Use one of those, or update the env var if a new client was added."
        )
    return True, "ok"


def _validate_command(command: str) -> tuple[bool, str]:
    if not command or not isinstance(command, str):
        return False, "command is required (non-empty string)"
    if len(command) > 2000:
        return False, f"command too long ({len(command)} chars > 2000)"

    cmd_padded = " " + command + " "
    for danger in _DANGEROUS_PHRASES:
        if " " + danger in cmd_padded or cmd_padded.lstrip().startswith(danger):
            return False, (
                f"dangerous keyword '{danger.strip()}' detected — "
                "ssh_remote only allows read-only commands; "
                "write/restart/install operations must be done by 用户 on the local terminal."
            )

    for forbid in _FORBIDDEN_SHELL_TOKENS:
        if forbid in command:
            return False, (
                f"shell operator '{forbid}' not allowed — "
                "only pipes (|) are allowed for chaining read commands."
            )

    segments = [s.strip() for s in command.split("|") if s.strip()]
    if not segments:
        return False, "command empty after parsing"

    for idx, seg in enumerate(segments):
        try:
            tokens = shlex.split(seg)
        except ValueError as e:
            return False, f"pipe segment {idx + 1} ('{seg[:60]}') shlex parse error: {e}"
        if not tokens:
            return False, f"pipe segment {idx + 1} is empty"

        verb = tokens[0]

        if verb == "docker":
            if len(tokens) < 2:
                return False, "docker requires a subcommand (e.g. 'docker ps' or 'docker logs <name>')"
            if tokens[1] not in _DOCKER_READ_SUBS:
                return False, (
                    f"docker {tokens[1]} not in read-only whitelist; "
                    f"allowed subs: {sorted(_DOCKER_READ_SUBS)}"
                )

        if verb == "systemctl":
            if len(tokens) < 2:
                return False, "systemctl requires a subcommand"
            if tokens[1] not in _SYSTEMCTL_READ_SUBS:
                return False, (
                    f"systemctl {tokens[1]} not in read-only whitelist; "
                    f"allowed: {sorted(_SYSTEMCTL_READ_SUBS)}"
                )

        if verb == "service":
            if len(tokens) < 2:
                return False, "service requires a name + subcommand"
            sub = tokens[-1]
            if sub not in _SERVICE_READ_SUBS:
                return False, f"service ... {sub} not in read-only whitelist"

        if verb == "ip":
            if len(tokens) < 2:
                return False, "ip requires a subcommand (e.g. 'ip a' / 'ip route show')"
            if tokens[1] not in _IP_READ_SUBS:
                return False, f"ip {tokens[1]} not in read-only whitelist"

        if verb == "sed":
            joined = " ".join(tokens)
            if " -i" in joined or "--in-place" in joined:
                return False, "sed -i (in-place edit) not allowed; sed without -i is fine"

        if verb in ("curl", "wget"):
            for token in tokens:
                if token in ("-o", "-O", "--output", "--output-document",
                             "--remote-name"):
                    return False, (
                        f"{verb} with file output ({token}) not allowed; "
                        "would write to remote disk"
                    )

        if verb not in _READ_VERBS:
            return False, (
                f"verb '{verb}' (segment {idx + 1}) not in whitelist. "
                "ssh_remote only allows read-only: tail/cat/head/grep/docker/"
                "systemctl/journalctl/df/free/ps/ls/awk/sort/sed (no -i)/find/"
                "stat/curl (no -o)/ping/ss/netstat etc."
            )

    return True, "ok"


def _summarize(args: dict) -> str:
    host = args.get("host", "?")
    command = (args.get("command") or "")[:60]
    if len(args.get("command") or "") > 60:
        command += "…"
    return f"ssh_remote  {host}  '{command}'"


def _run(args: dict) -> ToolResult:
    host = (args.get("host") or "").strip()
    command = (args.get("command") or "").strip()
    timeout_raw = args.get("timeout") or DEFAULT_TIMEOUT_SEC
    try:
        timeout = int(timeout_raw)
    except (ValueError, TypeError):
        timeout = DEFAULT_TIMEOUT_SEC
    timeout = max(1, min(timeout, MAX_TIMEOUT_SEC))

    ok, reason = _validate_host(host)
    if not ok:
        return ToolResult(ok=False, output="", error=f"host check failed: {reason}")

    ok, reason = _validate_command(command)
    if not ok:
        return ToolResult(ok=False, output="", error=f"command check failed: {reason}")

    try:
        proc = subprocess.run(
            [
                "ssh",
                "-o", "BatchMode=yes",
                "-o", "ConnectTimeout=10",
                "-o", "StrictHostKeyChecking=accept-new",
                "-o", "ServerAliveInterval=30",
                host,
                command,
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
            **no_window_kwargs(),
        )
    except subprocess.TimeoutExpired:
        return ToolResult(
            ok=False, output="",
            error=f"ssh {host} timed out after {timeout}s; "
                  "consider a smaller log slice or check server is alive."
        )
    except FileNotFoundError:
        return ToolResult(
            ok=False, output="",
            error="ssh binary not found in PATH; OpenSSH client must be installed."
        )
    except Exception as e:
        return ToolResult(
            ok=False, output="",
            error=f"ssh launch failed: {type(e).__name__}: {e}"
        )

    stdout = proc.stdout or ""
    stderr = proc.stderr or ""

    if proc.returncode == 0:
        lines = [
            f"ssh_remote · {host} · ok (exit 0)",
            f"command: {command}",
            "---",
        ]
        if stdout:
            if len(stdout) > MAX_OUTPUT_CHARS:
                lines.append(stdout[:MAX_OUTPUT_CHARS])
                lines.append(f"\n... [+{len(stdout) - MAX_OUTPUT_CHARS} chars truncated]")
            else:
                lines.append(stdout)
        else:
            lines.append("(no stdout)")
        if stderr.strip():
            stderr_clip = stderr[:1000]
            lines.append(f"\n--- stderr (first 1000 chars) ---\n{stderr_clip}")
        return ToolResult(ok=True, output="\n".join(lines))

    err_summary = stderr.strip() or stdout.strip() or "(no output)"
    return ToolResult(
        ok=False,
        output=(
            f"ssh {host} exit code: {proc.returncode}\n"
            f"command: {command}\n"
            f"--- stderr ---\n{stderr[:2000]}\n"
            f"--- stdout ---\n{stdout[:2000]}"
        ),
        error=f"ssh {host} returned non-zero ({proc.returncode}): {err_summary[:200]}",
    )


SPEC = ToolSpec(
    name="ssh_remote",
    description=(
        "Run a READ-ONLY diagnostic shell command on a remote server via SSH alias. "
        "Use this when the user is away from the local terminal and a remote/deployment "
        "server needs to be inspected (logs / status / disk / docker). "
        "\n\nStrict allow-list: "
        "host must be a pre-configured SSH alias listed in OPUS_SSH_HOST_WHITELIST "
        "(empty by default — the user configures their own server aliases). "
        "command must start with a read verb: tail / cat / head / grep / docker (logs|ps|"
        "inspect|stats|top|info) / systemctl status / journalctl / df / free / ps / "
        "ls / awk / sort / sed (no -i) / find / stat / uptime / uname / curl (no -o) / "
        "ping / ss / netstat etc. "
        "Pipes (|) are allowed if every segment is a read verb. "
        "\n\nAUTO-REJECT: rm / mv / cp / chmod / chown / shutdown / reboot / kill / sudo / "
        "su / eval / source / systemctl start|stop|restart|reload / docker run|exec|"
        "rm|kill|stop|start|restart|pull|push|build / docker compose up|down|restart / "
        "any shell operator (; && || > >> < $() backticks). "
        "\n\nTypical workflow: inspect the target server's logs / container status "
        "with a read-only command, then report the raw output plus your diagnosis."
    ),
    tier=TIER_CONFIRM,
    input_schema={
        "type": "object",
        "properties": {
            "host": {
                "type": "string",
                "description": "SSH alias from ~/.ssh/config; must be listed in the "
                               "OPUS_SSH_HOST_WHITELIST env var (comma-separated, empty by default).",
            },
            "command": {
                "type": "string",
                "description": "Shell command to run on the remote server. READ-ONLY only — "
                               "see tool description for allow-list. Pipes (|) OK if every "
                               "segment is a read verb.",
            },
            "timeout": {
                "type": "integer",
                "description": "Seconds before ssh times out. Default 30, max 120.",
                "default": 30,
                "minimum": 1,
                "maximum": 120,
            },
        },
        "required": ["host", "command"],
    },
    run=_run,
    summarize=_summarize,
)
register_tool(SPEC)
