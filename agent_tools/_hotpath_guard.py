"""Hot-path interceptors: keep accident rules out of the system prompt.

Shell / fetch / clipboard mistakes used to be taught as prose every turn.
The guard refuses or rewrites here so the prompt can stay short.
"""
from __future__ import annotations

import contextvars
import re
from urllib.parse import urlparse

_channel: contextvars.ContextVar[str] = contextvars.ContextVar("hotpath_channel", default="")
_fetch_blocks: contextvars.ContextVar[int] = contextvars.ContextVar("hotpath_fetch_blocks", default=0)

_PYTHON_C_RE = re.compile(
    r"(?:^|[;&|]\s*)(?:py(?:thon(?:3)?)?(?:\.exe)?)\s+(?:-\d+\s+)*-c\b",
    re.IGNORECASE,
)
_KILL_PY_RE = re.compile(
    r"Stop-Process.*python|taskkill\s+.*\bpython(\.exe)?\b|"
    r"Get-Process.*python.*Stop-Process|\bkill\s+-9\s+",
    re.IGNORECASE,
)
_SHELL_READ_RE = re.compile(r"^(?:Get-Content|gc|cat|type)\b", re.IGNORECASE)
_CHALLENGE_RE = re.compile(
    r"(?:验证码|请登录|异常访问|安全验证|请求异常|captcha|access denied)",
    re.IGNORECASE,
)


def begin_turn(channel: str = "") -> None:
    _channel.set(channel or "")
    _fetch_blocks.set(0)


def set_channel(channel: str) -> None:
    _channel.set(channel or "")


def block_shell(cmd: str) -> str | None:
    s = (cmd or "").strip()
    if not s:
        return None
    if _KILL_PY_RE.search(s):
        return (
            "blocked: killing python kills the daemon. "
            "Use request_restart(reason=...) instead."
        )
    if _PYTHON_C_RE.search(s):
        return (
            "blocked: python -c belongs in python_exec(code=...). "
            "PowerShell will mangle multiline scripts."
        )
    if _is_shell_file_dump(s):
        return (
            "blocked: read files with read_file, not shell Get-Content/type/cat."
        )
    return None


def _is_shell_file_dump(cmd: str) -> bool:
    if not _SHELL_READ_RE.match(cmd):
        return False
    if "|" not in cmd:
        return True
    rest = cmd.split("|", 1)[1].strip().lower()
    return rest.startswith("out-string") or rest.startswith("select-object -first")


def block_clipboard_write() -> str | None:
    if _channel.get() == "wechat":
        return (
            "blocked: this turn is WeChat. Send the real file with "
            "wechat_send(media_path=...), not write_clipboard, and do not reply with a C:\\ path."
        )
    return None


def fetch_precheck() -> str | None:
    if _fetch_blocks.get() >= 2:
        return (
            "blocked: two 401/403/challenge failures already this turn. "
            "Stop fetching. Tell what you have and which source failed."
        )
    return None


def note_fetch_status(status: int, body: str = "", url: str = "") -> str | None:
    if status not in (401, 403, 202) and not _CHALLENGE_RE.search(body or ""):
        return None
    _fetch_blocks.set(_fetch_blocks.get() + 1)
    host = urlparse(url).netloc if url else ""
    if _fetch_blocks.get() >= 2:
        where = f" ({host})" if host else ""
        return (
            f"blocked: same-class fetch failure twice{where}. "
            "Stop switching sources. Report what you already have."
        )
    return None
