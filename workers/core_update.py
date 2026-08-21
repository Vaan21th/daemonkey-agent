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

from workers import core_fingerprint
from workers.git_ops import ROOT, _ensure_identity, _has_git, _lock, _run_git, checkpoint_commit
from workers.kernel_takeover import load as load_takeover

MANIFEST_PATH = ROOT / "core_manifest.json"


def load_manifest() -> dict:
    """读 core_manifest.json · 缺失/坏掉返空壳 (不抛)。"""
    try:
        # utf-8-sig: 发布链 PowerShell 写回 core_manifest.json 会带 BOM · 硬 utf-8 撞 BOM 报错 →
        # 版本号/升级胶囊全灭 (2026-08-17 0.9.5 发布回归) · sig 兼容 BOM/无 BOM 双态
        return json.loads(MANIFEST_PATH.read_text(encoding="utf-8-sig"))
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
    """白名单文件里 · 用户改过的。

    给 update_core 用:升级前提醒「这些内核文件你本地改过 · 覆盖前会先 checkpoint ·
    可 git revert 找回」——对应「用户最爱改前端 · 别被无声覆盖」那条护栏(卷七十四续十八)。

    0.9.6 起两条腿走 —— 基线指纹为主·git status 补它管不到的部分。

    为什么加指纹 (git status 的死角):
      git status 只看【工作区 vs 最后一次 commit】· 而 commit 随时会发生 —— daemon 自己的
      checkpoint、用户手动 commit、别的工具落袋。 任何一次都让 status 变干净 →
      下次升级认为「他没改过」→ 不备份·直接覆盖·改动只剩在 git 历史里。
      指纹比的是【实际内容 vs 官方内容】· 跟 commit 了几次无关。

    为什么 git status 不能扔 (指纹也有管不到的):
      指纹只对【它记过的文件】有发言权。 基线比白名单旧、文件刚扩进白名单、或整台机器
      还没基线时·那些文件在指纹眼里是空白 —— 当成"没改过"就等于保护倒退。 所以基线
      覆盖不到的部分继续走 git status: 两者取并集·各补各的盲区。
    """
    files = kernel_files(manifest)
    if not files:
        return []

    baseline = (core_fingerprint.load().get("files") or {})
    dirty: list[str] = core_fingerprint.modified_files(files) if baseline else []

    uncovered = [f for f in files if f not in baseline]
    if uncovered and _has_git():
        with _lock("core_update:dirty"):
            rc, out, _ = _run_git(["status", "--porcelain", "--"] + uncovered, timeout=15)
        if rc == 0:
            for line in out.splitlines():
                # porcelain 行: "XY <path>" · 路径从第 4 字符起 · 带引号的去掉
                p = line[3:].strip().strip('"').replace("\\", "/")
                if p and p not in dirty:
                    dirty.append(p)
    return dirty


# ── 0.8.4 · 升级保护层 (wish-f2f0f9de) · 用户魔改备份 ─────────────────────
def _backup_user_overrides(files: list[str]) -> dict[str, str]:
    """把用户魔改的白名单文件【物理备份】到 data/runtime/user_overrides/。

    为什么物理备份 (不只靠 git checkpoint):
      - checkpoint 把改动 commit 进 git 历史 · 可 git revert 找回 · 但用户不一定懂 git
      - 物理备份给用户一个「看得见摸得着」的副本 · 合并时直接读它 · 零 git 门槛
    返回 {file: backup_path} · 备份失败的文件跳过(不阻塞升级)。
    """
    backup_dir = ROOT / "data" / "runtime" / "user_overrides"
    try:
        backup_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        return {}
    out: dict[str, str] = {}
    for f in files:
        try:
            src = ROOT / f
            if not src.is_file():
                continue
            safe = f.replace("/", "__").replace("\\", "__")
            dst = backup_dir / f"{safe}.bak"
            dst.write_bytes(src.read_bytes())
            out[f] = str(dst)
        except Exception:
            continue
    return out


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

    流程: ①先 checkpoint_commit 落袋(自己拿放锁) → ②抢锁 fetch → 拉一轮 →
    ③若本轮拉到了 core_manifest.json(白名单本身更新了) · 用新清单自动再补一轮。

    为什么要补第二轮 (卷七十五续八): update_core 是照【本地那份清单】的白名单拉的。
    当中心库"扩了白名单"(新增内核文件)时 · 用户第一轮只能先把新 core_manifest.json
    拉下来 · 新增文件不在旧清单里这轮进不来。 补一轮让本地清单已更新后立刻把新增文件
    补齐 —— 跨版本"扩白名单"升级免得让用户手动升两次。 (老版本用户第一次跳过来跑的是
    旧代码没这层 · 仍需两轮 · 故工具层会在第一轮后提示"再升一次"。)

    返 {"ok":bool, "updated":[...], "added":[...], "skipped_deleted":[...],
        "checkpoint": str, "commit_sha": str|None, "note": str, "passes": int}
    """
    out: dict = {"ok": False, "updated": [], "added": [], "skipped_deleted": [],
                 "checkpoint": "", "commit_sha": None, "note": "", "passes": 0,
                 "user_overrides": [],      # 0.8.4 · 用户魔改备份清单
                 "skipped_takeover": []}    # 0.9.6 · 用户接管 · 官方有新版但没覆盖
    if not _has_git():
        out["note"] = "git 未 init · 无法更新"
        return out

    # ① fetch 必须最先跑 —— 只有拿到中心库那份清单 · 才知道这次把白名单扩成了什么样。
    #    (独立拿锁放锁 · 后面 checkpoint 复用 git_ops 自己拿锁 · 嵌套会死锁)
    with _lock("core_update:fetch"):
        _ensure_identity()
        ok, msg = _fetch_locked(remote)
        remote_wl = _remote_kernel_files_locked(remote, branch) if ok else []
    if not ok:
        out["note"] = f"fetch 失败 · {msg}"
        return out

    # ② 升级保护层 · checkpoint 前记下用户魔改 (checkpoint 会把工作区落盘成 commit·
    #    之后 git status 就干净了·所以必须在这之前检测)。
    #    范围 = 本地清单 ∪ 远端清单: 0.9.6 前只查本地清单 · 于是"这次才纳入白名单的文件"
    #    在检测时还是隐形的 → 不备份不提示 → 补拉第二轮照新清单把它覆盖掉 · 用户改动无声消失。
    #    每次扩白名单的版本都会踩·而基线版本一次就扩了 12 个 (场景 E 守这条)。
    union = sorted(set(kernel_files()) | set(remote_wl))
    user_dirty = dirty_kernel_files({"kernel": {"_union": union}})

    # ③ 落袋为安: 覆盖前先把工作区所有改动 commit (复用 git_ops · 它自己拿放锁)。
    #    任何后续覆盖都能 git revert 找回 · 这是"绝不丢用户活儿"的物理保证。
    cp = checkpoint_commit(f"update_core 前存档 · 拉 {remote}/{branch} 内核")
    out["checkpoint"] = cp.get("note", "")

    # ④ 抢一次锁 · 备份 → 拉第一轮 →(必要时)拉第二轮 (不嵌套 checkpoint · 锁不可重入)
    with _lock("core_update:apply"):
        _ensure_identity()  # 工作区本来干净时 checkpoint 提前返回没设身份 · 这里兜底

        # 0.9.6 修 · 备份必须在 checkout 之前:_backup_user_overrides 读的是磁盘【当下】内容 ·
        #   原先放在 pull 之后 · 那时磁盘已被 checkout 成官方版 · .bak 里存的就是官方新版 ·
        #   于是 merge_user_override 拿 .bak 当"你的版本"跟磁盘对比 → 永远输出"两边完全一致"。
        #   0.8.5~0.9.5 的"合并我的改动"一直是这个哑火状态。
        #   此刻还不知道官方会覆盖哪些 · 所以把全部 user_dirty 都备份(多备的无害) ·
        #   冲突判定挪到两轮 pull 之后按累积结果算。
        #   已接管的文件不可能被覆盖 → 不需要保护 · 也不该留备份污染合并清单。
        backup_targets = [f for f in user_dirty if f not in set(load_takeover())]
        pre_backups = _backup_user_overrides(backup_targets) if backup_targets else {}

        p1 = _pull_pass_locked(remote, branch, base, do_commit)
        if not p1["ok"]:
            out["note"] = p1["note"]
            return out
        out["updated"] = list(p1["updated"])
        out["added"] = list(p1["added"])
        out["skipped_deleted"] = list(p1["deleted"])
        out["skipped_takeover"] = list(p1["skipped_takeover"])
        out["commit_sha"] = p1["commit_sha"]
        out["note"] = p1["note"]
        out["passes"] = 1

        # ⑤ 本轮拉到了 core_manifest.json → 白名单可能新增文件 · 用新清单从 HEAD 再补一轮。
        #    跑了第二轮就代表"新清单已完整生效"· passes=2 · 无论第二轮有没有捞到新文件。
        if p1["pulled_manifest"]:
            p2 = _pull_pass_locked(remote, branch, "HEAD", do_commit)
            out["passes"] = 2
            out["skipped_takeover"] += [f for f in p2["skipped_takeover"]
                                        if f not in out["skipped_takeover"]]
            if p2["ok"] and (p2["updated"] or p2["added"]):
                out["updated"] += [f for f in p2["updated"] if f not in out["updated"]]
                out["added"] += [f for f in p2["added"] if f not in out["added"]]
                out["skipped_deleted"] += [f for f in p2["deleted"]
                                           if f not in out["skipped_deleted"]]
                if p2["commit_sha"]:
                    out["commit_sha"] = p2["commit_sha"]
                out["note"] = "清单更新后自动补拉了一轮新增内核文件"

        # 0.8.4 升级保护层 · 冲突 = 用户魔改 ∩ 官方实际覆盖 · 含第二轮补拉(原先只算第一轮 ·
        #   靠新清单才拉进来的文件即使被覆盖也不会提示用户)
        conflicts = [f for f in user_dirty if f in (out["updated"] + out["added"])]
        if conflicts:
            out["user_overrides"] = [
                {"file": f, "backup": pre_backups.get(f, "")} for f in conflicts
            ]
        # 官方这次没覆盖的 · 备份是多余的:留着会让 merge_user_override 列出一堆"两边完全一致"
        #   的假条目(.bak 与磁盘同源) —— 那正是备份时序 bug 最迷惑人的症状 · 别自己再造一遍。
        for _f, _p in pre_backups.items():
            if _f not in conflicts:
                try:
                    Path(_p).unlink()
                except Exception:
                    pass

        if not out["updated"] and not out["added"]:
            out["note"] = (
                "官方有新版 · 但全部落在你接管的文件上 · 本次没动任何文件"
                if out["skipped_takeover"]
                else "内核已是最新 · 没有白名单文件需要更新")
        out["ok"] = True
    return out


# ── 不加锁内部实现 (调用方必须已持锁) ───────────────────────────────────

def _remote_kernel_files_locked(remote: str, branch: str) -> list[str]:
    """中心库那份清单里的白名单 · 拿不到返空 (调用方须已持锁且已 fetch)。

    为什么要读远端那份: 「用户改过哪些内核文件」是照【本地】清单查的·而补拉第二轮
    照【新】清单跑。 中心库扩白名单时·新纳入的文件在本地清单里还不存在 → 查不到 →
    不备份 → 第二轮照样覆盖它。 取本地 ∪ 远端·把这道缝焊上。
    """
    if not _has_git() or not remote:
        return []
    rc, out, _ = _run_git(["show", f"{remote}/{branch}:core_manifest.json"], timeout=15)
    if rc != 0 or not out.strip():
        return []
    try:
        return kernel_files(json.loads(out.lstrip("\ufeff")))
    except Exception:
        return []


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


def _pull_pass_locked(remote: str, branch: str, base: str, do_commit: bool) -> dict:
    """一轮拉取: diff(照【当前磁盘上】的白名单) → checkout 差异文件 → (可选)commit。

    调用方必须已持锁且已 fetch。 每轮都重新读磁盘上的 core_manifest.json (_diff_locked →
    kernel_files() 现读现算) · 所以第一轮把新清单 checkout 下来后 · 第二轮自然按新清单跑。
    返 {"ok","updated","added","deleted","commit_sha","note","pulled_manifest"}。
    """
    res: dict = {"ok": False, "updated": [], "added": [], "deleted": [],
                 "commit_sha": None, "note": "", "pulled_manifest": False,
                 "skipped_takeover": []}
    d = _diff_locked(remote, branch, base)
    if d.get("error"):
        res["note"] = f"diff 失败 · {d['error']}"
        return res
    to_pull = list(d["changed"]) + list(d["added"])
    res["deleted"] = d["deleted"]

    # 用户接管的文件:官方版根本不进 checkout 的参数表 → 物理上不可能被覆盖(与备份/合并那条
    #   事后补救路线互补)。 两轮 pull 共用本函数 · 所以这一处过滤对补拉那轮同样生效。
    taken = set(load_takeover())
    if taken:
        res["skipped_takeover"] = [f for f in to_pull if f in taken]
        to_pull = [f for f in to_pull if f not in taken]

    if not to_pull:
        res["ok"] = True
        return res
    ref = f"{remote}/{branch}"
    co_rc, _, co_err = _run_git(["checkout", ref, "--"] + to_pull, timeout=30)
    if co_rc != 0:
        res["note"] = f"checkout 覆盖失败 · {co_err.strip()[:200]} · 没有任何文件被改"
        return res
    # 只报真拉了的 · 被接管而跳过的不能算进 updated/added(否则报告说"更新了"而磁盘没动)
    pulled = set(to_pull)
    res["updated"] = [f for f in d["changed"] if f in pulled]
    res["added"] = [f for f in d["added"] if f in pulled]
    res["pulled_manifest"] = "core_manifest.json" in to_pull
    if do_commit:
        _run_git(["add", "--"] + to_pull, timeout=20)
        msg2 = f"[update_core] 同步内核 {len(to_pull)} 文件 from {ref}"
        c_rc, c_out, c_err = _run_git(["commit", "-m", msg2], timeout=30)
        if c_rc == 0:
            s_rc, s_out, _ = _run_git(["rev-parse", "--short", "HEAD"], timeout=5)
            res["commit_sha"] = s_out.strip() if s_rc == 0 else None
        else:
            # 覆盖后内容与 HEAD 相同也算成功 · 只是不留新 commit
            res["note"] = f"(已覆盖工作区 · commit 跳过: {(c_err or c_out).strip()[:120]})"
    res["ok"] = True
    return res
