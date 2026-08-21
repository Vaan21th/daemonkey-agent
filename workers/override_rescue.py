"""从 checkpoint commit 里捞回被【备份时序 bug】吞掉的用户魔改。

事故还原 (0.8.4 ~ 0.9.5):
    update_core 的 _backup_user_overrides() 跑在 git checkout 【之后】·
    于是"备份"下来的是刚拉到的官方版 —— 用户的真东西一个都没进 .bak。
    用户对 daemon 说「合并我的改动」· diff 两边同源 · 只会回一句"两边完全一致"。

为什么还能救:
    同一个流程里 checkpoint_commit 跑在 checkout 【之前】· 它 add -A 收了整个工作区。
    所以那次升级时用户手上的真版本·躺在那条 [checkpoint] commit 里。 git 没丢东西·
    只是用户不知道怎么进去拿 —— 这个模块负责拿出来·放回 .bak 让合并流程能用。

取哪一份:
    用户可能升级过多次·每次都留一条 checkpoint。 对每个文件取【最晚】那次 ——
    那是他最后一次真正拥有的版本 (之后的改动是基于新官方版继续演化的)。
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from workers.git_ops import ROOT, _has_git, _lock, _run_git

# core_update.checkpoint_commit(f"update_core 前存档 · ...") → "[checkpoint] update_core 前存档 · ..."
CHECKPOINT_MARK = "[checkpoint] update_core 前存档"

BACKUP_DIR_NAME = ("data", "runtime", "user_overrides")


def _backup_dir() -> Path:
    return ROOT.joinpath(*BACKUP_DIR_NAME)


def bak_name(rel: str) -> str:
    """与 core_update._backup_user_overrides 同一套命名 · 让现有合并流程直接认。"""
    return rel.replace("/", "__").replace("\\", "__") + ".bak"


def _checkpoints(limit: int = 40) -> list[tuple[str, str, str]]:
    """历次 update_core 的 checkpoint · 新→旧 · [(sha, 日期, 标题)]。"""
    if not _has_git():
        return []
    with _lock("override_rescue:log"):
        rc, out, _ = _run_git(
            ["log", f"--grep={CHECKPOINT_MARK}", "--fixed-strings",
             "--format=%H\t%ad\t%s", "--date=short", f"-{limit}"],
            timeout=30,
        )
    if rc != 0:
        return []
    rows = []
    for line in out.splitlines():
        parts = line.split("\t", 2)
        if len(parts) == 3 and parts[0].strip():
            rows.append((parts[0].strip(), parts[1].strip(), parts[2].strip()))
    return rows


def _files_in(sha: str) -> list[str]:
    """这条 checkpoint 相对父 commit 改了哪些文件 (posix 斜杠)。"""
    with _lock("override_rescue:diff"):
        rc, out, _ = _run_git(
            ["-c", "core.quotepath=false", "diff", "--name-only", f"{sha}^", sha],
            timeout=30,
        )
    if rc != 0:  # 首个 commit 没有父 · 或 sha 失效
        return []
    return [ln.strip().replace("\\", "/") for ln in out.splitlines() if ln.strip()]


def _content_at(sha: str, rel: str) -> Optional[str]:
    with _lock("override_rescue:show"):
        rc, out, _ = _run_git(["show", f"{sha}:{rel}"], timeout=30)
    return out if rc == 0 else None


def scan(kernel_files: list[str], limit: int = 40) -> list[dict]:
    """能救回来的东西 · [{file, sha, date, subject, content}]。

    只报【当前磁盘内容跟当时不一样】的 —— 一样说明那次没被覆盖·或者用户已经拿回去了·
    没必要惊动他。
    """
    if not _has_git():
        return []
    wl = {str(f).strip().replace("\\", "/") for f in kernel_files}
    found: dict[str, dict] = {}
    for sha, date, subject in _checkpoints(limit):  # 新→旧 · 先到的是最晚那次
        for rel in _files_in(sha):
            if rel not in wl or rel in found:
                continue
            content = _content_at(sha, rel)
            if content is None:
                continue
            now = ROOT / rel
            current = now.read_text(encoding="utf-8", errors="replace") if now.is_file() else None
            if current is not None and current == content:
                continue
            found[rel] = {"file": rel, "sha": sha[:10], "date": date,
                          "subject": subject[:80], "content": content}
    return [found[k] for k in sorted(found)]


def restore(candidates: list[dict]) -> list[dict]:
    """把捞出来的内容写成 .bak · 让「合并我的改动」照常走。

    已存在的 .bak 直接覆盖: 时序 bug 时期存下来的那些装的是官方版·
    留着只会让 diff 显示"两边完全一致"·毫无价值。
    """
    d = _backup_dir()
    d.mkdir(parents=True, exist_ok=True)
    done = []
    for c in candidates:
        p = d / bak_name(c["file"])
        existed = p.is_file()
        try:
            p.write_text(c["content"], encoding="utf-8")
            done.append({"file": c["file"], "backup": str(p), "from": c["sha"],
                         "date": c["date"], "replaced_stale": existed})
        except Exception as e:
            done.append({"file": c["file"], "error": str(e)[:120]})
    return done
