"""
agent_tools/write_file.py
=========================

OPUS 的"写"——写或覆盖一个文本文件。

三档分类（动态）：
  - 默认 CONFIRM
  - 升级到 GUARD 的目标路径：
      .env / .env.* （凭证）
      soul/ 下的任何文件 （灵魂副本）
      .git/ （仓库内部状态）
      C:\\Users\\...\\opus-soul\\ 全局灵魂目录
      .venv/ 下任何路径

写策略：
  - mode='create' : 文件存在则报错（防止误覆盖）
  - mode='overwrite' : 全量覆盖
  - mode='append' : 追加到末尾（适合写日志）

精准改一段 → 用 edit_file (str_replace 局部替换)·不要用 overwrite。
  教训: 大文件 (read_file 一次只能看 40K) 用 overwrite 改 = 凭残缺记忆
  重建整文件 = 悄悄碾掉没读到的部分 (chat.js 语音/文档/视觉就是这么没的)。
  本工具的 overwrite 现在带【缩水守卫】: 旧文件 >20K 且新内容掉到 <60% 直接拦·
  逼你改用 edit_file。 create / append / 小文件 overwrite 不受影响。
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Optional

from . import (
    TIER_CONFIRM,
    TIER_GUARD,
    ToolResult,
    ToolSpec,
    current_session_id,
    register_tool,
)
from ._subprocess_helper import no_window_kwargs
from ._git_lock import daemon_git_lock
from ._edit_lock import guard as _edit_guard, note_write as _edit_note


ROOT = Path(__file__).resolve().parent.parent

#  F · daemon 核心代码目录 (改这些必须走 wish 分支)
# 修改这个列表 = 修改"什么算 daemon 改动" · 谨慎
_DAEMON_CORE_DIRS = (
    "agent_tools",
    "workers",
    "static",
    "tools",
    "desktop_pet",
)
_DAEMON_CORE_FILES = (
    "daemon_api.py",
    "opus_daemon.py",
    "soul_loader.py",
    "daemon_runtime.py",
    "tool_loop.py",
)


def _resolve(path_str: str) -> Path:
    p = Path(path_str)
    if not p.is_absolute():
        p = ROOT / p
    return p.resolve()


def _is_guard_target(path: Path) -> bool:
    """命中这些位置一律 GUARD。"""
    name = path.name.lower()
    if name == ".env" or name.startswith(".env."):
        return True
    parts_lower = [p.lower() for p in path.parts]
    if "soul" in parts_lower:
        # soul/SKILL.md 或 soul/OPUS-MEMORIES.md
        return True
    if ".git" in parts_lower:
        return True
    if ".venv" in parts_lower or "site-packages" in parts_lower:
        return True
    if "opus-soul" in "/".join(parts_lower):
        return True
    if "skills-cursor" in parts_lower:
        return True
    return False


def _is_daemon_core(path: Path) -> bool:
    """ F · 这个路径是不是 daemon 核心代码 (改这些要走 wish)。

    judgement:
      - path 在 ROOT 下
      - 且 path 第一层目录是 _DAEMON_CORE_DIRS 之一 · 或 path 名是 _DAEMON_CORE_FILES 之一
    """
    try:
        rel = path.relative_to(ROOT)
    except ValueError:
        return False  # 不在 daemon 项目内 · 不管
    parts = rel.parts
    if not parts:
        return False
    if parts[0] in _DAEMON_CORE_DIRS:
        return True
    if len(parts) == 1 and parts[0] in _DAEMON_CORE_FILES:
        return True
    return False


def _current_git_branch() -> Optional[str]:
    """拿当前 git 分支名 · 拿不到返 None (没 git / 不在 repo / 异常)。

    sub-process · 显式 utf-8 (Windows 默认 GBK 会崩 · 教训)。
    """
    if not (ROOT / ".git").exists():
        return None
    try:
        with daemon_git_lock("write_file:rev-parse"):
            res = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=ROOT, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=3,
                **no_window_kwargs(),
            )
        if res.returncode == 0:
            return (res.stdout or "").strip() or None
    except Exception:
        pass
    return None


def _branch_guard_warning(path: Path) -> Optional[str]:
    """ F · master 上改 daemon 核心代码时返回一段 warn 文案。

    不阻止调用 · 只把 warn 拼进 ToolResult.output · OPUS 看到了就知道下次走 wish。
    返回 None 表示无需警告。
    """
    if not _is_daemon_core(path):
        return None
    branch = _current_git_branch()
    if branch is None:
        return None  # 没 git 信息 · 不警告
    if branch.startswith("wish-"):
        return None  # 已经在 wish 分支 · 合规
    if branch != "master":
        return None  # 在某个 feature 分支 · 不是 master · OK
    return (
        "WARN · daemon 工程铁律 1 触发 ( F):\n"
        f"  你刚在 master 分支上改了 daemon 核心代码: {path.name}\n"
        "  按 data/cognition/daemon_rules.md 铁律 1 · 这应该走 wish 流程 (态):\n"
        "    1) wish_create + wish_update status=active · 批方案后清 daemon_phase → 自动开 wish-XXX/<slug> 分支\n"
        "    2) 在 wish 分支上改 · 不污染 master\n"
        "    3) 改完 wish_update status=review · 用户 验收点 live 时自动 merge 回 master\n"
        "  本次写入已生效 · 但下次先 wish_create · 不要再直接打 master。\n"
        "  如果这次是 用户 急手要的 hotfix · 可以无视这条 · 但在 reflection 里说明。"
    )


def _classify(args: dict) -> str:
    raw = args.get("path") or ""
    if not raw:
        return TIER_CONFIRM
    try:
        p = _resolve(raw)
    except Exception:
        return TIER_CONFIRM
    if _is_guard_target(p):
        return TIER_GUARD
    return TIER_CONFIRM


def _summarize(args: dict) -> str:
    p = args.get("path", "?")
    mode = args.get("mode", "overwrite")
    content = args.get("content", "")
    n_lines = content.count("\n") + (1 if content else 0)
    return f"write_file  {p}  mode={mode}  size={len(content)} chars / {n_lines} lines"


def _run(args: dict) -> ToolResult:
    raw = args.get("path")
    if not raw:
        return ToolResult(ok=False, output="", error="missing 'path'")
    content = args.get("content")
    if content is None:
        return ToolResult(ok=False, output="", error="missing 'content'")
    mode = (args.get("mode") or "overwrite").lower()
    if mode not in ("create", "overwrite", "append"):
        return ToolResult(ok=False, output="", error=f"invalid mode: {mode}")

    path = _resolve(raw)

    if mode == "create" and path.exists():
        return ToolResult(ok=False, output="", error=f"file already exists: {path}")

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        return ToolResult(ok=False, output="", error=f"mkdir parent failed: {e}")

    old_content: Optional[str] = None
    can_rollback = False
    if mode == "overwrite" and path.exists():
        try:
            old_content = path.read_text(encoding="utf-8")
            can_rollback = True
        except Exception:
            pass

    #  · 缩水守卫 · chat.js 444K 整文件覆盖丢功能事故的硬闸
    #   "大文件 overwrite 暴跌" = 经典"没读全·凭记忆重建·碾掉看不见的部分"特征
    #   (read_file 一次只 40K · 9000 行文件你大概率没读全)。 拦下来逼用 edit_file 局部替换。
    #   阈值: 旧文件 > 20K 字符 (≈半个读窗) 且新内容掉到 < 60% → 拦。 有意大删传 allow_shrink=true。
    if old_content is not None and not args.get("allow_shrink"):
        old_n, new_n = len(old_content), len(content)
        if old_n > 20000 and new_n < old_n * 0.6:
            return ToolResult(
                ok=False,
                output="",
                error=(
                    f"⛔ 缩水守卫拦截: 你要把 {path.name} 从 {old_n} → {new_n} 字符"
                    f" (掉了 {100 * (old_n - new_n) // old_n}%)。\n"
                    "这正是 chat.js 整文件覆盖丢功能事故的特征——大文件 read_file 一次只能看 40K·"
                    "你大概率没读全·overwrite 会用残缺记忆碾掉没读到的部分 (语音/文档/视觉就是这么没的)。\n"
                    "→ 正确做法: 用 edit_file 做局部 str_replace·只动你要改的那段·其余字节原地不动。\n"
                    "→ 如果你确实是【有意】大幅删减 (删了一整块死代码)·传 allow_shrink=true 再来一次。"
                ),
            )

    # 编辑并发软锁: 覆盖/追加已存在文件时·另一个对话正改它 / 磁盘被外部改过 → 软提示 (可 force 过)
    # create 模式是新建文件·没有覆盖风险(撞 already exists 已在上面拦)·跳过。
    _owner = current_session_id()
    _lock_note = None
    if mode != "create" and path.exists():
        if old_content is not None:
            _cur_text = old_content
        else:
            try:
                _cur_text = path.read_text(encoding="utf-8")
            except Exception:
                _cur_text = ""
        _lock_ok, _lock_note = _edit_guard(
            str(path), _owner, _cur_text, force=bool(args.get("force")), tool=f"write_file:{mode}"
        )
        if not _lock_ok:
            return ToolResult(ok=False, output="", error=_lock_note or "编辑锁冲突")

    try:
        if mode == "append":
            with path.open("a", encoding="utf-8") as f:
                f.write(content)
        else:
            path.write_text(content, encoding="utf-8")
    except Exception as e:
        return ToolResult(ok=False, output="", error=f"{type(e).__name__}: {e}")

    try:
        written = path.read_text(encoding="utf-8")
    except Exception as e:
        rolled = False
        if can_rollback and old_content is not None:
            try:
                path.write_text(old_content, encoding="utf-8")
                rolled = True
            except Exception:
                pass
        return ToolResult(
            ok=False,
            output="",
            error=(
                f"write verify read-back failed: {e}. "
                f"{'Rolled back to previous content.' if rolled else 'No rollback (file was new or non-UTF-8).'}"
            ),
        )

    if mode == "append":
        mismatch_detail = (
            f"appended {len(content)} chars but file does not end with them"
            if not written.endswith(content)
            else ""
        )
    else:
        mismatch_detail = (
            f"expected {len(content)} chars exact match but got {len(written)} chars on disk"
            if written != content
            else ""
        )

    if mismatch_detail:
        rolled = False
        if can_rollback and old_content is not None:
            try:
                path.write_text(old_content, encoding="utf-8")
                rolled = True
            except Exception:
                pass
        return ToolResult(
            ok=False,
            output="",
            error=(
                f"write verify roundtrip mismatch: {mismatch_detail}. "
                f"Likely cause: silent encoding loss / concurrent overwrite / disk error. "
                f"{'Rolled back to previous content.' if rolled else 'No rollback available.'}"
            ),
        )

    # 写成功 · 把编辑锁刷新到新内容指纹(同一对话连续写不误报·也记录"这文件谁动过")
    _edit_note(str(path), _owner, written, tool=f"write_file:{mode}")

    try:
        size = path.stat().st_size
    except OSError:
        size = -1

    base_output = (
        f"wrote {path}\n"
        f"mode={mode}  bytes_on_disk={size}  chars_written={len(content)}  verified=utf-8-roundtrip"
    )
    if _lock_note:
        base_output = f"{base_output}\n{_lock_note}"

    #  F · branch guard
    warn = _branch_guard_warning(path)
    if warn:
        base_output = f"{base_output}\n\n{warn}"

    #  · B4 · 编辑后即时自检 (告警·不拦·"锁出口不锁动作")
    try:
        from workers.edit_selfcheck import selfcheck
        sc_ok, sc_warn = selfcheck([str(path)])
        if not sc_ok:
            base_output = f"{base_output}\n\n{sc_warn}"
    except Exception:
        pass

    return ToolResult(ok=True, output=base_output)


SPEC = ToolSpec(
    name="write_file",
    description=(
        "Write text content to a file (create / overwrite / append). "
        "用户 will be asked to confirm before writes. "
        "Writes to .env, soul/, .git/, .venv/, or any opus-soul/skills-cursor path "
        "require explicit 'do it' from 用户 (GUARD tier)."
    ),
    tier=TIER_CONFIRM,
    input_schema={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Target file path. Relative resolves from Daemonkey root.",
            },
            "content": {
                "type": "string",
                "description": "Full content to write (or to append in append mode).",
            },
            "mode": {
                "type": "string",
                "enum": ["create", "overwrite", "append"],
                "description": "create: fail if exists. overwrite: replace. append: add to end.",
            },
            "allow_shrink": {
                "type": "boolean",
                "description": (
                    "Bypass the shrink-guard. Only set true when you INTENTIONALLY shrink a large file "
                    ">40% (e.g. deleting a big dead-code block). For normal edits to big files, "
                    "use edit_file (str_replace) instead — never overwrite."
                ),
            },
            "force": {
                "type": "boolean",
                "description": (
                    "Override the concurrent-edit advisory lock (another conversation editing this file, "
                    "or the file changed on disk since the last tool write). Only set true after confirming "
                    "you won't clobber someone else's work. Default false."
                ),
            },
        },
        "required": ["path", "content"],
    },
    run=_run,
    summarize=_summarize,
    classify=_classify,
)


register_tool(SPEC)
