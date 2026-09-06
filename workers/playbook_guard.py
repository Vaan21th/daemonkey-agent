"""手册落点闸：文件工具和脚本都不得私改 data/playbooks。"""
from __future__ import annotations

import re
from pathlib import Path

_PB_PATH = re.compile(r"data[/\\]playbooks|PLAYBOOK_DIR", re.I)
_WRITE = re.compile(
    r"write_text|write_bytes|json\.dump|"
    r"open\s*\([^)]*,\s*['\"](?:w|a|x|wb|ab)|"
    r"Set-Content|Out-File|Add-Content|"
    r">\s*\S*playbooks|"
    r"(?:New-Item|Copy-Item|Move-Item|Remove-Item)\b",
    re.I,
)
_MSG = "操作手册请用 extract_playbook。不要用脚本或其它工具改 data/playbooks。"


def refuse_path(path: Path, content: str = "") -> str | None:
    from workers.playbook_case import refuse_loose_playbook
    return refuse_loose_playbook(path, content)


def refuse_script(text: str) -> str | None:
    """读手册可以。写 / 覆盖 / 挪走才拦。"""
    blob = text or ""
    if not _PB_PATH.search(blob):
        return None
    if not _WRITE.search(blob):
        return None
    return _MSG
