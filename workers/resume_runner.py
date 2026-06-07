"""
workers/resume_runner.py
========================

重启后自动触发 background LLM turn (卷四十六 III 补丁 3 · 2026-05-26)

----------------------------------------------------------------------
为什么有这个模块
----------------------------------------------------------------------

BRO 反馈: 当前 daemon 重启续场只在 session jsonl 里注一条 system message ·
但 LLM 不会被自动唤醒 · BRO 必须发一条消息触发 chat handler · OPUS 才能
读到 system message · 才能继续上次的任务。

BRO 期望: OPUS 调 request_restart 时可以塞一个 follow_up_message ·
重启后新 daemon 自动以这条作为 user message 触发 background LLM turn ·
OPUS 跑完结果落档进 session jsonl · BRO 下次进 WebUI 就看到验证结论。

----------------------------------------------------------------------
设计取舍
----------------------------------------------------------------------

1. **后台 turn 没有前端 SSE 接收方**: progress=None · 跑完落档 · BRO 进 WebUI 翻历史看
2. **auto_confirm = 'confirm'** (卷四十六 续 14 补丁 IV · 2026-05-26 · BRO 拍板):
   - 跟主对话 WebUI 默认 'confirm' **同级对齐** · 不再比主对话严一档
   - AUTO + CONFIRM **自动 go** (curl / shell_exec / python_exec / git commit /
     write_file 等都能跑 · OPUS 真有能力验证 endpoint / 跑 HTTP / 落档代码)
   - GUARD (rm / empty_trash / git push --force / 大改文件) 走 inline confirm ·
     **背景 turn 没 SSE 接收方** → 自动 skip = OPUS 看到 declined → OPUS 在 turn 里
     把要 GUARD 的事讲给 BRO · BRO 切回 WebUI 手动处理
   - 安全网: GUARD 永远不会在 background 跑过 · 99% follow_up 场景 (验证 endpoint /
     看 log / 跑测试) CONFIRM 就够 · 不需要 GUARD
   - 调整: 想回保守 `OPUS_RESUME_AUTO_CONFIRM=auto` · 想 yolo `=guard` · 都在 env
3. **等 RUNTIME ready**: daemon 启动时 lifecycle init 跑得早 (RUNTIME init 之前) ·
   resume turn 必须等 RUNTIME.client 就绪才能跑 LLM · 用轮询 + 超时 (max 30s)
4. **不阻塞 daemon 启动**: 全部在 daemon thread · 启动 thread 后立刻返回 ·
   daemon 主流程 (uvicorn) 不受影响
"""

from __future__ import annotations

import os
import threading
import time
from typing import Optional


_MAX_WAIT_RUNTIME_SEC = 30
# 卷四十六 续 14 补丁 IV · 跟主对话 WebUI 默认 'confirm' 对齐 · 不再严一档
# env override: OPUS_RESUME_AUTO_CONFIRM=auto / confirm / guard
_DEFAULT_AUTO_CONFIRM = (os.environ.get("OPUS_RESUME_AUTO_CONFIRM") or "confirm").strip().lower()
if _DEFAULT_AUTO_CONFIRM not in ("auto", "confirm", "guard"):
    _DEFAULT_AUTO_CONFIRM = "confirm"
_MAX_TOKENS = 4096

# 背景 turn 状态追踪 (wish-83fe7c7b 补丁 · 2026-06-03)
# WebUI waitForDaemonAfterRestartTool 轮询此状态 · 等 background turn 完成后再加载历史
#
# 卷五十六 · 2026-06-03 · 加 "scheduled" 态根治"重启后假死/输入没锁":
#   病根: 旧逻辑只在 _runner 里 _wait_runtime_ready 通过后才置 "running" · 这之前查到的是默认
#   "none" · 而前端 _waitForBackgroundTurn 把 none 当成"续写结束"→ 提前放行 → 解锁输入 → 但
#   几百 ms 后 resume turn 才真跑起来 · 前端已定格 idle 且不再轮询 → 卡假死直到手动刷新。
#   修法: schedule 当下(spawn 线程前)就同步置 "scheduled" · 前端在 RUNTIME-init 窗口看到的是
#   非终止态 → 继续等 · 不会误判。 状态流转: scheduled → running → completed/failed。
_bg_turn_status: dict[str, str] = {}  # session_id -> "scheduled" | "running" | "completed" | "failed"
_bg_status_lock = threading.Lock()


def get_background_turn_status(session_id: str) -> str:
    """查询指定 session 的背景 turn 状态. 返 'none' | 'scheduled' | 'running' | 'completed' | 'failed'"""
    with _bg_status_lock:
        return _bg_turn_status.get(session_id, "none")


def _wait_runtime_ready(max_wait_sec: int = _MAX_WAIT_RUNTIME_SEC) -> bool:
    """轮询等 RUNTIME.client 就绪 · 返 True = 就绪 · False = 超时"""
    from daemon_runtime import RUNTIME
    deadline = time.time() + max_wait_sec
    while time.time() < deadline:
        if RUNTIME.client is not None and RUNTIME.model:
            return True
        time.sleep(0.5)
    return False


def _run_background_turn(message: str, session_id: str) -> dict:
    """在 daemon 进程里以 background thread 跑一次 _chat_impl

    返 dict (跟 _chat_impl 一样) 或 raise · 调用方负责包 try/except

    卷四十六 续 14 补丁 VI · 2026-05-26 16:15:
      register turn_id 到 _TURN_TO_SID + _ACTIVE_TURNS · 让 GET /sessions/{sid}/active_turn
      能查到这个 background turn · 前端 _maybeStartPoll 才能启 polling 自动 reload
      (不然 BRO reload session 看到 follow_up turn 跑一半的快照 · 后续 reply 不出现 ·
      必须手动 F5 才能看到 final reply)
    """
    import threading
    from daemon_api import _chat_impl, _ACTIVE_TURNS, _TURN_TO_SID, _TURNS_LOCK

    turn_id = "resume-" + (session_id[-8:] if session_id else "x")
    cancel_event = threading.Event()
    with _TURNS_LOCK:
        _ACTIVE_TURNS[turn_id] = cancel_event
        _TURN_TO_SID[turn_id] = session_id
    try:
        return _chat_impl(
            message=message,
            session_id=session_id,
            auto_confirm=_DEFAULT_AUTO_CONFIRM,
            max_tokens=_MAX_TOKENS,
            progress=None,
            cancel_event=cancel_event,
            turn_id=turn_id,
        )
    finally:
        with _TURNS_LOCK:
            _ACTIVE_TURNS.pop(turn_id, None)
            _TURN_TO_SID.pop(turn_id, None)


def schedule_resume_turn(restart_req: Optional[dict]) -> bool:
    """如果 restart_req 有 follow_up_message + session_id · 启动 background thread

    返 True = 已 schedule · False = 没 follow_up / 没 session_id / restart_req 是 None
    """
    if not restart_req:
        return False
    follow_up = (restart_req.get("follow_up_message") or "").strip()
    sid = (restart_req.get("session_id") or "").strip()
    if not follow_up:
        return False
    if not sid:
        return False

    # 卷五十六 · 关键: 一确定要续写就同步置 "scheduled" (在 spawn 线程 + _wait_runtime_ready 之前)。
    # 这样前端在 daemon 刚 alive、resume turn 还没真跑起来的窗口里 · 查到的是 "scheduled" 而不是
    # "none" · 不会把"还没起来"误判成"已结束"。 这是治本重启后假死的那一刀。
    with _bg_status_lock:
        _bg_turn_status[sid] = "scheduled"

    def _runner():
        # 卷四十六 IV (2026-05-26 第二十二根毛): flush=True · 子进程 stdout
        # redirect 到文件时默认 block-buffered (4096 bytes) · 不 flush BRO 看不到 log
        print(f"[opus-resume] thread 启动 · session={sid} · auto_confirm={_DEFAULT_AUTO_CONFIRM} · follow_up='{follow_up[:80]}' · 等 RUNTIME ready", flush=True)
        if not _wait_runtime_ready():
            print(f"[opus-resume] RUNTIME 等了 {_MAX_WAIT_RUNTIME_SEC}s 没就绪 · resume turn 放弃", flush=True)
            with _bg_status_lock:
                _bg_turn_status[sid] = "failed"
            return
        with _bg_status_lock:
            _bg_turn_status[sid] = "running"
        try:
            print(f"[opus-resume] 启动 background turn · session={sid} · follow_up='{follow_up[:80]}'", flush=True)
            result = _run_background_turn(follow_up, sid)
            reply_preview = (result.get("reply") or "")[:200].replace("\n", " ")
            print(f"[opus-resume] background turn 完成 · reply='{reply_preview}...'", flush=True)
            with _bg_status_lock:
                _bg_turn_status[sid] = "completed"
        except Exception as e:
            import traceback
            print(f"[opus-resume] background turn 失败: {type(e).__name__}: {e}", flush=True)
            print(f"[opus-resume] traceback:\n{traceback.format_exc()}", flush=True)
            with _bg_status_lock:
                _bg_turn_status[sid] = "failed"

    t = threading.Thread(target=_runner, daemon=True, name="opus-resume-turn")
    t.start()
    return True
