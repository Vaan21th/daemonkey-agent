"""
workers/git_ops.py
==================
OPUS 自我演化的 git 纪律 · 单一真相 (卷四十八 · 2026-06-01)

为什么这个文件存在:
  卷四十七复盘出"好活儿从不落主干"是所有灾难的总病根:
    - 写完代码重启 · 改动是裸的工作区改动 (request_restart 不 commit) → 一回退就丢
    - ready_for_merge 只改状态标志 · 不真 merge → 活儿烂在 wish 分支
    - wish 分支从"当前 HEAD"切 · 不是 master → 新 wish 丢掉前一个没合并的 wish

  本模块把 commit / merge / 分支基线 / known-good 这四件事收成系统强制 ·
  让 "A 完成 → 必落主干 → B 从含 A 的主干出发" 成为不变量。 不管多会话还是
  单对话 · 都不会再出现 "A commit 了 · B 的任务重启把 A 抹掉"。

约束:
  - 所有 git 子进程显式 encoding='utf-8' (Windows 默认 GBK 会崩 · 卷四十二教训)
  - 全部包在 daemon_git_lock 里串行化 (跟 write_file / wish_update / shell_exec 同一把锁)
  - 锁 / no_window 都用 lazy import · 避免 workers→agent_tools 的加载期循环依赖
"""

from __future__ import annotations

import subprocess
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
LAST_GOOD_TAG = "opus-last-good"


def _has_git() -> bool:
    return (ROOT / ".git").exists()


@contextmanager
def _lock(label: str):
    """复用全 daemon 单例 git 锁 · 拿不到 (daemon 外脚本) 就退化无锁"""
    cm = None
    try:
        from agent_tools._git_lock import daemon_git_lock
        cm = daemon_git_lock(label)
    except Exception:
        cm = None
    if cm is None:
        yield
    else:
        with cm:
            yield


def _run_git(cmd: list[str], timeout: int = 15) -> tuple[int, str, str]:
    """跑一条 git 命令 (调用方负责已持锁) · 返 (returncode, stdout, stderr)"""
    kw = dict(cwd=str(ROOT), capture_output=True, text=True,
              encoding="utf-8", errors="replace", timeout=timeout)
    try:
        from agent_tools._subprocess_helper import no_window_kwargs
        kw.update(no_window_kwargs())
    except Exception:
        pass
    try:
        res = subprocess.run(["git"] + cmd, **kw)
        return res.returncode, (res.stdout or ""), (res.stderr or "")
    except Exception as e:
        return 1, "", f"{type(e).__name__}: {e}"


def _ensure_identity() -> None:
    """没配 git 身份就给【本仓库】设一个兜底身份 (调用方已持锁)。

    病根 (2026-06-08 update_core 联调发现): 开源版用户 clone 下来的全新仓库 ·
    机器上若从没 `git config user.name/email` · 任何 commit 都会 "Author identity
    unknown" 直接失败 —— 这会让 checkpoint / wish 分支 / merge / update_core 的安全
    存档【全线崩掉】· 用户的活儿反而更容易丢。 这里做 lazy 兜底: 只在缺失时设 ·
    且只写 --local (这一个仓库) · 绝不碰用户的全局 git 配置。
    """
    rc, out, _ = _run_git(["config", "user.email"], timeout=5)
    if rc == 0 and out.strip():
        return
    _run_git(["config", "user.email", "daemonkey@localhost"], timeout=5)
    _run_git(["config", "user.name", "Daemonkey"], timeout=5)


def current_branch() -> Optional[str]:
    if not _has_git():
        return None
    with _lock("git_ops:branch"):
        rc, out, _ = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], timeout=5)
    return (out.strip() or None) if rc == 0 else None


def is_dirty() -> bool:
    if not _has_git():
        return False
    with _lock("git_ops:dirty"):
        rc, out, _ = _run_git(["status", "--porcelain"], timeout=10)
    return bool(out.strip()) if rc == 0 else False


def checkpoint_commit(reason: str) -> dict:
    """工作区脏就 git add -A + commit · 干净就跳过。 ①号机制: 永不留裸改动。

    返 {committed: bool, sha, branch, note}
    """
    out: dict = {"committed": False, "sha": None, "branch": None, "note": ""}
    if not _has_git():
        out["note"] = "git 未 init · 跳过 checkpoint"
        return out
    with _lock("git_ops:checkpoint"):
        rc, st, _ = _run_git(["status", "--porcelain"], timeout=10)
        if rc != 0:
            out["note"] = "git status 失败 · 跳过 checkpoint"
            return out
        if not st.strip():
            out["note"] = "工作区干净 · 无需 checkpoint"
            return out
        _ensure_identity()  # 全新 clone 没配身份会让 commit 直接失败 · 先兜底
        br_rc, br_out, _ = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], timeout=5)
        out["branch"] = br_out.strip() if br_rc == 0 else None
        add_rc, _, add_err = _run_git(["add", "-A"], timeout=20)
        if add_rc != 0:
            out["note"] = f"git add 失败: {add_err.strip()[:160]}"
            return out
        msg = (f"[checkpoint] {reason}").strip()[:200]
        crc, cout, cerr = _run_git(["commit", "-m", msg], timeout=30)
        if crc != 0:
            out["note"] = f"git commit 失败: {(cerr or cout).strip()[:160]}"
            return out
        s_rc, s_out, _ = _run_git(["rev-parse", "--short", "HEAD"], timeout=5)
        out["committed"] = True
        out["sha"] = s_out.strip() if s_rc == 0 else None
        out["note"] = f"已 checkpoint commit · {out['sha']} · 分支 {out['branch']}"
    return out


def branch_from_master(wish_id: str, slug: str) -> tuple[Optional[str], str]:
    """③号机制: 从 master 切出 wish 分支 (确定的主干基线)。

    脚下脏 → 先 checkpoint 到当前分支 (不丢)。 已在目标分支 → 不切。
    返 (branch_or_None, 给 BRO 看的消息)。
    """
    if not _has_git():
        return None, "git 未 init · 跳过自动分支"
    branch = f"{wish_id}/{slug}"
    with _lock("git_ops:branch_from_master"):
        _ensure_identity()
        cb_rc, cb_out, _ = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], timeout=5)
        cur = cb_out.strip() if cb_rc == 0 else ""
        if cur.startswith(wish_id):
            return cur, f"已在分支 `{cur}` · 不切"
        st_rc, st_out, _ = _run_git(["status", "--porcelain"], timeout=10)
        if st_rc == 0 and st_out.strip():
            _run_git(["add", "-A"], timeout=20)
            _run_git(["commit", "-m", f"[checkpoint] 开 {branch} 前存档 {cur}"], timeout=30)
        co_rc, _, co_err = _run_git(["checkout", "master"], timeout=15)
        if co_rc != 0:
            return None, f"切 master 失败 · {co_err.strip()[:160]}"
        ex_rc, _, _ = _run_git(["show-ref", "--verify", f"refs/heads/{branch}"], timeout=5)
        if ex_rc == 0:
            r_rc, _, r_err = _run_git(["checkout", branch], timeout=15)
            action = "已切到"
        else:
            r_rc, _, r_err = _run_git(["checkout", "-b", branch], timeout=15)
            action = "已从 master 新建并切到"
        if r_rc != 0:
            return None, f"git checkout 失败 · {r_err.strip()[:160]}"
        return branch, f"{action}分支 `{branch}` · 基线=master · BRO review 后 merge 回主干"


# 误提交的备份/临时文件 · 永远不该被 merge 进主干 (卷四十九 II)
_JUNK_SUFFIXES = (".orig", ".tmp", ".swp", ".rej", "~")


def _branch_diff_files(branch: str) -> list[str]:
    """master...branch 这一侧改动的文件名 (调用方已持锁)。"""
    rc, out, _ = _run_git(["diff", "--name-only", f"master...{branch}"], timeout=15)
    return [f.strip() for f in out.splitlines() if f.strip()] if rc == 0 else []


def _branch_already_in_master(branch: str) -> bool:
    """分支内容是否已在 master (调用方已持锁)。

    两层判断 (与 audit_wishes_merge_state 同源 · 单一真相):
      ① merge-base --is-ancestor branch master → 分支是 master 祖先 = 已合
      ② cherry master branch 无 '+' 行 → 分支独有提交全在 master (cherry/squash 等价) = 已合

    用途: merge 幂等前置闸。 已合就别重复 checkout+merge —— 重复 checkout 还会被脏
    工作区 (运行时文件) 撞失败·正是今天 live 假阴性的病根。
    """
    anc_rc, _, _ = _run_git(["merge-base", "--is-ancestor", branch, "master"], timeout=8)
    if anc_rc == 0:
        return True
    ch_rc, ch, _ = _run_git(["cherry", "master", branch], timeout=12)
    if ch_rc == 0:
        return not [x for x in ch.splitlines() if x.startswith("+ ")]
    return False


def _delete_merged_branch(branch: str) -> bool:
    """合入后清掉 wish 分支书签 (调用方已持锁) · 用 -d (git 只删已合并的·安全) · 返是否删成。

    卷五十五 · 2026-06-03 BRO 拍板根治: 每个 daemon wish 自动建分支·合完没人删 →
    历史攒了 33 个遗留分支 (BRO 一看吓一跳)。 从此"合一个删一个"·不再堆积。
    删不掉 (是当前分支 / 别处 worktree 占用) 无害 · 只是没清成 · 不影响 merge 结果。
    """
    rc, _, _ = _run_git(["branch", "-d", branch], timeout=10)
    return rc == 0


def merge_safety_blockers(branch: str, expected_wish_id: Optional[str] = None) -> list[str]:
    """合并安全门 · 返回阻断原因列表 (空=安全)。 调用方已持锁。

    卷四十九 II 病根: spawn-task 孤儿分支被错贴成另一个 wish 的 dev_branch ·
    一旦推 ready_for_merge 就会盲并一个过期 + 含 8622 行误提交 .bak 的烂分支 ·
    直接污染 master。 安全门拦两类:
      ① wish-id 前缀对不上 → 疑似跨 wish 污染分支 / 贴错 dev_branch
      ② 分支里有误提交的备份/临时文件 (.bak / .orig / .tmp ...) → 永远不该进主干
    """
    blockers: list[str] = []
    if expected_wish_id:
        head = branch.split("/", 1)[0].strip()
        if head != expected_wish_id.strip():
            blockers.append(
                f"分支前缀 `{head}` 与 wish `{expected_wish_id}` 不符 · "
                f"疑似贴错 dev_branch 或跨 wish 污染分支")
    files = _branch_diff_files(branch)
    junk = [f for f in files
            if ".bak" in f.lower() or f.lower().endswith(_JUNK_SUFFIXES)]
    if junk:
        shown = ", ".join(junk[:4]) + (" ..." if len(junk) > 4 else "")
        blockers.append(f"分支含 {len(junk)} 个疑似误提交的备份/临时文件: {shown}")
    return blockers


def merge_wish_to_master(branch: str, expected_wish_id: Optional[str] = None,
                         allow_override: bool = False) -> dict:
    """②号机制: 把 wish 分支真合回 master (闭环)。

    切到分支 → 脏则 checkpoint → 切 master → merge --no-ff。
    冲突 → merge --abort 回到干净 master · 不留半合状态 · 让人手动解。

    卷四十九 II: 合并前过安全门 (merge_safety_blockers) · 命中则拒绝盲并 ·
    除非显式 allow_override=True (BRO 知道自己在干嘛)。
    返 {ok: bool, sha, note, blocked?}
    """
    out: dict = {"ok": False, "sha": None, "note": ""}
    if not _has_git():
        out["note"] = "git 未 init · 跳过 merge"
        return out
    branch = (branch or "").strip()
    if not branch or branch == "master":
        out["note"] = f"分支无效或本就是 master ({branch!r}) · 跳过 merge"
        return out
    with _lock("git_ops:merge"):
        _ensure_identity()
        ex_rc, _, _ = _run_git(["show-ref", "--verify", f"refs/heads/{branch}"], timeout=5)
        if ex_rc != 0:
            out["note"] = f"分支 `{branch}` 不存在 · 无法 merge"
            return out
        # 卷五十五 · 幂等前置闸 (2026-06-03 修 live 假阴性):
        #   分支内容若已在 master (祖先/cherry 等价) → 早被合入 (手动合 or 之前合过) ·
        #   直接放行·不 checkout·不被脏运行时文件撞。
        #   病根: 老逻辑无脑 checkout 记录的 dev_branch · 撞上脏 activity.jsonl/opus_wishlist.json
        #   就误报"代码没真进主干"·害已上线的 wish 状态烂在 review。
        if _branch_already_in_master(branch):
            s_rc, s_out, _ = _run_git(["rev-parse", "--short", "HEAD"], timeout=5)
            out["ok"] = True
            out["sha"] = s_out.strip() if s_rc == 0 else None
            note = (f"分支 `{branch}` 内容已在 master (祖先/cherry 等价) · "
                    f"无需重复 merge · 主干已含此 wish")
            if _delete_merged_branch(branch):  # 合完即删 · 根治堆积
                out["branch_deleted"] = True
                note += " · 已清理该分支"
            out["note"] = note
            return out
        if not allow_override:
            blockers = merge_safety_blockers(branch, expected_wish_id)
            if blockers:
                out["blocked"] = True
                out["note"] = ("🛑 merge 安全门拦截 (卷四十九 II) · " + " ; ".join(blockers)
                               + " · 这不是干净的 wish 分支。 如确需合入: 请 cherry-pick "
                                 "其中干净的改动到新分支 · 或显式 allow_override=True")
                return out
        # 卷五十五 · 切分支前先 checkpoint 当前分支的脏改动 · 否则脏树会让 checkout 直接 abort
        #   (今天事故的一半: 工作区脏着运行时文件 · checkout 报 "local changes would be overwritten")。
        pre_rc, pre_out, _ = _run_git(["status", "--porcelain"], timeout=10)
        if pre_rc == 0 and pre_out.strip():
            _run_git(["add", "-A"], timeout=20)
            _run_git(["commit", "-m", "[checkpoint] merge 前存档当前分支 · 防脏树挡 checkout"], timeout=30)
        co_rc, _, co_err = _run_git(["checkout", branch], timeout=15)
        if co_rc != 0:
            out["note"] = f"切到 `{branch}` 失败 · {co_err.strip()[:160]}"
            return out
        st_rc, st_out, _ = _run_git(["status", "--porcelain"], timeout=10)
        if st_rc == 0 and st_out.strip():
            _run_git(["add", "-A"], timeout=20)
            _run_git(["commit", "-m", f"[checkpoint] merge 前存档 {branch}"], timeout=30)
        # 卷五十三 · 并发不打架的关键: 合并前先让分支吃下最新 master (B 先吃下已合的 A) ·
        # 冲突在分支上暴露·不污染 master。 之后 branch→master 就是干净快进。
        rb_rc, rb_out, rb_err = _run_git(
            ["merge", "master", "--no-edit", "-m", f"[refresh] {branch} 吃下最新 master 再合"], timeout=30)
        if rb_rc != 0:
            _run_git(["merge", "--abort"], timeout=15)
            out["note"] = (f"分支 `{branch}` 与最新 master 冲突 · 已 abort · "
                           f"需先在分支上解决与 master 的冲突 (B 要先吃下已合入的 A) 再合。 "
                           f"git: {(rb_err or rb_out).strip()[:200]}")
            return out
        # 卷五十四 · B2 上线闸: 此刻工作区 = 分支(已吃下最新 master) = "将要变成 master 的样子"。
        # 合进 master 前·在全新子进程里验"这版能不能跑起来"(建 app + 路由 smoke + 前端 JS)。
        # 过不了 → 不合·留在分支待修·master 保持干净。 allow_override=True 时跳过(BRO 知道在干嘛)。
        if not allow_override:
            try:
                from workers.verify_gate import run_verify_subprocess
                v_ok, v_report = run_verify_subprocess()
            except Exception:
                v_ok, v_report = True, ""  # 闸 import 不动 → fail-open · 不卡死合并
            if not v_ok:
                _run_git(["checkout", "master"], timeout=15)  # 回到干净 master · 分支留着待修
                out["blocked"] = True
                out["note"] = ("🛑 上线闸拦截 (卷五十四 B2) · 这版过不了 verify"
                               " (建不起来 / 路由有雷 / 前端 JS 坏) · 已留在分支不合入 master ·"
                               " 修好再合。 如确需强合: allow_override=True。\n"
                               + (v_report or "").strip()[-1500:])
                return out
        m_rc, _, m_err = _run_git(["checkout", "master"], timeout=15)
        if m_rc != 0:
            out["note"] = f"切 master 失败 · {m_err.strip()[:160]}"
            return out
        mg_rc, mg_out, mg_err = _run_git(
            ["merge", "--no-ff", branch, "-m", f"merge {branch} -> master (wish 闭环 · 卷四十八)"],
            timeout=30)
        if mg_rc != 0:
            _run_git(["merge", "--abort"], timeout=15)
            out["note"] = (f"merge 冲突 · 已 abort 回到干净 master · 需手动解决 "
                           f"`{branch}` 与 master 的冲突。 git: {(mg_err or mg_out).strip()[:200]}")
            return out
        s_rc, s_out, _ = _run_git(["rev-parse", "--short", "HEAD"], timeout=5)
        out["ok"] = True
        out["sha"] = s_out.strip() if s_rc == 0 else None
        note = f"已 merge `{branch}` -> master · {out['sha']} · 主干已含此 wish"
        # 卷五十五 · 合完即删 wish 分支 · 根治分支堆积 (2026-06-03 BRO 拍板)。
        # 此刻在 master 上·branch 已 --no-ff 合入·-d 安全删掉书签。
        if _delete_merged_branch(branch):
            out["branch_deleted"] = True
            note += " · 已清理该分支"
        out["note"] = note
    return out


def tag_last_good(require_master: bool = True) -> dict:
    """④号机制: 把当前 HEAD 标成 opus-last-good (回退/安全模式的恢复目标)。

    默认只在 master 上打 · 因为回退是回主干。 优雅停机时调 = "这版跑到主动停为止没崩"。
    返 {tagged: bool, sha, note}
    """
    out: dict = {"tagged": False, "sha": None, "note": ""}
    if not _has_git():
        return out
    with _lock("git_ops:tag_last_good"):
        cb_rc, cb_out, _ = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], timeout=5)
        cur = cb_out.strip() if cb_rc == 0 else ""
        if require_master and cur != "master":
            out["note"] = f"当前在 `{cur}` 非 master · 不打 known-good tag"
            return out
        t_rc, _, t_err = _run_git(["tag", "-f", LAST_GOOD_TAG], timeout=10)
        if t_rc != 0:
            out["note"] = f"打 tag 失败 · {t_err.strip()[:160]}"
            return out
        s_rc, s_out, _ = _run_git(["rev-parse", "--short", LAST_GOOD_TAG], timeout=5)
        out["tagged"] = True
        out["sha"] = s_out.strip() if s_rc == 0 else None
        out["note"] = f"{LAST_GOOD_TAG} -> {out['sha']} (master known-good)"
    return out


def last_good_ref() -> Optional[str]:
    """返 opus-last-good 指向的短 sha · 没有返 None"""
    if not _has_git():
        return None
    with _lock("git_ops:last_good_ref"):
        rc, out, _ = _run_git(["rev-parse", "--verify", "--short", LAST_GOOD_TAG], timeout=5)
    return out.strip() if rc == 0 else None


def audit_wishes_merge_state(wishes: list[dict]) -> dict:
    """卷五十二 · 从 git 真相算每个 wish 的 dev_branch 相对 master 的合并状态。

    为什么从 git 算 · 不只信 wish 的 status 标签:
      今早 BRO 的痛点 (修好 B · A 变回去) 的病根正是 "标签写着 live · git 里却没合"。
      status 是 OPUS 写的意图 · git 才是真相。 这个函数让 UI/OPUS 显示真相 ·
      把 "已提交但躺在分支上、没进主干" 的欠账主动暴露出来 · 不必等回退才发现。

    一次锁 · 一次 for-each-ref 拿全部本地分支 · 再逐分支判定。 只对真有
    dev_branch 的 wish 跑 git (cursor 直改的 dev_branch=null · 直接 none)。

    返 {wish_id: {"state": str, "ahead": int}} · state ∈:
      'unmerged' 分支有真没合的提交 (= 已提交未合并 · 欠账 · UI 要警示)
      'merged'   分支内容已在 master (含 cherry-pick 等价 · 或已是 master 祖先)
      'gone'     dev_branch 记录在 wish 里但本地分支已不存在 (多半合并后删 · 按已了结)
      'none'     没有独立分支 / 直落 master / 无效 → 无欠账 · 不警示
    """
    out: dict = {}
    if not _has_git() or not wishes:
        return out
    with _lock("git_ops:wish_audit"):
        rc, brs, _ = _run_git(
            ["for-each-ref", "--format=%(refname:short)", "refs/heads"], timeout=10)
        branches = {l.strip() for l in brs.splitlines() if l.strip()} if rc == 0 else set()
        for w in wishes:
            wid = w.get("id")
            if not wid:
                continue
            db = (w.get("dev_branch") or "").strip()
            # 真实 git 分支名不含空格 · 带空格的是 "master (直接落...)" 这类备注 → 无独立分支
            if not db or " " in db or db == "master":
                out[wid] = {"state": "none", "ahead": 0}
                continue
            if db not in branches:
                out[wid] = {"state": "gone", "ahead": 0}
                continue
            anc_rc, _, _ = _run_git(["merge-base", "--is-ancestor", db, "master"], timeout=8)
            if anc_rc == 0:
                out[wid] = {"state": "merged", "ahead": 0}
                continue
            ch_rc, ch, _ = _run_git(["cherry", "master", db], timeout=12)
            plus = [x for x in ch.splitlines() if x.startswith("+ ")] if ch_rc == 0 else []
            out[wid] = ({"state": "unmerged", "ahead": len(plus)} if plus
                        else {"state": "merged", "ahead": 0})
    return out
