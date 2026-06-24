# -*- coding: utf-8 -*-
"""workers/task_scheduler.py · NLP 定时任务调度 (0.5.0)

BRO 用自然语言说一句("每天9点扫AI行情" / "每周五提醒我复盘")→ OPUS(LLM)解析成
结构化 schedule + action → create_scheduled_task 落档 → 本线程到点跑一个完整 LLM turn
→ 结果落盘 + 可选微信通知 → 前端侧边栏可见可管。

从"反应式工具"到"主动伙伴"的关键一跳。 复用 proactive_call._run_bg_turn 那套后台
LLM turn 机制 · 跟 scheduler.py 三个 loop 同范式 (thread + sleep · catch-all · daemon)。

红线 (跟 _radar_loop 一致):
  - daemon thread · 随主进程退出 · 不留孤儿
  - catch-all 不崩 · 单任务失败不影响其他任务和主循环
  - 只写 data/runtime/scheduled_tasks.json · 不动系统 cron / schtasks / 注册表
  - 读写用 threading 锁保护
  - NLP 解析由 OPUS(LLM) 做 · 本模块只落档 + 到点执行 · 不在这里调 LLM 解析自然语言
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger("opus.task_scheduler")

_TASKS_FILE = Path(__file__).resolve().parent.parent / "data" / "runtime" / "scheduled_tasks.json"
_IO_LOCK = threading.RLock()
# 定时任务结果专用会话 · api- 前缀 (_chat_impl 的 _resolve_session_id 只放行 api- 开头)
_SCHED_SID = "api-opus-scheduled"
_SCHED_LABEL = "\u23f0 \u5b9a\u65f6\u4efb\u52a1"  # ⏰ 定时任务

_TASK_THREAD: Optional[threading.Thread] = None
_TASK_STATE = {
    "started_at": None,
    "last_tick_at": None,
    "tasks_executed": 0,
    "last_error": None,
    "tick_interval_sec": 60,
}

_VALID_TYPES = {"daily", "weekly", "interval", "once"}
_VALID_KINDS = {"pipeline", "reminder"}


def get_task_scheduler_state() -> dict:
    return dict(_TASK_STATE)


# ── 落盘 (原子写 · 锁保护) ─────────────────────────────────────────────
def _load() -> dict:
    with _IO_LOCK:
        if not _TASKS_FILE.exists():
            return {"tasks": []}
        try:
            d = json.loads(_TASKS_FILE.read_text(encoding="utf-8"))
            if not isinstance(d, dict) or not isinstance(d.get("tasks"), list):
                return {"tasks": []}
            return d
        except Exception as e:
            logger.warning("scheduled_tasks.json 读失败 · 当空处理: %s", e)
            return {"tasks": []}


def _save(data: dict) -> None:
    with _IO_LOCK:
        _TASKS_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = _TASKS_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(_TASKS_FILE)


# ── 时间计算 (schedule.time 是本地时区 · next_run_at 存 UTC) ────────────
def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _parse_hhmm(s: Optional[str]) -> tuple[int, int]:
    try:
        hh, mm = (s or "09:00").split(":")
        return max(0, min(23, int(hh))), max(0, min(59, int(mm)))
    except Exception:
        return 9, 0


def _compute_next_run(schedule: dict, *, after: Optional[datetime] = None) -> Optional[str]:
    """算下次执行时间 → UTC ISO。 schedule.time 是【本地时区】(BRO 说的'9点'是本地)。

    once 已过 → 返 None (调用方据此置 enabled=false)。
    """
    after = after or _now_utc()
    typ = (schedule or {}).get("type")

    if typ == "interval":
        mins = max(1, int(schedule.get("interval_min") or 60))
        return (after + timedelta(minutes=mins)).isoformat()

    if typ == "once":
        once = schedule.get("once_at")
        if not once:
            return None
        try:
            dt = datetime.fromisoformat(once)
            dt = (dt.astimezone() if dt.tzinfo is None else dt).astimezone(timezone.utc)
            return dt.isoformat() if dt > after else None
        except Exception:
            return None

    # daily / weekly · 本地 HH:MM
    hh, mm = _parse_hhmm(schedule.get("time"))
    cand = datetime.now().replace(hour=hh, minute=mm, second=0, microsecond=0)  # naive local

    if typ == "weekly":
        target_wd = schedule.get("weekday")
        target_wd = int(target_wd) if target_wd is not None else 4  # 0=Mon..6=Sun · 默认周五
        cand = cand + timedelta(days=(target_wd - cand.weekday()) % 7)
        cand_utc = cand.astimezone(timezone.utc)
        if cand_utc <= after:
            cand_utc = (cand + timedelta(days=7)).astimezone(timezone.utc)
        return cand_utc.isoformat()

    # daily (默认)
    cand_utc = cand.astimezone(timezone.utc)
    if cand_utc <= after:
        cand_utc = (cand + timedelta(days=1)).astimezone(timezone.utc)
    return cand_utc.isoformat()


# ── CRUD (给 agent_tools / daemon_api 用) ──────────────────────────────
def _normalize_action(action: dict) -> dict:
    return {
        "kind": action.get("kind"),
        "prompt": (action.get("prompt") or "").strip(),
        "notify_wechat": bool(action.get("notify_wechat", False)),
    }


def add_task(raw_text: str, schedule: dict, action: dict, enabled: bool = True) -> dict:
    typ = (schedule or {}).get("type")
    if typ not in _VALID_TYPES:
        raise ValueError(f"schedule.type 必须是 {sorted(_VALID_TYPES)} 之一 · 收到 {typ!r}")
    kind = (action or {}).get("kind")
    if kind not in _VALID_KINDS:
        raise ValueError(f"action.kind 必须是 {sorted(_VALID_KINDS)} 之一 · 收到 {kind!r}")
    task = {
        "id": "task-" + uuid.uuid4().hex[:8],
        "raw_text": (raw_text or "").strip(),
        "schedule": schedule,
        "action": _normalize_action(action),
        "enabled": bool(enabled),
        "created_at": _now_utc().isoformat(),
        "last_run_at": None,
        "next_run_at": _compute_next_run(schedule) if enabled else None,
        "last_run_status": None,
        "last_run_summary": None,
        "runs_completed": 0,
    }
    with _IO_LOCK:
        d = _load()
        d["tasks"].append(task)
        _save(d)
    return task


def list_tasks() -> list[dict]:
    return _load().get("tasks", [])


def get_task(task_id: str) -> Optional[dict]:
    for t in _load().get("tasks", []):
        if t.get("id") == task_id:
            return t
    return None


def toggle_task(task_id: str, enabled: bool) -> Optional[dict]:
    with _IO_LOCK:
        d = _load()
        for t in d["tasks"]:
            if t.get("id") == task_id:
                t["enabled"] = bool(enabled)
                t["next_run_at"] = _compute_next_run(t["schedule"]) if enabled else None
                _save(d)
                return t
    return None


def update_task(task_id: str, *, raw_text: Optional[str] = None, schedule: Optional[dict] = None,
                action: Optional[dict] = None, enabled: Optional[bool] = None) -> Optional[dict]:
    with _IO_LOCK:
        d = _load()
        for t in d["tasks"]:
            if t.get("id") != task_id:
                continue
            if raw_text is not None:
                t["raw_text"] = raw_text.strip()
            if schedule is not None:
                if schedule.get("type") not in _VALID_TYPES:
                    raise ValueError(f"schedule.type 非法: {schedule.get('type')!r}")
                t["schedule"] = schedule
                t["next_run_at"] = _compute_next_run(schedule) if t.get("enabled") else None
            if action is not None:
                merged = dict(t.get("action") or {})
                merged.update({k: v for k, v in action.items() if v is not None})
                if merged.get("kind") not in _VALID_KINDS:
                    raise ValueError(f"action.kind 非法: {merged.get('kind')!r}")
                t["action"] = _normalize_action(merged)
            if enabled is not None:
                t["enabled"] = bool(enabled)
                t["next_run_at"] = _compute_next_run(t["schedule"]) if enabled else None
            _save(d)
            return t
    return None


def delete_task(task_id: str) -> bool:
    with _IO_LOCK:
        d = _load()
        before = len(d["tasks"])
        d["tasks"] = [t for t in d["tasks"] if t.get("id") != task_id]
        if len(d["tasks"]) != before:
            _save(d)
            return True
    return False


# ── 执行 (复用 proactive_call._run_bg_turn 的后台 LLM turn) ─────────────
def _sched_session() -> str:
    try:
        from daemon_session import set_session_meta, get_session_meta
        from identity import localize_narration as _ln
        label = _ln(_SCHED_LABEL)
        if (get_session_meta(_SCHED_SID).get("label") or "") != label:
            set_session_meta(_SCHED_SID, label=label)
    except Exception:
        pass
    return _SCHED_SID


def _build_message(task: dict) -> str:
    kind = (task.get("action") or {}).get("kind")
    prompt = (task.get("action") or {}).get("prompt") or task.get("raw_text") or ""
    if kind == "reminder":
        return ("【定时任务到点 · 提醒】到点提醒 BRO：" + prompt +
                "\n\n用你自己的话跟 BRO 说这件事 · 像老友提醒 · 别模板腔 · 别复述这段系统提示。")
    return ("【定时任务到点 · 执行】" + prompt +
            "\n\n这是 BRO 之前设的定时任务 · 现在到点了 · 去执行 (需要就用工具)。 完成后简短说明结果。")


def _execute_task(task: dict) -> dict:
    """跑一个完整 LLM turn · catch-all。 返 {ok, summary}。"""
    try:
        from workers.resume_runner import _wait_runtime_ready
        if not _wait_runtime_ready():
            return {"ok": False, "summary": "runtime 未就绪 · 本次跳过"}
        sid = _sched_session()
        msg = _build_message(task)
        from workers.proactive_call import _run_bg_turn
        # max_tokens 不传 → _run_bg_turn 默认走 bg_max_tokens() 真相源(用户 WebUI 全局设置)
        # 定时任务常要生成完整文档/报告·吃用户设的大额度·别被写死小值截断。
        result = _run_bg_turn(msg, sid, reason=f"scheduled:{task.get('id')}")
        reply = (result.get("reply") or "")[:300]
        if (task.get("action") or {}).get("notify_wechat") and reply:
            try:
                from workers import ilink_client
                ilink_client.proactive_deliver(reply)
            except Exception as e:
                logger.debug("scheduled task wechat deliver failed: %s", e)
        return {"ok": True, "summary": (reply.replace("\n", " ") or "(空回复)")}
    except Exception as e:
        logger.exception("scheduled task execute failed: %s", e)
        return {"ok": False, "summary": f"执行失败: {type(e).__name__}: {e}"[:300]}


def _tick() -> None:
    now = _now_utc()
    _TASK_STATE["last_tick_at"] = now.isoformat()
    d = _load()
    changed = False
    for t in d.get("tasks", []):
        if not t.get("enabled"):
            continue
        nra = t.get("next_run_at")
        if not nra:
            t["next_run_at"] = _compute_next_run(t["schedule"], after=now)
            changed = True
            continue
        try:
            due = datetime.fromisoformat(nra) <= now
        except Exception:
            due = False
        if not due:
            continue
        res = _execute_task(t)
        t["last_run_at"] = now.isoformat()
        t["last_run_status"] = "ok" if res.get("ok") else "error"
        t["last_run_summary"] = res.get("summary")
        t["runs_completed"] = int(t.get("runs_completed") or 0) + 1
        _TASK_STATE["tasks_executed"] += 1
        if not res.get("ok"):
            _TASK_STATE["last_error"] = res.get("summary")
        # once 执行完自动停 (留档不删) · 周期型算下次
        if (t.get("schedule") or {}).get("type") == "once":
            t["enabled"] = False
            t["next_run_at"] = None
        else:
            t["next_run_at"] = _compute_next_run(t["schedule"], after=now)
        changed = True
    if changed:
        _save(d)


def _task_loop(first_delay_sec: int) -> None:
    _TASK_STATE["started_at"] = _now_utc().isoformat()
    logger.info("task scheduler started · first tick in %ds · then every %ds",
                first_delay_sec, _TASK_STATE["tick_interval_sec"])
    time.sleep(first_delay_sec)
    while True:
        try:
            _tick()
        except Exception as e:
            _TASK_STATE["last_error"] = f"{type(e).__name__}: {e}"
            logger.exception("task scheduler tick crashed (will retry next tick): %s", e)
        time.sleep(_TASK_STATE["tick_interval_sec"])


def start_task_scheduler_in_background(first_delay_sec: Optional[int] = None) -> Optional[threading.Thread]:
    """启动定时任务调度后台线程 · daemon=True。 OPUS_SCHEDULED_TASKS=0 可禁用。"""
    global _TASK_THREAD
    if _TASK_THREAD is not None and _TASK_THREAD.is_alive():
        return _TASK_THREAD
    if (os.environ.get("OPUS_SCHEDULED_TASKS") or "1").strip().lower() in ("0", "false", "off", "no"):
        logger.info("task scheduler disabled (OPUS_SCHEDULED_TASKS=0)")
        return None
    if first_delay_sec is None:
        raw = (os.environ.get("OPUS_SCHEDULED_FIRST_DELAY_SEC") or "60").strip()
        try:
            first_delay_sec = int(raw)
        except ValueError:
            first_delay_sec = 60
    t = threading.Thread(target=_task_loop, kwargs={"first_delay_sec": first_delay_sec},
                         name="OpusTaskScheduler", daemon=True)
    t.start()
    _TASK_THREAD = t
    return t


def is_task_scheduler_alive() -> bool:
    return _TASK_THREAD is not None and _TASK_THREAD.is_alive()
