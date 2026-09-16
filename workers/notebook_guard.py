"""workers/notebook_guard.py — 画像 / 成长记录的落点闸。

仿 workers/playbook_guard.py：文件工具和脚本都不得直接改画像/成长记录，
必须走带「落位路由 + 预算 + 回执」的正规写入工具。

拦的对象：
    soul/OWNER-NOTEBOOK.md      → 请用 update_owner_note
    soul/OWNER-NOTEBOOK.md    → 同上（新旧名都拦，和 soul_loader 的两套叫法对齐）
    soul/SELF-EVOLUTION.md    → 请用 update_self_evolution
    soul/OPUS-MEMORIES.md     → 走 update_self_evolution(proposal) 提议流程，不直改

why（2026-09-16 拍板）：
    画像「三、本体约束」膨胀到 3,198 tok 的结构性原因之一 = 入口不唯一。
    在 write_file 的定界里 soul/ 是 CONFIRM 不是 GUARD，模型可以绕过全部写入闸
    直接改。本模块把写入路径收口 —— 让每一次写入都必然经过 route_write_section
    的落位判断（日期→events / 待办→提示 / 超长→拒），从源头防"边砍边长"。

放行：
    - 一切【读】操作（read_text / Get-Content / 无写特征的脚本）
    - 正规工具链的间接写（update_owner_note / update_self_evolution 不经本模块）
"""
from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]

# 目标文件名（soul/ 下四个受管文件）
_NB_PATH = re.compile(
    r"soul[/\\](?:BRO|OWNER)-NOTEBOOK\.md"
    r"|soul[/\\]SELF-EVOLUTION\.md"
    r"|soul[/\\]OPUS-MEMORIES\.md",
    re.I,
)

# 写特征（和 playbook_guard._WRITE 同款：多语言 / 多工具的写盘姿势）
_WRITE = re.compile(
    r"write_text|write_bytes|json\.dump|"
    r"open\s*\([^)]*,\s*['\"](?:w|a|x|wb|ab)|"
    r"mode\s*=\s*['\"](?:w|a|x)|"
    r"Set-Content|Out-File|Add-Content|"
    r"(?:New-Item|Copy-Item|Move-Item|Remove-Item)\b|"
    r"shutil\.(?:copy|copy2|copyfile|copytree|move|rmtree)|"
    r"os\.(?:rename|replace|remove|unlink)|"
    r"\.(?:unlink|rename|replace)\s*\(",
    re.I,
)
# cwd 已在 soul/ 下时，相对路径 `> OWNER-NOTEBOOK.md` 也要拦
_REDIR = re.compile(r"(?:(?<![-<])>\s*\S)|Out-File|Set-Content|Add-Content", re.I)
# 重定向写出目标落在受管目录内（哪怕 cwd 不在其下）: > / >> 后带 soul 前缀
# （2026-09-16 真链路测试抓到漏检；且 PowerShell >> 默认非 UTF-8，会写坏 UTF-8 文件）
_REDIR_SOUL = re.compile(r">>?\s*\S*soul[/\\]", re.I)

_MSG = (
    "记忆落点闸：soul/ 下的画像 / 成长记录不允许直接改（把路径换一下，或走正规工具）。\n"
    "  画像（OWNER-NOTEBOOK）    → update_owner_note（带落位路由+预算+回执）\n"
    "  成长记录（SELF-EVOLUTION）→ update_self_evolution\n"
    "  自传（OPUS-MEMORIES）    → update_self_evolution(mode='proposal') 提议流程"
)
_FAIL = "记忆落点闸校验失败，拒绝直接改 soul/ 画像/成长记录。"


def _cwd_in_soul(cwd: str | Path | None) -> bool:
    if cwd is None or str(cwd).strip() in {"", "."}:
        return False
    try:
        raw = Path(cwd)
        resolved = raw.resolve() if raw.is_absolute() else (_ROOT / raw).resolve()
        resolved.relative_to((_ROOT / "soul").resolve())
        return True
    except Exception:
        return False


def refuse_path(path: Path, content: str = "") -> str | None:
    """文件工具（write_file / edit_file）的写路径检查。读不走这里。"""
    p = str(path or "").replace("\\", "/")
    if not _NB_PATH.search(p):
        return None
    return _MSG


def refuse_script(text: str, cwd: str | Path | None = None) -> str | None:
    """读可以。写 / 覆盖 / 挪走才拦。cwd 在 soul/ 里时，相对路径写入也拦。"""
    blob = text or ""
    in_dir = _cwd_in_soul(cwd)
    if not in_dir and not _NB_PATH.search(blob):
        return None
    if _WRITE.search(blob):
        return _MSG
    if _REDIR.search(blob):
        if in_dir or _REDIR_SOUL.search(blob):
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
