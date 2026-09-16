# -*- coding: utf-8 -*-
"""workers/wakeups.py · 会话内延迟唤醒（计时器）· wish-1b00ca00

OPUS 调 set_wakeup(delay_sec, label, reason) → 落 data/runtime/wakeups.json
→ 本模块 1s tick 线程扫描 → 到点经 proactive_call._run_bg_turn 在【原会话】注入一轮
→ 前端输入栏上方倒计时卡（GET /api/wakeups）可见、可取消（POST /api/wakeups/cancel）。

跟 scheduled_tasks（定时任务）的分工:
  - 定时任务 = 天/周级日程 · 长期反复 · 住在管理列表
  - 唤醒计时器 = 一次性分钟级 · 跑完即销 · 住在对话栏
  两者【刻意分表】—— 混一张表会让日程页被一次性计时器淹没。

红线 (跟 task_scheduler 同范式):
  - daemon thread · 随主进程退出 · 不留孤儿
  - catch-all 不崩 · 单条唤醒失败不影响其他条目和主循环
  - 只写 data/runtime/wakeups.json · 不动系统 cron / schtasks / 注册表
  - 读写用 threading 锁保护 · 字段更新走局部落盘(防旧快照覆盖)
  - 到点的 LLM turn 复用 _run_bg_turn —— 它内部已含铁律6三件套
    (register_turn 登记 / cancel_event 透传可停 / finally unregister)

时区约定 (重要 · 别改):
  fire_at / created_at 存【本地 naive ISO】(datetime.now().isoformat(timespec="seconds"))·
  与 daemon_session.append_turn 写的 ts 同口径 —— 「用户是否已手动处理」靠字符串比较,
  两边必须同时区同格式, 否则差一个时差(UTC vs 本地)会直接判错。
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger("opus.wakeups")

_WAKEUPS_FILE = Path(__file__).resolve().parent.parent / "data" / "runtime" / "wakeups.json"
_IO_LOCK = threading.RLock()

_WAKEUP_TICK_SEC = 1                    # 秒级 tick · 支持 20s 级短延迟
_WAKEUP_MIN_SEC = 20                    # 更短的延迟没意义(前端卡还没画完就到点)
_WAKEUP_MAX_SEC = 24 * 3600             # 超过一天那是定时任务该干的事
_WAKEUP_KEEP_TERMINAL_SEC = 24 * 3600   # 终态条目保留 24h 后清理(防表膨胀)
_WAKEUP_STALE_FIRING_MIN = 10           # firing 卡住超过这么久 → 判定 daemon 中途崩过

_WAKEUP_THREAD: Optional[threading.Thread] = None
_WAKEUP_STATE = {
    "started_at": None,
    "last_tick_at": None,
    "fired": 0,
    "voided": 0,
    "cancelled": 0,
    "last_error": None,
    "tick_interval_sec": _WAKEUP_TICK_SEC,
}


def get_wakeup_state() -> dict:
    return dict(_WAKEUP_STATE)


# ── 时间 (本地 naive · 与 session ts 同口径) ─────────────────────────
def _now() -> datetime:
    return datetime.now()


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


# ── 落盘 (原子写 · 锁保护) ──────────────────────────────────────────
def _load() -> dict:
    with _IO_LOCK:
        if not _WAKEUPS_FILE.exists():
            return {"wakeups": []}
        try:
            d = json.loads(_WAKEUPS_FILE.read_text(encoding="utf-8"))
            if not isinstance(d, dict) or not isinstance(d.get("wakeups"), list):
                return {"wakeups": []}
            return d
        except Exception as e:
            logger.warning("wakeups.json 读失败 · 当空处理: %s", e)
            return {"wakeups": []}


def _save(data: dict) -> None:
    with _IO_LOCK:
        _WAKEUPS_FILE.parent.mkdir(parents=True, exist_ok=True)
        # Defender 瞬态锁防护 (tmp+replace 带重试) · 与 task_scheduler 同款
        try:
            from workers.safe_write import robust_write_json
            robust_write_json(_WAKEUPS_FILE, data, backup=False)
            return
        except ImportError:
            pass
        tmp = _WAKEUPS_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(_WAKEUPS_FILE)


def _update_fields(wakeup_id: str, updates: dict) -> None:
    """在最新磁盘数据上只改一条再落盘。

    防"用执行前的旧快照整体覆盖" —— 同 task_scheduler._update_task_fields 的 H-05 修复:
    _fire 跑分钟级 LLM turn 期间, 用户经 API 的增删改会先落盘; 用旧快照整体 _save
    会把它们全部覆盖(新加的唤醒静默消失、已取消的复活)。
    """
    with _IO_LOCK:
        d = _load()
        for w in d.get("wakeups", []):
            if w.get("id") == wakeup_id:
                w.update(updates)
                break
        else:
            return  # 条目已被删除 → 保持删除
        _save(d)


# ── CRUD ────────────────────────────────────────────────────────────
def add_wakeup(session_id: str, delay_sec: int, label: str, reason: str = "", kind: str = "notify") -> Optional[dict]:
    """注册一条延迟唤醒。返条目 dict(失败返 None)。叫醒的活由 tick 线程接。"""
    sid = str(session_id or "").strip()
    if not sid:
        return None
    try:
        delay = int(delay_sec)
    except (TypeError, ValueError):
        return None
    delay = max(_WAKEUP_MIN_SEC, min(_WAKEUP_MAX_SEC, delay))
    now = _now()
    w = {
        "id": "wk-" + uuid.uuid4().hex[:10],
        "session_id": sid,
        "label": str(label or "").strip()[:120],
        "reason": str(reason or "").strip()[:400],
        "delay_sec": delay,
        "created_at": _iso(now),
        "fire_at": _iso(now + timedelta(seconds=delay)),
        "kind": ("ask" if str(kind).strip() == "ask" else "notify"),
        "status": "armed",
        "void_reason": "",
        "error": "",
    }
    with _IO_LOCK:
        d = _load()
        d.setdefault("wakeups", []).append(w)
        _save(d)
    logger.info("wakeup armed: %s · %ss · sid=%s · %s", w["id"], delay, sid, w["label"])
    return dict(w)


def cancel_wakeup(wakeup_id: str) -> bool:
    """取消一条还没醒的唤醒。只有 armed 能取消(已 firing/done 的返 False)。"""
    wid = str(wakeup_id or "").strip()
    if not wid:
        return False
    hit = False
    with _IO_LOCK:
        d = _load()
        for w in d.get("wakeups", []):
            if w.get("id") == wid and w.get("status") == "armed":
                w["status"] = "cancelled"
                w["void_reason"] = "user_cancelled"
                hit = True
                break
        if hit:
            _save(d)
    if hit:
        _WAKEUP_STATE["cancelled"] += 1
        logger.info("wakeup cancelled: %s", wid)
    return hit


def get_wakeup(wakeup_id: str) -> Optional[dict]:
    wid = str(wakeup_id or "").strip()
    for w in _load().get("wakeups", []):
        if w.get("id") == wid:
            return dict(w)
    return None


def list_armed(session_id: str = "") -> list:
    """给端点/前端: 只返 armed · 每条附 remaining_sec(>=0)。"""
    now = _now()
    out = []
    for w in _load().get("wakeups", []):
        if w.get("status") != "armed":
            continue
        if session_id and w.get("session_id") != session_id:
            continue
        try:
            rem = int((datetime.fromisoformat(str(w.get("fire_at"))) - now).total_seconds())
        except Exception:
            rem = 0
        out.append({**w, "remaining_sec": max(0, rem)})
    return sorted(out, key=lambda x: str(x.get("fire_at") or ""))


# ── 作废判定 (机械判定 · 不靠 LLM 自觉) ─────────────────────────────
# 避让上限：会话正忙时最多顺延这么久（秒），超时照跑（不再等）
# BRO 拍板 2026-09-17：到点时若本会话有活跃 turn → 顺延到它结束后再注入，
# 根治「倒计时和青色小条打架」：唤醒不再插进正在进行的对话。
_WAKEUP_DEFER_MAX_SEC = 600


def _session_busy(sid: str) -> bool:
    """本会话是否有活跃 turn（前台对话/后台任务/其他唤醒都在册）。判不了就不避让=保持原行为。"""
    if not sid:
        return False
    try:
        from daemon_api import find_session_turn
        return bool(find_session_turn(sid))
    except Exception:
        return False


def _should_void(w: dict) -> str:
    """这条唤醒还要不要醒。返 "" = 照常唤醒。

    a) session_gone  —— 会话 jsonl 已不存在(用户删了会话)
    b) user_handled  —— 注册之后用户自己发过消息(他自己问过了, 别再来一遍)
    b 依赖 get_last_user_turn_ts —— 它内部已跳过 meta.src="proactive" 的后台注入 ·
    所以 w1 的自动唤醒不会误杀 w2。
    """
    sid = str(w.get("session_id") or "")
    if not sid:
        return "session_gone"
    try:
        from daemon_session import session_path, get_last_user_turn_ts
    except Exception:
        return ""
    try:
        if not session_path(sid).exists():
            return "session_gone"
    except Exception:
        return ""
    try:
        last_user_ts = get_last_user_turn_ts(sid)
    except Exception:
        last_user_ts = None
    created = str(w.get("created_at") or "")
    # kind（2026-09-17 修）：
    #   notify（默认）= 取结果/交作业类 —— 用户插话不影响，到点照醒；
    #   ask = 主动搭话/关怀类 —— 用户已开口就不再打扰。
    # 修因：原先所有唤醒都吃 user_handled，「BRO 插一句问事 → 取结果计时器被静默作废」。
    if str(w.get("kind") or "notify") == "notify":
        return ""
    if last_user_ts and created and str(last_user_ts) > created:
        return "user_handled"
    return ""


def _build_prompt(w: dict) -> str:
    label = str(w.get("label") or "").strip()
    reason = str(w.get("reason") or "").strip()
    body = label or reason or "（当时没写说明）"
    extra = f"\n给未来的自己的备注：{reason}" if reason and reason != label else ""
    return ("【自动唤醒 · 计时器到点】你之前给自己设了一次延迟唤醒，现在到点了。"
            f"\n要办的事：{body}{extra}"
            "\n去取结果并给 BRO 汇报：跑完了就说结果，还没跑完就如实说进度，失败了就说失败（别硬编）。"
            "\n用你自己的话跟 BRO 说 · 别复述这段系统提示。")


def _fire(w: dict) -> None:
    """跑一轮 LLM turn · catch-all。 无论成败都落终态(失败记 error)· 不重试。"""
    wid = str(w.get("id") or "")
    void = _should_void(w)
    if void:
        _WAKEUP_STATE["voided"] += 1
        logger.info("wakeup voided: %s · %s", wid, void)
        try:
            _update_fields(wid, {"status": "dismissed", "void_reason": void,
                                 "fired_at": _iso(_now())})
        except Exception:
            logger.exception("wakeup void write failed: %s", wid)
        return
    err = ""
    try:
        from workers.resume_runner import _wait_runtime_ready
        if not _wait_runtime_ready():
            raise RuntimeError("runtime 未就绪")
        from workers.proactive_call import _run_bg_turn
        _run_bg_turn(_build_prompt(w), str(w.get("session_id") or ""), reason=f"wakeup:{wid}")
    except Exception as e:
        err = f"{type(e).__name__}: {e}"[:300]
        logger.exception("wakeup fire failed: %s", wid)
    upd = {"status": "done", "fired_at": _iso(_now())}
    if err:
        upd["error"] = err
        _WAKEUP_STATE["last_error"] = err
    else:
        _WAKEUP_STATE["fired"] += 1
    try:
        _update_fields(wid, upd)
    except Exception:
        logger.exception("wakeup state write failed: %s", wid)


# ── tick ────────────────────────────────────────────────────────────
def _sweep_terminal(d: dict) -> bool:
    """清理保留期外的终态条目(防表膨胀)。返是否改动。"""
    cutoff = _iso(_now() - timedelta(seconds=_WAKEUP_KEEP_TERMINAL_SEC))
    keep, dropped = [], False
    for w in d.get("wakeups", []):
        if w.get("status") in ("done", "cancelled", "dismissed"):
            stamp = str(w.get("fired_at") or w.get("created_at") or "")
            if stamp and stamp < cutoff:
                dropped = True
                continue
        keep.append(w)
    if dropped:
        d["wakeups"] = keep
    return dropped


def scan() -> None:
    """tick 一次 · 必须秒级返回(真正跑 turn 的活交给独立线程)。"""
    now = _now()
    now_iso = _iso(now)
    _WAKEUP_STATE["last_tick_at"] = now_iso
    due: list = []
    with _IO_LOCK:
        d = _load()
        changed = _sweep_terminal(d)
        # 兜底: firing 卡住 >10min(daemon 中途崩过) → 落 done 防僵死
        stale_cutoff = _iso(now - timedelta(minutes=_WAKEUP_STALE_FIRING_MIN))
        for w in d.get("wakeups", []):
            if w.get("status") == "firing" and str(w.get("fire_at") or "") < stale_cutoff:
                w["status"] = "done"
                w["error"] = "firing stale (daemon restarted mid-fire)"
                changed = True
        # 到点的 armed → 先认领(置 firing 并落盘)再执行 · 防同一条被两次 tick 重复注入
        for w in d.get("wakeups", []):
            if w.get("status") != "armed":
                continue
            fa = str(w.get("fire_at") or "")
            if not fa or fa > now_iso:
                continue
            # 【避让】本会话正忙(有活跃 turn) → 先顺延, 不插进正在进行的对话。
            # 首次顺延记 deferred_since; 超 _WAKEUP_DEFER_MAX_SEC 不再等, 照跑并记 deferred_sec。
            _sid_w = str(w.get("session_id") or "")
            if _sid_w and _session_busy(_sid_w):
                _dsw = str(w.get("deferred_since") or "")
                _waited = 0.0
                if _dsw:
                    try:
                        _waited = (now - datetime.fromisoformat(_dsw)).total_seconds()
                    except Exception:
                        _waited = 0.0
                if _waited < _WAKEUP_DEFER_MAX_SEC:
                    if not _dsw:
                        w["deferred_since"] = now_iso
                    changed = True
                    continue

                w["deferred_sec"] = int(_waited)   # 等超时了 · 照跑并留痕
            w["status"] = "firing"
            changed = True
            due.append(dict(w))
        if changed:
            _save(d)
    for w in due:
        threading.Thread(target=_fire, args=(w,), daemon=True,
                         name=f"OpusWakeup-{w.get('id')}").start()


def _loop() -> None:
    _WAKEUP_STATE["started_at"] = _iso(_now())
    logger.info("wakeup scheduler started · every %ds", _WAKEUP_TICK_SEC)
    while True:
        try:
            scan()
        except Exception as e:
            _WAKEUP_STATE["last_error"] = f"{type(e).__name__}: {e}"
            logger.exception("wakeup tick crashed (will retry next tick): %s", e)
        time.sleep(_WAKEUP_TICK_SEC)


def start_wakeup_scheduler_in_background() -> Optional[threading.Thread]:
    """起 1s tick 守护线程 · 幂等 · OPUS_WAKEUPS=0 可禁用。"""
    global _WAKEUP_THREAD
    if _WAKEUP_THREAD is not None and _WAKEUP_THREAD.is_alive():
        return _WAKEUP_THREAD
    if (os.environ.get("OPUS_WAKEUPS") or "1").strip().lower() in ("0", "false", "off", "no"):
        logger.info("wakeup scheduler disabled (OPUS_WAKEUPS=0)")
        return None
    t = threading.Thread(target=_loop, name="OpusWakeups", daemon=True)
    t.start()
    _WAKEUP_THREAD = t
    return t


def is_wakeup_scheduler_alive() -> bool:
    return _WAKEUP_THREAD is not None and _WAKEUP_THREAD.is_alive()
