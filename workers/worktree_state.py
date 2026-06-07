# -*- coding: utf-8 -*-
"""workers/worktree_state.py · 工作区 / 跨 agent git 真相自检 (卷五十五 · P2 · 2026-06-03)

────────────────────────────────────────────────────────────────────
为什么这个文件存在
────────────────────────────────────────────────────────────────────
今天 (2026-06-03) BRO 在 OPUS 合主干时撞了一次车: Cursor 为了不碰 daemon 的活
开了个 master worktree · 把 master 这个分支占着 checkout 了 · OPUS 一 merge 就被
git 拒掉 ("master is already checked out at ...")。 这类"两个 agent 共用一棵工作
树 / 共享分支 · 谁占了谁就挡住另一个"的坑 · 靠人肉协调治标不治本。

这个模块把"现在 git 工作区到底什么状态、安不安全做某个操作"做成一个**自包含的
真相报告** · 让三方都能自己判断该怎么处理:
  - daemon / OPUS (通过 agent_tools/worktree_status.py 工具) —— 动 master 前先自检
  - 应急维修台 (repair_console) —— daemon 崩了时看清现场
  - 开源用户 (没有 Cursor · 全靠 daemon + 维修台自救) —— 一眼看懂"该不该合、谁占着"

────────────────────────────────────────────────────────────────────
铁律: 自包含 · 只依赖标准库
────────────────────────────────────────────────────────────────────
绝不 import agent_tools / git_ops 的锁 (那条链今天还把整机 import 卡死过一次) ·
也不 import 任何会被 OPUS 改坏的 daemon 代码。 自己跑 git 子进程 · 纯只读 ·
任何时候 (daemon 活着 / 崩了 / 根本没起) 都能跑。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]

# Windows 下藏掉子进程黑窗 (不 import agent_tools 的 helper · 保持自包含)
_NO_WINDOW: dict = {}
if sys.platform == "win32":
    _NO_WINDOW = {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}


def _git(args: list[str], timeout: int = 8) -> tuple[int, str]:
    """跑一条只读 git · 返 (rc, stdout.strip())。 显式 utf-8 (Windows GBK 会崩)。"""
    try:
        r = subprocess.run(
            ["git"] + args, cwd=str(ROOT), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout, **_NO_WINDOW)
        return r.returncode, (r.stdout or "").strip()
    except Exception:
        return 1, ""


def _parse_worktrees() -> list[dict]:
    """解析 `git worktree list --porcelain` → [{path, head, branch}]。

    branch 形如 refs/heads/master · 取末段。 detached 的没 branch 行。
    """
    rc, out = _git(["worktree", "list", "--porcelain"], timeout=8)
    if rc != 0 or not out:
        return []
    trees: list[dict] = []
    cur: dict = {}
    for line in out.splitlines():
        line = line.rstrip()
        if line.startswith("worktree "):
            if cur:
                trees.append(cur)
            cur = {"path": line[len("worktree "):].strip(), "head": None, "branch": None}
        elif line.startswith("HEAD "):
            cur["head"] = line[len("HEAD "):].strip()[:12]
        elif line.startswith("branch "):
            ref = line[len("branch "):].strip()
            cur["branch"] = ref.rsplit("/", 1)[-1] if "/" in ref else ref
        elif line == "detached":
            cur["branch"] = None
    if cur:
        trees.append(cur)
    return trees


def _branch_kind(branch: Optional[str]) -> str:
    if not branch or branch == "HEAD":
        return "detached"
    if branch == "master":
        return "master"
    if branch.startswith("wish-") or branch.startswith("dev-wish"):
        return "wish"
    return "other"


def _same_path(a: str, b: Path) -> bool:
    try:
        return Path(a).resolve() == b.resolve()
    except Exception:
        return str(a).replace("\\", "/").rstrip("/") == str(b).replace("\\", "/").rstrip("/")


def working_tree_report() -> dict:
    """采集工作区 + 跨 agent git 真相 · 返结构化 dict (含 summary markdown + verdicts + advice)。

    对无 git 的目录返 {"git": False}。 纯只读 · 不改任何东西。
    """
    if not (ROOT / ".git").exists():
        return {"git": False, "summary": "(此目录不是 git 仓库)"}

    _, branch = _git(["rev-parse", "--abbrev-ref", "HEAD"])
    _, head = _git(["rev-parse", "--short", "HEAD"])
    _, dirty_raw = _git(["status", "--porcelain"], timeout=10)
    dirty_files = [l for l in dirty_raw.splitlines() if l.strip()]

    behind = ahead = 0
    rc, lr = _git(["rev-list", "--left-right", "--count", "master...HEAD"])
    if rc == 0 and lr:
        parts = lr.replace("\t", " ").split()
        if len(parts) == 2:
            try:
                behind, ahead = int(parts[0]), int(parts[1])
            except ValueError:
                pass

    worktrees = _parse_worktrees()
    other_worktrees = [w for w in worktrees if not _same_path(w.get("path") or "", ROOT)]
    master_holders = [w for w in worktrees if w.get("branch") == "master"]
    master_locked_elsewhere = any(
        not _same_path(w.get("path") or "", ROOT) for w in master_holders)

    rc, stash_raw = _git(["stash", "list"], timeout=8)
    stash_count = len([l for l in stash_raw.splitlines() if l.strip()]) if rc == 0 else 0

    rc, lg = _git(["rev-parse", "--short", "opus-last-good"])
    last_good = lg if rc == 0 and lg else None

    kind = _branch_kind(branch)
    rep = {
        "git": True,
        "branch": branch,
        "branch_kind": kind,
        "head": head,
        "dirty_count": len(dirty_files),
        "dirty_files": dirty_files[:20],
        "behind_master": behind,
        "ahead_of_master": ahead,
        "worktrees": worktrees,
        "other_worktree_count": len(other_worktrees),
        "master_locked_elsewhere": master_locked_elsewhere,
        "master_holders": [w.get("path") for w in master_holders],
        "stash_count": stash_count,
        "last_good": last_good,
    }

    # ── verdicts: 某个操作现在安不安全 ──────────────────────────────
    rep["verdicts"] = {
        "safe_to_checkpoint": True,  # checkpoint 只动当前分支 · 永远安全
        "safe_to_merge_to_master": not master_locked_elsewhere,
        "cross_agent_active": len(other_worktrees) > 0,
        "has_uncommitted": len(dirty_files) > 0,
        "has_unmerged_branch_work": kind == "wish" and ahead > 0,
    }

    # ── advice: 大白话"该怎么处理" (给 OPUS / 维修台 / 开源用户) ──────
    advice: list[str] = []
    if master_locked_elsewhere:
        who = ", ".join(p for p in rep["master_holders"] if not _same_path(p, ROOT))
        advice.append(
            f"⚠ master 正被另一个工作树占用 ({who})。 现在别在本仓 checkout master / "
            f"merge 到 master —— git 会直接拒绝。 先让对方释放 (Cursor 撤 worktree / 关掉) 再合。")
    if len(other_worktrees) > 0:
        advice.append(
            f"检测到 {len(other_worktrees)} 个额外工作树 (多半是 Cursor 在并行改)。 "
            f"提交前先看 git status · 用 `git add <你改的文件>` 而不是 `git add -A` · "
            f"别把对方的未提交改动卷进自己的 commit (这正是'A 抹 B'的源头)。")
    if dirty_files:
        advice.append(
            f"工作区有 {len(dirty_files)} 个未提交改动。 切分支 / 合并前先 checkpoint "
            f"(checkpoint_commit 会自动落档不丢)。")
    if rep["verdicts"]["has_unmerged_branch_work"]:
        advice.append(
            f"当前在 wish 分支 `{branch}` · 有 {ahead} 个提交没合进 master = 欠账。 "
            f"验收后走 live / merge_wish_to_master 合主干 · 别让它烂在分支上 (回退就丢)。")
    if not advice:
        advice.append(f"工作区干净 · 在 `{branch}` 上 · 无跨 agent 占用 · 常规操作安全。")
    rep["advice"] = advice
    rep["summary"] = format_report(rep)
    return rep


def format_report(rep: dict) -> str:
    """把 working_tree_report 的 dict 渲成人/LLM 都好读的 markdown。"""
    if not rep.get("git"):
        return rep.get("summary") or "(非 git 仓库)"
    lines = ["## 工作区状态自检 (git 真相)", ""]
    lines.append(f"- 当前分支: `{rep['branch']}` ({rep['branch_kind']}) · HEAD `{rep['head']}`")
    lines.append(f"- 相对 master: 领先 {rep['ahead_of_master']} · 落后 {rep['behind_master']}")
    dc = rep["dirty_count"]
    lines.append(f"- 未提交改动: {dc} 个" + (
        " · " + ", ".join(f.strip()[:40] for f in rep["dirty_files"][:6]) + (" …" if dc > 6 else "")
        if dc else " (干净)"))
    wt = rep.get("worktrees") or []
    lines.append(f"- 工作树: {len(wt)} 个" + (
        f" · ⚠ master 被别处占用" if rep.get("master_locked_elsewhere") else ""))
    for w in wt:
        tag = " ← 本仓" if _same_path(w.get("path") or "", ROOT) else ""
        lines.append(f"    · {w.get('path')} [{w.get('branch') or 'detached'}]{tag}")
    if rep.get("stash_count"):
        lines.append(f"- 遗留 stash: {rep['stash_count']} 个")
    if rep.get("last_good"):
        lines.append(f"- opus-last-good: `{rep['last_good']}` (回退目标)")
    lines.append("")
    lines.append("### 该怎么处理")
    for a in rep.get("advice") or []:
        lines.append(f"- {a}")
    return "\n".join(lines)


if __name__ == "__main__":
    # 命令行直接跑 = 打印当前工作区自检 (维修台 / 开源用户手动诊断用)
    print(format_report(working_tree_report()))
