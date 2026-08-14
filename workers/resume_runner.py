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
    from daemon_api import _chat_impl, _ACTIVE_TURNS, _TURN_TO_SID, _TURNS_LOCK, _TURN_PROGRESS

    turn_id = "resume-" + (session_id[-8:] if session_id else "x")
    cancel_event = threading.Event()
    with _TURNS_LOCK:
        _ACTIVE_TURNS[turn_id] = cancel_event
        _TURN_TO_SID[turn_id] = session_id
    try:
        # wish-8914f90c · 墙钟熔断: 后台续场 turn 收紧预算 — 总墙钟 300s · 单次 LLM 60s。
        # daemon_api._env_float 每次调用时读 os.environ · 同进程内设置即刻生效。
        # 治: LLM 调用挂起 25min 占 session 锁 (墨言 08-09 16:47 第三次重启卡死事故)。
        _prev_wall = os.environ.get("_RESUME_WALL_CLOCK_SEC")
        _prev_llm = os.environ.get("_RESUME_LLM_TIMEOUT_SEC")
        os.environ["_RESUME_WALL_CLOCK_SEC"] = "300.0"
        os.environ["_RESUME_LLM_TIMEOUT_SEC"] = "60.0"
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
            # 恢复现场 · 不污染同进程其它路径 (主对话不应被墙钟限制)
            if _prev_wall is None:
                os.environ.pop("_RESUME_WALL_CLOCK_SEC", None)
            else:
                os.environ["_RESUME_WALL_CLOCK_SEC"] = _prev_wall
            if _prev_llm is None:
                os.environ.pop("_RESUME_LLM_TIMEOUT_SEC", None)
            else:
                os.environ["_RESUME_LLM_TIMEOUT_SEC"] = _prev_llm
    finally:
        with _TURNS_LOCK:
            _ACTIVE_TURNS.pop(turn_id, None)
            _TURN_TO_SID.pop(turn_id, None)
            _TURN_PROGRESS.pop(turn_id, None)  # ② 进度快照跟 turn 同生命周期


def schedule_resume_turn(restart_req: Optional[dict]) -> bool:
    """如果 restart_req 有 follow_up_message + session_id · 启动 background thread

    返 True = 已 schedule · False = 没 follow_up / 没 session_id / restart_req 是 None
    """
    if not restart_req:
        return False
    follow_up = (restart_req.get("follow_up_message") or "").strip()
    sid = (restart_req.get("session_id") or "").strip()
    # 卷八十四 · 防呆 (2026-07-28): DeepSeek 调 request_restart 时常不传 follow_up_message
    # (null/空串) · BRO 只能手动戳。 从 session 历史自动摘最后一条 user 消息续场。
    if not follow_up and sid:
        try:
            from daemon_session import load_session
            msgs = load_session(sid) or []
            for m in reversed(msgs):
                if m.get("role") == "user" and m.get("content") and m["content"].strip():
                    last_user = m["content"].strip()
                    follow_up = f"(自动续场) BRO 上次说: {last_user[:120]}"
                    break
        except Exception:
            pass
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
            # 墨言 094-2 · 续场结果按最新活跃通道推送 (飞书/微信) · WebUI 不推 (用户看着)
            try:
                _push_background_reply(result.get("reply") or "")
            except Exception as e:
                print(f"[opus-resume] 续场推送异常: {type(e).__name__}: {e}", flush=True)
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


def _feishu_push_background_reply(session_id: str, reply: str) -> None:
    """重启续场的 background turn 回复 → 若会话是飞书 → 推给用户 (墨言 094 wish-db293e5f 移植)。

    背景: 重启续场 turn 无 SSE 接收方 · 回复只落 session jsonl · WebUI 用户翻历史能看到 ·
    但飞书用户看不到 (飞书侧没渠道)。 这里把 reply 直接 send_text 推过去。
    只处理 api-feishu-* session · 其他 session 不推 (避免 WebUI 重复)。
    """
    if not session_id or not session_id.startswith("api-feishu-"):
        return
    if not reply or not reply.strip():
        return
    # api-feishu-user_ou_xxx-sN → open_id = ou_xxx
    open_id = ""
    try:
        # 去掉前缀后取 user_ou_ 段: "user_ou_abc-def-s26" → user_seg="user_ou_abc-def"
        # 用 "-s" 后截断避免 open_id 内含 "-" 时 split 拆碎
        body = session_id.removeprefix("api-feishu-")
        cut = body.rfind("-s")
        if cut > 0:
            body = body[:cut]
        if body.startswith("user_ou_"):
            open_id = body.replace("user_", "", 1)
        else:
            # 兼容直接带 ou_ 段的旧格式
            for seg in session_id.split("-"):
                if seg.startswith("ou_"):
                    open_id = seg
                    break
    except Exception:
        pass
    if not open_id:
        print(f"[opus-resume] 飞书后台回复推送: session 解析不出 open_id · session={session_id}", flush=True)
        return
    try:
        from workers import feishu_client
        r = feishu_client.send_text(reply[:1500], open_id, "open_id")
        print(f"[opus-resume] 飞书后台回复已推送 · ok={r.get('ok')} · msg={str(r.get('msg', ''))[:60]}", flush=True)
    except Exception as e:
        print(f"[opus-resume] 飞书后台回复推送失败: {type(e).__name__}: {e}", flush=True)


def _resolve_latest_push_channel() -> Optional[tuple[str, str]]:
    """扫全部 sessions 找 mtime 最新活跃会话 → 判定推送通道 (墨言 094-2 wish-a65228cd)。

    返回 (channel, sid) 或 None:
      - 最新是 api-feishu-* → ("feishu", sid)
      - 最新是 api-wechat    → ("wechat", sid)
      - 最新是其它 api-* (WebUI/API) → None (用户正在 WebUI 看着 · 不推)
    只判定最新一个 · 不继续找 (ever 08-14 拍板)。
    """
    try:
        from workers.daemon_lifecycle import SESSIONS_DIR
        files = [p for p in SESSIONS_DIR.glob("*.jsonl") if p.is_file()]
        if not files:
            return None
        latest = max(files, key=lambda p: p.stat().st_mtime)
        sid = latest.stem
        if sid.startswith("api-feishu-") and "-user_" in sid:
            return ("feishu", sid)
        if sid == "api-wechat":
            return ("wechat", sid)
        return None  # 最新是 WebUI/API 或其它 → 不推
    except Exception as e:
        print(f"[opus-resume] 通道解析异常: {type(e).__name__}: {e}", flush=True)
        return None


def _push_background_reply(reply: str) -> None:
    """续场验证回复 → 按最新活跃通道推送 (墨言 094-2 wish-a65228cd)。

    最新活跃会话是飞书 → 推飞书；是微信 → 推微信；是 WebUI/API → 不推。
    """
    if not reply or not reply.strip():
        return
    ch = _resolve_latest_push_channel()
    if not ch:
        print("[opus-resume] 续场推送跳过 · 最新活跃会话不是飞书/微信 (WebUI/API 不推)", flush=True)
        return
    channel, sid = ch
    if channel == "feishu":
        _feishu_push_background_reply(sid, reply)
    elif channel == "wechat":
        try:
            from workers import ilink_client
            if not ilink_client.enabled() or not ilink_client.window_open():
                print("[opus-resume] 微信续场推送跳过 · 未扫码或 24h 窗口关", flush=True)
                return
            r = ilink_client.send_text(reply[:1500])
            print(f"[opus-resume] 微信后台回复已推送 · ok={r.get('ok')} · ret={r.get('ret')}", flush=True)
        except Exception as e:
            print(f"[opus-resume] 微信后台回复推送失败: {type(e).__name__}: {e}", flush=True)


def schedule_auto_boot_verify() -> bool:
    """墨言 094 wish-db293e5f · 手动/外部重启自动续场。

    无 restart_request 的重启（手动 / WebUI 按钮 / start.bat）后调用:
    对最近 30min 活跃的 api-feishu-* session 自动跑一个轻量验证 turn + 推回飞书。

    触发条件 (全部满足):
      - env OPUS_AUTO_RESUME_ON_BOOT != "0" (默认开)
      - 有最近 30min 活跃的飞书 session (说明用户最近在用飞书)
      - 该 session 没有未完成的 background turn (scheduled/running → skip)

    返 True = 已 schedule · False = 没触发
    """
    if (os.environ.get("OPUS_AUTO_RESUME_ON_BOOT") or "1").strip() == "0":
        return False
    try:
        from workers.daemon_lifecycle import _classify_active_sessions
        recent = _classify_active_sessions(window_min=30)
    except Exception:
        recent = []
    feishu = [p for p in recent if p.stem.startswith("api-feishu-") and "-user_" in p.stem]
    if not feishu:
        return False
    # 取最新活跃的飞书 session
    try:
        sid = max(feishu, key=lambda p: p.stat().st_mtime).stem
    except Exception:
        return False

    with _bg_status_lock:
        st = _bg_turn_status.get(sid, "none")
        if st in ("scheduled", "running"):
            return False
        _bg_turn_status[sid] = "scheduled"

    follow_up = (
        "[SYSTEM · 自动续场 · 无重启请求]\n"
        "daemon 刚刚重启（非 request_restart 路径，可能是手动重启 / 启动脚本）。\n"
        "请做一个轻量验证：1) 确认 daemon 端点正常（本机 curl 或读文件任选其一）；"
        "2) 瞄一眼 data/daemon.out 末尾有没有明显报错。\n"
        "然后用一两句话告诉用户『重启完成 · 状态正常（或异常点）』。"
        "不要跑长任务 / 不要深度调研。"
    )

    def _runner():
        print(f"[opus-resume] 自动续场 thread 启动 · session={sid} · 等 RUNTIME ready", flush=True)
        if not _wait_runtime_ready():
            print(f"[opus-resume] RUNTIME 等了 {_MAX_WAIT_RUNTIME_SEC}s 没就绪 · 自动续场放弃", flush=True)
            with _bg_status_lock:
                _bg_turn_status[sid] = "failed"
            return
        with _bg_status_lock:
            _bg_turn_status[sid] = "running"
        try:
            print(f"[opus-resume] 启动自动续场 turn · session={sid}", flush=True)
            result = _run_background_turn(follow_up, sid)
            reply_preview = (result.get("reply") or "")[:200].replace("\n", " ")
            print(f"[opus-resume] 自动续场 turn 完成 · reply='{reply_preview}...'", flush=True)
            _feishu_push_background_reply(sid, result.get("reply") or "")
            with _bg_status_lock:
                _bg_turn_status[sid] = "completed"
        except Exception as e:
            import traceback
            print(f"[opus-resume] 自动续场 turn 失败: {type(e).__name__}: {e}", flush=True)
            print(f"[opus-resume] traceback:\n{traceback.format_exc()}", flush=True)
            with _bg_status_lock:
                _bg_turn_status[sid] = "failed"

    t = threading.Thread(target=_runner, daemon=True, name="opus-auto-boot-verify")
    t.start()
    return True


def maybe_schedule_resume(lc: Optional[dict]) -> bool:
    """启动路径统一续场调度入口 (对齐 daemon_api + run_api_only 双入口 · 防漂移)。

    有 restart_request → schedule_resume_turn (follow_up 续场)
    无 restart_request + ok + 非 safe_mode → schedule_auto_boot_verify (手动重启兜底 · wish-db293e5f)

    修复: daemon_api 入口缺 auto_boot_verify 兜底 (不对称) · 从 opus_daemon.py 启动时
    手动/按钮重启后无自动续场。 两入口统一走这里 · 后续行为变化只改一处。

    防御语义: lc.ok=False 时直接 False —— 实际不可达 (init_lifecycle 只有 pid lock
    失败才 ok=False · 两个调用方此时都立即终止 sys.exit/raise) · 前置防御纯保险。
    """
    if not lc or not lc.get("ok"):
        return False
    if lc.get("restart_request"):
        try:
            return schedule_resume_turn(lc["restart_request"])
        except Exception as e:
            print(f"[opus-resume] schedule_resume_turn 异常: {type(e).__name__}: {e}", flush=True)
            return False
    try:
        return schedule_auto_boot_verify()
    except Exception as e:
        print(f"[opus-resume] schedule_auto_boot_verify 异常: {type(e).__name__}: {e}", flush=True)
        return False
