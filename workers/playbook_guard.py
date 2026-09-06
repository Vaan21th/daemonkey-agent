"""手册落点闸：文件工具和脚本都不得私改 data/playbooks。"""
from __future__ import annotations

import re
from pathlib import Path

_PB_PATH = re.compile(r"data[/\\]playbooks|PLAYBOOK_DIR", re.I)
_WRITE = re.compile(
    r"write_text|write_bytes|json\.dump|"
    r"open\s*\([^)]*,\s*['\"](?:w|a|x|wb|ab)|"
    r"mode\s*=\s*['\"](?:w|a|x)|"
    r"Set-Content|Out-File|Add-Content|"
    r">\s*\S*playbooks|"
    r"(?:New-Item|Copy-Item|Move-Item|Remove-Item)\b|"
    r"shutil\.(?:copy|copy2|copyfile|copytree|move|rmtree)|"
    r"os\.(?:rename|replace|remove|unlink)|"
    r"\.(?:unlink|rename|replace)\s*\(",
    re.I,
)
# cwd 已在手册目录时，相对路径 `> foo.md` 也要拦
_REDIR = re.compile(r"(?:(?<![-<])>\s*\S)|Out-File|Set-Content|Add-Content", re.I)
_FAIL = "操作手册闸校验失败，拒绝改 data/playbooks。"
_MSG = "操作手册请用 extract_playbook。不要用脚本或其它工具改 data/playbooks。"


def _cwd_in_playbooks(cwd: str | Path | None) -> bool:
    if cwd is None or str(cwd).strip() in {"", "."}:
        return False
    try:
        from workers.playbooks import PLAYBOOK_DIR, ROOT
        raw = Path(cwd)
        resolved = raw.resolve() if raw.is_absolute() else (ROOT / raw).resolve()
        resolved.relative_to(PLAYBOOK_DIR.resolve())
        return True
    except Exception:
        return False


def refuse_path(path: Path, content: str = "") -> str | None:
    from workers.playbook_case import refuse_loose_playbook
    return refuse_loose_playbook(path, content)


def refuse_script(text: str, cwd: str | Path | None = None) -> str | None:
    """读手册可以。写 / 覆盖 / 挪走才拦。cwd 在手册目录里时，相对路径写入也拦。"""
    blob = text or ""
    in_dir = _cwd_in_playbooks(cwd)
    if not in_dir and not _PB_PATH.search(blob):
        return None
    if _WRITE.search(blob):
        return _MSG
    if in_dir and _REDIR.search(blob):
        return _MSG
    return None


def check_path(path: Path, content: str = "") -> str | None:
    try:
        return refuse_path(path, content)
    except Exception:
        return _FAIL


def check_script(text: str, cwd: str | Path | None = None) -> str | None:
    try:
        return refuse_script(text, cwd)
    except Exception:
        return _FAIL
