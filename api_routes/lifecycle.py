"""
api_routes/lifecycle.py · daemon 生命周期路由 (wish-413999da · phase 1)
=====================================================================

7 路由 · daemon 的生死掌控:

  POST /restart-daemon        · 重启 daemon (装载新 Python 代码) · 卷四十一/卷四十六 III+IV
  POST /shutdown-daemon       · 关闭 daemon (不起新进程)
  GET  /rollback              · 拉候选 commits 给 BRO 选 · 卷四十四 G
  POST /rollback              · 执行回档 + 重启 (wish-196213df)
  POST /reload-soul           · 热重载 system prompt (改 SKILL.md/BRO-NOTEBOOK 不用重启)
  GET  /api/env/reload_status · .env hot reload watcher 状态 (Y6)
  GET  /api/lifecycle_status  · daemon 生命周期可见 UI banner / 重启历史 (wish-ed5553d5)

注: spawn 三处都用 DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW
    (bba1093 · 黑框 UX 修复 · 跟 workers/service_runner.py 对齐)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Body, Header, HTTPException

from agent_tools._subprocess_helper import detached_kwargs, no_window_kwargs, pythonw_path
from agent_tools._git_lock import daemon_git_lock

from api_routes._deps import check_auth


ROOT = Path(__file__).resolve().parent.parent


router = APIRouter()


@router.get("/api/env/reload_status")
async def env_reload_status(authorization: Optional[str] = Header(None)):
    """卷四十六 III 补丁 5 · Y6 · .env hot reload watcher 状态

    无 auth · 让 BRO 调 curl 一行看 watcher 在不在跑 + 上次 reload 改了啥
    """
    try:
        from workers.env_reloader import get_status
        return get_status()
    except Exception as e:
        return {"alive": False, "error": f"{type(e).__name__}: {e}"}


@router.get("/api/lifecycle_status")
async def lifecycle_status(authorization: Optional[str] = Header(None)):
    """卷四十六 III · wish-ed5553d5 · UI banner / 重启历史可见 · 无需 auth"""
    try:
        from workers.daemon_lifecycle import get_status
        return get_status()
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


@router.post("/restart-daemon")
async def restart_daemon(
    payload: Optional[dict] = Body(None),
    authorization: Optional[str] = Header(None),
):
    """重启 daemon · 装载新 Python 代码 (改完 .py 用 · /reload-soul 只重读 prompt)。

    卷四十一 V2 (改自 V1 子进程绑不上端口的 bug):
    - V1 用 DETACHED_PROCESS + DEVNULL stdout/stderr → 子进程 uvicorn 启动崩 (依赖 stdout)
    - V2 把 stdout/stderr 重定向到 data/daemon.out/.err · 不再 DEVNULL · 顺便让 BRO 能 tail log
    - parent 关 socket 后等 1.5s 给子进程绑端口的窗口 · 然后 os._exit

    卷四十六 III · os._exit 跳 atexit · 必须显式 mark_graceful_shutdown
    + 写 restart_request 让新 daemon 续场 (告诉它这是 WebUI 重启 · 不是 crash)

    卷四十六 IV · payload 加 follow_up_message + session_id (BRO 痛点 2026-05-26 早 8:48):
      WebUI 重启按钮原本不传 body · 新 daemon 起来只 inject system notice 不自动续场 ·
      BRO 期待"重启完帮我验证 X"必须手动再发一条 user 消息。 现在 UI 可以填验证任务 ·
      走跟 request_restart 工具完全一样的 follow_up_message 通道 · resume_runner 会 spawn
      background turn。
    """
    check_auth(authorization)
    argv = [pythonw_path()] + sys.argv
    out_path = ROOT / "data" / "daemon.out"
    err_path = ROOT / "data" / "daemon.err"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    body = payload or {}
    follow_up_message = (body.get("follow_up_message") or "").strip() or None
    if follow_up_message and len(follow_up_message) > 1000:
        raise HTTPException(400, "follow_up_message too long (max 1000 chars)")
    session_id = (body.get("session_id") or "").strip() or None

    try:
        from workers.daemon_lifecycle import write_restart_request, mark_graceful_shutdown
        write_restart_request(
            reason="webui_restart_button",
            session_id=session_id,
            follow_up_message=follow_up_message,
        )
    except Exception:
        mark_graceful_shutdown = None  # type: ignore

    parent_pid = os.getpid()
    child_env = os.environ.copy()
    child_env["OPUS_DAEMON_TAKEOVER_PID"] = str(parent_pid)

    def do_restart():
        time.sleep(0.3)
        try:
            out_f = open(out_path, "ab")
            err_f = open(err_path, "ab")
            subprocess.Popen(
                argv,
                close_fds=False,
                stdin=subprocess.DEVNULL,
                stdout=out_f,
                stderr=err_f,
                cwd=str(ROOT),
                env=child_env,
                **detached_kwargs(),
            )
            time.sleep(1.5)
        except Exception:
            pass
        try:
            if mark_graceful_shutdown:
                mark_graceful_shutdown("webui_restart_button")
        except Exception:
            pass
        os._exit(0)

    threading.Thread(target=do_restart, daemon=True).start()
    return {"ok": True, "message": "restarting", "argv": argv, "wait_seconds": 5}


@router.post("/shutdown-daemon")
async def shutdown_daemon(authorization: Optional[str] = Header(None)):
    """关闭 daemon · 不起新进程。

    卷四十一 · BRO 想完全停下后用 GUI 启动器从头来 · 或者就单纯让 OPUS 睡一下。
    卷四十六 III · 加 mark_graceful_shutdown · 否则下次启动会误判 crash
    """
    check_auth(authorization)

    def do_shutdown():
        time.sleep(0.4)
        try:
            from workers.daemon_lifecycle import mark_graceful_shutdown
            mark_graceful_shutdown("webui_shutdown_button")
        except Exception:
            pass
        os._exit(0)

    threading.Thread(target=do_shutdown, daemon=True).start()
    return {"ok": True, "message": "shutting down · go to GUI launcher to restart"}


@router.get("/rollback")
async def rollback_candidates(authorization: Optional[str] = Header(None)):
    """卷四十四 G · UI 回档按钮 (wish-196213df) · 拉候选 commits 给 BRO 选目标

    返回:
      - current_branch · 当前 git 分支
      - dirty          · 是否有未 commit 改动 (POST /rollback 会自动 stash)
      - candidates     · 最近 5 个 commits [{sha, short, msg, date}]
      - history        · 最近 10 条回档记录 (sessions/_rollback_history.json)

    OPUS 改崩了 daemon · BRO 在 UI 上点 ⏪ 回档 · 这个端点先返回候选给 BRO 选。
    """
    check_auth(authorization)

    if not (ROOT / ".git").exists():
        raise HTTPException(503, "not a git repo · 回档不可用")

    _kw = dict(cwd=ROOT, capture_output=True, text=True,
               encoding="utf-8", errors="replace", timeout=5,
               **no_window_kwargs())
    try:
        with daemon_git_lock("rollback:GET"):
            cur = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], **_kw)
            cur_branch = (cur.stdout or "").strip()

            dirty_p = subprocess.run(["git", "status", "--porcelain"], **_kw)
            dirty = bool((dirty_p.stdout or "").strip())

            log_p = subprocess.run(
                ["git", "log", "-5", "--pretty=format:%H|%h|%s|%cI"], **_kw,
            )
        candidates = []
        for ln in (log_p.stdout or "").strip().splitlines():
            parts = ln.split("|", 3)
            if len(parts) == 4:
                candidates.append({
                    "sha": parts[0],
                    "short": parts[1],
                    "msg": parts[2],
                    "date": parts[3],
                })
    except Exception as e:
        raise HTTPException(500, f"git query failed: {type(e).__name__}: {e}") from e

    history_path = ROOT / "sessions" / "_rollback_history.json"
    history = []
    if history_path.exists():
        try:
            history = json.loads(history_path.read_text(encoding="utf-8"))
            history = history[-10:]
        except Exception:
            history = []

    return {
        "ok": True,
        "current_branch": cur_branch,
        "dirty": dirty,
        "candidates": candidates,
        "history": history,
    }


@router.post("/rollback")
async def rollback_execute(
    payload: dict = Body(...),
    authorization: Optional[str] = Header(None),
):
    """卷四十四 G · UI 回档按钮 (wish-196213df) · 执行回档 + 重启 daemon

    body:
      - target_commit       · str  · 必须在最近 5 个 commits 内 (GET /rollback 返回的 sha)
      - confirm             · bool · 必须 true · 防误点
      - reason              · str  · 可选 · BRO 写为啥要回档
      - follow_up_message   · str  · 可选 · 卷四十六 IV (2026-05-26): 回档完成后 OPUS 自动跑的验证任务
      - session_id          · str  · 可选 · 跟 follow_up_message 配对 · resume turn 落档的目标 session

    流程:
      1. 验证 target_commit 在 candidates 内 (安全限制 · 不让一次跳太远)
      2. 有 dirty → git stash push --include-untracked (BRO 后悔可 git stash pop)
      3. git reset --hard <target_commit>
      4. append sessions/_rollback_history.json
      5. 触发 daemon restart (复用 /restart-daemon 的机制 · 子进程接管 · os._exit)
    """
    check_auth(authorization)

    target = (payload.get("target_commit") or "").strip()
    confirm = payload.get("confirm") is True
    reason = (payload.get("reason") or "").strip()
    follow_up_message = (payload.get("follow_up_message") or "").strip() or None
    if follow_up_message and len(follow_up_message) > 1000:
        raise HTTPException(400, "follow_up_message too long (max 1000 chars)")
    session_id = (payload.get("session_id") or "").strip() or None

    if not target:
        raise HTTPException(400, "target_commit 必填")
    if not confirm:
        raise HTTPException(400, "confirm=true 必填 · 防误点")

    if not (ROOT / ".git").exists():
        raise HTTPException(503, "not a git repo · 回档不可用")

    _kw = dict(cwd=ROOT, capture_output=True, text=True,
               encoding="utf-8", errors="replace", timeout=10,
               **no_window_kwargs())

    with daemon_git_lock("rollback:POST"):
        log_p = subprocess.run(["git", "log", "-5", "--pretty=format:%H"], **_kw)
        safe_shas = {ln.strip() for ln in (log_p.stdout or "").splitlines() if ln.strip()}
        if target not in safe_shas:
            raise HTTPException(
                400,
                f"target_commit 不在最近 5 个 commits 内 · 安全限制 (sha={target[:12]}…)",
            )

        cur_p = subprocess.run(["git", "rev-parse", "HEAD"], **_kw)
        from_sha = (cur_p.stdout or "").strip()

        if from_sha == target:
            raise HTTPException(400, "target_commit 跟当前 HEAD 一样 · 不需要回档")

        dirty_p = subprocess.run(["git", "status", "--porcelain"], **_kw)
        had_dirty = bool((dirty_p.stdout or "").strip())
        stash_msg: Optional[str] = None
        if had_dirty:
            ts = time.strftime("%Y-%m-%d %H:%M:%S")
            stash_msg = f"rollback at {ts} · BRO clicked UI button"
            sp = subprocess.run(
                ["git", "stash", "push", "-m", stash_msg, "--include-untracked"], **_kw,
            )
        if sp.returncode != 0:
            raise HTTPException(500, f"git stash 失败: {(sp.stderr or '')[:300]}")

    rp = subprocess.run(["git", "reset", "--hard", target], **_kw)
    if rp.returncode != 0:
        raise HTTPException(500, f"git reset 失败: {(rp.stderr or '')[:300]}")

    history_path = ROOT / "sessions" / "_rollback_history.json"
    history = []
    if history_path.exists():
        try:
            history = json.loads(history_path.read_text(encoding="utf-8"))
            if not isinstance(history, list):
                history = []
        except Exception:
            history = []
    history.append({
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "from_commit": from_sha,
        "to_commit": target,
        "stashed": had_dirty,
        "stash_msg": stash_msg,
        "triggered_by": "BRO",
        "reason": reason or None,
    })
    history_path.parent.mkdir(parents=True, exist_ok=True)
    history_path.write_text(
        json.dumps(history, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    argv = [pythonw_path()] + sys.argv
    out_path = ROOT / "data" / "daemon.out"
    err_path = ROOT / "data" / "daemon.err"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        from workers.daemon_lifecycle import write_restart_request, mark_graceful_shutdown
        write_restart_request(
            reason=f"webui_rollback to {target[:12]}",
            session_id=session_id,
            follow_up_message=follow_up_message,
        )
    except Exception:
        mark_graceful_shutdown = None  # type: ignore

    parent_pid = os.getpid()
    child_env = os.environ.copy()
    child_env["OPUS_DAEMON_TAKEOVER_PID"] = str(parent_pid)

    def do_restart():
        time.sleep(0.5)
        try:
            out_f = open(out_path, "ab")
            err_f = open(err_path, "ab")
            subprocess.Popen(
                argv,
                close_fds=False,
                stdin=subprocess.DEVNULL,
                stdout=out_f, stderr=err_f, cwd=str(ROOT),
                env=child_env,
                **detached_kwargs(),
            )
            time.sleep(1.5)
        except Exception:
            pass
        try:
            if mark_graceful_shutdown:
                mark_graceful_shutdown(f"webui_rollback to {target[:12]}")
        except Exception:
            pass
        os._exit(0)

    threading.Thread(target=do_restart, daemon=True).start()
    return {
        "ok": True,
        "message": "rolled back · daemon restarting",
        "from_commit": from_sha[:12],
        "to_commit": target[:12],
        "stashed": had_dirty,
        "stash_msg": stash_msg,
        "wait_seconds": 5,
    }


@router.post("/reload-soul")
async def reload_soul(authorization: Optional[str] = Header(None)):
    """热重载 system prompt · 改了 SKILL.md / runtime_addendum / BRO-NOTEBOOK 不用重启 daemon。

    卷三十九 · 改 system prompt 后下一次 chat 即刻生效。返回 before/after 字符数差。
    """
    check_auth(authorization)
    try:
        from soul_loader import load_soul
        from daemon_runtime import RUNTIME
        before_chars = len(RUNTIME.system_prompt or "")
        soul = load_soul()
        RUNTIME.system_prompt = soul.system_prompt
        after_chars = len(RUNTIME.system_prompt)
        return {
            "ok": True,
            "before_chars": before_chars,
            "after_chars": after_chars,
            "delta": after_chars - before_chars,
            "skill_chars": soul.skill_chars,
            "memories_chars": soul.memories_chars,
        }
    except Exception as e:
        raise HTTPException(500, f"reload-soul failed: {type(e).__name__}: {e}") from e
