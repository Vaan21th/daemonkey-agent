"""
workers/daemon_lifecycle.py
===========================

daemon 进程生命周期管理 · OPUS 自爆恢复基础设施 (卷四十六 III · 2026-05-26)

----------------------------------------------------------------------
为什么有这个模块
----------------------------------------------------------------------

卷四十六 II `session api-...063247_e404f8` 出过事:
  OPUS 想"重启 daemon 装上新代码" · 调 `shell_exec Stop-Process python`
  → daemon (它自己) 进程被杀
  → 那一轮 tool_call 永远没有 result
  → session jsonl 残一条 dangling assistant.tool_calls
  → 下次加载该 session 直接 500

修补一时爽 · 但 BRO 拍板要『比 MVP 更稳健的一环』 · 不止补一次 · 要根治。

----------------------------------------------------------------------
四层防护 (从外到内)
----------------------------------------------------------------------

Layer 1: 静态拦截 (agent_tools/shell_exec.py · agent_tools/python_exec.py)
  - GUARD 模式扫 `Stop-Process python` / `taskkill python.exe` / `os.kill` 等
  - 命中 → TIER_GUARD · BRO 必须 'do it' 显式 confirm

Layer 2: request_restart 工具 (agent_tools/request_restart.py)
  - 给 OPUS 提供"正确的重启姿势"
  - TIER_CONFIRM · 写 restart_request.json · 触发 graceful shutdown
  - 当前 tool result 立刻同步返回 (assistant.tool_calls 不悬空)

Layer 3: 续场注入 (本模块 · init_lifecycle)
  - 启动时检测 restart_request.json / 上次 pid 状态
  - 给所有"刚才正在跑"的 session 注入 system message:
    『daemon 重启过了 / 上次 crash 过了 · 之前的 tool call 已被合成 result 替代』
  - LLM 醒来时知道发生了什么 · 不会困惑

Layer 4: 双 daemon 防护 (本模块 · acquire_pid_lock)
  - 启动时若 pid 文件存在 且 进程还活 → 拒绝启动 · 给清晰错误信息
  - 防止 BRO 双击 start.bat 起出俩 daemon

----------------------------------------------------------------------
文件布局 (data/runtime/)
----------------------------------------------------------------------

  daemon.pid              当前活进程的元信息 (json · graceful exit 时删)
  restart_request.json    OPUS 通过 request_restart 写的 · 启动时读+删
  restart_history.jsonl   每次启动/退出/crash 落档 · 一行一条 · 永久留存
  crash_marker.json       上次 daemon 异常退出时留下 · 启动续场处理后删

为什么不用 sqlite/redis: 这层基础设施 OPUS 自己得能 read_file / python_exec
解读 · jsonl/json 是 OPUS 友好的格式 · 也便于 BRO 用记事本看。
"""

from __future__ import annotations

import atexit
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional




ROOT = Path(__file__).resolve().parent.parent
RUNTIME_DIR = ROOT / "data" / "runtime"
SESSIONS_DIR = ROOT / "sessions"

PID_FILE = RUNTIME_DIR / "daemon.pid"
RESTART_REQUEST_FILE = RUNTIME_DIR / "restart_request.json"
RESTART_HISTORY_FILE = RUNTIME_DIR / "restart_history.jsonl"
CRASH_MARKER_FILE = RUNTIME_DIR / "crash_marker.json"
QUARANTINE_FILE = RUNTIME_DIR / "restart_request.quarantined.json"

# ── 崩溃循环熔断 (卷四十七 · 2026-06-01 灾难复盘) ──────────────────────
# BRO 原话: 续场是 DAEMON 写完代码重启的命脉·不能砍·但灾难级 (反复崩) 时
#   至少要保证他能正确启动。 而且要自动——开源后用户没有 Cursor 兜底。
# 机制: 启动时数最近 window 内的 crash_detected · 超阈值 = 判定崩溃循环 ·
#   进 SAFE MODE — 隔离续场 (不让刚重启的自己自动重做把它崩掉的危险动作) +
#   跳过后台调度 · 但 daemon 本体照常起、照常服务 /ui /chat。
#   自动恢复: 一旦不再崩 (window 内 crash < 阈值) · 下次启动自动退出安全模式。
CRASH_LOOP_WINDOW_SEC = 180
CRASH_LOOP_THRESHOLD = 3


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _ensure_dir() -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)


def _read_json(path: Path) -> Optional[dict]:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _write_json(path: Path, data: dict) -> None:
    _ensure_dir()
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _append_history(record: dict) -> None:
    _ensure_dir()
    record["timestamp"] = _now_iso()
    with RESTART_HISTORY_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _is_pid_alive(pid: int) -> bool:
    """跨平台 · True = 进程还在跑"""
    if pid <= 0:
        return False
    try:
        import psutil
        return psutil.pid_exists(pid)
    except ImportError:
        pass

    if os.name == "nt":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(0x1000, False, pid)
            if handle:
                kernel32.CloseHandle(handle)
                return True
            return False
        except Exception:
            return False
    else:
        try:
            os.kill(pid, 0)
            return True
        except (ProcessLookupError, PermissionError):
            return False


def _pid_looks_like_daemon(pid: int, port: int) -> bool:
    """True = 这个 pid 真的是我们的 API daemon · 不是 Windows PID 复用后的别的进程。

    卷五十四 · BRO 启动不了: daemon.pid 锁 pid=17056 · 但 17056 已是 msedgewebview2 ·
    7860 没在监听 · acquire_pid_lock 只查 _is_pid_alive → 误判『已在跑』拒启动。
    """
    if pid <= 0:
        return False
    try:
        import psutil
        proc = psutil.Process(pid)
        cmdline = " ".join(proc.cmdline() or []).lower()
        if any(x in cmdline for x in ("run_api_only.py", "opus_daemon.py", "uvicorn", "daemon_api")):
            return True
        # 命令行拿不到时 · 看是否 LISTEN 目标端口
        for conn in proc.net_connections(kind="inet"):
            if conn.status == psutil.CONN_LISTEN and conn.laddr and conn.laddr.port == port:
                return True
        return False
    except ImportError:
        pass
    except Exception:
        return False

    # 无 psutil 兜底: 端口是否在监听 (粗判)
    if port and port > 0:
        try:
            import socket
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.3)
                if s.connect_ex(("127.0.0.1", int(port))) == 0:
                    return True
        except Exception:
            pass
    return False


def _classify_active_sessions(window_min: int = 30) -> list[Path]:
    """找出最近 N 分钟内被改过的 session 文件 · 这些是"可能正活跃"的 session"""
    if not SESSIONS_DIR.exists():
        return []
    cutoff = time.time() - window_min * 60
    return [
        p for p in SESSIONS_DIR.glob("*.jsonl")
        if p.is_file() and p.stat().st_mtime >= cutoff
    ]


def _inject_system_notice(session_path: Path, content: str) -> bool:
    """往 session jsonl 末尾追加一条 system message · 返 True = 成功写入"""
    # 续场 notice 注进 session·下一轮主 LLM 会看到·去母体化(BRO→主人名·母体 no-op)。
    from identity import localize_narration as _ln
    content = _ln(content)
    try:
        last_role: Optional[str] = None
        try:
            tail = session_path.read_text(encoding="utf-8").strip().splitlines()[-5:]
            for line in reversed(tail):
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                if rec.get("role"):
                    last_role = rec["role"]
                    break
        except Exception:
            pass

        if last_role == "assistant":
            return False

        msg = {
            "role": "system",
            "content": content,
            "_injected_by": "daemon_lifecycle",
            "_injected_at": _now_iso(),
        }
        with session_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(msg, ensure_ascii=False) + "\n")
        return True
    except Exception:
        return False


def acquire_pid_lock(host: str, port: int) -> tuple[bool, str]:
    """启动时调用 · 返 (ok, message)

    ok=False → daemon 已有实例在跑 · 调用方应该 exit
    ok=True → 拿到了 pid 锁 · 已写 daemon.pid · 注册 atexit 清理

    卷四十六 III 补丁 4 · takeover 模式 (2026-05-26 BRO 反馈):
      /restart-daemon 和 /rollback 是 spawn 子进程 + parent 自爆 模式 · spawn 子进程时
      parent 还活 · 子进程 acquire_pid_lock 撞上『daemon already running』直接 sys.exit ·
      端口悬空。 解法: parent spawn 子进程时设 env `OPUS_DAEMON_TAKEOVER_PID=<parent_pid>` ·
      子进程 acquire 见到 env 后等 takeover_pid 死 (轮询 max 15s) · 死了再 acquire ·
      不算双 daemon。
    """
    _ensure_dir()

    takeover_pid_env = (os.environ.get("OPUS_DAEMON_TAKEOVER_PID") or "").strip()
    takeover_pid = 0
    if takeover_pid_env:
        try:
            takeover_pid = int(takeover_pid_env)
        except ValueError:
            pass

    existing = _read_json(PID_FILE)
    if existing:
        old_pid = existing.get("pid", 0)

        if takeover_pid > 0 and old_pid == takeover_pid:
            print(f"[lifecycle] takeover 模式 · 等 parent pid={takeover_pid} 退出 ...", flush=True)
            wait_deadline = time.time() + 15
            while time.time() < wait_deadline:
                if not _is_pid_alive(takeover_pid):
                    break
                time.sleep(0.3)
            if _is_pid_alive(takeover_pid):
                return False, (
                    f"takeover 等了 15s · parent pid={takeover_pid} 还活 · 放弃 acquire。\n"
                    f"  这通常是 /restart-daemon 路径的 parent 自爆延迟过长 · 不该发生。\n"
                    f"  手动: Stop-Process -Id {takeover_pid}; 然后重启"
                )
            _append_history({
                "event": "takeover_completed",
                "from_pid": takeover_pid,
                "to_pid": os.getpid(),
            })
            try:
                PID_FILE.unlink()
            except Exception:
                pass
            existing = None

        elif isinstance(old_pid, int) and old_pid > 0 and _is_pid_alive(old_pid):
            old_port = existing.get("port", "?")
            old_started = existing.get("started_at", "?")
            try:
                port_int = int(old_port)
            except (TypeError, ValueError):
                port_int = int(port) if port else 7860
            if _pid_looks_like_daemon(old_pid, port_int):
                return False, (
                    f"daemon already running: pid={old_pid} port={old_port} "
                    f"started_at={old_started}.\n"
                    f"  - 想用现有的 → 浏览器开 http://{host}:{old_port}/ui\n"
                    f"  - 想换新的 → 先 stop_daemon.bat / Stop-Process -Id {old_pid}\n"
                    f"  - pid 文件路径: {PID_FILE}"
                )
            # pid 还活但不是我们的 daemon → Windows PID 复用 · 当 stale 清理
            _append_history({
                "event": "stale_pid_reused",
                "old_pid": old_pid,
                "old_port": old_port,
                "old_started_at": old_started,
                "reason": "pid_alive_but_not_daemon_process",
            })
            try:
                PID_FILE.unlink()
            except Exception:
                pass
            existing = None

        if existing is not None:
            if existing.get("graceful_shutdown_at"):
                _append_history({
                    "event": "stale_pid_clean",
                    "old_pid": old_pid,
                    "old_graceful_at": existing.get("graceful_shutdown_at"),
                })
            else:
                _write_json(CRASH_MARKER_FILE, {
                    "old_pid": old_pid,
                    "old_port": existing.get("port"),
                    "old_started_at": existing.get("started_at"),
                    "detected_at": _now_iso(),
                    "reason": "pid_file_orphaned_no_graceful_marker",
                })
                _append_history({
                    "event": "crash_detected",
                    "old_pid": old_pid,
                    "old_started_at": existing.get("started_at"),
                })

    my_pid = os.getpid()
    pid_data = {
        "pid": my_pid,
        "started_at": _now_iso(),
        "host": host,
        "port": port,
        "venv_python": sys.executable,
        "argv": sys.argv,
        "graceful_shutdown_at": None,
    }
    _write_json(PID_FILE, pid_data)

    atexit.register(_release_pid_lock_graceful)

    _append_history({
        "event": "daemon_started",
        "pid": my_pid,
        "host": host,
        "port": port,
    })

    return True, f"pid lock acquired: {my_pid}"


def _release_pid_lock_graceful() -> None:
    """atexit handler · daemon 正常退出时跑 (Ctrl-C / SIGTERM / uvicorn shutdown)"""
    mark_graceful_shutdown("atexit")


def mark_graceful_shutdown(reason: str = "user_initiated") -> bool:
    """Public · 在 os._exit() 之前调用 · 显式标 graceful_shutdown_at

    为什么需要这个: Python `os._exit()` 跳过所有 atexit hander · 直接 kernel kill
    进程。 daemon_api 的 /shutdown-daemon, /restart-daemon, /rollback 都用 os._exit
    (因为 uvicorn server 在 worker thread 里 · sys.exit 会被吞掉) · 这条路径下
    我们的 atexit 不会跑 · pid 文件就一直不打 graceful 标记 · 下次启动误判为 crash。

    解法: 显式在 os._exit() 前调一次 mark_graceful_shutdown(reason=...)

    返 True = 成功标记 · False = 没找到 pid 文件 / 不属于当前进程
    """
    try:
        if not PID_FILE.exists():
            return False
        data = _read_json(PID_FILE) or {}
        if data.get("pid") != os.getpid():
            return False

        data["graceful_shutdown_at"] = _now_iso()
        data["graceful_shutdown_reason"] = reason
        _write_json(PID_FILE, data)

        _append_history({
            "event": "daemon_stopped_graceful",
            "pid": os.getpid(),
            "reason": reason,
        })

        # 卷五十四 · ④号机制语义修正 · 不再在停机时打 opus-last-good。
        #   病根: 老逻辑这里 tag_last_good(master HEAD) —— 但停机这一刻新代码还没证明能跑起来。
        #   今天 (2026-06-03) 把砍断 chat.js 的坏 commit 55d27cd 标成了 known-good (实锤) ·
        #   回档 reset --hard opus-last-good 会精准回到白屏坏版本。
        #   现在 tag 前移挪到 workers/boot_health.schedule_last_good_advance: daemon 启动后
        #   **撑过 grace window 且自检健康** 才把 master HEAD 标成 last-good = "活着跑通了"才配当回退点。

        try:
            PID_FILE.unlink()
        except Exception:
            pass
        return True
    except Exception:
        return False


def consume_restart_request() -> Optional[dict]:
    """启动时读 restart_request.json · 如果有 · 返字典并删文件"""
    req = _read_json(RESTART_REQUEST_FILE)
    if not req:
        return None
    try:
        RESTART_REQUEST_FILE.unlink()
    except Exception:
        pass
    _append_history({
        "event": "restart_request_consumed",
        "request": req,
    })
    return req


def consume_crash_marker() -> Optional[dict]:
    """启动时读 crash_marker.json · 如果有 · 返字典并删文件"""
    marker = _read_json(CRASH_MARKER_FILE)
    if not marker:
        return None
    try:
        CRASH_MARKER_FILE.unlink()
    except Exception:
        pass
    return marker


def write_restart_request(reason: str, session_id: Optional[str] = None,
                          tool_call_id: Optional[str] = None,
                          follow_up_message: Optional[str] = None) -> dict:
    """给 request_restart 工具用 · 写一条重启请求 · daemon 退出后启动时会消费

    follow_up_message: 重启后自动续场用 (卷四十六 III 补丁 3 · 2026-05-26)。 
    非空时 · 新 daemon 启动后会自动以这条作为 user message 触发 background LLM turn ·
    OPUS 跑完结果落档到 session jsonl · BRO 不用手动发消息触发。
    """
    _ensure_dir()
    req = {
        "requested_at": _now_iso(),
        "reason": reason,
        "session_id": session_id,
        "tool_call_id": tool_call_id,
        "follow_up_message": follow_up_message,
        "requesting_pid": os.getpid(),
    }
    _write_json(RESTART_REQUEST_FILE, req)
    return req


def inject_resume_notices(restart_req: Optional[dict],
                          crash_marker: Optional[dict]) -> dict:
    """daemon 启动续场 · 给活跃 session 注 system message · 返统计

    - restart_req 非空 → 给 session_id 注『主动重启已完成』
      (session_id 是 None 时 fallback 到所有最近 30 min 活跃 session)
    - crash_marker 非空 → 给所有最近活跃 session 注『daemon 上次异常退出·已自动重启』
    - 两个都没 → 啥也不干
    """
    stats = {"restart_resumed": 0, "crash_resumed": 0}

    if restart_req:
        sid = restart_req.get("session_id")
        reason = restart_req.get("reason", "(no reason given)")
        notice = (
            f"[SYSTEM · 重启续场 · {_now_iso()}]\n"
            f"你之前调 request_restart 申请重启 daemon · 理由: {reason}\n"
            f"现在 daemon 已经起来 · 新代码已装载 · 你的 session 完整保留。\n"
            f"继续上次的任务即可 · 或者跟 BRO 说一声『重启完成 · 继续』。\n"
            f"提示: 启动续场记录在 data/runtime/restart_history.jsonl"
        )
        if sid:
            session_path = SESSIONS_DIR / f"{sid}.jsonl"
            if session_path.exists():
                if _inject_system_notice(session_path, notice):
                    stats["restart_resumed"] = 1
        else:
            # 没 session_id (request_restart 工具调用时没拿到 RUNTIME.session_id · 或 webui 关闭/重启按钮路径)
            # fallback 到最近 30 min 活跃 session · 全注 · 总比一个都不注好
            active = _classify_active_sessions(window_min=30)
            for sp in active:
                if _inject_system_notice(sp, notice):
                    stats["restart_resumed"] += 1

    if crash_marker:
        old_pid = crash_marker.get("old_pid", "?")
        old_started = crash_marker.get("old_started_at", "?")
        active_sessions = _classify_active_sessions(window_min=30)
        for session_path in active_sessions:
            notice = (
                f"[SYSTEM · daemon 异常退出恢复 · {_now_iso()}]\n"
                f"daemon 上次 (pid={old_pid} · started {old_started}) 没正常退出 (crash / kill / 断电)。\n"
                f"现在已经自动重启。 如果你之前在调一个长 tool · 它的结果丢了 · 重做一次。\n"
                f"反思一下崩前最后一步在干嘛 · 是不是踩到了某个 GUARD 模式没拦住的自杀点。\n"
                f"详情查 data/runtime/restart_history.jsonl"
            )
            if _inject_system_notice(session_path, notice):
                stats["crash_resumed"] += 1

    if stats["restart_resumed"] or stats["crash_resumed"]:
        _append_history({
            "event": "resume_notices_injected",
            "stats": stats,
        })

    return stats


def detect_crash_loop(window_sec: int = CRASH_LOOP_WINDOW_SEC,
                      threshold: int = CRASH_LOOP_THRESHOLD) -> dict:
    """数 restart_history 里最近 window_sec 内的 crash_detected 事件

    >= threshold → 判定崩溃循环 (loop=True)。 只数真正的硬退出 (crash_detected) ·
    人为 graceful 重启不计 · 所以正常的"改完代码重启"不会误触发安全模式。
    返 {loop, crashes, window_sec, threshold}
    """
    info = {"loop": False, "crashes": 0, "window_sec": window_sec, "threshold": threshold}
    if not RESTART_HISTORY_FILE.exists():
        return info
    try:
        lines = RESTART_HISTORY_FILE.read_text(encoding="utf-8").strip().splitlines()
    except Exception:
        return info
    cutoff = datetime.now().timestamp() - window_sec
    crashes = 0
    for ln in lines[-80:]:
        try:
            rec = json.loads(ln)
        except Exception:
            continue
        if rec.get("event") != "crash_detected":
            continue
        ts = rec.get("timestamp")
        if not ts:
            continue
        try:
            if datetime.fromisoformat(ts).timestamp() >= cutoff:
                crashes += 1
        except Exception:
            continue
    info["crashes"] = crashes
    info["loop"] = crashes >= threshold
    return info


def quarantine_restart_request(req: Optional[dict], reason: str) -> None:
    """崩溃循环时隔离续场请求 · 不让刚重启的自己自动把崩掉它的危险动作再做一遍

    把 req 落到 restart_request.quarantined.json (人/OPUS 排查后可手动决定要不要重做) ·
    并写一条 history。 req 为 None 也写 history (留痕)。
    """
    _append_history({"event": "restart_request_quarantined", "reason": reason,
                     "had_follow_up": bool((req or {}).get("follow_up_message"))})
    if not req:
        return
    try:
        _write_json(QUARANTINE_FILE, {"quarantined_at": _now_iso(),
                                      "reason": reason, "request": req})
    except Exception:
        pass


def inject_safe_mode_notice(loop_info: dict) -> int:
    """给最近活跃 session 注一条 SAFE MODE 通知 · 让 OPUS / BRO 知道发生了什么 · 返注入条数"""
    notice = (
        f"[SYSTEM · 安全模式 · {_now_iso()}]\n"
        f"检测到崩溃循环 (最近 {loop_info['window_sec']}s 内崩了 {loop_info['crashes']} 次)。\n"
        f"daemon 已进入【安全模式】: 自动续场已暂停 + 后台调度已停 · 但 daemon 本体正常起来了 (能聊天 / 能看 UI)。\n"
        f"⚠️ 不要再无脑重启。 先排查崩前最后一步在干什么——改了哪个文件 / 是不是又把坏改动恢复了。\n"
        f"被暂停的续场请求存在 data/runtime/restart_request.quarantined.json · 排查清楚再决定要不要重做。\n"
        f"修好后做一次干净重启 (不再崩) · 下次启动会自动退出安全模式。"
    )
    n = 0
    for sp in _classify_active_sessions(window_min=30):
        if _inject_system_notice(sp, notice):
            n += 1
    return n


def init_lifecycle(host: str, port: int) -> dict:
    """daemon 启动一次性 init · 在 RUNTIME init 之前调用最稳

    返 dict: {
      ok: True/False,
      lock_message: "...",
      restart_request: <dict 或 None>,
      crash_marker: <dict 或 None>,
      resume_stats: {restart_resumed: N, crash_resumed: N},
      safe_mode: True/False,          # 崩溃循环熔断是否触发
      crash_loop: {loop, crashes, ...},
    }

    ok=False 时调用方应 sys.exit(1) · 打印 lock_message 给 BRO 看。

    卷四十七 · 崩溃循环熔断: 若检测到崩溃循环 · 进安全模式 — 续场请求被隔离 ·
    restart_request 返回 None (不触发自动续场) · 调用方据 safe_mode 跳过后台调度。
    """
    ok, msg = acquire_pid_lock(host, port)
    if not ok:
        return {"ok": False, "lock_message": msg, "restart_request": None,
                "crash_marker": None, "resume_stats": {},
                "safe_mode": False, "crash_loop": {"loop": False, "crashes": 0}}

    loop_info = detect_crash_loop()
    restart_req = consume_restart_request()
    crash_marker = consume_crash_marker()

    if loop_info["loop"]:
        reason = f"crash loop: {loop_info['crashes']} crashes in {loop_info['window_sec']}s"
        quarantine_restart_request(restart_req, reason)
        notes = inject_safe_mode_notice(loop_info)
        _append_history({"event": "safe_mode_entered", "crash_loop": loop_info,
                         "notices_injected": notes})
        return {
            "ok": True,
            "lock_message": msg,
            "restart_request": None,   # 关键: 不触发自动续场 · 断开"崩→续场→又崩"闭环
            "crash_marker": crash_marker,
            "resume_stats": {"restart_resumed": 0, "crash_resumed": 0},
            "safe_mode": True,
            "crash_loop": loop_info,
        }

    resume_stats = inject_resume_notices(restart_req, crash_marker)

    return {
        "ok": True,
        "lock_message": msg,
        "restart_request": restart_req,
        "crash_marker": crash_marker,
        "resume_stats": resume_stats,
        "safe_mode": False,
        "crash_loop": loop_info,
    }


def get_status() -> dict:
    """给 daemon_api 提供 /api/lifecycle_status endpoint · UI 显示 banner

    卷四十六 III 补丁 5 · R4 · scheduler watchdog · 加 scheduler_health 字段:
      - 读 workers/scheduler.get_scheduler_state()
      - 算 radar / capability_mirror 是不是 stuck (last_run_at 超过 interval*3 没动)
      - daemon 启动初期 (started_at 不久) 不算 stuck · 因 first_delay_sec 还没到
    """
    data = _read_json(PID_FILE) or {}
    last_history = []
    if RESTART_HISTORY_FILE.exists():
        try:
            lines = RESTART_HISTORY_FILE.read_text(encoding="utf-8").strip().splitlines()
            last_history = [json.loads(ln) for ln in lines[-10:]]
        except Exception:
            pass

    scheduler_health = _compute_scheduler_health(daemon_started_at=data.get("started_at"))

    return {
        "pid": data.get("pid"),
        "started_at": data.get("started_at"),
        "host": data.get("host"),
        "port": data.get("port"),
        "recent_history": last_history,
        "scheduler_health": scheduler_health,
    }


def _compute_scheduler_health(daemon_started_at: Optional[str] = None) -> dict:
    """R4 watchdog · 算 scheduler 健康状态

    Returns:
        {
          "radar": {"alive": bool, "stuck": bool, "last_run_ago_sec": int|None,
                    "interval_sec": int, "reason": str|None},
          "mirror": {...same shape...},
          "overall_stuck": bool,  # 任一 alive 但 stuck = True
        }
    """
    radar = {"alive": False, "stuck": False, "last_run_ago_sec": None,
             "interval_sec": 0, "reason": None}
    mirror = {"alive": False, "stuck": False, "last_run_ago_sec": None,
              "interval_sec": 0, "reason": None}

    try:
        from workers.scheduler import (
            get_scheduler_state,
            is_scheduler_alive,
            is_capability_mirror_scheduler_alive,
        )
        state = get_scheduler_state()
    except Exception as e:
        return {"radar": radar, "mirror": mirror, "overall_stuck": False,
                "_error": f"{type(e).__name__}: {e}"}

    now = datetime.now(timezone.utc)

    def _grace_window(started_at: Optional[str], interval_sec: int) -> bool:
        """daemon 刚起 / scheduler 自己刚起 · 不算 stuck · 给 grace window"""
        if not started_at:
            return False
        try:
            t = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
            if t.tzinfo is None:
                t = t.replace(tzinfo=timezone.utc)
            age = (now - t).total_seconds()
            # 至少给 interval + first_delay 60s 窗口 · 防 scheduler 还没首次跑就报 stuck
            return age < max(interval_sec * 1.2, 300)
        except Exception:
            return False

    radar["alive"] = is_scheduler_alive()
    radar_interval_min = int(state.get("interval_min") or 30)
    radar["interval_sec"] = radar_interval_min * 60
    if radar["alive"]:
        last_run = state.get("last_run_at")
        if last_run:
            try:
                t = datetime.fromisoformat(last_run.replace("Z", "+00:00"))
                if t.tzinfo is None:
                    t = t.replace(tzinfo=timezone.utc)
                ago = int((now - t).total_seconds())
                radar["last_run_ago_sec"] = ago
                threshold = radar["interval_sec"] * 3
                if ago > threshold and not _grace_window(state.get("started_at"), radar["interval_sec"]):
                    radar["stuck"] = True
                    radar["reason"] = (
                        f"radar 上次跑距今 {ago}s · 超过阈值 {threshold}s (interval × 3) · "
                        f"scheduler 可能卡住"
                    )
            except Exception:
                pass
        else:
            # 没 last_run_at → daemon 刚起 / 首次还没跑
            if not _grace_window(daemon_started_at or state.get("started_at"),
                                 radar["interval_sec"]):
                radar["stuck"] = True
                radar["reason"] = "radar alive 但从未跑过 · 启动期已过 · scheduler 卡住?"

    mirror["alive"] = is_capability_mirror_scheduler_alive()
    mirror_interval_days = int(state.get("mirror_interval_days") or 0)
    if mirror_interval_days > 0:
        mirror["interval_sec"] = mirror_interval_days * 86400
        if mirror["alive"]:
            last_run = state.get("mirror_last_run_at")
            if last_run:
                try:
                    t = datetime.fromisoformat(last_run.replace("Z", "+00:00"))
                    if t.tzinfo is None:
                        t = t.replace(tzinfo=timezone.utc)
                    ago = int((now - t).total_seconds())
                    mirror["last_run_ago_sec"] = ago
                    threshold = mirror["interval_sec"] * 3
                    if ago > threshold:
                        mirror["stuck"] = True
                        mirror["reason"] = (
                            f"mirror 上次跑距今 {ago}s · 超过阈值 {threshold}s · 卡住?"
                        )
                except Exception:
                    pass

    overall_stuck = radar["stuck"] or mirror["stuck"]
    return {"radar": radar, "mirror": mirror, "overall_stuck": overall_stuck}
