"""
workers/core_update.py
======================
选择性内核更新 (update_core) 的机制层 · 卷六十四续六 · 2026-06-08

为什么存在:
  Daemonkey 是开源版 · 每个用户的实例会随对话长出各自的 L2 功能 / L3 灵魂记忆。
  官方没法做整包更新 (会盖掉用户的自演化)。 但"写代码 / 编辑安全 / git 纪律 /
  daemon 救命"这些 L1 内核基础设施是所有人共享的 · 必须能统一升级。

  本模块实现"外科手术式"更新: 只从中心库 (gitee/github) 同步 core_manifest.json
  白名单里列的内核文件 · 清单外的一个字节都不碰。 用户的 soul/ data/ 应用 永不受影响。

机制 (全用 git · 不手写文件拷贝):
  fetch <remote>                          → 把中心库最新内核拉到本地 ref · 不动工作区
  diff  HEAD <remote>/<branch> -- 白名单   → 看哪些内核文件有更新 (只读 · 预览)
  checkout <remote>/<branch> -- 白名单     → 只把白名单文件覆盖成中心库版本 · 其他全不动

安全:
  - 覆盖前先 checkpoint_commit (复用 git_ops) · 任何改动都能 git revert 找回
  - checkout 命令里【物理上只列白名单文件】· soul/data/应用 根本不在参数里 · 不可能被碰
  - 复用 git_ops 的 _run_git / _lock · 与全 daemon git 操作同一把锁 · 串行不打架
  - 锁是不可重入的 threading.Lock · 所以 apply 先让 checkpoint_commit 自己拿放锁 ·
    再单独抢一次锁做 fetch/diff/checkout · 绝不嵌套
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from workers.git_ops import ROOT, _ensure_identity, _has_git, _lock, _run_git, checkpoint_commit

MANIFEST_PATH = ROOT / "core_manifest.json"


def load_manifest() -> dict:
    """读 core_manifest.json · 缺失/坏掉返空壳 (不抛)。"""
    try:
        return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"kernel": {}, "never_sync": [], "sources": {}}


def local_core_version(manifest: Optional[dict] = None) -> str:
    """本地内核语义版本 (core_manifest.json 的 core_version) · 没有返空串。

    这是版本号唯一真相源的【本地侧】 · launcher / WebUI / update_core 全读它。
    """
    m = manifest or load_manifest()
    return str(m.get("core_version") or "").strip()


def remote_core_version(remote: str, branch: str = "master") -> str:
    """中心库那一份 core_manifest.json 里的 core_version · 拿不到返空串。

    用 `git show <remote>/<branch>:core_manifest.json` 直接读远程文件内容(不动工作区) ·
    调用前应已 fetch 过该 remote(check 流程里 fetch 在前)。给「有没有新版」的对比用。
    """
    if not _has_git() or not remote:
        return ""
    with _lock("core_update:remote_ver"):
        rc, out, _ = _run_git(["show", f"{remote}/{branch}:core_manifest.json"], timeout=15)
    if rc != 0 or not out.strip():
        return ""
    try:
        return str(json.loads(out).get("core_version") or "").strip()
    except Exception:
        return ""


def kernel_files(manifest: Optional[dict] = None) -> list[str]:
    """把 manifest.kernel 下所有分类的文件名拍平成一个去重列表 (posix 斜杠)。"""
    m = manifest or load_manifest()
    files: list[str] = []
    for group in (m.get("kernel") or {}).values():
        for f in group:
            f = str(f).strip().replace("\\", "/")
            if f and f not in files:
                files.append(f)
    return files


def dirty_kernel_files(manifest: Optional[dict] = None) -> list[str]:
    """白名单文件里 · 当前工作区有未提交改动的 (git status --porcelain)。

    给 update_core 用:升级前提醒「这些内核文件你本地改过 · 覆盖前会先 checkpoint ·
    可 git revert 找回」——对应「用户最爱改前端 · 别被无声覆盖」那条护栏(卷七十四续十八)。
    """
    if not _has_git():
        return []
    files = kernel_files(manifest)
    if not files:
        return []
    with _lock("core_update:dirty"):
        rc, out, _ = _run_git(["status", "--porcelain", "--"] + files, timeout=15)
    if rc != 0:
        return []
    dirty: list[str] = []
    for line in out.splitlines():
        # porcelain 行: "XY <path>" · 路径从第 4 字符起 · 带引号的去掉
        p = line[3:].strip().strip('"').replace("\\", "/")
        if p and p not in dirty:
            dirty.append(p)
    return dirty


def list_configured_remotes() -> dict[str, str]:
    """解析 `git remote -v` → {name: fetch_url}。 没仓库/没远程返空。"""
    if not _has_git():
        return {}
    with _lock("core_update:remotes"):
        rc, out, _ = _run_git(["remote", "-v"], timeout=8)
    if rc != 0:
        return {}
    remotes: dict[str, str] = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[2] == "(fetch)":
            remotes[parts[0]] = parts[1]
    return remotes


def resolve_remote(remote: Optional[str], manifest: Optional[dict] = None) -> tuple[Optional[str], str]:
    """定哪个 remote 拉。 优先级: 显式入参 > manifest.sources.primary > 唯一已配置 remote。

    返 (remote_name_or_None, 给人看的说明/错误)。
    """
    configured = list_configured_remotes()
    if not configured:
        return None, "本仓库没配置任何 git remote · 先 `git remote add gitee <中心库URL>`"
    if remote:
        if remote in configured:
            return remote, f"用指定 remote `{remote}` ({configured[remote]})"
        return None, (f"指定的 remote `{remote}` 没配置 · 现有: {list(configured)} · "
                      f"或 `git remote add {remote} <URL>`")
    m = manifest or load_manifest()
    primary = ((m.get("sources") or {}).get("primary") or "").strip()
    if primary and primary in configured:
        return primary, f"用 manifest 主源 `{primary}` ({configured[primary]})"
    if len(configured) == 1:
        only = next(iter(configured))
        return only, f"用唯一已配置 remote `{only}` ({configured[only]})"
    return None, (f"有多个 remote {list(configured)} 但 manifest 没钉主源 · "
                  f"请显式传 remote 参数")


# ── 加锁版基础操作 (各自独立拿锁 · 给单独调用用) ─────────────────────────

def fetch(remote: str, timeout: int = 90) -> tuple[bool, str]:
    """git fetch <remote> · 把中心库最新拉到本地 ref · 不碰工作区。"""
    if not _has_git():
        return False, "git 未 init"
    with _lock("core_update:fetch"):
        return _fetch_locked(remote, timeout)


def diff_kernel(remote: str, branch: str = "master", base: str = "HEAD") -> dict:
    """看白名单文件 base..<remote>/<branch> 的差异 (只读)。

    返 {"changed":[M文件], "added":[远程新增], "deleted":[远程已删·不动],
        "stat": 行级统计文本, "error": str|None}
    """
    if not _has_git():
        return {"error": "git 未 init"}
    with _lock("core_update:diff"):
        return _diff_locked(remote, branch, base)


def preview_diff(remote: str, files: list[str], branch: str = "master",
                 base: str = "HEAD", max_chars: int = 6000) -> str:
    """给出白名单文件的真实 diff 文本 (截断) · 让 OPUS/BRO 看到具体改了什么。"""
    if not _has_git() or not files:
        return ""
    ref = f"{remote}/{branch}"
    with _lock("core_update:preview"):
        rc, out, err = _run_git(["diff", f"{base}..{ref}", "--"] + files, timeout=20)
    if rc != 0:
        return f"[diff 失败] {(err or out).strip()[:300]}"
    return out[:max_chars] + ("\n... [diff 已截断]" if len(out) > max_chars else "")


def apply_update(remote: str, branch: str = "master", base: str = "HEAD",
                 do_commit: bool = True) -> dict:
    """外科手术: 只把【有差异的白名单文件】覆盖成中心库版本 · 其他物理不碰。

    流程: ①先 checkpoint_commit 落袋(自己拿放锁) → ②抢锁 fetch+diff+checkout+commit。
    返 {"ok":bool, "updated":[...], "added":[...], "skipped_deleted":[...],
        "checkpoint": str, "commit_sha": str|None, "note": str}
    """
    out: dict = {"ok": False, "updated": [], "added": [], "skipped_deleted": [],
                 "checkpoint": "", "commit_sha": None, "note": ""}
    if not _has_git():
        out["note"] = "git 未 init · 无法更新"
        return out

    # ① 落袋为安: 覆盖前先把工作区所有改动 commit (复用 git_ops · 它自己拿放锁)。
    #    任何后续覆盖都能 git revert 找回 · 这是"绝不丢用户活儿"的物理保证。
    cp = checkpoint_commit(f"update_core 前存档 · 拉 {remote}/{branch} 内核")
    out["checkpoint"] = cp.get("note", "")

    # ② 抢一次锁 · 做 fetch → diff → checkout → commit (不嵌套 checkpoint · 锁不可重入)
    with _lock("core_update:apply"):
        _ensure_identity()  # 工作区本来干净时 checkpoint 提前返回没设身份 · 这里兜底
        ok, msg = _fetch_locked(remote)
        if not ok:
            out["note"] = f"fetch 失败 · {msg}"
            return out
        d = _diff_locked(remote, branch, base)
        if d.get("error"):
            out["note"] = f"diff 失败 · {d['error']}"
            return out
        to_pull = list(d["changed"]) + list(d["added"])
        out["skipped_deleted"] = d["deleted"]
        if not to_pull:
            out["ok"] = True
            out["note"] = "内核已是最新 · 没有白名单文件需要更新"
            return out
        ref = f"{remote}/{branch}"
        co_rc, _, co_err = _run_git(["checkout", ref, "--"] + to_pull, timeout=30)
        if co_rc != 0:
            out["note"] = f"checkout 覆盖失败 · {co_err.strip()[:200]} · 没有任何文件被改"
            return out
        out["updated"] = d["changed"]
        out["added"] = d["added"]
        if do_commit:
            _run_git(["add", "--"] + to_pull, timeout=20)
            msg2 = f"[update_core] 同步内核 {len(to_pull)} 文件 from {ref}"
            c_rc, c_out, c_err = _run_git(["commit", "-m", msg2], timeout=30)
            if c_rc == 0:
                s_rc, s_out, _ = _run_git(["rev-parse", "--short", "HEAD"], timeout=5)
                out["commit_sha"] = s_out.strip() if s_rc == 0 else None
            else:
                # 没东西可提交(覆盖后内容与 HEAD 相同)也算成功 · 只是不留新 commit
                out["note"] = f"(已覆盖工作区 · commit 跳过: {(c_err or c_out).strip()[:120]})"
        out["ok"] = True
    return out


# ── 不加锁内部实现 (调用方必须已持锁) ───────────────────────────────────

def _fetch_locked(remote: str, timeout: int = 90) -> tuple[bool, str]:
    rc, out, err = _run_git(["fetch", remote, "--prune"], timeout=timeout)
    if rc != 0:
        return False, (err or out).strip()[:300]
    return True, (err or out).strip()[:200] or "fetch ok"


def _diff_locked(remote: str, branch: str, base: str) -> dict:
    files = kernel_files()
    res: dict = {"changed": [], "added": [], "deleted": [], "stat": "", "error": None}
    if not files:
        res["error"] = "core_manifest.json 白名单为空"
        return res
    ref = f"{remote}/{branch}"
    rc, out, err = _run_git(["diff", "--name-status", f"{base}..{ref}", "--"] + files, timeout=20)
    if rc != 0:
        res["error"] = (err or out).strip()[:300]
        return res
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        status, path = parts[0].strip(), parts[-1].strip()
        if status.startswith("M"):
            res["changed"].append(path)
        elif status.startswith("A"):
            res["added"].append(path)
        elif status.startswith("D"):
            res["deleted"].append(path)
    s_rc, s_out, _ = _run_git(["diff", "--stat", f"{base}..{ref}", "--"] + files, timeout=20)
    res["stat"] = s_out.strip() if s_rc == 0 else ""
    return res
